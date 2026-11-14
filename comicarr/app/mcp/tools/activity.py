#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Activity read tools: what happened, what is in flight, and what needs the operator."""

from typing import Annotated

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from comicarr.app import attention
from comicarr.app.activity import service as activity_service
from comicarr.app.mcp.contracts import (
    ActivityEvent,
    ActivityPage,
    AttentionItem,
    AttentionPage,
    AttentionProblem,
    ContractError,
    InFlightItem,
    InFlightPage,
    Limit,
    Offset,
    paging,
    tool_result,
)
from comicarr.app.series import service as series_service

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def _text(value):
    if value in (None, ""):
        return None
    return str(value)


def page_summary(noun, returned, page):
    summary = "%d of %d %s" % (returned, page.total, noun)
    if page.next_offset is not None:
        summary += "; next page at offset %d" % page.next_offset
    return summary + "."


def _event(row) -> ActivityEvent:
    return ActivityEvent(
        event_id=str(row["event_id"]),
        at=str(row["created_at"]),
        activity=row["activity"],
        status=row["status"],
        subject_type=row["subject_type"],
        subject_id=str(row["subject_id"]),
        subject_label=row.get("subject_label") or "",
        series_id=_text(row.get("parent_series_id"))
        or (str(row["subject_id"]) if row["subject_type"] == "series" else None),
        reason_code=_text(row.get("reason_code")),
        reason_detail=_text(row.get("reason_detail")),
        provider=_text(row.get("provider")),
        run_id=_text(row.get("run_id")),
        release_key=_text(row.get("release_key")),
        actor=_text(row.get("actor")),
    )


def _in_flight(item) -> InFlightItem:
    return InFlightItem(
        kind=item["kind"],
        item_id=_text(item.get("item_id")),
        run_id=_text(item.get("run_id")),
        release_key=_text(item.get("release_key")),
        state=_text(item.get("state") or item.get("stage")),
        label=item.get("label") or "",
        issue_id=_text(item.get("issueid")),
        series_id=_text(item.get("comicid")),
        provider=_text(item.get("provider")),
        updated_at=_text(item.get("updated_at")),
        stuck=bool(item.get("stuck")),
        can_retry_post_processing=bool(item.get("retry_postprocess")),
    )


def _problem(group) -> AttentionProblem:
    return AttentionProblem(
        group_key=group.group_key,
        series_id=_text(group.comic_id),
        series_label=group.series_label,
        reason_code=_text(group.base_reason),
        reason=group.reason_phrase,
        stage=group.stage,
        count=group.member_count,
        newest_at=_text(group.newest_updated_at),
        oldest_at=_text(group.oldest_updated_at),
        actions=list(group.available_actions),
        items=[
            AttentionItem(
                release_key=member.release_key,
                issue_id=_text(member.issue_id),
                issue_label=member.issue_label,
                stage=member.stage,
                actions=list(member.available_actions),
                updated_at=_text(member.updated_at),
            )
            for member in group.members
        ],
    )


def register(server, get_ctx):
    """Add the activity read tools to ``server``."""

    @server.tool(
        name="list_activity",
        title="List activity",
        description=(
            "What Comicarr did, newest first: searches, grabs, downloads, imports and series changes. "
            "Give series_id or issue_id to see only that series or issue."
        ),
        annotations=READ,
    )
    def list_activity(
        series_id: Annotated[str | None, Field(min_length=1, description="Only this series and its issues.")] = None,
        issue_id: Annotated[str | None, Field(min_length=1, description="Only this issue or annual.")] = None,
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Annotated[CallToolResult, ActivityPage]:
        ctx = get_ctx()
        scope_type = scope_id = None
        if series_id is not None and issue_id is not None:
            raise ContractError("invalid_argument", "Give series_id or issue_id, not both.")
        if series_id is not None:
            if series_service.get_series_status(ctx, series_id) is None:
                raise ContractError("not_found", "No series has id %s." % series_id)
            scope_type, scope_id = "series", series_id
        elif issue_id is not None:
            found = series_service.get_issue_status(ctx, issue_id)
            if found is None:
                raise ContractError("not_found", "No issue or annual has id %s." % issue_id)
            scope_type, scope_id = found["entity_type"], issue_id
        result = activity_service.get_timeline(limit=limit, offset=offset, scope_type=scope_type, scope_id=scope_id)
        rows = result["results"]
        page = ActivityPage(events=[_event(row) for row in rows], **paging(offset, len(rows), result["total"]))
        return tool_result(page, page_summary("events", len(rows), page))

    @server.tool(
        name="list_in_flight",
        title="List in-flight work",
        description=(
            "What is being searched, downloaded or post-processed right now, and which of it is stuck "
            "(not updated for seven days)."
        ),
        annotations=READ,
    )
    def list_in_flight(
        stuck_only: Annotated[bool, Field(description="Only stuck items.")] = False,
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Annotated[CallToolResult, InFlightPage]:
        result = activity_service.get_in_flight()
        items = result["results"]
        if stuck_only:
            items = [item for item in items if item["stuck"]]
        rows = items[offset : offset + limit]
        page = InFlightPage(
            stuck=result["stuck"],
            items=[_in_flight(item) for item in rows],
            **paging(offset, len(rows), len(items)),
        )
        summary = "%d in flight, %d stuck. " % (result["total"], result["stuck"])
        return tool_result(page, summary + page_summary("items", len(rows), page))

    @server.tool(
        name="list_attention",
        title="List what needs attention",
        description=(
            "Problems that need the operator, one per series and reason, each with its items and the "
            "actions that would clear them."
        ),
        annotations=READ,
    )
    def list_attention(
        series_id: Annotated[str | None, Field(min_length=1, description="Only this series.")] = None,
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Annotated[CallToolResult, AttentionPage]:
        scope = attention.Scope(type="series", id=series_id) if series_id is not None else None
        view = attention.read(scope=scope)
        groups = view.groups[offset : offset + limit]
        page = AttentionPage(
            items_total=view.member_total,
            problems=[_problem(group) for group in groups],
            **paging(offset, len(groups), view.total),
        )
        if not view.total:
            return tool_result(page, "Nothing needs attention.")
        summary = "%d item(s) across %d problem(s) need attention. " % (view.member_total, view.total)
        return tool_result(page, summary + page_summary("problems", len(groups), page))
