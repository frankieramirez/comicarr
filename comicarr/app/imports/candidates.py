#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The Import page's pick panel: which series a review group could be.

A review group is the set of ``importresults`` rows the page shows as one
line. This reads those rows back, scores every library series against the
group with the same scoring the inbox scan uses (``importinbox.score_series``),
and says why the group stopped for a person instead of importing itself.
Provider candidates (series not in the library yet) come from a separate call,
because they cost a ComicVine or MangaDex search.
"""

from __future__ import annotations

import datetime
import os

from sqlalchemy import select

import comicarr
from comicarr import db, logger
from comicarr.app.imports import finalization, folder_memory
from comicarr.tables import comics, importresults

LIBRARY_LIMIT = 3
REMOTE_LIMIT = 3
MIN_SCORE = 0.4
# A series whose start year is not the year the files name is still offered,
# scored down so it never reads as confident: files usually carry the issue's
# cover year, not the year the series began.
OTHER_YEAR_FACTOR = 0.7

# What the page says when a confident group fails; the full error goes to the log.
_FAILURE_PHASES = {
    "preflight": "the files did not pass the pre-import checks",
    "series": "the series could not be added",
    "issues": "some files did not match an issue in the series",
    "move": "the files could not be moved",
    "commit": "the import could not be saved",
    "finalization": "the import could not be saved",
    "rescan": "the series could not be rescanned",
}


def _bar(ctx):
    config = getattr(ctx, "config", None) or comicarr.CONFIG
    try:
        return int(getattr(config, "AUTO_IMPORT_CONFIDENCE", 80) or 80)
    except (TypeError, ValueError):
        return 80


def _rows(imp_ids):
    ids = [str(i) for i in imp_ids or [] if i]
    if not ids:
        return []
    return db.select_all(select(importresults).where(importresults.c.impID.in_(ids))) or []


def _found_at(rows):
    stamps = sorted(str(row.get("ImportDate") or "") for row in rows if row.get("ImportDate"))
    if not stamps:
        return None
    try:
        when = datetime.datetime.strptime(stamps[0], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return when.astimezone().isoformat()


def _size(path):
    try:
        return os.path.getsize(path) if path else None
    except OSError:
        return None


def _source(rows, config):
    """``inbox`` or ``library``, and the folder the group sits in relative to that root."""
    location = next((row.get("ComicLocation") for row in rows if row.get("ComicLocation")), None)
    folder = os.path.dirname(location) if location else None
    import_dir = getattr(config, "IMPORT_DIR", None) if config else None
    inbox = any(str(row.get("MatchSource") or "").startswith("inbox") for row in rows)
    if folder and import_dir:
        root = os.path.abspath(import_dir)
        if os.path.abspath(folder) == root or os.path.abspath(folder).startswith(root + os.sep):
            inbox = True
            rel = os.path.relpath(folder, root)
            folder = "inbox/" if rel == "." else "inbox/%s/" % rel.replace(os.sep, "/")
    return ("inbox" if inbox else "library"), folder


def _year(value):
    try:
        return int(str(value or "").strip())
    except ValueError:
        return None


def _panel_score(importinbox, match_name, years, series):
    """``score_series`` for the pick panel, which keeps other-year series in play.

    Auto-import keeps the strict rule. Here a series that began on or before
    the files' year scores ``OTHER_YEAR_FACTOR`` of its title match; one that
    began after it cannot hold those files and still scores zero.
    """
    strict = importinbox.score_series(match_name, years, series)
    if strict > 0 or not years:
        return strict
    loose = importinbox.score_series(match_name, set(), series)
    start = _year(series.get("ComicYear"))
    file_years = [y for y in (_year(v) for v in years) if y is not None]
    if loose <= 0 or start is None or not file_years or start > max(file_years):
        return 0.0
    return loose * OTHER_YEAR_FACTOR


def _other_year(candidate, years):
    return bool(years) and bool(candidate.get("year")) and candidate["year"] not in years


def _library_series():
    return [
        dict(row)
        for row in db.select_all(
            select(
                comics.c.ComicID,
                comics.c.ComicName,
                comics.c.ComicSortName,
                comics.c.ComicYear,
                comics.c.ComicPublisher,
                comics.c.Total,
                comics.c.Have,
                comics.c.DynamicComicName.label("DynamicName"),
            )
        )
        or []
    ]


def _library_candidate(series, score):
    return {
        "comic_id": str(series["ComicID"]),
        "name": series.get("ComicName") or "",
        "year": str(series.get("ComicYear") or "") or None,
        "publisher": series.get("ComicPublisher") or None,
        "issues": series.get("Total"),
        "have": series.get("Have"),
        "in_library": True,
        "image": None,
        "score": int(round(score * 100)),
    }


def _reason(*, remembered, best, tied, years, bar, candidates):
    if remembered:
        return "remembered"
    if not candidates or best <= 0:
        return "no_match"
    if tied > 1:
        return "tied"
    if len(years) > 1:
        return "mixed_years"
    if _other_year(candidates[0], years):
        return "other_year"
    if best < bar:
        return "below_bar"
    return "confident"


def group_candidates(ctx, imp_ids):
    """The pick panel for one review group, or ``None`` when its rows are gone."""
    from comicarr import importinbox

    rows = _rows(imp_ids)
    if not rows:
        return None
    config = getattr(ctx, "config", None) or comicarr.CONFIG
    bar = _bar(ctx)
    rows = sorted(rows, key=lambda row: str(row.get("ComicFilename") or ""))
    group_name = next((row.get("ComicName") for row in rows if row.get("ComicName")), "") or ""
    locations = [row.get("ComicLocation") or row.get("ComicFilename") or "" for row in rows]
    match_name, years = importinbox.match_terms(group_name, locations)

    scored = []
    for series in _library_series():
        score = _panel_score(importinbox, match_name, years, series)
        if score > 0:
            scored.append((score, series))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("ComicName") or "")))
    best = scored[0][0] if scored else 0.0
    tied = sum(1 for score, _ in scored if score == best) if scored else 0

    picked = [(s, series) for s, series in scored if s >= MIN_SCORE][:LIBRARY_LIMIT]
    picked_ids = {str(series["ComicID"]) for _, series in picked}
    suggested_id = next((str(row["SuggestedComicID"]) for row in rows if row.get("SuggestedComicID")), None)
    group_key = rows[0].get("DynamicName")
    remembered = folder_memory.recall(group_key)
    for wanted in (suggested_id, (remembered or {}).get("comic_id")):
        if wanted and wanted not in picked_ids:
            extra = next(((s, series) for s, series in scored if str(series["ComicID"]) == wanted), None)
            if extra:
                picked.append(extra)
                picked_ids.add(wanted)
    candidates = [_library_candidate(series, score) for score, series in picked]

    files = [
        {
            "impID": row["impID"],
            "filename": row.get("ComicFilename") or os.path.basename(row.get("ComicLocation") or ""),
            "bytes": _size(row.get("ComicLocation")),
            "issue_number": row.get("IssueNumber"),
        }
        for row in rows
    ]
    sizes = [f["bytes"] for f in files if f["bytes"] is not None]
    source, folder = _source(rows, config)
    pick = (remembered or {}).get("comic_id") or suggested_id or (candidates[0]["comic_id"] if candidates else None)
    # Best score first; among equals, the pick leads so the panel opens on it.
    candidates.sort(key=lambda c: (-c["score"], c["comic_id"] != pick))
    return {
        "group_name": group_name,
        "match_name": match_name,
        "years": sorted(years),
        "source": source,
        "folder": folder,
        "found_at": _found_at(rows),
        "total_bytes": sum(sizes) if sizes else None,
        "files": files,
        "confidence_bar": bar,
        "reason": _reason(
            remembered=remembered, best=best * 100, tied=tied, years=years, bar=bar, candidates=candidates
        ),
        "tied": tied,
        "remembers": folder_memory.is_folder_key(group_key),
        "remembered": remembered,
        "pick": pick,
        "candidates": candidates,
    }


def _remote_candidate(result, score):
    comic_id = result.get("comicid") or result.get("id")
    issues = result.get("count_of_issues") or result.get("issues")
    try:
        issues = int(issues) if issues not in (None, "") else None
    except (TypeError, ValueError):
        issues = None
    return {
        "comic_id": str(comic_id),
        "name": result.get("name") or result.get("comicname") or "",
        "year": str(result.get("comicyear") or result.get("start_year") or "") or None,
        "publisher": result.get("publisher") or None,
        "issues": issues,
        "have": None,
        "in_library": bool(result.get("in_library")),
        "image": result.get("comicthumb") or result.get("image") or result.get("comicimage") or None,
        "score": int(round(score * 100)),
    }


def remote_candidates(ctx, imp_ids, content_type=None):
    """Provider series the group could be, scored like library ones. ``{"candidates": [...]}``."""
    from comicarr import importinbox
    from comicarr.app.search import service as search_service

    rows = _rows(imp_ids)
    if not rows:
        return None
    group_name = next((row.get("ComicName") for row in rows if row.get("ComicName")), "") or ""
    locations = [row.get("ComicLocation") or row.get("ComicFilename") or "" for row in rows]
    match_name, years = importinbox.match_terms(group_name, locations)
    if not match_name:
        return {"candidates": [], "query": match_name}
    try:
        found = search_service.find_comic(
            ctx, name=match_name, limit=10, content_type="manga" if content_type == "manga" else None
        )
    except Exception as e:
        logger.fdebug("[IMPORT-PICK] Provider search for '%s' failed: %s" % (match_name, e))
        return {"candidates": [], "query": match_name, "error": "Provider search failed"}
    if not isinstance(found, dict) or "error" in found:
        return {
            "candidates": [],
            "query": match_name,
            "error": (found or {}).get("error") if isinstance(found, dict) else None,
        }
    scored = []
    for result in found.get("results") or []:
        if not (result.get("comicid") or result.get("id")):
            continue
        series = {"ComicName": result.get("name") or result.get("comicname"), "ComicYear": result.get("comicyear")}
        score = _panel_score(importinbox, match_name, years, series)
        if score >= MIN_SCORE:
            scored.append(_remote_candidate(result, score))
    scored.sort(key=lambda c: -c["score"])
    return {"candidates": scored[:REMOTE_LIMIT], "query": match_name}


def import_confident(ctx, *, page_size=200):
    """Import every group in the Confident tab as its suggested series.

    Returns ``{"groups", "imported", "failed": [{name, error}]}``. Groups are
    listed first and imported after, so one that fails does not stall the rest.
    """
    from comicarr.app.series import queries as series_queries

    bar = _bar(ctx)
    groups = []
    offset = 0
    while True:
        page = series_queries.get_import_pending(limit=page_size, offset=offset, bucket="confident", threshold=bar)
        groups.extend(page["imports"])
        if not page["pagination"]["has_more"]:
            break
        offset += page_size

    imported = 0
    failed = []
    for group in groups:
        imp_ids = [f["impID"] for f in group.get("files") or [] if f.get("impID")]
        comic_id = group.get("SuggestedComicID")
        name = group.get("ComicName") or group.get("DynamicName")
        if not imp_ids or not comic_id:
            continue
        try:
            folder = folder_memory.folder_of(imp_ids)
            result = finalization.finalize_manual_match(
                ctx, imp_ids, comic_id, series_name=group.get("SuggestedComicName")
            )
        except finalization.ImportFinalizationError as e:
            logger.warning("[IMPORT-PICK] Unable to import '%s' as its confident match [%s]: %s" % (name, e.phase, e))
            failed.append({"name": name, "error": _FAILURE_PHASES.get(e.phase, "import failed")})
            continue
        except Exception as e:
            logger.error("[IMPORT-PICK] Unable to import '%s' as its confident match: %s" % (name, e))
            failed.append({"name": name, "error": "import failed"})
            continue
        imported += result.matched
        if result.matched:
            folder_memory.remember(folder, result.series_id, result.series_name)
    return {"groups": len(groups), "imported": imported, "failed": failed}
