#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""The MCP tool contract: names, results, paging and errors.

Section 6 of docs/architecture/mcp-server.md. Every tool is named
``verb_noun`` with a verb from :data:`VERBS`, returns :func:`tool_result`
(a published ``outputSchema``, ``structuredContent`` and a one-line text
summary) or :func:`tool_error`, and takes :data:`Limit` and :data:`Offset`
when it lists. Identifiers are Comicarr's own, always strings.
"""

from typing import Annotated, Literal

from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel, Field

VERBS = (
    "list",
    "get",
    "find",
    "add",
    "set",
    "search",
    "refresh",
    "retry",
    "resolve",
    "cancel",
    "pause",
    "resume",
)

ErrorCode = Literal[
    "not_found",
    "invalid_argument",
    "writes_disabled",
    "stale_preview",
    "busy",
    "provider_unavailable",
    "maintenance",
    "internal",
]

Limit = Annotated[int, Field(ge=1, le=100, description="Page size, 1 to 100.")]
Offset = Annotated[int, Field(ge=0, description="Items to skip before this page.")]
SeriesKind = Literal["comic", "manga", "magazine"]
SeriesStatus = Literal["Active", "Paused", "Ended", "Loading", "Error"]


class ToolErrorBody(BaseModel):
    """The ``structuredContent`` of every ``isError`` result."""

    code: ErrorCode
    message: str
    retryable: bool


class ContractError(Exception):
    """Raise from a tool to return :func:`tool_error` with these fields."""

    def __init__(self, code: ErrorCode, message: str, retryable: bool = False):
        super().__init__(message)
        self.body = ToolErrorBody(code=code, message=message, retryable=retryable)


class Paged(BaseModel):
    """Base for every list result."""

    total: int = Field(description="Items matching the filters, across all pages.")
    next_offset: int | None = Field(description="Offset of the next page; null on the last page.")


def paging(offset: int, returned: int, total: int) -> dict:
    """``total`` and ``next_offset`` for a page of ``returned`` items starting at ``offset``."""
    following = offset + returned
    return {"total": total, "next_offset": following if following < total else None}


def tool_result(output: BaseModel, summary: str) -> CallToolResult:
    """A successful result: ``output`` as ``structuredContent``, ``summary`` as its one line of text."""
    return CallToolResult(
        content=[TextContent(type="text", text=summary)],
        structured_content=output.model_dump(mode="json"),
    )


def tool_error(code: ErrorCode, message: str, retryable: bool = False) -> CallToolResult:
    """A failed result carrying ``{code, message, retryable}``."""
    body = ToolErrorBody(code=code, message=message, retryable=retryable)
    return CallToolResult(
        content=[TextContent(type="text", text="%s: %s" % (code, message))],
        structured_content=body.model_dump(mode="json"),
        is_error=True,
    )


SeriesId = Annotated[str, Field(min_length=1, description="Comicarr's series id, from list_series.")]
IssueId = Annotated[str, Field(min_length=1, description="Comicarr's issue or annual id.")]


class IssueStatusChange(BaseModel):
    issue_id: str
    entity_type: Literal["issue", "annual"]
    status: Literal["Wanted", "Skipped"]
    changed: bool = Field(description="False when the issue already had this status.")


class SeriesStatusChange(BaseModel):
    series_id: str
    status: Literal["Paused", "Active"]
    changed: bool = Field(description="False when the series already had this status.")


class SeriesSummary(BaseModel):
    series_id: str
    name: str
    year: str | None
    publisher: str | None
    kind: SeriesKind
    status: str | None
    have: int = Field(description="Issues on disk.")
    total: int = Field(description="Issues the series has.")
    latest_issue: str | None


class SeriesPage(Paged):
    series: list[SeriesSummary]
