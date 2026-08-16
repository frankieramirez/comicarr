#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Activity Center production helpers — journal stage map and run brackets.

Producers call these after a durable transition wins. All narrative inserts
go through :func:`comicarr.app.activity.events.record_activity`.
"""

from __future__ import annotations

import json

from sqlalchemy import select

from comicarr import logger
from comicarr.app.activity.events import publish_activity, record_activity
from comicarr.app.common.redaction import redact_sensitive_text
from comicarr.db import get_engine
from comicarr.tables import annuals, comics, issues

# ---------------------------------------------------------------------------
# pipeline_journal stage → (activity, status)
# reserved / moved are internal (no narrative row).
# failed: download vs import depends on prior stage rank (#426 finding 1).
# ---------------------------------------------------------------------------

# Stages that always map to a single cell (not failed).
_STAGE_CELLS = {
    "snatched": ("grab", "succeeded"),
    "downloaded": ("download", "succeeded"),
    "post_processing": ("import", "started"),
    "post_processed": ("import", "succeeded"),
    "manual_review": ("import", "needs_attention"),
}

# Rank threshold: at/after post_processing the failure is an import failure.
_IMPORT_FAIL_MIN_RANK = 30  # POST_PROCESSING


def _issue_subject(issueid, conn=None):
    """Resolve (subject_type, subject_id, subject_label, parent_series_id) for an issueid.

    Returns None when the issue cannot be resolved to a label. When ``conn`` is
    supplied, resolve on that connection (avoids nested engines under an open
    journal transaction).
    """
    if issueid in (None, ""):
        return None
    sid = str(issueid)

    def _lookup(active_conn):
        row = active_conn.execute(
            select(
                issues.c.IssueID,
                issues.c.ComicID,
                issues.c.ComicName,
                issues.c.Issue_Number,
                comics.c.ComicName.label("series_name"),
                comics.c.ComicYear,
            )
            .select_from(issues.outerjoin(comics, comics.c.ComicID == issues.c.ComicID))
            .where(issues.c.IssueID == sid)
        ).fetchone()
        if row is None:
            row = active_conn.execute(
                select(
                    annuals.c.IssueID,
                    annuals.c.ComicID,
                    annuals.c.ComicName,
                    annuals.c.Issue_Number,
                    comics.c.ComicName.label("series_name"),
                    comics.c.ComicYear,
                )
                .select_from(annuals.outerjoin(comics, comics.c.ComicID == annuals.c.ComicID))
                .where(annuals.c.IssueID == sid)
                .where(annuals.c.Deleted != 1)
            ).fetchone()
            if row is None:
                return None
            subject_type = "annual"
        else:
            subject_type = "issue"

        m = dict(row._mapping)
        name = m.get("ComicName") or m.get("series_name") or "Unknown"
        number = m.get("Issue_Number")
        if number not in (None, ""):
            label = "%s #%s" % (name, number)
        else:
            label = str(name)
        parent = m.get("ComicID")
        return subject_type, sid, label, str(parent) if parent not in (None, "") else None

    try:
        if conn is not None:
            return _lookup(conn)
        with get_engine().connect() as owned:
            return _lookup(owned)
    except Exception as e:
        logger.fdebug("[ACTIVITY] issue subject resolve failed for %s: %s" % (sid, e))
        return None


def _series_label(comicid, comicname=None, seriesyear=None):
    if comicname and seriesyear not in (None, "", "None"):
        return "%s (%s)" % (comicname, seriesyear)
    if comicname:
        return str(comicname)
    if comicid in (None, ""):
        return "series"
    try:
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                select(comics.c.ComicName, comics.c.ComicYear).where(comics.c.ComicID == str(comicid))
            ).fetchone()
            if row is not None:
                name = row._mapping.get("ComicName") or str(comicid)
                year = row._mapping.get("ComicYear")
                if year not in (None, "", "None"):
                    return "%s (%s)" % (name, year)
                return str(name)
    except Exception as e:
        logger.fdebug("[ACTIVITY] series label resolve failed for %s: %s" % (comicid, e))
    return str(comicid)


def emit_for_journal_stage(
    stage,
    *,
    release_key,
    issueid=None,
    provider=None,
    fail_reason=None,
    payload=None,
    prior_stage_rank=None,
    conn=None,
    won=True,
):
    """Emit the legal narrative cell for a won journal stage advance.

    When ``conn`` is supplied the insert co-commits; the caller must
    :func:`publish_activity` after their commit. When ``conn`` is None the
    facade owns the transaction and publishes after commit.
    """
    if not won:
        return None

    cell = _STAGE_CELLS.get(stage)
    if cell is None and stage == "failed":
        if prior_stage_rank is not None and int(prior_stage_rank) >= _IMPORT_FAIL_MIN_RANK:
            cell = ("import", "failed")
        else:
            cell = ("download", "failed")
    if cell is None and stage == "cancelled":
        if prior_stage_rank is not None and int(prior_stage_rank) >= _IMPORT_FAIL_MIN_RANK:
            cell = ("import", "cancelled")
        elif prior_stage_rank is not None and int(prior_stage_rank) >= 20:
            cell = ("download", "cancelled")
        else:
            cell = ("grab", "cancelled")
    if cell is None:
        # reserved / moved / unknown — internal only
        return None

    activity, status = cell
    subject = _issue_subject(issueid, conn=conn)
    if subject is None:
        # Synthetic / one-off / unresolved — still narrate if we have an id.
        if issueid in (None, ""):
            logger.fdebug("[ACTIVITY] skip journal emit stage=%s release_key=%s: no issueid" % (stage, release_key))
            return None
        subject_type, subject_id, subject_label, parent_series_id = (
            "issue",
            str(issueid),
            str(issueid),
            None,
        )
    else:
        subject_type, subject_id, subject_label, parent_series_id = subject

    reason_code = None
    reason_detail = None
    if status in ("failed", "needs_attention", "blocked"):
        reason_code = fail_reason or ("import_failed" if activity == "import" else "download_failed")
        if isinstance(payload, dict):
            detail = payload.get("fail_detail")
            if detail:
                reason_detail = redact_sensitive_text(str(detail))[:1000]

    return record_activity(
        activity,
        status,
        subject_type,
        subject_id,
        subject_label,
        reason_code=reason_code,
        reason_detail=reason_detail,
        provider=provider,
        release_key=release_key,
        parent_series_id=parent_series_id,
        conn=conn,
        won=True,
    )


def emit_run_completion(run):
    """Narrate a closed acquisition search run as ``search.succeeded`` @ ``run``.

    In-flight progress is derived (ledger only) — never call this while the run
    is still open. Counts ride ``reason_detail`` as JSON for the client sentence
    templates (not a table column; optional envelope field).
    """
    if not run or not run.get("run_id"):
        return None
    completion = str(run.get("completion_state") or "")
    if completion in ("pending", "running", ""):
        return None
    # Only narrate search runs (refresh runs use series refresh.* cells).
    if str(run.get("command_kind") or "").strip().lower() != "search":
        return None

    accepted = int(run.get("accepted_count") or 0)
    succeeded = int(run.get("succeeded_count") or 0)
    no_match = int(run.get("no_match_count") or 0)
    failed = int(run.get("failed_count") or 0)
    blocked = int(run.get("blocked_count") or 0)

    counts = {
        "accepted": accepted,
        "grabbed": succeeded,
        "no_match": no_match,
        "failed": failed + blocked,
    }

    # Empty scan that never accepted items vs fruitless provider sweep.
    if accepted == 0:
        reason_code = "nothing_to_search"
        subject_label = "wanted issues"
    elif succeeded == 0 and no_match == accepted:
        reason_code = "no_results"
        subject_label = "wanted issues"
    else:
        reason_code = None
        subject_label = "wanted issues"

    scope_type = run.get("scope_type")
    scope_id = run.get("scope_id")
    if scope_type and scope_id:
        # Keep scope on the run subject for series-scoped timeline filters.
        pass
    else:
        scope_type = None
        scope_id = None

    return record_activity(
        "search",
        "succeeded",
        "run",
        str(run["run_id"]),
        subject_label,
        reason_code=reason_code,
        reason_detail=json.dumps(counts, sort_keys=True, separators=(",", ":")),
        run_id=str(run["run_id"]),
        scope_type=scope_type,
        scope_id=scope_id,
    )


def emit_series_activity(
    activity,
    status,
    comicid,
    *,
    comicname=None,
    seriesyear=None,
    reason_code=None,
    reason_detail=None,
    provider=None,
):
    """Convenience for ``refresh.*`` / ``add.*`` @ series producers."""
    if comicid in (None, ""):
        return None
    label = _series_label(comicid, comicname=comicname, seriesyear=seriesyear)
    return record_activity(
        activity,
        status,
        "series",
        str(comicid),
        label,
        reason_code=reason_code,
        reason_detail=reason_detail,
        provider=provider,
        parent_series_id=str(comicid),
    )


def emit_arc_activity(
    activity,
    status,
    storyarcid,
    storyarcname,
    *,
    reason_code=None,
    reason_detail=None,
):
    """Convenience for ``add.*`` / ``refresh.*`` @ arc producers."""
    if storyarcid in (None, ""):
        return None
    label = storyarcname or str(storyarcid)
    return record_activity(
        activity,
        status,
        "arc",
        str(storyarcid),
        label,
        reason_code=reason_code,
        reason_detail=reason_detail,
    )


def emit_tag_activity(
    status,
    *,
    issueid=None,
    comicid=None,
    comicname=None,
    seriesyear=None,
    reason_code=None,
    reason_detail=None,
    subject_level="issue",
):
    """Metatagger narrative — always ``tag.*``, never ``refresh`` (#430 §3.1)."""
    if subject_level == "series":
        if comicid in (None, ""):
            return None
        label = _series_label(comicid, comicname=comicname, seriesyear=seriesyear)
        return record_activity(
            "tag",
            status,
            "series",
            str(comicid),
            label,
            reason_code=reason_code,
            reason_detail=reason_detail,
            parent_series_id=str(comicid),
        )

    subject = _issue_subject(issueid) if issueid not in (None, "") else None
    if subject is None:
        if comicid in (None, "") and issueid in (None, ""):
            return None
        # Fall back to series subject when the issue row is missing.
        if issueid not in (None, ""):
            return record_activity(
                "tag",
                status,
                "issue",
                str(issueid),
                str(issueid),
                reason_code=reason_code,
                reason_detail=reason_detail,
                parent_series_id=str(comicid) if comicid not in (None, "") else None,
            )
        return emit_tag_activity(
            status,
            comicid=comicid,
            comicname=comicname,
            seriesyear=seriesyear,
            reason_code=reason_code,
            reason_detail=reason_detail,
            subject_level="series",
        )

    subject_type, subject_id, subject_label, parent_series_id = subject
    # tag is legal only @ issue|series (not annual) — map annual → issue cell.
    if subject_type == "annual":
        subject_type = "issue"
    return record_activity(
        "tag",
        status,
        subject_type,
        subject_id,
        subject_label,
        reason_code=reason_code,
        reason_detail=reason_detail,
        parent_series_id=parent_series_id or (str(comicid) if comicid not in (None, "") else None),
    )


def emit_search_cancelled(entity_type, entity_id, *, label=None, reason_code="cancelled_by_operator"):
    """Operator-stopped in-flight search — ``search.cancelled`` @ issue|annual."""
    if entity_id in (None, ""):
        return None
    subject_type = "annual" if str(entity_type or "").strip().lower() == "annual" else "issue"
    return record_activity(
        "search",
        "cancelled",
        subject_type,
        str(entity_id),
        label or str(entity_id),
        reason_code=reason_code,
    )


def emit_grab_cancelled_series(comicid, *, reason_code="pack_reversed", count=None):
    """Pack-reversal producer — ``grab.cancelled`` @ series (#430)."""
    if comicid in (None, ""):
        return None
    label = _series_label(comicid)
    detail = None
    if count is not None:
        detail = json.dumps({"accepted": int(count)}, sort_keys=True, separators=(",", ":"))
    return record_activity(
        "grab",
        "cancelled",
        "series",
        str(comicid),
        label,
        reason_code=reason_code,
        reason_detail=detail,
        parent_series_id=str(comicid),
    )


# Re-export publish for shared-conn call sites that co-commit then publish.
__all__ = [
    "emit_arc_activity",
    "emit_for_journal_stage",
    "emit_grab_cancelled_series",
    "emit_search_cancelled",
    "emit_run_completion",
    "emit_series_activity",
    "emit_tag_activity",
    "publish_activity",
]
