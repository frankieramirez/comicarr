#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import os
import re
import threading
import time

from sqlalchemy import select

import comicarr
from comicarr import db, filers, helpers, metron, series_kind
from comicarr.app.common.library_roots import is_strict_library_descendant
from comicarr.app.metadata.series_type import resolve_series_edition
from comicarr.tables import comics, issues

_ADD_LOCK = threading.Lock()
_MAX_PAGES = 20
_PROVIDER_SECONDS = 150


def canonical_series_id(series_id):
    series_id = str(series_id).strip()
    if metron.is_metron_id(series_id):
        mapped = metron.get_cv_id(series_id)
        if not mapped:
            raise ValueError("Metron series %s has no ComicVine mapping" % series_id)
        series_id = str(mapped)
    if series_kind.provider_of(series_id) in series_kind.MANGA_PROVIDERS:
        return series_id
    series_id = series_id.removeprefix("4050-")
    if not series_id.isdecimal():
        raise ValueError("Invalid ComicVine series ID")
    return str(int(series_id))


def metadata_ready(series):
    return bool(
        series
        and series.get("ComicLocation")
        and series.get("LastUpdated")
        and series.get("Status") in ("Active", "Paused")
        and series.get("ComicName")
        and not series["ComicName"].startswith(("Fetch failed", "Comic ID:"))
    )


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Series metadata request timed out; retry the import")
    return remaining


def _cv_request(endpoint, params, deadline):
    if not comicarr.CONFIG.COMICVINE_API or comicarr.CONFIG.COMICVINE_API == "None":
        raise ValueError("ComicVine API key is required")
    comicarr.CV_RATE_LIMITER.acquire(timeout=_remaining(deadline))
    response = comicarr.CV_SESSION.get(
        comicarr.CVURL + endpoint,
        params={**params, "api_key": comicarr.CONFIG.COMICVINE_API, "format": "json"},
        verify=comicarr.CONFIG.CV_VERIFY,
        timeout=min(20, _remaining(deadline)),
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status_code") != 1:
        raise ValueError("ComicVine could not load series metadata")
    return payload


def _comic_metadata(series_id, deadline):
    volume = _cv_request("volume/4050-%s/" % series_id, {}, deadline)["results"]
    if str(volume.get("id")) != series_id:
        raise ValueError("ComicVine returned a different series")
    name = str(volume.get("name") or "").strip()
    year = str(volume.get("start_year") or "").strip()
    publisher = (volume.get("publisher") or {}).get("name") or "Unknown"
    if not name or not re.fullmatch(r"\d{4}", year):
        raise ValueError("Series name and start year must be resolved before importing")
    total = int(volume.get("count_of_issues") or 0)
    if total <= 0 or total > _MAX_PAGES * 100:
        raise ValueError("Series has no issues or exceeds the import metadata limit; add and refresh it first")
    records = []
    for offset in range(0, total, 100):
        page = _cv_request("issues/", {"filter": "volume:%s" % series_id, "limit": 100, "offset": offset}, deadline)
        if int(page.get("number_of_total_results", -1)) != total:
            raise ValueError("ComicVine issue roster changed or is incomplete; retry the import")
        for issue in page.get("results") or []:
            if str((issue.get("volume") or {}).get("id")) != series_id:
                raise ValueError("ComicVine returned an issue from another series")
            number = str(issue.get("issue_number") or "").strip()
            if not issue.get("id") or not number:
                raise ValueError("ComicVine issue identity is incomplete")
            records.append(
                {
                    "IssueID": str(issue["id"]),
                    "Issue_Number": number,
                    "IssueName": issue.get("name"),
                    "IssueDate": issue.get("cover_date"),
                    "ReleaseDate": issue.get("store_date"),
                    "ImageURL": (issue.get("image") or {}).get("original_url"),
                }
            )
    if len(records) != total or len({row["IssueID"] for row in records}) != total:
        raise ValueError("ComicVine issue roster is incomplete; retry the import")
    booktype = resolve_series_edition(
        series_type="Print",
        issue_count=total,
        series_year=year,
        description=volume.get("description"),
        deck=volume.get("deck"),
        issue_names=[row.get("IssueName") for row in records],
        series_name=name,
    )
    values = {
        "ComicName": name,
        "ComicYear": year,
        "ComicPublisher": publisher,
        "PublisherImprint": None,
        "ComicVersion": None,
        "Type": booktype,
        "Corrected_Type": None,
        "DetailURL": volume.get("site_detail_url"),
        "Description": volume.get("description"),
        "ComicImageURL": (volume.get("image") or {}).get("original_url"),
        "ContentType": "comic",
    }
    handler = filers.FileHandlers(comic=values)
    location = handler.folder_create()["comlocation"]
    collision = handler.series_folder_collision_detection(location, series_id, booktype, year, None)
    values["ComicLocation"] = collision["comlocation"] if collision else location
    return values, records


def _manga_metadata(series_id, deadline):
    from comicarr import mangadex, myanimelist
    from comicarr.app.manga.duplicates import find_existing_manga_series
    from comicarr.config import get_manga_destination

    mal = series_kind.provider_of(series_id) is series_kind.SeriesProvider.MYANIMELIST
    details = myanimelist.get_manga_details(series_id) if mal else mangadex.get_manga_details(series_id)
    _remaining(deadline)
    if not details or not details.get("name"):
        raise ValueError("Manga metadata could not be loaded")
    md_id = series_kind.strip_prefix(series_id)
    if mal:
        md_id = mangadex.find_by_mal_id(
            series_id, title_hint=details["name"], alternate_titles=[], allow_title_match=False
        )
        _remaining(deadline)
        if not md_id:
            raise ValueError("Manga has no verified MangaDex chapter source; add and refresh it first")
    duplicate = find_existing_manga_series(
        comic_id=series_id,
        mal_id=series_kind.strip_prefix(series_id) if mal else details.get("mal_id"),
        mangadex_id=md_id,
    )
    if duplicate:
        raise ValueError("Manga already exists under another provider; match the existing series")
    chapters = []
    total = None
    for page_number in range(_MAX_PAGES):
        _remaining(deadline)
        page = mangadex.get_manga_chapters(md_id, limit=100, offset=page_number * 100)
        page_total = int(page.get("pagination", {}).get("total") or 0)
        if page_total <= 0 or page_total > _MAX_PAGES * 100 or (total is not None and page_total != total):
            raise ValueError("Manga chapter roster is unavailable or incomplete; add and refresh it first")
        total = page_total
        chapters.extend(page.get("chapters") or [])
        if len(chapters) >= total:
            break
        if not page.get("chapters"):
            raise ValueError("Manga chapter roster is incomplete")
    _remaining(deadline)
    if len(chapters) != total:
        raise ValueError("Manga chapter roster is incomplete")
    records = {}
    for chapter in chapters:
        number = str(chapter.get("chapter") or "").strip()
        if not number:
            continue
        records.setdefault(
            number,
            {
                "IssueID": "%s-ch%s" % (series_id, number),
                "Issue_Number": number,
                "ChapterNumber": number,
                "VolumeNumber": chapter.get("volume"),
                "IssueName": chapter.get("title"),
                "IssueDate": chapter.get("release_date"),
                "ReleaseDate": chapter.get("release_date"),
            },
        )
    if not records:
        raise ValueError("Manga has no numbered chapters to match")
    name = details["name"]
    year = str(details.get("year") or "")
    if not re.fullmatch(r"\d{4}", year):
        raise ValueError("Manga start year must be resolved before importing")
    destination = get_manga_destination()
    if not destination:
        raise ValueError("Manga library destination must be configured")
    folder_format = comicarr.CONFIG.FOLDER_FORMAT or "$Series ($Year)"
    folder = helpers.filesafe(folder_format.replace("$Series", name).replace("$Year", year))
    values = {
        "ComicName": name,
        "ComicYear": year,
        "ComicPublisher": details.get("author") or "Unknown",
        "ComicLocation": os.path.join(destination, folder),
        "ContentType": "manga",
        "Type": "Manga",
        "MetadataSource": "mal" if mal else "mangadex",
        "ExternalID": series_kind.strip_prefix(series_id),
        "MangaDexID": md_id,
        "MalID": series_kind.strip_prefix(series_id) if mal else details.get("mal_id"),
        "ReadingDirection": "rtl",
        "Description": details.get("description"),
        "ComicImageURL": details.get("cover_url"),
        "DetailURL": details.get("url"),
    }
    return values, list(records.values())


def add_series_metadata(series_id):
    """Return canonical, complete metadata without acquisition or file operations.

    Provider failure writes nothing. Once created, a Paused series remains in
    the library if subsequent issue matching or file placement fails.
    """
    series_id = canonical_series_id(series_id)
    with _ADD_LOCK:
        existing = db.select_one(select(comics).where(comics.c.ComicID == series_id))
        if metadata_ready(existing):
            return {"status": "complete", "comicid": series_id, "comicname": existing["ComicName"], "added": False}
        deadline = time.monotonic() + _PROVIDER_SECONDS
        if series_kind.provider_of(series_id) in series_kind.MANGA_PROVIDERS:
            values, records = _manga_metadata(series_id, deadline)
        else:
            values, records = _comic_metadata(series_id, deadline)
        if not values.get("ComicLocation") or not os.path.isabs(values["ComicLocation"]):
            raise ValueError("A library destination must be configured before importing")
        if existing and existing.get("ComicLocation"):
            values["ComicLocation"] = existing["ComicLocation"]
        if not is_strict_library_descendant(values["ComicLocation"], comicarr.CONFIG):
            raise ValueError("Series folder must be inside a configured library root")
        for other in db.select_all(select(comics).where(comics.c.ComicID != series_id)):
            taken = other.get("ComicLocation")
            if taken and os.path.commonpath([os.path.realpath(taken), os.path.realpath(values["ComicLocation"])]) in (
                os.path.realpath(taken),
                os.path.realpath(values["ComicLocation"]),
            ):
                raise ValueError("Series folder overlaps an existing series; add it with a distinct folder first")
        latest = max(records, key=lambda row: helpers.issuedigits(row["Issue_Number"]))
        values.update(
            {
                "ComicSortName": values["ComicName"].removeprefix("The "),
                "ComicName_Filesafe": helpers.filesafe(values["ComicName"]),
                "DynamicComicName": helpers.filesafe(values["ComicName"].lower()),
                "Status": "Paused",
                "Total": len(records),
                "Have": 0,
                "LastUpdated": helpers.now(),
                "DateAdded": (existing or {}).get("DateAdded") or helpers.today(),
                "ComicPublished": values["ComicYear"],
                "LatestIssue": latest["Issue_Number"],
                "intLatestIssue": helpers.issuedigits(latest["Issue_Number"]),
                "LatestIssueID": latest["IssueID"],
                "LatestDate": latest.get("ReleaseDate") or latest.get("IssueDate") or "%s-01-01" % values["ComicYear"],
            }
        )
        with db.get_engine().begin() as conn:
            current = conn.execute(select(comics).where(comics.c.ComicID == series_id)).mappings().first()
            if dict(current or {}) != (existing or {}):
                raise ValueError("Series changed while loading metadata; retry the import")
            for record in records:
                old = conn.execute(select(issues).where(issues.c.IssueID == record["IssueID"])).mappings().first()
                if old and old["ComicID"] != series_id:
                    raise ValueError("Issue identity already belongs to another series")
                row = {
                    **record,
                    "ComicID": series_id,
                    "ComicName": values["ComicName"],
                    "Int_IssueNumber": helpers.issuedigits(record["Issue_Number"]),
                }
                if not old:
                    row.update({"Status": "Skipped", "DateAdded": helpers.today()})
                db.upsert_conn(conn, "issues", row, {"IssueID": record["IssueID"]})
            db.upsert_conn(conn, "comics", values, {"ComicID": series_id})
        return {"status": "complete", "comicid": series_id, "comicname": values["ComicName"], "added": True}
