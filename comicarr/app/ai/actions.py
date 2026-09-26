#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Confirmed write actions for Library Chat.

The model proposes an action with `{"action_id": ..., "parameters": {...}}`
on the first response line, exactly like read-only query patterns. The
backend resolves the proposal into a preview (`prepare_action`) that is
streamed to the client and persisted on the assistant message. Nothing
writes until the user's session calls `confirm_action`, which re-reads
live row state and applies through the same services the UI uses.
"""

from typing import Literal

from sqlalchemy import select

import comicarr
from comicarr import db, logger
from comicarr.tables import annuals, comics, issues

ACTION_PATTERNS = {
    "add_series": "Add a series to the watchlist (params: query = series name to search providers for)",
    "mark_issues": (
        "Mark issues of a library series as Wanted or Skipped "
        "(params: series_name, status = Wanted|Skipped, scope = all|issues|annuals; scope defaults to all)"
    ),
}

_MARK_TARGET_STATUSES = {"wanted": "Wanted", "skipped": "Skipped"}
_MARK_SCOPES = {"all", "issues", "annuals"}

_OWNED_OR_IN_FLIGHT = {"downloaded", "archived", "snatched", "reserved"}

_MAX_CANDIDATES = 5


def get_action_descriptions():
    """Return the action catalogue formatted for the chat system prompt."""
    return "\n".join("- %s: %s" % (action_id, description) for action_id, description in ACTION_PATTERNS.items())


def _error_proposal(action_id, message):
    return {
        "action_id": action_id,
        "status": "error",
        "summary": "Could not prepare this action.",
        "error": message,
    }


def _resolve_series(name):
    term = str(name or "").strip()
    if not term:
        return None
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = db.select_all(
        select(comics.c.ComicID, comics.c.ComicName, comics.c.ComicYear).where(
            comics.c.ComicName.like("%" + escaped + "%", escape="\\")
        )
    )
    if not rows:
        return None

    def _rank(row):
        candidate = (row.get("ComicName") or "").strip().lower()
        if candidate == term.lower():
            return (0, candidate)
        if candidate.startswith(term.lower()):
            return (1, candidate)
        return (2, candidate)

    rows.sort(key=_rank)
    return rows[0]


def _annuals_enabled(ctx):
    config = getattr(ctx, "config", None)
    if config is not None:
        return bool(getattr(config, "ANNUALS_ON", False))
    return bool(getattr(comicarr, "CONFIG", None) and comicarr.CONFIG.ANNUALS_ON)


def _markable(row, target_status):
    status = str(row.get("Status") or "").strip().lower()
    intent = str(row.get("AcquisitionIntent") or "").strip().lower()
    if status in _OWNED_OR_IN_FLIGHT or "ignored" in (status, intent):
        return False
    return status != target_status.lower()


def _affected_issues(comic_id, target_status, scope, annuals_on):
    affected = []
    if scope in ("all", "issues"):
        for row in db.select_all(
            select(
                issues.c.IssueID,
                issues.c.Issue_Number,
                issues.c.Status,
                issues.c.AcquisitionIntent,
            ).where(issues.c.ComicID == str(comic_id))
        ):
            if _markable(row, target_status):
                affected.append(
                    {
                        "issue_id": row["IssueID"],
                        "number": row.get("Issue_Number"),
                        "kind": "issue",
                        "current_status": row.get("Status"),
                    }
                )
    if scope in ("all", "annuals") and annuals_on:
        for row in db.select_all(
            select(
                annuals.c.IssueID,
                annuals.c.Issue_Number,
                annuals.c.Status,
                annuals.c.AcquisitionIntent,
            ).where(
                annuals.c.ComicID == str(comic_id),
                (annuals.c.Deleted.is_(None)) | (annuals.c.Deleted != 1),
            )
        ):
            if _markable(row, target_status):
                affected.append(
                    {
                        "issue_id": row["IssueID"],
                        "number": row.get("Issue_Number"),
                        "kind": "annual",
                        "current_status": row.get("Status"),
                    }
                )
    return affected


def _prepare_add_series(params, ctx):
    query = str((params or {}).get("query") or "").strip()
    if not query:
        return _error_proposal("add_series", "A series name is required.")

    from comicarr.app.search import service as search_service

    result = search_service.find_comic(ctx, query, type_="comic", mode="series", limit=_MAX_CANDIDATES)
    if isinstance(result, dict) and "error" in result:
        return _error_proposal("add_series", str(result["error"]))

    candidates = []
    for item in (result or {}).get("results") or []:
        comicid = item.get("comicid") or item.get("id")
        if comicid in (None, ""):
            continue
        candidates.append(
            {
                "comicid": str(comicid),
                "name": item.get("comicname") or item.get("name"),
                "year": item.get("comicyear"),
                "publisher": item.get("publisher"),
                "issues": item.get("issues") or item.get("count_of_issues"),
                "image": item.get("image") or item.get("comicimage"),
                "in_library": bool(item.get("in_library")),
            }
        )
        if len(candidates) >= _MAX_CANDIDATES:
            break

    if not candidates:
        return _error_proposal("add_series", "No series matched '%s'." % query)

    return {
        "action_id": "add_series",
        "status": "pending",
        "summary": "Add a series to your library",
        "parameters": {"query": query},
        "preview": {"query": query, "candidates": candidates},
    }


def _prepare_mark_issues(params, ctx):
    params = params or {}
    status = str(params.get("status") or "").strip().lower()
    if status not in _MARK_TARGET_STATUSES:
        return _error_proposal("mark_issues", "Status must be Wanted or Skipped.")
    scope = str(params.get("scope") or "all").strip().lower()
    if scope not in _MARK_SCOPES:
        return _error_proposal("mark_issues", "Scope must be all, issues, or annuals.")

    series = None
    comic_id = str(params.get("comic_id") or "").strip()
    if comic_id:
        series = db.select_one(
            select(comics.c.ComicID, comics.c.ComicName, comics.c.ComicYear).where(comics.c.ComicID == comic_id)
        )
    if series is None:
        series = _resolve_series(params.get("series_name"))
    if series is None:
        return _error_proposal("mark_issues", "No series in your library matched.")

    target = _MARK_TARGET_STATUSES[status]
    affected = _affected_issues(series["ComicID"], target, scope, _annuals_enabled(ctx))
    if not affected:
        return _error_proposal(
            "mark_issues",
            "Nothing to change — every issue of %s is already %s or owned." % (series["ComicName"], target),
        )

    return {
        "action_id": "mark_issues",
        "status": "pending",
        "summary": "Mark %d issue%s of %s as %s"
        % (len(affected), "" if len(affected) == 1 else "s", series["ComicName"], target),
        "parameters": {"series_name": series["ComicName"], "status": target, "scope": scope},
        "preview": {
            "comic_id": series["ComicID"],
            "comic_name": series["ComicName"],
            "comic_year": series.get("ComicYear"),
            "target_status": target,
            "scope": scope,
            "count": len(affected),
            "issues": affected,
        },
    }


def prepare_action(action_id, params, ctx):
    """Resolve a model-proposed action into a confirmation preview.

    Returns a proposal dict. A failed proposal carries status "error" with a
    human-readable reason so the chat can show it without aborting the turn.
    """
    action_id = str(action_id or "").strip()
    if action_id == "add_series":
        return _prepare_add_series(params, ctx)
    if action_id == "mark_issues":
        return _prepare_mark_issues(params, ctx)
    return _error_proposal(action_id or "unknown", "Unknown action.")


def _current_row(kind, issue_id):
    if kind == "annual":
        return db.select_one(
            select(annuals.c.Status, annuals.c.AcquisitionIntent).where(
                annuals.c.IssueID == issue_id,
                (annuals.c.Deleted.is_(None)) | (annuals.c.Deleted != 1),
            )
        )
    return db.select_one(select(issues.c.Status, issues.c.AcquisitionIntent).where(issues.c.IssueID == issue_id))


def _apply_mark(item, target_status, actor, comic_id=None) -> Literal["applied", "stale", "failed"]:
    from comicarr.app.acquisition.models import AcquisitionIntent
    from comicarr.app.acquisition.policy import explicit_intent_values
    from comicarr.app.series import queries as series_queries

    issue_id = item["issue_id"]
    kind = item["kind"]
    row = _current_row(kind, issue_id)
    if row is None or not _markable(row, target_status):
        return "stale"

    if target_status == "Wanted":
        if kind == "annual":
            db.upsert("annuals", explicit_intent_values(AcquisitionIntent.WANTED, actor), {"IssueID": issue_id})
        else:
            series_queries.queue_issue(issue_id, actor)
        try:
            from comicarr.app.search.commands import enqueue_search_command

            enqueue_search_command(
                {
                    "issueid": issue_id,
                    "comicid": comic_id,
                    "issuenumber": item.get("number"),
                    "entity_type": kind,
                },
                trigger="issue_wanted",
            )
        except Exception as e:
            logger.warn("[AI-ACTIONS] Issue %s marked Wanted but search handoff failed: %s" % (issue_id, e))
    elif kind == "annual":
        db.upsert("annuals", explicit_intent_values(AcquisitionIntent.SKIPPED, actor), {"IssueID": issue_id})
    else:
        series_queries.unqueue_issue(issue_id, actor)
    return "applied"


def _confirm_add_series(proposal, selection, ctx):
    comicid = str((selection or {}).get("comicid") or "").strip()
    allowed = {str(c["comicid"]) for c in (proposal.get("preview") or {}).get("candidates") or []}
    if not comicid or comicid not in allowed:
        return {"success": False, "error": "Pick one of the listed series matches."}

    from comicarr.app.search import service as search_service

    result = search_service.add_comic(ctx, comicid)
    if not result.get("success"):
        return {"success": False, "error": result.get("error") or "Could not add the series."}
    name = next((c["name"] for c in proposal["preview"]["candidates"] if str(c["comicid"]) == comicid), comicid)
    return {
        "success": True,
        "message": result.get("message") or "Adding %s" % name,
        "comicid": result.get("comicid") or comicid,
        "name": name,
    }


def _confirm_mark_issues(proposal, actor):
    preview = proposal.get("preview") or {}
    target = preview.get("target_status")
    items = preview.get("issues") or []
    if target not in _MARK_TARGET_STATUSES.values() or not items:
        return {"success": False, "error": "This proposal can no longer be applied."}

    applied = stale = failed = 0
    for item in items:
        try:
            outcome = _apply_mark(item, target, actor, comic_id=preview.get("comic_id"))
        except Exception as e:
            logger.error("[AI-ACTIONS] Failed to mark %s %s: %s" % (item["kind"], item["issue_id"], e))
            outcome = "failed"
        applied += outcome == "applied"
        stale += outcome == "stale"
        failed += outcome == "failed"

    if applied == 0 and failed == 0:
        return {"success": False, "error": "Those issues no longer need this change."}

    summary = "Marked %d issue%s %s" % (applied, "" if applied == 1 else "s", target)
    if stale:
        summary += " (%d no longer needed it)" % stale
    if failed:
        summary += " (%d failed)" % failed
    return {
        "success": failed == 0,
        "message": summary,
        "applied": applied,
        "stale": stale,
        "failed": failed,
        "comicid": preview.get("comic_id"),
    }


def confirm_action(proposal, selection, ctx, actor):
    """Execute a pending proposal. Only the persisted proposal's action and
    preview decide what may change; ``selection`` carries the user's pick."""
    action_id = proposal.get("action_id")
    if action_id == "add_series":
        return _confirm_add_series(proposal, selection, ctx)
    if action_id == "mark_issues":
        return _confirm_mark_issues(proposal, actor)
    return {"success": False, "error": "Unknown action."}
