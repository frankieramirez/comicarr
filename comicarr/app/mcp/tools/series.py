#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Series tools."""

from typing import Annotated, Literal

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from comicarr import series_kind
from comicarr.app.activity import producers as activity
from comicarr.app.mcp.contracts import (
    ContractError,
    IssueId,
    IssueStatusChange,
    Limit,
    Offset,
    SeriesId,
    SeriesKind,
    SeriesPage,
    SeriesStatus,
    SeriesStatusChange,
    SeriesSummary,
    paging,
    tool_result,
)
from comicarr.app.series import service as series_service

ACTOR = "mcp"


def _kind(row) -> str:
    if series_kind.is_manga(row):
        return "manga"
    if series_kind.is_magazine(row):
        return "magazine"
    return "comic"


def _summary(row) -> SeriesSummary:
    year = row.get("ComicYear")
    return SeriesSummary(
        series_id=str(row["ComicID"]),
        name=row.get("ComicName") or "",
        year=str(year) if year not in (None, "") else None,
        publisher=row.get("ComicPublisher"),
        kind=_kind(row),
        status=row.get("Status"),
        have=int(row.get("Have") or 0),
        total=int(row.get("Total") or 0),
        latest_issue=row.get("LatestIssue"),
    )


def register(server, get_ctx):
    """Add the series tools to ``server``; ``get_ctx`` returns the live AppContext."""

    @server.tool(
        name="list_series",
        title="List series",
        description="List the series in the library, filtered by name, kind and status.",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def list_series(
        name: Annotated[str | None, Field(description="Part of the series name, any case.")] = None,
        kind: Annotated[SeriesKind | None, Field(description="comic (includes magazines), manga or magazine.")] = None,
        status: Annotated[SeriesStatus | None, Field(description="Series status.")] = None,
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Annotated[CallToolResult, SeriesPage]:
        result = series_service.list_comics(get_ctx(), limit=limit, offset=offset, name=name, kind=kind, status=status)
        rows = result["comics"]
        page = SeriesPage(
            series=[_summary(row) for row in rows],
            **paging(offset, len(rows), result["pagination"]["total"]),
        )
        summary = "%d of %d series" % (len(rows), page.total)
        if page.next_offset is not None:
            summary += "; next page at offset %d" % page.next_offset
        return tool_result(page, summary + ".")

    @server.write_tool(
        name="set_issue_status",
        title="Set issue status",
        description="Mark one issue or annual Wanted (Comicarr searches for it) or Skipped (it stops).",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
        ),
    )
    def set_issue_status(
        issue_id: IssueId,
        status: Annotated[Literal["wanted", "skipped"], Field(description="wanted or skipped.")],
    ) -> Annotated[CallToolResult, IssueStatusChange]:
        ctx = get_ctx()
        current = series_service.get_issue_status(ctx, issue_id)
        if current is None:
            raise ContractError("not_found", "No issue or annual has id %s." % issue_id)
        wanted = status.capitalize()
        changed = current["status"] != wanted
        if changed:
            result = series_service.set_issue_status(ctx, issue_id, status, ACTOR, entity_type=current["entity_type"])
            if not result.get("success"):
                raise ContractError("not_found", "No issue or annual has id %s." % issue_id)
            activity.emit_status_change(current["entity_type"], issue_id, wanted, actor=ACTOR)
        change = IssueStatusChange(
            issue_id=issue_id, entity_type=current["entity_type"], status=wanted, changed=changed
        )
        verb = "Marked" if changed else "Already"
        return tool_result(change, "%s %s %s %s." % (verb, current["entity_type"], issue_id, wanted))

    def _set_series_status(series_id, target, write):
        ctx = get_ctx()
        current = series_service.get_series_status(ctx, series_id)
        if current is None:
            raise ContractError("not_found", "No series has id %s." % series_id)
        changed = current != target
        if changed:
            if not write(ctx, series_id).get("success"):
                raise ContractError("not_found", "No series has id %s." % series_id)
            activity.emit_status_change("series", series_id, target, actor=ACTOR)
        change = SeriesStatusChange(series_id=series_id, status=target, changed=changed)
        verb = "Series %s is now %s." if changed else "Series %s was already %s."
        return tool_result(change, verb % (series_id, target))

    series_write = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    @server.write_tool(
        name="pause_series",
        title="Pause series",
        description="Stop automatic searching for one series. Its issues keep their status.",
        annotations=series_write,
    )
    def pause_series(series_id: SeriesId) -> Annotated[CallToolResult, SeriesStatusChange]:
        return _set_series_status(series_id, "Paused", series_service.pause_comic)

    @server.write_tool(
        name="resume_series",
        title="Resume series",
        description="Restart automatic searching for a paused series.",
        annotations=series_write,
    )
    def resume_series(series_id: SeriesId) -> Annotated[CallToolResult, SeriesStatusChange]:
        return _set_series_status(series_id, "Active", series_service.resume_comic)
