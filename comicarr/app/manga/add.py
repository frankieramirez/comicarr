#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Add a manga series from MangaDex or MyAnimeList.

Moved from ``comicarr/importer.py`` (#1463): ``add_mangadex`` was
``addMangaToDB`` and ``add_myanimelist`` was ``addMangaToDB_MAL``. Other
modules add a manga through ``app/series/add.add_manga``.
"""

import os

from sqlalchemy import select

from comicarr.app.common import configured as configured
from comicarr.app.common import dates as common_dates
from comicarr.app.common import series_kind
from comicarr.app.common import strings as common_strings
from comicarr.app.common.series_names import dynamic_series_key
from comicarr.app.core import db, logger, runtime
from comicarr.app.core.tables import comics, issues
from comicarr.app.library import directories
from comicarr.app.metadata import service as metadata_service
from comicarr.app.series import service as series_service
from comicarr.app.series.add_activity import emit_add_activity


def _refuse_duplicate_manga(attempted_id, existing):
    """Log and return a refused add when the same work is already tracked."""
    existing_id = existing.get("ComicID")
    existing_name = existing.get("ComicName") or existing_id
    detail = "Already in the library as %s (%s)" % (existing_name, existing_id)
    logger.warn("[MANGA] Refusing to add %s; %s" % (attempted_id, detail))
    emit_add_activity("failed", attempted_id, comicname=existing_name, reason_detail=detail)
    return {
        "status": "duplicate",
        "comicid": existing_id,
        "comicname": existing_name,
        "error": detail,
    }


def _upsert_placeholder_manga_chapters(mangaid, manga_name, total):
    """Create deterministic placeholder rows for missing integer chapters."""
    if total <= 0:
        return 0

    existing_chapters = set()
    rows = db.select_all(
        select(issues.c.Int_IssueNumber, issues.c.ChapterNumber, issues.c.Issue_Number).where(
            issues.c.ComicID == mangaid
        )
    )
    for row in rows:
        int_issue_number = row.get("Int_IssueNumber")
        if int_issue_number is None:
            chapter_number = row.get("ChapterNumber") or row.get("Issue_Number")
            if chapter_number is not None:
                int_issue_number = configured.issuedigits(str(chapter_number))
        if int_issue_number is not None:
            existing_chapters.add(int_issue_number)

    created = 0
    for chapter_number in range(1, total + 1):
        chapter_number_str = str(chapter_number)
        if configured.issuedigits(chapter_number_str) in existing_chapters:
            continue

        placeholder_id = "%s-ch%s" % (mangaid, chapter_number_str)
        placeholder_values = {
            "IssueID": placeholder_id,
            "ComicID": mangaid,
            "ComicName": manga_name,
            "Issue_Number": chapter_number_str,
            "IssueName": "Chapter %s" % chapter_number_str,
            "Status": "Skipped",
            "Int_IssueNumber": configured.issuedigits(chapter_number_str),
            "ChapterNumber": chapter_number_str,
            "DateAdded": common_dates.now(),
        }
        db.upsert("issues", placeholder_values, {"IssueID": placeholder_id})
        created += 1

    return created


def _populate_manga_chapters(mangaid, manga_name, mangadex_uuid, mal_num_chapters, controlValueDict):
    """Shared helper: fetch chapters and set Total/Have for a manga series.

    Uses a multi-source approach:
    1. Language-filtered chapters from MangaDex (for detailed issue rows)
    2. Language-unfiltered aggregate from MangaDex (for authoritative Total)
    3. MAL num_chapters as fallback (when MangaDex is unavailable)
    4. Explicit 0 as terminal default (never leaves Total/Have as NULL)

    On refresh, existing chapter rows keep their Status and DateAdded so
    Downloaded/Snatched/Wanted/etc. survive metadata updates; only new
    chapters get the default Status. Have is recounted here from chapter
    files and owned volumes, so a refresh never zeroes it.

    Args:
        mangaid: The comic ID used in the database (e.g. 'md-xxx' or 'mal-xxx')
        manga_name: Display name for logging
        mangadex_uuid: MangaDex UUID for chapter fetching (None if unavailable)
        mal_num_chapters: Chapter count from MAL (None if not from MAL)
        controlValueDict: Dict used as WHERE clause for db.upsert
    """
    from comicarr.app.manga import mangadex

    issue_count = 0
    latest_chapter = None
    latest_date = None

    existing_issue_ids = {
        row["IssueID"]
        for row in db.select_all(select(issues.c.IssueID).where(issues.c.ComicID == mangaid))
        if row.get("IssueID")
    }

    if mangadex_uuid:
        mdex_id = series_kind.strip_prefix(mangadex_uuid)

        logger.info("[MANGA-IMPORT] Fetching chapters for: %s" % manga_name)
        chapters = mangadex.get_all_chapters(mdex_id)

        if chapters:
            for chapter in chapters:
                chapter_num = chapter.get("chapter")
                if chapter_num is None:
                    continue

                issue_id = "%s-ch%s" % (mangaid, chapter_num)

                release_date = (
                    chapter.get("release_date") or chapter.get("publish_at", "")[:10]
                    if chapter.get("publish_at")
                    else None
                )

                issue_values = {
                    "IssueID": issue_id,
                    "ComicID": mangaid,
                    "ComicName": manga_name,
                    "Issue_Number": str(chapter_num),
                    "IssueName": chapter.get("title") or ("Chapter %s" % chapter_num),
                    "ReleaseDate": release_date,
                    "IssueDate": release_date,
                    "Int_IssueNumber": configured.issuedigits(chapter_num),
                    "ChapterNumber": str(chapter_num),
                    "VolumeNumber": str(chapter.get("volume")) if chapter.get("volume") else None,
                }
                if issue_id not in existing_issue_ids:
                    issue_status = "Skipped"
                    if runtime.current().config.AUTOWANT_ALL:
                        issue_status = "Wanted"
                    issue_values["Status"] = issue_status
                    issue_values["DateAdded"] = common_dates.now()

                db.upsert("issues", issue_values, {"IssueID": issue_id})
                issue_count += 1

                try:
                    chapter_float = float(chapter_num)
                    if latest_chapter is None:
                        latest_chapter = chapter_num
                        latest_date = release_date
                    else:
                        try:
                            if chapter_float > float(latest_chapter):
                                latest_chapter = chapter_num
                                latest_date = release_date
                        except ValueError:
                            latest_chapter = chapter_num
                            latest_date = release_date
                except ValueError:
                    if latest_chapter is None:
                        latest_chapter = chapter_num
                        latest_date = release_date

            logger.info("[MANGA-IMPORT] Added %d chapters for %s" % (issue_count, manga_name))

        total_from_aggregate = mangadex.get_total_chapter_count(mdex_id)

        if total_from_aggregate > 0:
            total = max(total_from_aggregate, issue_count)

        else:
            total = issue_count
    else:
        logger.warn("[MANGA-IMPORT] No MangaDex UUID for %s — cannot fetch chapters" % manga_name)
        total = 0

    if total == 0 and mal_num_chapters is not None:
        try:
            total = int(float(mal_num_chapters))
            logger.info("[MANGA-IMPORT] Using MAL chapter count for %s: %d" % (manga_name, total))
        except (ValueError, TypeError):
            logger.error("[MANGA-IMPORT] Invalid MAL chapter count for %s: %s" % (manga_name, mal_num_chapters))

    placeholder_count = _upsert_placeholder_manga_chapters(mangaid, manga_name, total)
    if placeholder_count:
        logger.info(
            "[MANGA-IMPORT] Generated %d missing placeholder chapters for %s (total: %d, detailed: %d)"
            % (placeholder_count, manga_name, total, issue_count)
        )

    update_values = {
        "Total": total,
        "Have": 0,
        "LatestIssue": str(latest_chapter) if latest_chapter else "0",
        "LatestDate": latest_date or "Unknown",
    }
    db.upsert("comics", update_values, controlValueDict)
    from comicarr.app.manga import volumes as manga_volumes

    manga_volumes.recount_have(mangaid)

    if total == 0:
        logger.warn(
            "[MANGA-IMPORT] 0 chapters found for %s (languages: %s). "
            "Check MangaDex content rating and language settings."
            % (manga_name, runtime.current().config.MANGADEX_LANGUAGES or "en")
        )

    return {"total": total, "issue_count": issue_count, "latest_chapter": latest_chapter}


def _manga_series_folder(manga_dest, manga_name, manga_year):
    """The library folder for a manga Series being added.

    Uses the folder format ("$Series ($Year)" by default), unless that folder
    does not exist yet and one named for the plain title does. Manga libraries
    built by hand or by other tools usually use the plain title, and creating
    the formatted folder beside it left two folders for one Series, with
    Comicarr watching the empty one.
    """
    folder_format = runtime.current().config.FOLDER_FORMAT or "$Series ($Year)"
    formatted = common_strings.filesafe(folder_format.replace("$Series", manga_name).replace("$Year", str(manga_year)))
    root = os.path.normpath(os.path.abspath(manga_dest))
    formatted_path = os.path.join(manga_dest, formatted)
    checked_formatted = os.path.normpath(os.path.join(root, formatted))
    plain_path = os.path.normpath(os.path.join(root, common_strings.filesafe(manga_name)))
    if not checked_formatted.startswith(root + os.sep) or not plain_path.startswith(root + os.sep):
        return formatted_path
    if plain_path != checked_formatted and not os.path.isdir(checked_formatted) and os.path.isdir(plain_path):
        logger.info("[MANGA] Using the existing folder %s for %s" % (plain_path, manga_name))
        return plain_path
    return formatted_path


def add_mangadex(mangaid, imported=None, calledfrom=None, location=None):
    """
    Add a manga from MangaDex to the database.

    Args:
        mangaid: MangaDex manga ID (prefixed with 'md-')
        imported: Import information if coming from file import
        calledfrom: Calling context

    Returns:
        dict with status information
    """
    from comicarr.app.config.ini import get_manga_destination
    from comicarr.app.manga import mangadex
    from comicarr.app.manga.duplicates import find_existing_manga_series

    logger.info("[MANGADEX] Adding manga with ID: %s" % mangaid)

    mangadex_uuid = series_kind.strip_prefix(mangaid)

    controlValueDict = {"ComicID": mangaid}

    with db.get_engine().connect() as conn:
        stmt = select(comics).where(comics.c.ComicID == mangaid)
        dbmanga = next((dict(row._mapping) for row in conn.execute(stmt)), None)

    if dbmanga is not None:
        if dbmanga["Status"] == "Active":
            series_status = "Active"
        elif dbmanga["Status"] == "Paused":
            series_status = "Paused"
        else:
            series_status = "Loading"
        comlocation = dbmanga["ComicLocation"]
    else:
        series_status = "Loading"
        comlocation = location

    if dbmanga is None:
        manga = mangadex.get_manga_details(mangaid)
        if not manga:
            logger.error("[MANGADEX] Error fetching manga details for: %s" % mangaid)
            db.upsert(
                "comics",
                {"ComicName": "Fetch failed, try refreshing. (%s)" % mangaid, "Status": "Active"},
                controlValueDict,
            )
            emit_add_activity("failed", mangaid, reason_detail="MangaDex details fetch failed")
            return {"status": "incomplete"}
        existing = find_existing_manga_series(
            comic_id=mangaid,
            mal_id=manga.get("mal_id"),
            mangadex_id=mangadex_uuid,
        )
        if existing:
            return _refuse_duplicate_manga(mangaid, existing)

    db.upsert("comics", {"Status": "Loading"}, controlValueDict)

    if dbmanga is not None:
        manga = mangadex.get_manga_details(mangaid)
        if not manga:
            logger.error("[MANGADEX] Error fetching manga details for: %s" % mangaid)
            restore_status = series_status if series_status != "Loading" else "Active"
            db.upsert("comics", {"Status": restore_status}, controlValueDict)
            emit_add_activity("failed", mangaid, reason_detail="MangaDex details fetch failed")
            return {"status": "incomplete"}

    manga_name = manga.get("name", "Unknown")
    manga_year = manga.get("year") or "0000"
    description = manga.get("description", "No description available")

    logger.info("[MANGADEX] Now adding: %s (%s)" % (manga_name, manga_year))

    if manga_name.startswith("The "):
        sortname = manga_name[4:]
    else:
        sortname = manga_name

    dynamic_name = dynamic_series_key(manga_name)

    manga_dest = get_manga_destination()
    if manga_dest and not comlocation:
        comlocation = _manga_series_folder(manga_dest, manga_name, manga_year)

        if runtime.current().config.CREATE_FOLDERS:
            checkdirectory = directories.validateAndCreateDirectory(comlocation, True)
            if not checkdirectory:
                logger.warn("[MANGADEX] Error creating directory for %s" % manga_name)
    elif comlocation is None:
        comlocation = None

    md_status = manga.get("status", "unknown")
    status_mapping = {"ongoing": "Continuing", "completed": "Ended", "hiatus": "Continuing", "cancelled": "Ended"}
    comic_published = status_mapping.get(md_status, "Unknown")

    comic_values = {
        "ComicID": mangaid,
        "ComicName": manga_name,
        "ComicSortName": sortname,
        "ComicYear": str(manga_year),
        "Status": series_status if series_status != "Loading" else "Active",
        "ComicPublished": comic_published,
        "ComicPublisher": manga.get("author", "Unknown"),
        "Description": description[:4000] if description else None,
        "ComicImage": manga.get("cover_url"),
        "ComicImageURL": manga.get("cover_url"),
        "DetailURL": manga.get("url"),
        "DynamicComicName": dynamic_name,
        "ComicLocation": comlocation,
        "dirlocked": 1 if location else (dbmanga or {}).get("dirlocked"),
        "Type": "Manga",
        "ContentType": (
            dbmanga["ContentType"]
            if dbmanga is not None and dbmanga.get("ContentType") in ("comic", "manga")
            else "manga"
        ),
        "ReadingDirection": "rtl",
        "MetadataSource": "mangadex",
        "ExternalID": mangadex_uuid,
        "MangaDexID": mangadex_uuid,
        "MalID": manga.get("mal_id") or (dbmanga or {}).get("MalID"),
        "LastUpdated": common_dates.now(),
        "DateAdded": common_dates.today() if dbmanga is None else dbmanga.get("DateAdded", common_dates.today()),
    }

    alt_titles = manga.get("alt_titles", [])
    if alt_titles:
        comic_values["AlternateSearch"] = "##".join(alt_titles[:5])

    db.upsert("comics", comic_values, controlValueDict)

    cover_url = manga.get("cover_url")
    if cover_url:
        try:
            covercheck = metadata_service.getImage(mangaid, cover_url)
            if covercheck["status"] == "retry":
                logger.info("[MANGADEX] Retrying alternate cover image for: %s" % manga_name)
            elif covercheck["status"] == "success":
                db.upsert(
                    "comics",
                    {"ComicImage": common_strings.replacetheslash(os.path.join("cache", str(mangaid) + ".jpg"))},
                    controlValueDict,
                )
        except Exception as e:
            logger.warn("[MANGADEX] Failed to cache cover for %s: %s" % (manga_name, e))

    _populate_manga_chapters(mangaid, manga_name, mangadex_uuid, None, controlValueDict)

    series_service.ComicSort(comicorder=runtime.current().comic_sort, imported=mangaid)

    logger.info("[MANGADEX] Successfully added manga: %s" % manga_name)
    emit_add_activity("succeeded", mangaid, comicname=manga_name)

    return {"status": "complete", "comicid": mangaid, "comicname": manga_name, "content_type": "manga"}


def add_myanimelist(mangaid, imported=None, calledfrom=None, location=None):
    """Add a manga from MyAnimeList to the database, with chapters from MangaDex.

    1. Fetch metadata from MAL (title, images, synopsis, status, authors)
    2. Find corresponding MangaDex entry for chapter data
    3. Store in comics table with MetadataSource="mal"
    4. Fetch chapters from MangaDex and store as issues

    Args:
        mangaid: MAL manga ID (prefixed with 'mal-')
        imported: Import information if coming from file import
        calledfrom: Calling context

    Returns:
        dict with status information
    """
    from comicarr.app.config.ini import get_manga_destination
    from comicarr.app.manga import mangadex, myanimelist
    from comicarr.app.manga.duplicates import find_existing_manga_series

    logger.info("[MAL] Adding manga with ID: %s" % mangaid)

    mal_numeric_id = series_kind.strip_prefix(mangaid)
    mangaid = series_kind.add_prefix(mangaid, series_kind.SeriesProvider.MYANIMELIST)

    controlValueDict = {"ComicID": mangaid}

    with db.get_engine().connect() as conn:
        stmt = select(comics).where(comics.c.ComicID == mangaid)
        dbmanga = next((dict(row._mapping) for row in conn.execute(stmt)), None)

    if dbmanga is not None:
        if dbmanga["Status"] == "Active":
            series_status = "Active"
        elif dbmanga["Status"] == "Paused":
            series_status = "Paused"
        else:
            series_status = "Loading"
        comlocation = dbmanga["ComicLocation"]
    else:
        series_status = "Loading"
        comlocation = location

    mangadex_uuid = None
    resolved_mangadex = False
    if dbmanga is None:
        manga = myanimelist.get_manga_details(mangaid)
        if not manga:
            logger.error("[MAL] Error fetching manga details for: %s" % mangaid)
            db.upsert(
                "comics",
                {"ComicName": "Fetch failed, try refreshing. (%s)" % mangaid, "Status": "Active"},
                controlValueDict,
            )
            emit_add_activity("failed", mangaid, reason_detail="MyAnimeList details fetch failed")
            return {"status": "incomplete"}
        mangadex_uuid = mangadex.find_by_mal_id(
            mal_numeric_id,
            title_hint=manga.get("name"),
            alternate_titles=manga.get("alt_titles", []),
            allow_title_match=False,
        )
        resolved_mangadex = True
        existing = find_existing_manga_series(
            comic_id=mangaid,
            mal_id=mal_numeric_id,
            mangadex_id=mangadex_uuid,
        )
        if existing:
            return _refuse_duplicate_manga(mangaid, existing)

    db.upsert("comics", {"Status": "Loading"}, controlValueDict)

    if dbmanga is not None:
        manga = myanimelist.get_manga_details(mangaid)
        if not manga:
            logger.error("[MAL] Error fetching manga details for: %s" % mangaid)
            restore_status = series_status if series_status != "Loading" else "Active"
            db.upsert("comics", {"Status": restore_status}, controlValueDict)
            emit_add_activity("failed", mangaid, reason_detail="MyAnimeList details fetch failed")
            return {"status": "incomplete"}

    manga_name = manga.get("name", "Unknown")
    manga_year = manga.get("year") or "0000"
    description = manga.get("description", "No description available")

    logger.info("[MAL] Now adding: %s (%s)" % (manga_name, manga_year))

    if manga_name.startswith("The "):
        sortname = manga_name[4:]
    else:
        sortname = manga_name

    dynamic_name = dynamic_series_key(manga_name)

    manga_dest = get_manga_destination()
    if manga_dest and not comlocation:
        comlocation = _manga_series_folder(manga_dest, manga_name, manga_year)

        if runtime.current().config.CREATE_FOLDERS:
            checkdirectory = directories.validateAndCreateDirectory(comlocation, True)
            if not checkdirectory:
                logger.warn("[MAL] Error creating directory for %s" % manga_name)
    elif comlocation is None:
        comlocation = None

    md_status = manga.get("status", "unknown")
    status_mapping = {"ongoing": "Continuing", "completed": "Ended", "hiatus": "Continuing", "cancelled": "Ended"}
    comic_published = status_mapping.get(md_status, "Unknown")

    if not resolved_mangadex:
        mangadex_uuid = mangadex.find_by_mal_id(
            mal_numeric_id,
            title_hint=manga_name,
            alternate_titles=manga.get("alt_titles", []),
        )

    comic_values = {
        "ComicID": mangaid,
        "ComicName": manga_name,
        "ComicSortName": sortname,
        "ComicYear": str(manga_year),
        "Status": series_status if series_status != "Loading" else "Active",
        "ComicPublished": comic_published,
        "ComicPublisher": manga.get("author", "Unknown"),
        "Description": description[:4000] if description else None,
        "ComicImage": manga.get("cover_url"),
        "ComicImageURL": manga.get("cover_url"),
        "DetailURL": manga.get("url"),
        "DynamicComicName": dynamic_name,
        "ComicLocation": comlocation,
        "dirlocked": 1 if location else (dbmanga or {}).get("dirlocked"),
        "Type": "Manga",
        "ContentType": (
            dbmanga["ContentType"]
            if dbmanga is not None and dbmanga.get("ContentType") in ("comic", "manga")
            else "manga"
        ),
        "ReadingDirection": "rtl",
        "MetadataSource": "mal",
        "ExternalID": mal_numeric_id,
        "MalID": mal_numeric_id,
        "MangaDexID": mangadex_uuid,
        "LastUpdated": common_dates.now(),
        "DateAdded": common_dates.today() if dbmanga is None else dbmanga.get("DateAdded", common_dates.today()),
    }

    alt_titles = manga.get("alt_titles", [])
    if alt_titles:
        comic_values["AlternateSearch"] = "##".join(alt_titles[:5])

    db.upsert("comics", comic_values, controlValueDict)

    cover_url = manga.get("cover_url")
    if cover_url:
        try:
            covercheck = metadata_service.getImage(mangaid, cover_url)
            if covercheck["status"] == "retry":
                logger.info("[MAL] Retrying alternate cover image for: %s" % manga_name)
            elif covercheck["status"] == "success":
                db.upsert(
                    "comics",
                    {"ComicImage": common_strings.replacetheslash(os.path.join("cache", str(mangaid) + ".jpg"))},
                    controlValueDict,
                )
        except Exception as e:
            logger.warn("[MAL] Failed to cache cover for %s: %s" % (manga_name, e))

    mal_num_chapters = manga.get("last_chapter")
    _populate_manga_chapters(mangaid, manga_name, mangadex_uuid, mal_num_chapters, controlValueDict)

    series_service.ComicSort(comicorder=runtime.current().comic_sort, imported=mangaid)

    logger.info("[MAL] Successfully added manga: %s" % manga_name)
    emit_add_activity("succeeded", mangaid, comicname=manga_name)

    return {"status": "complete", "comicid": mangaid, "comicname": manga_name, "content_type": "manga"}
