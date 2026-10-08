#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Private reconciliation for non-actionable ``fail_reason`` tokens (#541).

Excluding a reason from the needs-attention band is not free. The band's retry
button was previously the sole recovery path for issues left at
``Status='Snatched'`` after a silent journal-only failure. When a reason is
excluded, this module returns the issue to Wanted and — when the *release*
is dead — blocklists it so the next sweep cannot re-snatch the same source.

Call after (or with) the journal write that records the excluded reason.
Safe no-op for admitted reasons and for ``download_failed_researching``
(already reconciled by ``failed.py``).
"""

from __future__ import annotations

from sqlalchemy import func, or_, select, text

from comicarr import logger
from comicarr.app.attention._policy import base_reason, is_actionable, reconciliation_for

RECONCILE_AUDIT_IDENTITY = "system:band-actionability"
PHANTOM_BACKUP_TABLE = "issues_phantom_backup_969"


def _payload_dict(payload):
    if isinstance(payload, dict):
        return payload
    if payload in (None, ""):
        return {}
    try:
        from comicarr.app.downloads import journal

        loaded = journal.load_payload(payload)
        return loaded if isinstance(loaded, dict) else {}
    except Exception as e:
        logger.fdebug("[ATTENTION] reconciliation payload decode skipped: %s" % e)
        return {}


def _issue_id(*, issueid=None, payload=None):
    if issueid not in (None, ""):
        return str(issueid)
    data = _payload_dict(payload)
    for key in ("issueid", "IssueID"):
        value = data.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _release_identity(*, provider=None, nzbname=None, release_id=None, payload=None, hash=None):
    """Best-effort (ID, Provider, NZBName) for the failed-table blocklist key."""
    data = _payload_dict(payload)
    di = data.get("download_info") if isinstance(data.get("download_info"), dict) else {}

    rid = release_id
    if rid in (None, ""):
        rid = data.get("ddl_id") or data.get("id") or di.get("id") or hash or data.get("hash") or None
    prov = provider if provider not in (None, "") else (data.get("provider") or di.get("provider"))
    name = (
        nzbname if nzbname not in (None, "") else (data.get("nzbname") or data.get("filename") or data.get("nzb_name"))
    )
    return (
        str(rid) if rid not in (None, "") else None,
        str(prov) if prov not in (None, "") else None,
        str(name) if name not in (None, "") else None,
    )


def _blocklist_release(
    *,
    release_id,
    provider,
    nzbname,
    issueid=None,
    comicid=None,
    comicname=None,
    issue_number=None,
    payload=None,
    conn=None,
):
    from comicarr import db, helpers

    data = _payload_dict(payload)
    comicid = comicid if comicid not in (None, "") else data.get("comicid")
    comicname = comicname if comicname not in (None, "") else data.get("comicname") or data.get("series")
    issue_number = (
        issue_number if issue_number not in (None, "") else data.get("issuenumber") or data.get("Issue_Number")
    )

    values = {
        "Status": "Failed",
        "ComicName": comicname,
        "Issue_Number": issue_number,
        "IssueID": issueid,
        "ComicID": comicid,
        "DateFailed": helpers.now(),
    }
    ctrl = {"ID": release_id, "Provider": provider, "NZBName": nzbname}
    if conn is not None:
        db.upsert_conn(conn, "failed", values, ctrl)
    else:
        db.upsert("failed", values, ctrl)
    logger.warn(
        "[BAND-RECONCILE] blocklisted release ID=%s Provider=%s NZBName=%s issueid=%s"
        % (release_id, provider, nzbname, issueid)
    )


def _entity_type_from_payload(payload):
    from comicarr.app.series.queries import normalize_obligation_entity_type

    data = _payload_dict(payload)
    return normalize_obligation_entity_type(data.get("mode"))


def _rewant_issue(issueid, *, payload=None, conn=None):
    from comicarr.app.series import queries as series_queries

    outcome = series_queries.update_obligation_intent(
        issueid,
        RECONCILE_AUDIT_IDENTITY,
        intent="wanted",
        entity_type=_entity_type_from_payload(payload),
        conn=conn,
    )
    if not outcome.get("ok"):
        logger.warn(
            "[BAND-RECONCILE] re-want found no library row issueid=%s (audit=%s)" % (issueid, RECONCILE_AUDIT_IDENTITY)
        )
        return False
    logger.info(
        "[BAND-RECONCILE] re-wanted issueid=%s entity_type=%s (audit=%s)"
        % (issueid, outcome.get("entity_type"), RECONCILE_AUDIT_IDENTITY)
    )
    return True


def reconcile_excluded(
    fail_reason,
    *,
    issueid=None,
    provider=None,
    nzbname=None,
    release_id=None,
    hash=None,
    comicid=None,
    comicname=None,
    issue_number=None,
    payload=None,
    conn=None,
    strict=False,
):
    """Discharge the clause-2 obligation for ``fail_reason``, if any.

    ``strict=True`` propagates persistence failures so the owning Attention
    transaction can roll back instead of committing a stranded exclusion.

    Returns a short status string for tests/logging:
    ``noop`` / ``none`` / ``rewanted`` / ``blocklisted_and_rewanted`` /
    ``rewanted_no_issue`` / ``logged_and_rewanted`` / ``logged_no_issue``.
    """
    obligation = reconciliation_for(fail_reason)
    if obligation is None:
        return "noop"
    if obligation == "none":
        return "none"

    token = base_reason(fail_reason)
    resolved_issue = _issue_id(issueid=issueid, payload=payload)

    if obligation == "rewant_and_log":
        logger.error(
            "[BAND-RECONCILE] immutable/internal exclusion token=%s issueid=%s — "
            "re-wanting if possible; this belongs in logs, not the work queue" % (token, resolved_issue)
        )

    needs_blocklist = obligation == "blocklist_and_rewant"
    needs_rewant = obligation in (
        "rewant",
        "blocklist_and_rewant",
        "rewant_if_issue",
        "rewant_and_log",
    )

    if needs_blocklist:
        rid, prov, name = _release_identity(
            provider=provider,
            nzbname=nzbname,
            release_id=release_id,
            payload=payload,
            hash=hash,
        )
        if rid and prov and name:
            try:
                _blocklist_release(
                    release_id=rid,
                    provider=prov,
                    nzbname=name,
                    issueid=resolved_issue,
                    comicid=comicid,
                    comicname=comicname,
                    issue_number=issue_number,
                    payload=payload,
                    conn=conn,
                )
            except Exception as e:
                logger.error("[BAND-RECONCILE] blocklist failed token=%s ID=%s: %s" % (token, rid, e))
                if strict:
                    raise
        else:
            logger.warn(
                "[BAND-RECONCILE] cannot blocklist token=%s — missing ID/Provider/NZBName "
                "(id=%r provider=%r nzbname=%r); still re-wanting if possible" % (token, rid, prov, name)
            )

    if needs_rewant:
        if not resolved_issue:
            if obligation == "rewant_if_issue":
                logger.fdebug("[BAND-RECONCILE] token=%s has no issue id — nothing to re-want (expected)" % token)
            else:
                logger.warn("[BAND-RECONCILE] token=%s owes re-want but no issue id resolved" % token)
            if obligation == "rewant_and_log":
                return "logged_no_issue"
            return "rewanted_no_issue"
        try:
            if not _rewant_issue(resolved_issue, payload=payload, conn=conn):
                return "rewant_failed"
        except Exception as e:
            logger.error("[BAND-RECONCILE] re-want failed token=%s issueid=%s: %s" % (token, resolved_issue, e))
            if strict:
                raise
            return "rewant_failed"

    if obligation == "rewant_and_log":
        return "logged_and_rewanted"
    if needs_blocklist:
        return "blocklisted_and_rewanted"
    return "rewanted"


def _close_if_already_fulfilled(row):
    """Close a parked row whose work is provably already done. True if closed.

    Runs BEFORE the actionability skip on purpose: an actionable reason is
    exactly what puts a row in front of an operator, and the whole point of this
    check is to establish there is nothing left for them to do. Skipping it for
    actionable rows would exempt every row this is meant to clear.
    """
    try:
        from comicarr.app.downloads.recovery import close_fulfilled_band_row

        if not close_fulfilled_band_row(row):
            return False
    except Exception as e:
        logger.warn("[BAND-RECONCILE] fulfilled-close skipped for release_key=%s: %s" % (row.get("release_key"), e))
        return False
    logger.info(
        "[BAND-RECONCILE] closed release_key=%s, its issue is already Downloaded with a "
        "verified library file, so no operator action can clear it (audit=%s)"
        % (row.get("release_key"), RECONCILE_AUDIT_IDENTITY)
    )
    return True


def _ensure_phantom_backup_table(conn):
    dialect = conn.engine.dialect.name
    false_predicate = "0" if dialect == "sqlite" else "FALSE"
    conn.execute(
        text("CREATE TABLE IF NOT EXISTS %s AS SELECT * FROM issues WHERE %s" % (PHANTOM_BACKUP_TABLE, false_predicate))
    )


def cleanup_phantom_issue_rows():
    """Copy-then-delete issues rows that are annual or story-arc phantoms (#969).

    Phantoms have NULL ComicID and an IssueID that also exists in annuals or
    storyarcs.IssueArcID. A plain DELETE is irreversible, so rows are copied
    into ``issues_phantom_backup_969`` first. Idempotent: a second pass finds
    nothing to copy.
    """
    from comicarr import db
    from comicarr.tables import annuals, issues, storyarcs

    phantom_filter = (issues.c.ComicID.is_(None)) & or_(
        issues.c.IssueID.in_(select(annuals.c.IssueID)),
        issues.c.IssueID.in_(select(storyarcs.c.IssueArcID)),
    )
    engine = db.get_engine()
    with engine.begin() as conn:
        count = conn.execute(select(func.count()).select_from(issues).where(phantom_filter)).scalar() or 0
        if not count:
            return {"copied": 0, "deleted": 0}
        _ensure_phantom_backup_table(conn)
        conn.execute(
            text(
                "INSERT INTO %s SELECT issues.* FROM issues WHERE issues.ComicID IS NULL AND ("
                "EXISTS (SELECT 1 FROM annuals WHERE annuals.IssueID = issues.IssueID) OR "
                "EXISTS (SELECT 1 FROM storyarcs WHERE storyarcs.IssueArcID = issues.IssueID))" % PHANTOM_BACKUP_TABLE
            )
        )
        deleted = conn.execute(issues.delete().where(phantom_filter)).rowcount
    logger.warn(
        "[BAND-RECONCILE] copied %s phantom issues row(s) to %s and deleted %s" % (count, PHANTOM_BACKUP_TABLE, deleted)
    )
    return {"copied": int(count), "deleted": int(deleted)}


def reconcile_existing_excluded_rows():
    """One-shot pass: re-want / blocklist issues stranded by pre-#541 exclusions.

    The band is computed live, so changing admission drops excluded rows on
    deploy with no journal migration. Those rows still leave issues at
    ``Snatched`` unless clause 2 runs. Walk unresolved journal rows whose
    reason is now non-actionable and discharge their obligations.

    Idempotent: re-wanting an already-Wanted issue is a no-op UPDATE; blocklist
    upserts the same failed-table key. Also copies then deletes phantom issues
    rows left by pre-#969 re-wants of annuals and story arcs.
    """
    from sqlalchemy import and_, or_, select

    from comicarr import db
    from comicarr.app.downloads.journal import FAILED, MANUAL_REVIEW, RESOLVED_STATUSES
    from comicarr.tables import pipeline_journal

    phantom_cleanup = cleanup_phantom_issue_rows()

    pre_actionability = and_(
        pipeline_journal.c.stage.in_((FAILED, MANUAL_REVIEW)),
        or_(
            pipeline_journal.c.status.is_(None),
            pipeline_journal.c.status.notin_(RESOLVED_STATUSES),
        ),
    )

    rows = db.select_all(select(pipeline_journal).where(pre_actionability))
    summary = {
        "scanned": 0,
        "acted": 0,
        "closed_fulfilled": 0,
        "skipped_actionable": 0,
        "results": {},
        "phantom_cleanup": phantom_cleanup,
    }
    for row in rows or []:
        summary["scanned"] += 1
        reason = row.get("fail_reason")
        if _close_if_already_fulfilled(row):
            summary["closed_fulfilled"] += 1
            continue
        if is_actionable(reason):
            summary["skipped_actionable"] += 1
            continue
        result = reconcile_excluded(
            reason,
            issueid=row.get("issueid"),
            provider=row.get("provider"),
            nzbname=row.get("nzbname"),
            hash=row.get("hash"),
            payload=row.get("payload_json"),
        )
        summary["acted"] += 1
        summary["results"][result] = summary["results"].get(result, 0) + 1
    if summary["acted"] or summary["closed_fulfilled"] or phantom_cleanup.get("deleted"):
        logger.warn(
            "[BAND-RECONCILE] one-shot stranded-row pass: scanned=%s acted=%s "
            "closed_fulfilled=%s results=%s phantom_cleanup=%s"
            % (
                summary["scanned"],
                summary["acted"],
                summary["closed_fulfilled"],
                summary["results"],
                phantom_cleanup,
            )
        )
    return summary
