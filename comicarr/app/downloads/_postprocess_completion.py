#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Private post-processing completion and recovery facts.

This module deliberately owns the terminal write: deleting the legacy
``nzblog`` anchor and advancing the pipeline journal must commit together.
"""

from sqlalchemy import and_, delete, or_, select

from comicarr import db, logger
from comicarr.app.acquisition.evidence import has_verified_library_file
from comicarr.app.downloads import journal
from comicarr.app.downloads.postprocess_pipeline import PostProcessContext, PostProcessJournalStage
from comicarr.tables import comics, issues, nzblog, storyarcs

_JOURNAL_STAGE = PostProcessJournalStage()
_UNSCOPED = object()


def _is_story_arc_obligation(issue_id):
    if issue_id is None:
        return None
    try:
        row = db.select_one(select(storyarcs.c.IssueArcID).where(storyarcs.c.IssueArcID == str(issue_id)))
    except Exception as e:
        logger.warn("[POSTPROCESS] story-arc discriminator lookup failed for %s: %s" % (issue_id, e))
        return None
    return row is not None


def complete(
    context: PostProcessContext,
    *,
    issue_id=None,
    issue_arc_id=None,
    anchor_ids=(),
    arc_scope=_UNSCOPED,
    database=None,
):
    """Atomically delete completion anchors and write ``post_processed``.

    ``anchor_ids`` and ``arc_scope`` preserve the caller's exact legacy
    predicates while keeping transaction ownership here. Any journal failure
    propagates and rolls back the anchor deletion.
    """
    store = database or db
    with store.get_engine().begin() as conn:
        for anchor_id in anchor_ids:
            predicate = nzblog.c.IssueID == str(anchor_id)
            if arc_scope is not _UNSCOPED:
                predicate = and_(predicate, nzblog.c.SARC == arc_scope)
            conn.execute(delete(nzblog).where(predicate))
        _JOURNAL_STAGE.transition(
            context,
            journal.POST_PROCESSED,
            issue_id=issue_id,
            issue_arc_id=issue_arc_id,
            conn=conn,
        )


def finish_obligation(rkey, row, payload):
    """Finish a physically moved obligation without re-importing it."""
    issue_id = row.get("issueid")
    provider = row.get("provider")
    story_arc = None
    if isinstance(payload, dict) and "mode" in payload:
        story_arc = payload.get("mode") == "story_arc"
    if story_arc is None:
        story_arc = _is_story_arc_obligation(issue_id)

    nzb_name = None
    if isinstance(payload, dict):
        nzb_name = payload.get("nzbname") or payload.get("nzb_name")
    with db.get_engine().begin() as conn:
        if story_arc is False:
            predicate = nzblog.c.IssueID == str(issue_id)
        elif story_arc is True:
            predicate = or_(
                nzblog.c.IssueID == str(issue_id),
                nzblog.c.IssueID == "S" + str(issue_id),
            )
        elif nzb_name:
            predicate = and_(
                or_(
                    nzblog.c.IssueID == str(issue_id),
                    nzblog.c.IssueID == "S" + str(issue_id),
                ),
                nzblog.c.NZBName == nzb_name,
            )
        else:
            predicate = nzblog.c.IssueID == str(issue_id)
        stmt = delete(nzblog).where(predicate)
        if provider:
            stmt = stmt.where(nzblog.c.PROVIDER == provider)
        conn.execute(stmt)
        journal.record_transition(
            rkey,
            journal.POST_PROCESSED,
            payload=payload,
            conn=conn,
            issueid=issue_id,
            provider=provider,
        )


def obligation_already_fulfilled(row):
    """Return true only for verified destination placement evidence."""
    issue_id = row.get("issueid")
    if not issue_id:
        return False
    try:
        issue = db.select_one(
            select(issues.c.Status, issues.c.Location, issues.c.ComicID).where(issues.c.IssueID == str(issue_id))
        )
    except Exception as e:
        logger.warn("[POSTPROCESS] fulfillment lookup failed for issue %s: %s" % (issue_id, e))
        return False
    if not issue or issue.get("Status") != "Downloaded":
        return False
    try:
        series = db.select_one(select(comics.c.ComicLocation).where(comics.c.ComicID == str(issue.get("ComicID"))))
    except Exception as e:
        logger.warn("[POSTPROCESS] fulfillment series lookup failed for issue %s: %s" % (issue_id, e))
        return False
    if not series:
        return False
    return has_verified_library_file(series.get("ComicLocation"), issue.get("Location"))
