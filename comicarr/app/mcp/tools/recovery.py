#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Recovery write tools: retry post-processing, resolve attention, cancel in-flight work."""

from typing import Annotated, Literal

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from comicarr.app.activity import service as activity_service
from comicarr.app.attention import BATCH_CAP, InvalidAttentionRequest, ResolutionRequest, resolve
from comicarr.app.downloads import service as downloads_service
from comicarr.app.mcp.contracts import (
    AttentionItemResult,
    AttentionResolution,
    ContractError,
    InFlightCancelled,
    PostProcessingRetry,
    ReleaseKey,
    tool_result,
)

ACTOR = "mcp"

_RETRY_ERRORS = {
    "not_found": ("not_found", False),
    "busy": ("busy", True),
    "maintenance": ("maintenance", True),
    "not_retryable": ("invalid_argument", False),
}


def register(server, get_ctx):
    """Add the recovery write tools to ``server``."""

    @server.write_tool(
        name="retry_post_processing",
        title="Retry post-processing",
        description=(
            "Retry importing one finished download, by the release_key list_in_flight returns. "
            "Never takes a folder path."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
        ),
    )
    def retry_post_processing(release_key: ReleaseKey) -> Annotated[CallToolResult, PostProcessingRetry]:
        result = downloads_service.retry_post_processing(release_key)
        if not result["success"]:
            code, retryable = _RETRY_ERRORS.get(result["status"], ("internal", True))
            raise ContractError(code, result["detail"] or "Post-processing could not be retried.", retryable)
        retry = PostProcessingRetry(release_key=release_key, status=result["status"])
        verb = "Post-processed" if retry.status == "processed" else "Queued post-processing of"
        return tool_result(retry, "%s %s." % (verb, release_key))

    @server.write_tool(
        name="resolve_attention",
        title="Resolve needs-attention items",
        description=(
            "Act on needs-attention items by release_key: retry the download, search again, or stop wanting "
            "the issue. Only the actions an item offers apply to it."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True
        ),
    )
    def resolve_attention(
        action: Annotated[
            Literal["retry", "search_again", "stop_wanting"],
            Field(description="retry, search_again, or stop_wanting (the issue is no longer Wanted)."),
        ],
        release_keys: Annotated[
            list[str], Field(min_length=1, max_length=BATCH_CAP, description="Items' release keys.")
        ],
    ) -> Annotated[CallToolResult, AttentionResolution]:
        try:
            report = resolve(get_ctx(), ResolutionRequest(action=action, release_keys=release_keys, actor=ACTOR))
        except InvalidAttentionRequest as e:
            raise ContractError("invalid_argument", str(e)) from e
        resolution = AttentionResolution(
            action=action,
            succeeded=report.succeeded,
            failed=report.failed,
            results=[
                AttentionItemResult(
                    release_key=item.release_key,
                    ok=item.ok,
                    problem=item.problem,
                    message=item.message,
                    run_id=item.run_id,
                )
                for item in report.results
            ],
        )
        if not report.success and report.results and all(i.problem == "row_not_found" for i in report.results):
            raise ContractError("not_found", "None of these release keys is a download Comicarr knows.")
        return tool_result(resolution, "%s: %d resolved, %d not." % (action, resolution.succeeded, resolution.failed))

    @server.write_tool(
        name="cancel_in_flight",
        title="Cancel in-flight work",
        description=(
            "Cancel one queued or running search item (kind run, with item_id) or download "
            "(kind journal, with release_key), as list_in_flight returns them."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False
        ),
    )
    def cancel_in_flight(
        kind: Annotated[Literal["run", "journal"], Field(description="run for a search item, journal for a download.")],
        item_id: Annotated[int | None, Field(description="The search item's item_id, for kind run.")] = None,
        release_key: Annotated[str | None, Field(description="The download's release_key, for kind journal.")] = None,
    ) -> Annotated[CallToolResult, InFlightCancelled]:
        if kind == "run" and item_id is None:
            raise ContractError("invalid_argument", "kind run needs item_id.")
        if kind == "journal" and not release_key:
            raise ContractError("invalid_argument", "kind journal needs release_key.")
        try:
            result = activity_service.cancel_in_flight(kind, item_id=item_id, release_key=release_key, actor=ACTOR)
        except activity_service.InFlightCancelError as e:
            if getattr(e, "status_code", None) == 404:
                raise ContractError("not_found", "Nothing in flight matches that id.") from e
            if getattr(e, "status_code", None) == 409:
                # The service refuses finished work rather than treating it as a no-op.
                raise ContractError("not_found", "That item already finished, so there was nothing to cancel.") from e
            raise ContractError("invalid_argument", str(e)) from e
        cancelled = InFlightCancelled(
            kind=kind, item_id=result.get("item_id"), release_key=result.get("release_key"), state=str(result["state"])
        )
        target = "search item %s" % cancelled.item_id if kind == "run" else "download %s" % cancelled.release_key
        return tool_result(cancelled, "Cancelled %s." % target)
