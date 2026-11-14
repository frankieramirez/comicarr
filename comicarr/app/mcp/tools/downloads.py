#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Download read tools: what finished or failed, and the direct-download queue.

Rows leave out download folders, links and hashes: an agent needs what
happened, not where Comicarr keeps its files.
"""

from typing import Annotated, Literal

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from comicarr.app.downloads import service as downloads_service
from comicarr.app.mcp.contracts import (
    DownloadHistoryPage,
    DownloadQueuePage,
    DownloadRecord,
    Limit,
    Offset,
    QueuedDownload,
    paging,
    tool_result,
)
from comicarr.app.mcp.tools.activity import page_summary

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def _text(value):
    if value in (None, ""):
        return None
    return str(value)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _record(row) -> DownloadRecord:
    return DownloadRecord(
        issue_id=_text(row.get("IssueID")),
        series_id=_text(row.get("ComicID")),
        series_name=_text(row.get("ComicName")),
        issue_number=_text(row.get("Issue_Number")),
        status=_text(row.get("Status")),
        provider=_text(row.get("Provider")),
        size_bytes=_int(row.get("Size")),
        at=_text(row.get("DateAdded")),
    )


def _queued(row) -> QueuedDownload:
    return QueuedDownload(
        queue_id=str(row.get("ID")),
        series_name=_text(row.get("series")),
        year=_text(row.get("year")),
        file_name=_text(row.get("filename")),
        issue_id=_text(row.get("issueid")),
        series_id=_text(row.get("comicid")),
        site=_text(row.get("site")),
        status=_text(row.get("status")) or "Queued",
        pack=bool(row.get("pack")),
        submitted_at=_text(row.get("submit_date")),
        updated_at=_text(row.get("updated_date")),
    )


def register(server, get_ctx):
    """Add the download read tools to ``server``."""

    @server.tool(
        name="list_download_history",
        title="List download history",
        description="Releases Comicarr grabbed and what became of them, newest first.",
        annotations=READ,
    )
    def list_download_history(
        status: Annotated[
            str | None,
            Field(min_length=1, description="Only this status, such as Snatched, Post-Processed or Failed."),
        ] = None,
        name: Annotated[str | None, Field(description="Part of the series name, issue number or provider.")] = None,
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Annotated[CallToolResult, DownloadHistoryPage]:
        result = downloads_service.get_history(limit=limit, offset=offset, search=name, status=status)
        rows = result["history"]
        page = DownloadHistoryPage(
            downloads=[_record(row) for row in rows], **paging(offset, len(rows), result["pagination"]["total"])
        )
        return tool_result(page, page_summary("downloads", len(rows), page))

    @server.tool(
        name="list_download_queue",
        title="List download queue",
        description="The direct-download queue: files waiting, downloading, or failed.",
        annotations=READ,
    )
    def list_download_queue(
        status: Annotated[
            Literal["Queued", "Downloading", "Failed"] | None, Field(description="Only this status.")
        ] = None,
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Annotated[CallToolResult, DownloadQueuePage]:
        result = downloads_service.get_ddl_queue(limit=limit, offset=offset, status=status)
        rows = result["queue"]
        page = DownloadQueuePage(
            downloads=[_queued(row) for row in rows], **paging(offset, len(rows), result["pagination"]["total"])
        )
        return tool_result(page, page_summary("queued downloads", len(rows), page))
