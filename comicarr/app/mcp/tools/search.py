#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Search tools: find a series on the providers, follow a search run, start a
search for one issue or a series, retry a run.

The MCP client's approval prompt is the confirmation, so each tool runs the
browser's preview and confirm ledger in one call, with actor ``mcp`` and a
session id minted per call. The ledger's fingerprint check still applies.
"""

import uuid
from typing import Annotated, Literal

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from comicarr import logger
from comicarr.app.acquisition.maintenance import acquisition_paused
from comicarr.app.activity import producers as activity
from comicarr.app.common import series_kind
from comicarr.app.mcp.contracts import (
    ContractError,
    FoundSeries,
    FoundSeriesPage,
    IssueId,
    Limit,
    Offset,
    RunId,
    SearchRun,
    SearchRunItem,
    SearchRunRetry,
    SearchStarted,
    SeriesId,
    paging,
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


METRON_PREFIX = "metron-"
RUN_ITEMS_SHOWN = 100


def _text(value):
    if value in (None, ""):
        return None
    return str(value)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _provider_id(comic_id):
    """``(provider, provider_id)`` for a search result's id, in add_series' terms."""
    comic_id = str(comic_id or "")
    if comic_id.startswith(METRON_PREFIX):
        return "metron", comic_id[len(METRON_PREFIX) :]
    return series_kind.provider_of(comic_id).value, series_kind.strip_prefix(comic_id)


def _found(row, kind) -> FoundSeries | None:
    provider, provider_id = _provider_id(row.get("comicid"))
    if not provider_id:
        return None
    year = _text(row.get("comicyear"))
    return FoundSeries(
        provider=provider,
        provider_id=provider_id,
        kind=kind,
        name=str(row.get("name") or ""),
        year=None if year in (None, "0000") else year,
        publisher=_text(row.get("publisher")),
        issues=_int(row.get("issues")),
        url=_text(row.get("url")),
        in_library=bool(row.get("in_library")),
    )


def _run(result) -> SearchRun:
    run, items = result["run"], result.get("items") or []
    return SearchRun(
        run_id=str(run["run_id"]),
        trigger=_text(run.get("trigger")),
        scope_type=_text(run.get("scope_type")),
        scope_id=_text(run.get("scope_id")),
        state=str(run.get("completion_state") or ""),
        dispatch_state=_text(run.get("dispatch_state")),
        accepted=int(run.get("accepted_count") or 0),
        finished=int(run.get("terminal_count") or 0),
        succeeded=int(run.get("succeeded_count") or 0),
        no_match=int(run.get("no_match_count") or 0),
        blocked=int(run.get("blocked_count") or 0),
        failed=int(run.get("failed_count") or 0),
        created_at=_text(run.get("created_at")),
        updated_at=_text(run.get("updated_at")),
        completed_at=_text(run.get("completed_at")),
        items_total=len(items),
        items=[
            SearchRunItem(
                entity_type=str(item.get("entity_type") or ""),
                entity_id=str(item.get("entity_id") or ""),
                status=str(item.get("attempt_status") or item.get("state") or ""),
                attempts=int(item.get("attempt_count") or 0),
                reason=_text(item.get("reason")),
                updated_at=_text(item.get("updated_at")),
            )
            for item in items[:RUN_ITEMS_SHOWN]
        ],
    )


# The errors find_comic and find_manga return for a bad request; any other is the provider's.
_ARGUMENT_ERRORS = frozenset({"Missing a Comic name", "Invalid pagination parameters"})


def register(server, get_ctx):
    """Add the search tools to ``server``."""

    @server.tool(
        name="find_series",
        title="Find a series",
        description=(
            "Look a series up on the metadata providers (ComicVine or Metron for comics, MyAnimeList or "
            "MangaDex for manga) before adding it. Each result carries the provider, provider_id and kind "
            "add_series takes."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    def find_series(
        name: Annotated[str, Field(min_length=1, max_length=200, description="The series name to look up.")],
        kind: Annotated[Literal["comic", "manga"], Field(description="comic or manga.")] = "comic",
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Annotated[CallToolResult, FoundSeriesPage]:
        ctx = get_ctx()
        try:
            if kind == "manga":
                result = search_service.find_manga(ctx, name, limit=limit, offset=offset)
            else:
                result = search_service.find_comic(ctx, name, limit=limit, offset=offset)
        except Exception as e:
            logger.warn("[MCP] find_series lookup for %s failed: %r" % (kind, e))
            raise ContractError(
                "provider_unavailable", "The metadata provider could not be reached. Try again.", retryable=True
            ) from e
        error = result.get("error")
        if error and "no results" not in error:
            if error in _ARGUMENT_ERRORS:
                raise ContractError("invalid_argument", error)
            if "not enabled" in error or "not configured" in error:
                raise ContractError("provider_unavailable", "%s. Turn it on in Settings." % error)
            raise ContractError("provider_unavailable", error, retryable=True)
        found = [item for item in (_found(row, kind) for row in result.get("results") or []) if item]
        total = (result.get("pagination") or {}).get("total")
        if not isinstance(total, int):
            total = offset + len(found)
        elif found:
            total = max(total, offset + len(found))
        page = FoundSeriesPage(results=found, **paging(offset, len(found), total))
        if not found:
            return tool_result(page, "No %s series matched %r." % (kind, name))
        summary = "%d %s series matched; %d already in the library." % (
            page.total,
            kind,
            sum(item.in_library for item in found),
        )
        return tool_result(page, summary)

    @server.tool(
        name="get_search_run",
        title="Get a search run",
        description="Progress and outcome of a search run, by the run_id a search tool or list_activity gave.",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def get_search_run(run_id: RunId) -> Annotated[CallToolResult, SearchRun]:
        result = search_service.get_run(get_ctx(), run_id)
        if not result.get("success"):
            raise ContractError("not_found", "No search run has id %s." % run_id)
        run = _run(result)
        return tool_result(
            run,
            "Run %s is %s: %d of %d finished, %d found, %d no match."
            % (run.run_id, run.state, run.finished, run.accepted, run.succeeded, run.no_match),
        )

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
