#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Series tools."""

from typing import Annotated

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from comicarr import series_kind
from comicarr.app.mcp.contracts import (
    Limit,
    Offset,
    SeriesKind,
    SeriesPage,
    SeriesStatus,
    SeriesSummary,
    paging,
    tool_result,
)
from comicarr.app.series import service as series_service


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
