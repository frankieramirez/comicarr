#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Private resolution orchestration for Needs attention."""

from collections.abc import Sequence

from comicarr import logger
from comicarr.app.attention._policy import (
    ACTION_IMPORT,
    ACTION_RETRY,
    ACTION_SEARCH_AGAIN,
    ACTION_STOP_WANTING,
    ATTENTION_ACTIONS,
    STAGE_ACTIONS,
    TROUBLE_STAGES,
)
from comicarr.app.attention.contracts import (
    BATCH_CAP,
    ImportSource,
    InvalidAttentionRequest,
    ResolutionItem,
    ResolutionReport,
    ResolutionRequest,
)
from comicarr.app.downloads import journal


class _RuntimeResolutionEffects:
    """Production adapter for effects outside the Attention implementation."""

    def __init__(self, ctx):
        self.ctx = ctx

    def search_health(self):
        from comicarr.app.search import routes as search_routes

        return search_routes.route_health(self.ctx)

    def rewant(self, issue_id, actor):
        from comicarr.app.series import queries as series_queries

        series_queries.queue_issue(issue_id, actor)

    def search(self, issue_id, trigger):
        from comicarr.app.search import service as search_service

        return search_service.search_issue(self.ctx, issue_id, trigger=trigger)

    def stop_wanting(self, issue_id, actor):
        from comicarr.app.series import queries as series_queries

        series_queries.ignore_issue(issue_id, actor)

    def enqueue_import(self, item):
        from comicarr.app.downloads import service as downloads_service
        from comicarr.app.downloads.pp_commands import PostProcessCommandError, validate_postprocess_item

        try:
            validated = validate_postprocess_item(item)
        except PostProcessCommandError as e:
            return {"success": False, "problem": "invalid_import_source", "message": str(e)}
        result = downloads_service.force_process(
            nzb_name=validated["nzb_name"],
            nzb_folder=validated["nzb_folder"],
            issueid=validated.get("issueid"),
            comicid=validated.get("comicid"),
            ddl=validated.get("ddl") or False,
            oneoff=validated.get("oneoff") or False,
        )
        if not result.get("success"):
            return {
                "success": False,
                "problem": "import_failed",
                "message": result.get("error") or "Post-process queue failed",
            }
        return {"success": True, "message": result.get("message") or "Import queued"}


def _issue_id(row):
    value = row.get("issueid")
    if value not in (None, ""):
        return str(value)
    try:
        payload = journal.load_payload(row.get("payload_json"))
    except Exception as e:
        logger.fdebug("[ATTENTION] payload decode for issue id failed: %s" % e)
        payload = None
    if isinstance(payload, dict):
        for key in ("issueid", "IssueID"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def _payload(row):
    value = journal.load_payload(row.get("payload_json"))
    return value if isinstance(value, dict) else {}


def _failure(key, problem, message, *, status="failed", issue_id=None, stamp_written=None):
    return ResolutionItem(
        release_key=key,
        ok=False,
        status=status,
        problem=problem,
        message=message,
        issue_id=issue_id,
        stamp_written=stamp_written,
    )


def _admitted_row(key):
    row = journal.read_one(key)
    if row is None:
        return None, _failure(key, "row_not_found", "Journal row not found")
    if row.get("stage") not in TROUBLE_STAGES:
        return None, _failure(key, "not_in_attention", "Row is not in Needs attention")
    if row.get("status") in journal.RESOLVED_STATUSES:
        return None, _failure(key, "already_resolved", "Row is already resolved")
    return row, None


def _retry_or_search(row, key, *, action, actor, effects):
    issue_id = _issue_id(row)
    if not issue_id:
        return _failure(key, "missing_issue", "Journal row has no issueid")
    precheck = effects.search_health()
    if not precheck.get("success"):
        return _failure(
            key,
            "search_blocked",
            precheck.get("error") or precheck.get("message") or "Search is blocked",
            status="blocked",
            issue_id=issue_id,
        )
    effects.rewant(issue_id, actor)
    trigger = "band_retry" if action == ACTION_RETRY else "band_search_again"
    result = effects.search(issue_id, trigger)
    if not result.get("success"):
        blocked = result.get("status") == "blocked"
        return _failure(
            key,
            "search_blocked" if blocked else "search_failed",
            result.get("error") or result.get("message") or "Search could not be queued",
            status="blocked" if blocked else (result.get("status") or "failed"),
            issue_id=issue_id,
            stamp_written=False,
        )
    stamped = journal.stamp_resolution(key, journal.STATUS_RETRIED, increment_retry=True)
    return ResolutionItem(
        release_key=key,
        ok=True,
        status="retried",
        message="Issue re-wanted and search queued",
        issue_id=issue_id,
        run_id=result.get("run_id"),
        stamp_written=stamped,
    )


def _stop_wanting(row, key, *, actor, effects):
    issue_id = _issue_id(row)
    if not issue_id:
        return _failure(key, "missing_issue", "Journal row has no issueid")
    effects.stop_wanting(issue_id, actor)
    stamped = journal.stamp_resolution(key, journal.STATUS_IGNORED)
    return ResolutionItem(
        release_key=key,
        ok=True,
        status="ignored",
        message="Issue will not be searched again until you want it back",
        issue_id=issue_id,
        stamp_written=stamped,
    )


def _import(row, key, *, source, effects):
    payload = _payload(row)
    source = source or ImportSource()
    name = source.nzb_name or payload.get("nzb_name") or payload.get("nzbname") or row.get("nzbname")
    folder = source.nzb_folder or payload.get("nzb_folder")
    if not name or not folder:
        return _failure(key, "missing_import_source", "Missing nzb_name or nzb_folder for import")
    outcome = effects.enqueue_import(
        {
            "nzb_name": name,
            "nzb_folder": folder,
            "issueid": row.get("issueid") or payload.get("issueid"),
            "comicid": payload.get("comicid"),
            "ddl": bool(payload.get("ddl")),
            "oneoff": bool(payload.get("oneoff")),
        }
    )
    if not outcome.get("success"):
        return _failure(key, outcome["problem"], outcome.get("message") or "Import could not be queued")
    stamped = journal.stamp_resolution(key, journal.STATUS_IMPORTED)
    return ResolutionItem(
        release_key=key,
        ok=True,
        status="imported",
        message=outcome.get("message"),
        stamp_written=stamped,
    )


def _resolve_one(request, key, effects):
    row, failure = _admitted_row(key)
    if failure is not None:
        return failure
    action = request.action
    stage = row.get("stage")
    if action not in STAGE_ACTIONS.get(stage, ()):
        return _failure(key, "action_not_allowed", "Action %s is not valid for %s rows" % (action, stage))
    if action in {ACTION_RETRY, ACTION_SEARCH_AGAIN}:
        return _retry_or_search(row, key, action=action, actor=request.actor, effects=effects)
    if action == ACTION_STOP_WANTING:
        return _stop_wanting(row, key, actor=request.actor, effects=effects)
    return _import(row, key, source=request.import_source, effects=effects)


def _normalize(request):
    if not isinstance(request, ResolutionRequest):
        raise InvalidAttentionRequest("request must be a ResolutionRequest")
    if not isinstance(request.actor, str):
        raise InvalidAttentionRequest("actor is required")
    actor = request.actor.strip()
    if not actor:
        raise InvalidAttentionRequest("actor is required")
    if not isinstance(request.action, str):
        raise InvalidAttentionRequest("unknown action")
    action = request.action.strip().lower()
    if action not in ATTENTION_ACTIONS:
        raise InvalidAttentionRequest("unknown action")
    if isinstance(request.release_keys, (str, bytes)) or not isinstance(request.release_keys, Sequence):
        raise InvalidAttentionRequest("release_keys must be a sequence of strings")
    raw_keys = request.release_keys or ()
    keys = []
    seen = set()
    for raw in raw_keys:
        if not isinstance(raw, str):
            raise InvalidAttentionRequest("release_keys must contain only strings")
        key = raw.strip()
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    if not keys:
        raise InvalidAttentionRequest("no release_keys supplied")
    if request.import_source is not None and not isinstance(request.import_source, ImportSource):
        raise InvalidAttentionRequest("import_source must be an ImportSource")
    if request.import_source is not None:
        values = (request.import_source.nzb_name, request.import_source.nzb_folder)
        if any(value is not None and not isinstance(value, str) for value in values):
            raise InvalidAttentionRequest("import_source values must be strings")
    if request.import_source is not None and (action != ACTION_IMPORT or len(keys) != 1):
        raise InvalidAttentionRequest("import_source is valid only for one-key import")
    return ResolutionRequest(
        action=action,
        release_keys=tuple(keys),
        actor=actor,
        import_source=request.import_source,
    )


def _batch_order(keys):
    stamped = []
    for key in keys:
        row = journal.read_one(key)
        updated = (row or {}).get("updated_date")
        stamped.append((updated is not None, str(updated or ""), key))
    ranked = iter(sorted((item for item in stamped if item[0]), key=lambda item: item[1], reverse=True))
    return [next(ranked)[2] if item[0] else item[2] for item in stamped]


def _resolve(request, effects):
    normalized = _normalize(request)
    ordered = _batch_order(normalized.release_keys)
    processed_keys = ordered[:BATCH_CAP]
    results = tuple(_resolve_one(normalized, key, effects) for key in processed_keys)
    succeeded = sum(1 for result in results if result.ok)
    failed = len(results) - succeeded
    skipped = len(ordered) - len(processed_keys)
    return ResolutionReport(
        action=normalized.action,
        requested=len(ordered),
        processed=len(processed_keys),
        succeeded=succeeded,
        failed=failed,
        capped=skipped > 0,
        skipped_for_cap=skipped,
        cap=BATCH_CAP,
        results=results,
    )


def resolve(ctx, request):
    """Resolve one or many admitted obligations through one command path."""
    return _resolve(request, _RuntimeResolutionEffects(ctx))
