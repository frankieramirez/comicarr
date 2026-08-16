#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Series domain queries — comics, issues, annuals, importresults tables.

Uses SQLAlchemy Core via the existing db module.
"""

from sqlalchemy import delete, func, literal, or_, select

from comicarr import db
from comicarr.app.core.database import paginated_query  # noqa: F401 — re-exported
from comicarr.tables import acquisition_run_items as t_acquisition_run_items
from comicarr.tables import annuals as t_annuals
from comicarr.tables import comics as t_comics
from comicarr.tables import importresults as t_importresults
from comicarr.tables import issues as t_issues
from comicarr.tables import storyarcs as t_storyarcs
from comicarr.tables import upcoming as t_upcoming

# ---------------------------------------------------------------------------
# Column projections (matching api.py _*_COLUMNS)
# ---------------------------------------------------------------------------

COMICS_COLUMNS = [
    t_comics.c.ComicID.label("ComicID"),
    t_comics.c.ComicName.label("ComicName"),
    t_comics.c.ComicImage.label("ComicImage"),
    t_comics.c.ComicImageURL.label("ComicImageURL"),
    t_comics.c.Status.label("Status"),
    t_comics.c.ComicPublisher.label("ComicPublisher"),
    t_comics.c.ComicYear.label("ComicYear"),
    t_comics.c.LatestIssue.label("LatestIssue"),
    t_comics.c.LatestDate.label("LatestDate"),
    t_comics.c.LastUpdated.label("LastUpdated"),
    t_comics.c.Description.label("Description"),
    t_comics.c.Total.label("Total"),
    t_comics.c.Have.label("Have"),
    t_comics.c.DetailURL.label("DetailURL"),
    t_comics.c.ComicLocation.label("ComicLocation"),
    t_comics.c.ContentType.label("ContentType"),
    t_comics.c.AllowPacks.label("AllowPacks"),
    t_comics.c.IgnoreType.label("IgnoreType"),
    t_comics.c.BareNumberMode.label("BareNumberMode"),
    t_comics.c.MonitorMode.label("MonitorMode"),
    t_comics.c.MangaDexID.label("MangaDexID"),
]

ISSUES_COLUMNS = [
    t_issues.c.IssueID.label("id"),
    t_issues.c.IssueName.label("name"),
    t_issues.c.ImageURL.label("imageURL"),
    t_issues.c.Issue_Number.label("number"),
    t_issues.c.ReleaseDate.label("releaseDate"),
    t_issues.c.IssueDate.label("issueDate"),
    t_issues.c.Status.label("status"),
    t_issues.c.AcquisitionIntent.label("acquisitionIntent"),
    t_issues.c.Location.label("location"),
    t_issues.c.DigitalDate.label("digitalDate"),
    t_issues.c.ComicID.label("comicId"),
    t_issues.c.ComicName.label("comicName"),
    t_issues.c.ChapterNumber.label("chapterNumber"),
    t_issues.c.VolumeNumber.label("volumeNumber"),
]

ANNUALS_COLUMNS = [
    t_annuals.c.IssueID.label("id"),
    t_annuals.c.IssueName.label("name"),
    t_annuals.c.Issue_Number.label("number"),
    t_annuals.c.ReleaseDate.label("releaseDate"),
    t_annuals.c.IssueDate.label("issueDate"),
    t_annuals.c.Status.label("status"),
    t_annuals.c.AcquisitionIntent.label("acquisitionIntent"),
    t_annuals.c.Location.label("location"),
    t_annuals.c.DigitalDate.label("digitalDate"),
    t_annuals.c.ComicID.label("comicId"),
    t_annuals.c.ComicName.label("comicName"),
]


# ---------------------------------------------------------------------------
# Series (comics) queries
# ---------------------------------------------------------------------------


def library_cover_src(comic_id):
    """Same-origin cover URL for a library series.

    The browser must load covers through ``GET /api/metadata/art/{id}``
    (cache-first, server-side fallback). Never return a provider CDN URL
    here — MangaDex hotlink-protects ``uploads.mangadex.org``.
    """
    if not comic_id:
        return None
    return "/api/metadata/art/%s" % comic_id


def with_library_cover_src(row):
    """Copy a comics row and point ComicImage at the same-origin art URL."""
    if row is None:
        return None
    item = dict(row)
    src = library_cover_src(item.get("ComicID"))
    if src:
        item["ComicImage"] = src
    return item


def list_comics():
    """List all comics ordered by sort name."""
    return db.select_all(select(*COMICS_COLUMNS).order_by(t_comics.c.ComicSortName))


def list_comics_paginated(limit, offset=0):
    """List comics with pagination."""
    stmt = select(*COMICS_COLUMNS).order_by(t_comics.c.ComicSortName)
    return paginated_query(stmt, limit=limit, offset=offset)


def get_comic(comic_id):
    """Get a single comic's summary columns."""
    stmt = select(*COMICS_COLUMNS).where(t_comics.c.ComicID == comic_id)
    return db.select_all(stmt)


def get_comic_for_delete(comic_id):
    """Get comic name/year/location for deletion confirmation."""
    return db.select_one(
        select(t_comics.c.ComicName, t_comics.c.ComicYear, t_comics.c.ComicLocation).where(
            t_comics.c.ComicID == comic_id
        )
    )


def get_comic_name(comic_id):
    """Get just the comic name for a given ID."""
    row = db.select_one(select(t_comics.c.ComicName).where(t_comics.c.ComicID == comic_id))
    return row["ComicName"] if row else None


def get_comic_for_import(comic_id):
    """Get series fields needed to finalize manual imports."""
    return db.select_one(
        select(t_comics.c.ComicID, t_comics.c.ComicName, t_comics.c.ComicLocation).where(t_comics.c.ComicID == comic_id)
    )


def get_comic_for_refresh(comic_id):
    """Get comic name/year for refresh validation."""
    return db.select_one(select(t_comics.c.ComicName, t_comics.c.ComicYear).where(t_comics.c.ComicID == comic_id))


def get_search_candidate_state(issue_id, entity_type=None):
    """Return current intent/fulfillment and series state for eligibility."""
    sources = (
        (t_issues, t_issues.c.IssueID, ()),
        (
            t_annuals,
            t_annuals.c.IssueID,
            (or_(t_annuals.c.Deleted.is_(None), t_annuals.c.Deleted != 1),),
        ),
        (t_storyarcs, t_storyarcs.c.IssueArcID, ()),
    )
    normalized_type = str(entity_type or "").strip().lower()
    if normalized_type == "issue":
        sources = sources[:1]
    elif normalized_type == "annual":
        sources = sources[1:2]
    for table, identity, extra_conditions in sources:
        acquisition_intent = (table.c.AcquisitionIntent if "AcquisitionIntent" in table.c else literal(None)).label(
            "AcquisitionIntent"
        )
        stmt = (
            select(
                table.c.Status.label("LegacyStatus"),
                acquisition_intent,
                t_comics.c.Status.label("SeriesStatus"),
            )
            .select_from(table.outerjoin(t_comics, t_comics.c.ComicID == table.c.ComicID))
            .where(identity == str(issue_id), *extra_conditions)
        )
        row = db.select_one(stmt)
        if row is not None:
            return row
    return None


def delete_comic(comic_id):
    """Delete a comic and its issues/upcoming entries in a single transaction."""
    with db.get_engine().begin() as conn:
        conn.execute(delete(t_comics).where(t_comics.c.ComicID == comic_id))
        conn.execute(delete(t_issues).where(t_issues.c.ComicID == comic_id))
        conn.execute(delete(t_upcoming).where(t_upcoming.c.ComicID == comic_id))


def get_comic_search_settings(comic_id):
    """Get the per-series search flags (pack matching / booktype / manga modes)."""
    return db.select_one(
        select(
            t_comics.c.ComicID,
            t_comics.c.AllowPacks,
            t_comics.c.IgnoreType,
            t_comics.c.BareNumberMode,
            t_comics.c.MonitorMode,
        ).where(t_comics.c.ComicID == comic_id)
    )


def update_comic_search_settings(comic_id, values):
    """Persist per-series search flags.

    ``AllowPacks`` is a Text column read as ``== 1 / == "1"`` by search.py, so
    it is stored as "1"/"0" strings; ``IgnoreType`` is an Integer flag column.
    """
    db.upsert("comics", values, {"ComicID": comic_id})


def get_comic_content_kind(comic_id):
    """Get the persisted provider-independent content kind for a Series."""
    return db.select_one(select(t_comics.c.ComicID, t_comics.c.ContentType).where(t_comics.c.ComicID == comic_id))


def update_comic_content_kind(comic_id, content_type):
    """Atomically persist only the Series content-kind field."""
    db.upsert("comics", {"ContentType": content_type}, {"ComicID": comic_id})


def pause_comic(comic_id):
    """Set comic status to Paused."""
    db.upsert("comics", {"Status": "Paused"}, {"ComicID": comic_id})


def resume_comic(comic_id):
    """Set comic status to Active."""
    db.upsert("comics", {"Status": "Active"}, {"ComicID": comic_id})


# ---------------------------------------------------------------------------
# Issue queries
# ---------------------------------------------------------------------------


def get_issues(comic_id):
    """Get all issues for a comic, ordered by issue number descending."""
    stmt = select(*ISSUES_COLUMNS).where(t_issues.c.ComicID == comic_id).order_by(t_issues.c.Int_IssueNumber.desc())
    return db.select_all(stmt)


def get_annuals(comic_id):
    """Get all annuals for a comic."""
    return db.select_all(
        select(*ANNUALS_COLUMNS).where(
            t_annuals.c.ComicID == comic_id,
            or_(t_annuals.c.Deleted.is_(None), t_annuals.c.Deleted != 1),
        )
    )


def queue_issue(issue_id, audit_identity, *, conn=None):
    """Mark an issue as Wanted, optionally in a caller-owned transaction."""
    from comicarr.app.acquisition.models import AcquisitionIntent
    from comicarr.app.acquisition.policy import explicit_intent_values

    values = explicit_intent_values(AcquisitionIntent.WANTED, audit_identity)
    controls = {"IssueID": issue_id}
    if conn is not None:
        db.upsert_conn(conn, "issues", values, controls)
    else:
        db.upsert("issues", values, controls)


def unqueue_issue(issue_id, audit_identity):
    """Mark an issue as Skipped."""
    from comicarr.app.acquisition.models import AcquisitionIntent
    from comicarr.app.acquisition.policy import explicit_intent_values

    db.upsert(
        "issues",
        explicit_intent_values(AcquisitionIntent.SKIPPED, audit_identity),
        {"IssueID": issue_id},
    )


def ignore_issue(issue_id, audit_identity):
    """Mark an issue as Ignored (operator permanent decline; not Skipped)."""
    from comicarr.app.acquisition.models import AcquisitionIntent
    from comicarr.app.acquisition.policy import explicit_intent_values

    db.upsert(
        "issues",
        explicit_intent_values(AcquisitionIntent.IGNORED, audit_identity),
        {"IssueID": issue_id},
    )


# ---------------------------------------------------------------------------
# Wanted queries
# ---------------------------------------------------------------------------


def get_wanted_issues(limit=None, offset=None, search=None):
    """Get all wanted issues joined with comic info.

    When ``search`` is set, ComicName and Issue_Number are matched with a
    case-insensitive substring filter *before* pagination so the page total,
    has_more flag, and returned rows all describe the same filtered set.
    """
    stmt = (
        select(
            t_comics.c.ComicName,
            t_comics.c.ComicYear,
            t_comics.c.ComicVersion,
            t_comics.c.Type.label("BookType"),
            t_comics.c.ComicPublisher,
            t_comics.c.PublisherImprint,
            t_issues.c.Issue_Number,
            t_issues.c.IssueName,
            t_issues.c.ReleaseDate,
            t_issues.c.IssueDate,
            t_issues.c.DigitalDate,
            t_issues.c.Status,
            t_issues.c.ComicID,
            t_issues.c.IssueID,
            t_issues.c.DateAdded,
        )
        .select_from(t_comics.join(t_issues, t_comics.c.ComicID == t_issues.c.ComicID))
        .where(t_issues.c.Status == "Wanted")
    )
    if search and str(search).strip():
        pattern = "%%%s%%" % str(search).strip().lower()
        stmt = stmt.where(
            or_(
                t_comics.c.ComicName.ilike(pattern),
                t_issues.c.Issue_Number.ilike(pattern),
            )
        )
    if limit is not None:
        return paginated_query(stmt, limit=limit, offset=offset)
    return db.select_all(stmt)


def get_wanted_storyarc_issues():
    """Get wanted story arc issues."""
    return db.select_all(
        select(
            t_storyarcs.c.StoryArc,
            t_storyarcs.c.StoryArcID,
            t_storyarcs.c.IssueArcID,
            t_storyarcs.c.ComicName,
            t_storyarcs.c.IssueNumber,
            t_storyarcs.c.IssueName,
            t_storyarcs.c.ReleaseDate,
            t_storyarcs.c.IssueDate,
            t_storyarcs.c.DigitalDate,
            t_storyarcs.c.Status,
            t_storyarcs.c.ComicID,
            t_storyarcs.c.IssueID,
            t_storyarcs.c.DateAdded,
        ).where(t_storyarcs.c.Status == "Wanted")
    )


def get_wanted_annuals():
    """Get wanted annuals joined with comic info."""
    return db.select_all(
        select(
            t_annuals.c.ReleaseComicName.label("ComicName"),
            t_comics.c.ComicYear,
            t_comics.c.ComicVersion,
            t_comics.c.Type.label("BookType"),
            t_comics.c.ComicPublisher,
            t_comics.c.PublisherImprint,
            t_comics.c.ComicName.label("SeriesName"),
            t_annuals.c.Issue_Number.label("Issue_Number"),
            t_annuals.c.IssueName,
            t_annuals.c.ReleaseDate,
            t_annuals.c.IssueDate,
            t_annuals.c.DigitalDate,
            t_annuals.c.Status,
            t_annuals.c.ComicID,
            t_annuals.c.IssueID,
            t_annuals.c.ReleaseComicID.label("SeriesComicID"),
            t_annuals.c.DateAdded,
        )
        .select_from(t_comics.join(t_annuals, t_comics.c.ComicID == t_annuals.c.ComicID))
        .where(t_annuals.c.Deleted != 1)
        .where(t_annuals.c.Status == "Wanted")
    )


def get_latest_search_items_by_entity_ids(entity_ids):
    """Return the latest search run item per entity id (live-and-sticky annotation).

    "Latest" is the most recently updated ``acquisition_run_items`` row for
    ``command_kind='search'`` on entity types ``issue`` / ``annual``. A closed
    run keeps annotating until a newer run supersedes that entity. Membership
    of Wanted is not decided here — callers only attach fields.
    """
    ids = []
    seen = set()
    for raw in entity_ids or []:
        entity_id = str(raw).strip() if raw is not None else ""
        if not entity_id or entity_id in seen:
            continue
        seen.add(entity_id)
        ids.append(entity_id)
    if not ids:
        return {}

    row_number = func.row_number().over(
        partition_by=(
            t_acquisition_run_items.c.entity_type,
            t_acquisition_run_items.c.entity_id,
        ),
        order_by=(
            t_acquisition_run_items.c.updated_at.desc(),
            t_acquisition_run_items.c.item_id.desc(),
        ),
    )
    ranked = (
        select(
            t_acquisition_run_items.c.item_id,
            t_acquisition_run_items.c.run_id,
            t_acquisition_run_items.c.entity_type,
            t_acquisition_run_items.c.entity_id,
            t_acquisition_run_items.c.state,
            t_acquisition_run_items.c.attempt_count,
            t_acquisition_run_items.c.reason,
            t_acquisition_run_items.c.updated_at,
            t_acquisition_run_items.c.completed_at,
            row_number.label("rn"),
        )
        .where(t_acquisition_run_items.c.command_kind == "search")
        .where(t_acquisition_run_items.c.entity_type.in_(("issue", "annual")))
        .where(t_acquisition_run_items.c.entity_id.in_(ids))
        .subquery()
    )
    rows = db.select_all(select(ranked).where(ranked.c.rn == 1))
    # One annotation key per IssueID. If both an issue and annual row somehow
    # share an id (should not), the later row in the result set wins — callers
    # always key by the Wanted row's IssueID alone.
    latest = {}
    for row in rows:
        latest[str(row["entity_id"])] = {
            "state": row["state"],
            "attempt_count": int(row["attempt_count"] or 0),
            "reason": row["reason"],
            "run_id": row["run_id"],
            "entity_type": row["entity_type"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
        }
    return latest


# ---------------------------------------------------------------------------
# Import queries
# ---------------------------------------------------------------------------


def get_import_pending(limit=50, offset=0, include_ignored=False):
    """Get pending import files grouped by DynamicName/Volume with pagination."""
    ir = t_importresults
    group_key_expr = func.coalesce(
        func.nullif(ir.c.DynamicName, ""),
        func.nullif(ir.c.ComicName, ""),
        ir.c.impID,
    )

    base_conds = [
        (ir.c.WatchMatch.is_(None)) | (ir.c.WatchMatch.like("C%")),
        ir.c.Status != "Imported",
    ]
    if not include_ignored:
        base_conds.append((ir.c.IgnoreFile.is_(None)) | (ir.c.IgnoreFile == 0))

    # Count distinct groups. New import-inbox rows always carry DynamicName;
    # older rows fall back to ComicName so they remain reviewable.
    group_count_subq = (
        select(group_key_expr.label("GroupKey"), ir.c.Volume).where(*base_conds).group_by(group_key_expr, ir.c.Volume)
    )
    count_stmt = select(func.count()).select_from(group_count_subq.subquery())
    file_count_stmt = select(func.count()).select_from(ir).where(*base_conds)
    with db.get_engine().connect() as conn:
        total = conn.execute(count_stmt).scalar() or 0
        file_total = conn.execute(file_count_stmt).scalar() or 0

    # Get paginated groups
    group_stmt = (
        select(
            group_key_expr.label("GroupKey"),
            func.min(ir.c.ComicName).label("ComicName"),
            ir.c.Volume.label("Volume"),
            func.min(ir.c.ComicYear).label("ComicYear"),
            func.min(ir.c.Status).label("Status"),
            func.min(ir.c.SRID).label("SRID"),
            func.min(ir.c.ComicID).label("ComicID"),
            func.min(ir.c.SuggestedComicID).label("SuggestedComicID"),
            func.min(ir.c.SuggestedComicName).label("SuggestedComicName"),
            func.count().label("FileCount"),
        )
        .where(*base_conds)
        .group_by(group_key_expr, ir.c.Volume)
        .order_by(func.min(ir.c.ComicName))
        .limit(limit)
        .offset(offset)
    )
    results = db.select_all(group_stmt)

    imports = []
    for result in results:
        dynamic_name = result["GroupKey"]
        volume = result["Volume"]

        # Get all files for this group
        file_conds = list(base_conds)
        file_conds.append(group_key_expr == dynamic_name)

        if volume is None or volume == "None":
            file_conds.append((ir.c.Volume.is_(None)) | (ir.c.Volume == "None"))
        else:
            file_conds.append(ir.c.Volume == volume)

        files = db.select_all(select(ir).where(*file_conds).order_by(ir.c.ComicFilename))

        file_list = []
        for f in files:
            file_list.append(
                {
                    "impID": f["impID"],
                    "ComicFilename": f["ComicFilename"],
                    "ComicLocation": f["ComicLocation"],
                    "IssueNumber": f["IssueNumber"],
                    "ComicYear": f["ComicYear"],
                    "Status": f["Status"],
                    "IgnoreFile": f["IgnoreFile"] or 0,
                    "MatchConfidence": f["MatchConfidence"],
                    "SuggestedComicID": f["SuggestedComicID"],
                    "SuggestedComicName": f["SuggestedComicName"],
                    "SuggestedIssueID": f["SuggestedIssueID"],
                    "MatchSource": f["MatchSource"],
                }
            )

        confidences = [f["MatchConfidence"] for f in file_list if f["MatchConfidence"] is not None]
        avg_confidence = sum(confidences) // len(confidences) if confidences else None

        imports.append(
            {
                "DynamicName": dynamic_name,
                "ComicName": result["ComicName"],
                "Volume": volume,
                "ComicYear": result["ComicYear"],
                "FileCount": result["FileCount"],
                "Status": result["Status"],
                "SRID": result["SRID"],
                "ComicID": result["ComicID"],
                "MatchConfidence": avg_confidence,
                "SuggestedComicID": result["SuggestedComicID"],
                "SuggestedComicName": result["SuggestedComicName"],
                "files": file_list,
            }
        )

    return {
        "imports": imports,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total,
        },
        "summary": {
            "group_count": total,
            "file_count": file_total,
        },
    }


def get_import_row(imp_id):
    """Get one raw import row by impID."""
    return db.select_one(select(t_importresults).where(t_importresults.c.impID == imp_id))


def update_import_issue_number(imp_id, issue_number):
    """Update editable file-level import metadata."""
    db.upsert("importresults", {"IssueNumber": issue_number}, {"impID": imp_id})


def ignore_import(imp_id, ignore=True):
    """Mark an import file as ignored or unignored."""
    db.upsert("importresults", {"IgnoreFile": 1 if ignore else 0}, {"impID": imp_id})


def delete_import(imp_id):
    """Delete an import record."""
    with db.get_engine().begin() as conn:
        conn.execute(delete(t_importresults).where(t_importresults.c.impID == imp_id))


# ---------------------------------------------------------------------------
# REST-compat queries (full-row, no column projection)
# ---------------------------------------------------------------------------


def list_comics_full():
    """List all comics with all columns, ordered by sort name.

    Used by the legacy REST /comics endpoint which returns every column.
    """
    return db.select_all(select(t_comics).order_by(t_comics.c.ComicSortName))


def get_comic_full(comic_id):
    """Get a single comic with all columns."""
    return db.select_all(select(t_comics).where(t_comics.c.ComicID == comic_id))


def get_issues_full(comic_id):
    """Get all issues for a comic with all columns."""
    return db.select_all(select(t_issues).where(t_issues.c.ComicID == comic_id))


def get_issue_full(comic_id, issue_id):
    """Get a single issue by comic and issue ID, all columns."""
    return db.select_all(select(t_issues).where(t_issues.c.ComicID == comic_id).where(t_issues.c.IssueID == issue_id))
