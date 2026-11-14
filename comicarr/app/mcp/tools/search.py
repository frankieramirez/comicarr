#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Search write tools: start a search for one issue or a series, retry a run.

The MCP client's approval prompt is the confirmation, so each tool runs the
browser's preview and confirm ledger in one call, with actor ``mcp`` and a
session id minted per call. The ledger's fingerprint check still applies.
"""

import uuid
from typing import Annotated

from mcp_types import CallToolResult, ToolAnnotations

from comicarr.app.acquisition.maintenance import acquisition_paused
from comicarr.app.activity import producers as activity
from comicarr.app.mcp.contracts import (
    ContractError,
    IssueId,
    RunId,
    SearchRunRetry,
    SearchStarted,
    SeriesId,
    tool_result,
)
from comicarr.app.search import service as search_service
from comicarr.app.series import service as series_service

ACTOR = "mcp"

SEARCH_WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)


def _session_id() -> str:
    return "mcp-%s" % uuid.uuid4().hex


def _refuse_during_maintenance(ctx):
    if acquisition_paused(getattr(ctx, "config", None)):
        raise ContractError(
            "maintenance",
            "Acquisition maintenance is running, so no search can start. Try again when it ends.",
            retryable=True,
        )


def _started(result, *, series_id, scope_type, scope_id) -> SearchStarted:
    """Turn a confirm result into the tool's output, or raise its contract error."""
    if not result.get("success"):
        status = result.get("status")
        if status == "stale_preview":
            raise ContractError(
                "stale_preview", "The library changed while the search was being queued. Call again.", retryable=True
            )
        if status == "blocked":
            raise ContractError(
                "provider_unavailable",
                "No search provider or download client is ready, so nothing was searched.",
                retryable=True,
            )
        raise ContractError("internal", "The search could not be queued.", retryable=True)
    started = SearchStarted(
        run_id=result.get("run_id"),
        series_id=series_id,
        accepted=int(result.get("accepted") or 0),
        status=result.get("status") or "accepted",
    )
    if started.run_id and not result.get("idempotent"):
        activity.emit_run_started(
            started.run_id, started.accepted, scope_type=scope_type, scope_id=scope_id, actor=ACTOR
        )
    return started


def register(server, get_ctx):
    """Add the search write tools to ``server``."""

    @server.write_tool(
        name="search_issue",
        title="Search for an issue",
        description=(
            "Search the providers for one Wanted issue now. Returns a run_id at once; "
            "the search runs in the background."
        ),
        annotations=SEARCH_WRITE,
    )
    def search_issue(issue_id: IssueId) -> Annotated[CallToolResult, SearchStarted]:
        ctx = get_ctx()
        current = series_service.get_issue_status(ctx, issue_id)
        if current is None:
            raise ContractError("not_found", "No issue has id %s." % issue_id)
        if current["entity_type"] != "issue":
            raise ContractError(
                "invalid_argument", "%s is an annual; search_missing searches a series' annuals." % issue_id
            )
        if current["status"] != "Wanted":
            raise ContractError(
                "invalid_argument",
                "Issue %s is %s, not Wanted. Mark it wanted with set_issue_status first."
                % (issue_id, current["status"] or "unset"),
            )
        _refuse_during_maintenance(ctx)
        result = series_service.search_wanted_issue_now(issue_id, actor=ACTOR, session_id=_session_id())
        if not result.get("success") and result.get("status_code") == 404:
            raise ContractError("invalid_argument", "Issue %s is no longer Wanted." % issue_id)
        started = _started(result, series_id=None, scope_type="issue", scope_id=issue_id)
        return tool_result(started, "Searching for issue %s; run %s." % (issue_id, started.run_id))

    @server.write_tool(
        name="search_missing",
        title="Search for missing issues",
        description=(
            "Search the providers for every Wanted issue of one series now. Returns a run_id at once; "
            "the search runs in the background."
        ),
        annotations=SEARCH_WRITE,
    )
    def search_missing(series_id: SeriesId) -> Annotated[CallToolResult, SearchStarted]:
        ctx = get_ctx()
        if series_service.get_series_status(ctx, series_id) is None:
            raise ContractError("not_found", "No series has id %s." % series_id)
        _refuse_during_maintenance(ctx)
        result = series_service.search_all_missing_now(ctx, series_id, actor=ACTOR, session_id=_session_id())
        if not result.get("success") and result.get("status_code") == 404:
            raise ContractError("not_found", "No series has id %s." % series_id)
        started = _started(result, series_id=series_id, scope_type="series", scope_id=series_id)
        if started.run_id is None:
            return tool_result(started, "Series %s has no Wanted issues to search." % series_id)
        return tool_result(
            started,
            "Searching %d Wanted issue(s) of series %s; run %s." % (started.accepted, series_id, started.run_id),
        )

    @server.write_tool(
        name="retry_search_run",
        title="Retry a search run",
        description=(
            "Hand a search run's waiting items to a worker again, for a run that is "
            "still open but stuck before it started searching."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
        ),
    )
    def retry_search_run(run_id: RunId) -> Annotated[CallToolResult, SearchRunRetry]:
        ctx = get_ctx()
        _refuse_during_maintenance(ctx)
        result = search_service.retry_run(ctx, run_id)
        code = result.get("status_code")
        if code == 404:
            raise ContractError("not_found", "No search run has id %s." % run_id)
        if code == 409:
            raise ContractError("invalid_argument", "Search run %s has finished; start a new search instead." % run_id)
        if code == 503:
            raise ContractError("busy", "The search queue did not accept the retry. Try again.", retryable=True)
        retry = SearchRunRetry(
            run_id=run_id, dispatched=int(result.get("dispatched") or 0), pending=len(result.get("errors") or [])
        )
        return tool_result(
            retry,
            "Run %s: %d item(s) handed to a worker, %d still waiting." % (run_id, retry.dispatched, retry.pending),
        )
