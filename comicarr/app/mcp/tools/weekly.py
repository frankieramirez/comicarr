#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Weekly releases read tool."""

from typing import Annotated

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from comicarr.app.mcp.contracts import (
    ContractError,
    Limit,
    Offset,
    WeeklyRelease,
    WeeklyReleases,
    WeekRef,
    paging,
    tool_result,
)
from comicarr.app.mcp.tools.activity import page_summary
from comicarr.app.weekly import service as weekly_service


def _text(value):
    if value in (None, ""):
        return None
    return str(value)


def _release(row) -> WeeklyRelease:
    comicvine_id = _text(row.get("ComicID"))
    return WeeklyRelease(
        series_name=row.get("COMIC") or "",
        issue_number=_text(row.get("ISSUE")),
        publisher=_text(row.get("PUBLISHER")),
        ship_date=_text(row.get("SHIPDATE")),
        format=_text(row.get("format")),
        comicvine_id=comicvine_id,
        series_id=comicvine_id if row.get("in_library") else None,
        issue_id=_text(row.get("library_issue_id")),
        state=row.get("state") or "not_in_library",
    )


def _week(ref):
    return WeekRef(week=str(ref["week"]), year=str(ref["year"])) if ref else None


def register(server, get_ctx):
    """Add the weekly releases tool to ``server``."""

    @server.tool(
        name="get_weekly_releases",
        title="Get weekly releases",
        description=(
            "The industry's releases for this week, or a given week, and which belong to series in the library. "
            "A week Comicarr has not stored yet is fetched from the pull-list sources."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    def get_weekly_releases(
        week: Annotated[
            int | None, Field(ge=0, le=53, description="Week number, Sunday-based. Give with year; omit both for now.")
        ] = None,
        year: Annotated[int | None, Field(ge=1900, le=2999, description="Four-digit year, with week.")] = None,
        followed_only: Annotated[bool, Field(description="Only releases of series in the library.")] = False,
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Annotated[CallToolResult, WeeklyReleases]:
        if (week is None) != (year is None):
            raise ContractError("invalid_argument", "Give week and year together, or neither for this week.")
        try:
            result = weekly_service.get_week(week, year)
        except weekly_service.WeekError as e:
            raise ContractError("invalid_argument", str(e)) from e
        rows = result["rows"]
        followed = sum(1 for row in rows if row.get("in_library"))
        if followed_only:
            rows = [row for row in rows if row.get("in_library")]
        page_rows = rows[offset : offset + limit]
        page = WeeklyReleases(
            week=str(result["week"]),
            year=str(result["year"]),
            start=result["start"],
            end=result["end"],
            source=result["source"],
            followed=followed,
            previous_week=_week(result.get("prev")),
            next_week=_week(result.get("next")),
            releases=[_release(row) for row in page_rows],
            **paging(offset, len(page_rows), len(rows)),
        )
        if page.source == "unavailable" and not rows:
            return tool_result(page, "The pull list for week %s, %s could not be fetched." % (page.week, page.year))
        head = "Week %s, %s (%s to %s): %d followed. " % (page.week, page.year, page.start, page.end, followed)
        return tool_result(page, head + page_summary("releases", len(page_rows), page))
