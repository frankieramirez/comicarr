#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Library read tools: one series, its issues, what is missing, and one issue's story."""

import datetime
from typing import Annotated, Literal

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from comicarr.app.mcp.contracts import (
    ContractError,
    IssueCounts,
    IssueId,
    IssuePage,
    IssueRef,
    IssueState,
    IssueStory,
    IssueSummary,
    LastSearch,
    Limit,
    Offset,
    ProviderLink,
    SearchAttempts,
    SearchCandidate,
    SearchReason,
    SearchSummary,
    SeriesDetail,
    SeriesId,
    WantedIssue,
    WantedPage,
    WantedSeries,
    paging,
    tool_result,
)
from comicarr.app.mcp.tools.series import _kind
from comicarr.app.series import issue_story
from comicarr.app.series import service as series_service

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def _text(value):
    if value in (None, ""):
        return None
    return str(value)


def _page_summary(noun, returned, page):
    summary = "%d of %d %s" % (returned, page.total, noun)
    if page.next_offset is not None:
        summary += "; next page at offset %d" % page.next_offset
    return summary + "."


def _issue_ref(row):
    return IssueRef(
        issue_id=str(row["id"]), number=_text(row.get("number")), release_date=series_service.issue_release_date(row)
    )


def _last_and_next(projected, today=None):
    """The latest released issue and the earliest announced one, by the date Comicarr goes by."""
    today = (today or datetime.date.today()).isoformat()
    dated = [(series_service.issue_release_date(row), row) for row in projected if not row.get("annual")]
    released = [pair for pair in dated if pair[0] and pair[0] <= today]
    upcoming = [pair for pair in dated if pair[0] and pair[0] > today]
    last = max(released, key=lambda pair: pair[0])[1] if released else None
    upcoming_first = min(upcoming, key=lambda pair: pair[0])[1] if upcoming else None
    return (
        _issue_ref(last) if last else None,
        _issue_ref(upcoming_first) if upcoming_first else None,
    )


def _issue_summary(row) -> IssueSummary:
    return IssueSummary(
        issue_id=str(row["id"]),
        entity_type="annual" if row.get("annual") else "issue",
        number=_text(row.get("number")),
        name=_text(row.get("name")),
        state=row["displayState"],
        release_date=series_service.issue_release_date(row),
        owned=bool(row.get("owned")),
        in_flight=bool(row.get("inFlight")),
        monitored=bool(row.get("monitored")),
        eligible=bool(row.get("eligible")),
        eligibility_reason=row.get("eligibilityReason"),
    )


def _last_search(acquisition):
    if not acquisition:
        return None
    return LastSearch(
        state=str(acquisition.get("state") or ""),
        attempts=int(acquisition.get("attempt_count") or 0),
        reason=acquisition.get("reason"),
        run_id=_text(acquisition.get("run_id")),
        searched_at=_text(acquisition.get("updated_at")),
    )


def _wanted_issue(row) -> WantedIssue:
    return WantedIssue(
        issue_id=str(row["IssueID"]),
        series_id=str(row["ComicID"]),
        series_name=row.get("ComicName"),
        number=_text(row.get("Issue_Number")),
        name=_text(row.get("IssueName")),
        release_date=_text(row.get("ReleaseDate") or row.get("DigitalDate") or row.get("IssueDate")),
        last_search=_last_search(row.get("acquisition")),
    )


def _wanted_series(group) -> WantedSeries:
    buckets = group.get("buckets") or {}
    return WantedSeries(
        series_id=str(group["comicid"]),
        name=group.get("comic_name"),
        year=_text(group.get("comic_year")),
        publisher=group.get("publisher"),
        kind=group.get("kind") or "comic",
        missing=int(group.get("missing") or 0),
        which=group.get("which") or "",
        not_found=int(buckets.get("not_found") or 0),
        searching=int(buckets.get("searching") or 0),
        queued=int(buckets.get("queued") or 0),
        last_searched_at=_text(group.get("last_searched_at")),
        eta_hours=group.get("eta_hours"),
    )


def _search_summary(search):
    if not search:
        return None
    return SearchSummary(
        searched_at=_text(search.get("searched_at")),
        results=int(search.get("total") or 0),
        accepted=int(search.get("accepted_count") or 0),
        rejected=int(search.get("rejected_count") or 0),
        providers=list(search.get("providers") or []),
        reasons=[
            SearchReason(code=str(r.get("code")), label=str(r.get("label")), count=int(r.get("count") or 0))
            for r in search.get("reasons") or []
        ],
        candidates=[
            SearchCandidate(
                title=str(row.get("title") or ""),
                provider=str(row.get("provider") or ""),
                size_bytes=row.get("size_bytes"),
                pack=bool(row.get("pack")),
                chosen=bool(row.get("chosen")),
            )
            for row in search.get("accepted") or []
        ],
    )


def register(server, get_ctx):
    """Add the library read tools to ``server``."""

    @server.tool(
        name="get_series",
        title="Get series",
        description=(
            "One series in the library: status, folder, issue counts, provider pages, "
            "and its last released and next announced issue."
        ),
        annotations=READ,
    )
    def get_series(series_id: SeriesId) -> Annotated[CallToolResult, SeriesDetail]:
        detail = series_service.get_comic_detail(get_ctx(), series_id)
        if not detail["comic"]:
            raise ContractError("not_found", "No series has id %s." % series_id)
        row = detail["comic"][0]
        summary = detail["summary"]
        last_issue, next_issue = _last_and_next(detail["issues"])
        year = row.get("ComicYear")
        series = SeriesDetail(
            series_id=str(row["ComicID"]),
            name=row.get("ComicName") or "",
            year=_text(year),
            publisher=row.get("ComicPublisher"),
            kind=_kind(row),
            status=row.get("Status"),
            location=_text(row.get("ComicLocation")),
            description=_text(row.get("Description")),
            have=int(row.get("Have") or 0),
            total=int(row.get("Total") or 0),
            counts=IssueCounts(
                issues=summary["issues"],
                annuals=summary["annuals"],
                owned=summary["owned"],
                wanted=summary["wanted"],
                missing=summary["missing"],
                in_flight=summary["inFlight"],
                skipped=summary["skipped"],
                failed=summary["failed"],
                future=summary["future"],
            ),
            providers=[ProviderLink(provider=link["provider"], url=link["url"]) for link in detail["providerLinks"]],
            search_providers=list((detail.get("searchProviders") or {}).get("effective") or []),
            last_issue=last_issue,
            next_issue=next_issue,
        )
        return tool_result(
            series,
            "%s (%s): %s, %d of %d issues on disk, %d wanted."
            % (
                series.name,
                series.year or "?",
                series.status or "no status",
                series.have,
                series.total,
                series.counts.wanted,
            ),
        )

    @server.tool(
        name="list_issues",
        title="List issues",
        description="List the issues and annuals of one series, newest first, optionally only those in one state.",
        annotations=READ,
    )
    def list_issues(
        series_id: SeriesId,
        state: Annotated[IssueState | None, Field(description="Only issues in this state.")] = None,
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Annotated[CallToolResult, IssuePage]:
        result = series_service.list_series_issues(get_ctx(), series_id, status=state, limit=limit, offset=offset)
        if result is None:
            raise ContractError("not_found", "No series has id %s." % series_id)
        rows = result["issues"]
        page = IssuePage(
            series_id=series_id,
            issues=[_issue_summary(row) for row in rows],
            **paging(offset, len(rows), result["total"]),
        )
        noun = "%s issues" % state if state else "issues"
        return tool_result(page, _page_summary(noun, len(rows), page))

    @server.tool(
        name="list_wanted",
        title="List wanted issues",
        description=(
            "What is missing: Wanted issues one by one, or grouped by series with how many were "
            "searched and not found, are being searched, or are waiting."
        ),
        annotations=READ,
    )
    def list_wanted(
        group_by: Annotated[Literal["issue", "series"], Field(description="issue or series.")] = "issue",
        name: Annotated[str | None, Field(description="Part of the series name or issue number, any case.")] = None,
        series_id: Annotated[
            str | None, Field(min_length=1, description="Only this series. Applies when group_by is issue.")
        ] = None,
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Annotated[CallToolResult, WantedPage]:
        ctx = get_ctx()
        if group_by == "series":
            if series_id is not None:
                raise ContractError("invalid_argument", "series_id applies only when group_by is issue.")
            result = series_service.get_wanted_by_series(ctx, limit=limit, offset=offset, search=name)
            groups = result["series"]
            page = WantedPage(
                group_by="series",
                issues=[],
                series=[_wanted_series(group) for group in groups],
                **paging(offset, len(groups), result["pagination"]["total"]),
            )
            return tool_result(page, _page_summary("series with Wanted issues", len(groups), page))
        result = series_service.get_wanted(ctx, limit=limit, offset=offset, search=name, comic_id=series_id)
        rows = result["issues"]
        page = WantedPage(
            group_by="issue",
            issues=[_wanted_issue(row) for row in rows],
            series=[],
            **paging(offset, len(rows), result["pagination"]["total"]),
        )
        return tool_result(page, _page_summary("Wanted issues", len(rows), page))

    @server.tool(
        name="get_issue_story",
        title="Get issue story",
        description=(
            "Why an issue is not here yet: its state, whether automatic search will look for it, "
            "what the last search found and rejected, and what was grabbed."
        ),
        annotations=READ,
    )
    def get_issue_story(issue_id: IssueId) -> Annotated[CallToolResult, IssueStory]:
        ctx = get_ctx()
        state = series_service.get_issue_state(ctx, issue_id)
        if state is None:
            raise ContractError("not_found", "No issue or annual has id %s." % issue_id)
        issue, series = state["issue"], state["series"] or {}
        details = issue_story.story_details(ctx, issue_id, include_log=False)
        attempts = details["attempts"]
        story = IssueStory(
            issue_id=issue_id,
            entity_type="annual" if issue.get("annual") else "issue",
            series_id=_text(issue.get("comicId")),
            series_name=series.get("ComicName") or issue.get("comicName"),
            number=_text(issue.get("number")),
            state=issue["displayState"],
            eligible=bool(issue.get("eligible")),
            eligibility_reason=issue.get("eligibilityReason"),
            release_date=series_service.issue_release_date(issue),
            attempts=SearchAttempts(
                search=attempts["search"],
                grab=attempts["grab"],
                download=attempts["download"],
                imported=attempts["import"],
            ),
            last_search=_search_summary(details["search"]),
            chosen_release=details["chosen"],
        )
        label = "%s #%s" % (story.series_name or "Issue", story.number or issue_id)
        if story.last_search:
            tail = "last search saw %d release(s), %d acceptable" % (
                story.last_search.results,
                story.last_search.accepted,
            )
        else:
            tail = "never searched"
        return tool_result(story, "%s is %s; %s." % (label, story.state, tail))
