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


Provider = Literal["comicvine", "metron", "mangadex", "myanimelist"]


class SeriesAdded(BaseModel):
    series_id: str = Field(description="The library's id for the series; get_series reads it.")
    already_in_library: bool = Field(description="True when the series was already there and nothing was queued.")
    want_queued: bool = Field(description="True when its issues will be marked Wanted once the add finishes.")


class SeriesRefreshQueued(BaseModel):
    series_id: str
    already_queued: bool = Field(description="True when a refresh of this series was already waiting.")


ReleaseKey = Annotated[str, Field(min_length=1, description="A download's release_key, as list_in_flight returns it.")]


class PostProcessingRetry(BaseModel):
    release_key: str
    status: Literal["processed", "queued"] = Field(
        description="processed: done in this call. queued: handed to the post-processing worker."
    )


class AttentionItemResult(BaseModel):
    release_key: str
    ok: bool
    problem: str | None = Field(description="Why it was not resolved, when ok is false.")
    message: str | None
    run_id: str | None = Field(description="The search run a retry or search_again started.")


class AttentionResolution(BaseModel):
    action: Literal["retry", "search_again", "stop_wanting"]
    succeeded: int
    failed: int
    results: list[AttentionItemResult]


class InFlightCancelled(BaseModel):
    kind: Literal["run", "journal"]
    item_id: int | None
    release_key: str | None
    state: str


RunId = Annotated[str, Field(min_length=1, description="A search run id, as a search tool returned it.")]


class SearchStarted(BaseModel):
    run_id: str | None = Field(description="Poll this run for progress. Null when nothing was eligible.")
    series_id: str | None
    accepted: int = Field(description="Wanted issues the run will search.")
    status: Literal["accepted", "pending_dispatch", "noop"] = Field(
        description="pending_dispatch: recorded, and Comicarr hands it to a worker as soon as it can."
    )


class SearchRunRetry(BaseModel):
    run_id: str
    dispatched: int = Field(description="Search items handed to a worker by this retry.")
    pending: int = Field(description="Items still waiting for a worker after this retry.")


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


IssueState = Literal[
    "Wanted",
    "Missing",
    "Skipped",
    "Ignored",
    "Reserved",
    "Snatched",
    "Downloaded",
    "Archived",
    "Failed",
    "Covered",
    "Unknown",
]


class IssueRef(BaseModel):
    issue_id: str
    number: str | None
    release_date: str | None = Field(description="The date Comicarr goes by: release, digital or cover date.")


class IssueCounts(BaseModel):
    issues: int
    annuals: int
    owned: int = Field(description="On disk or archived.")
    wanted: int
    missing: int = Field(description="Not owned, not in flight and not covered by a pack.")
    in_flight: int = Field(description="Snatched or reserved, on its way.")
    skipped: int
    failed: int
    future: int = Field(description="Monitored issues not released yet.")


class ProviderLink(BaseModel):
    provider: str
    url: str


class SeriesDetail(BaseModel):
    series_id: str
    name: str
    year: str | None
    publisher: str | None
    kind: SeriesKind
    status: str | None
    location: str | None = Field(description="The series folder.")
    description: str | None
    have: int = Field(description="Issues on disk.")
    total: int = Field(description="Issues the series has.")
    counts: IssueCounts
    providers: list[ProviderLink] = Field(description="The series' pages on its metadata providers.")
    search_providers: list[str] = Field(description="Search providers this series uses, in order.")
    last_issue: IssueRef | None = Field(description="The most recently released issue.")
    next_issue: IssueRef | None = Field(description="The next issue to be released, when one is announced.")


class IssueSummary(BaseModel):
    issue_id: str
    entity_type: Literal["issue", "annual"]
    number: str | None
    name: str | None
    state: IssueState
    release_date: str | None
    owned: bool
    in_flight: bool
    monitored: bool = Field(description="False when Skipped or Ignored: automatic search leaves it alone.")
    eligible: bool = Field(description="Automatic search will look for it now.")
    eligibility_reason: str | None = Field(description="Why it is or is not eligible, such as future or paused.")


class IssuePage(Paged):
    series_id: str
    issues: list[IssueSummary]


class LastSearch(BaseModel):
    state: str = Field(description="The latest search run item's state, such as no_match, searching or grabbed.")
    attempts: int
    reason: str | None
    run_id: str | None
    searched_at: str | None


class WantedIssue(BaseModel):
    issue_id: str
    series_id: str
    series_name: str | None
    number: str | None
    name: str | None
    release_date: str | None
    last_search: LastSearch | None = Field(description="Null when it was never searched.")


class WantedSeries(BaseModel):
    series_id: str
    name: str | None
    year: str | None
    publisher: str | None
    kind: str
    missing: int = Field(description="Wanted issues in this series.")
    which: str = Field(description="The Wanted issue numbers, folded, such as #1-12, #20.")
    not_found: int = Field(description="Searched and nothing usable was found.")
    searching: int
    queued: int = Field(description="Waiting for automatic search to reach them.")
    last_searched_at: str | None
    eta_hours: float | None = Field(description="Hours until automatic search reaches the last of them.")


class WantedPage(Paged):
    group_by: Literal["issue", "series"]
    issues: list[WantedIssue] = Field(description="Filled when group_by is issue.")
    series: list[WantedSeries] = Field(description="Filled when group_by is series.")


class SearchReason(BaseModel):
    code: str
    label: str
    count: int


class SearchCandidate(BaseModel):
    title: str
    provider: str
    size_bytes: int | None
    pack: bool
    chosen: bool = Field(description="True for the release Comicarr grabbed.")


class SearchSummary(BaseModel):
    searched_at: str | None
    results: int = Field(description="Releases the providers returned.")
    accepted: int
    rejected: int
    providers: list[str]
    reasons: list[SearchReason] = Field(description="Why releases were rejected, most common first.")
    candidates: list[SearchCandidate] = Field(description="Acceptable releases, at most 20.")


class SearchAttempts(BaseModel):
    search: int
    grab: int
    download: int
    imported: int


class IssueStory(BaseModel):
    issue_id: str
    entity_type: Literal["issue", "annual"]
    series_id: str | None
    series_name: str | None
    number: str | None
    state: IssueState
    eligible: bool
    eligibility_reason: str | None
    release_date: str | None
    attempts: SearchAttempts = Field(description="Finished searches, grabs, downloads and imports for this issue.")
    last_search: SearchSummary | None = Field(description="What the most recent search saw; null if never searched.")
    chosen_release: str | None = Field(description="The release name last handed to a download client.")


class ActivityEvent(BaseModel):
    event_id: str
    at: str = Field(description="When it happened, ISO 8601.")
    activity: str = Field(description="What kind of work: search, grab, download, import, series and so on.")
    status: str = Field(description="How it went: started, succeeded, failed, no_match and so on.")
    subject_type: str = Field(description="issue, annual, series or run.")
    subject_id: str
    subject_label: str
    series_id: str | None
    reason_code: str | None
    reason_detail: str | None
    provider: str | None
    run_id: str | None = Field(description="The search run, for get_search_run.")
    release_key: str | None
    actor: str | None = Field(description="Who started it: null for Comicarr itself, mcp for an agent.")


class ActivityPage(Paged):
    events: list[ActivityEvent] = Field(description="Newest first.")


class InFlightItem(BaseModel):
    kind: Literal["run", "journal"] = Field(description="run: a search run item. journal: a grabbed release.")
    item_id: str | None = Field(description="The run item id, for kind run.")
    run_id: str | None
    release_key: str | None = Field(description="The release, for kind journal.")
    state: str | None = Field(description="Run item state, or the journal stage.")
    label: str
    issue_id: str | None
    series_id: str | None
    provider: str | None
    updated_at: str | None
    stuck: bool = Field(description="Not updated for seven days.")
    can_retry_post_processing: bool


class InFlightPage(Paged):
    stuck: int = Field(description="Stuck items across all pages.")
    items: list[InFlightItem]


class AttentionItem(BaseModel):
    release_key: str = Field(description="The attention item id.")
    issue_id: str | None
    issue_label: str
    stage: str
    actions: list[str] = Field(description="What the operator can do: retry, search_again, import, stop_wanting.")
    updated_at: str | None


class AttentionProblem(BaseModel):
    group_key: str
    series_id: str | None
    series_label: str
    reason_code: str | None
    reason: str
    stage: str
    count: int
    newest_at: str | None
    oldest_at: str | None
    actions: list[str]
    items: list[AttentionItem]


class AttentionPage(Paged):
    items_total: int = Field(description="Items across every problem, all pages.")
    problems: list[AttentionProblem] = Field(description="One per series and reason.")


class DownloadRecord(BaseModel):
    issue_id: str | None
    series_id: str | None
    series_name: str | None
    issue_number: str | None
    status: str | None = Field(description="Such as Snatched, Downloaded, Post-Processed or Failed.")
    provider: str | None
    size_bytes: int | None
    at: str | None


class DownloadHistoryPage(Paged):
    downloads: list[DownloadRecord] = Field(description="Newest first.")


class QueuedDownload(BaseModel):
    queue_id: str
    series_name: str | None
    year: str | None
    file_name: str | None
    issue_id: str | None
    series_id: str | None
    site: str | None
    status: str | None = Field(description="Queued, Downloading or Failed.")
    pack: bool
    submitted_at: str | None
    updated_at: str | None


class DownloadQueuePage(Paged):
    downloads: list[QueuedDownload]


class WeekRef(BaseModel):
    week: str
    year: str


class WeeklyRelease(BaseModel):
    series_name: str
    issue_number: str | None
    publisher: str | None
    ship_date: str | None
    format: str | None
    comicvine_id: str | None = Field(description="Pass to add_series with provider comicvine when not in the library.")
    series_id: str | None = Field(description="The library's series id, when the series is followed.")
    issue_id: str | None = Field(description="The library's issue id, when the issue is known.")
    state: Literal["not_in_library", "in_library", "wanted", "downloaded"]


class WeeklyReleases(Paged):
    week: str
    year: str
    start: str = Field(description="The Sunday the week starts.")
    end: str
    source: Literal["stored", "fetched", "unavailable"] = Field(
        description="unavailable: the pull list could not be fetched for this week; try again later."
    )
    followed: int = Field(description="Releases of series in the library, across all pages.")
    previous_week: WeekRef | None
    next_week: WeekRef | None
    releases: list[WeeklyRelease]


class IndexerHealth(BaseModel):
    name: str
    type: str | None
    searching: bool = Field(description="True while a search is running on this indexer right now.")
    last_run: str | None
    hits: int | None


class RouteHealth(BaseModel):
    route: Literal["ddl", "nzb", "torrent"]
    enabled: bool
    ready: bool
    reason: str = Field(description="ready, or why not, such as client_not_ready or providers_temporarily_blocked.")
    client: str | None = Field(description="The download client this route hands releases to.")
    last_success: str | None
    last_failure: str | None
    last_error: str | None


class ConnectionHealth(BaseModel):
    key: str
    label: str
    kind: str = Field(description="client, indexers, metadata or folder.")
    ok: bool | None = Field(description="The last check's answer; null when never checked since start.")
    result: str | None
    checked_at: str | None
    latency_ms: float | None
    version: str | None


class JobHealth(BaseModel):
    job_id: str
    name: str
    status: str = Field(description="Waiting, Running, Paused and so on.")
    next_run: str | None
    last_run: str | None
    last_success: str | None
    last_failure: str | None
    last_error: str | None
    result: str | None = Field(description="What the last run did, in one line.")


class SystemHealth(BaseModel):
    can_search: bool = Field(description="At least one search route is ready.")
    maintenance: str | None = Field(description="Why acquisition is paused for maintenance; null when it is not.")
    routes: list[RouteHealth]
    indexers: list[IndexerHealth]
    connections: list[ConnectionHealth]
    jobs: list[JobHealth]


class FoundSeries(BaseModel):
    provider: Provider = Field(description="Pass to add_series with provider_id and kind.")
    provider_id: str
    kind: Literal["comic", "manga"]
    name: str
    year: str | None
    publisher: str | None = Field(description="The publisher, or the author for manga.")
    issues: int | None = Field(description="Issues or chapters the provider lists.")
    url: str | None
    in_library: bool


class FoundSeriesPage(Paged):
    results: list[FoundSeries]


class SearchRunItem(BaseModel):
    entity_type: str
    entity_id: str
    status: str = Field(description="queued, searching, succeeded, no_match, blocked, failed and so on.")
    attempts: int
    reason: str | None
    updated_at: str | None


class SearchRun(BaseModel):
    run_id: str
    trigger: str | None
    scope_type: str | None
    scope_id: str | None
    state: str = Field(description="How far the run got; completed, partial, blocked and failed are final.")
    dispatch_state: str | None
    accepted: int
    finished: int
    succeeded: int
    no_match: int
    blocked: int
    failed: int
    created_at: str | None
    updated_at: str | None
    completed_at: str | None
    items_total: int
    items: list[SearchRunItem] = Field(description="At most 100.")
