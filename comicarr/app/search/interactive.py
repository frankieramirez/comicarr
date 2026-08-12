#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Issue-scoped provider collection for Interactive release search."""

from __future__ import annotations

import threading

from sqlalchemy import select

from comicarr import db, helpers, logger, search, search_filer
from comicarr.app.common.redaction import redact_sensitive_text
from comicarr.app.core.workers import start_background_thread
from comicarr.app.search.interactive_sessions import (
    complete_search_session,
    create_pending_session,
    read_session,
    update_search_progress,
)
from comicarr.app.search.providers import effective_provider_plan
from comicarr.app.search.service import _search_route_health
from comicarr.tables import storyarcs

_ENTITY_TYPES = frozenset({"issue", "annual", "story_arc_issue"})
_WORKER_LOCK = threading.Lock()


def _resolve_entity(entity_type, entity_id):
    entity_type = str(entity_type or "").strip().lower()
    entity_id = str(entity_id or "").strip()
    if entity_type not in _ENTITY_TYPES or not entity_id:
        return None, {"success": False, "status_code": 400, "error": "Unsupported tracked item"}
    if entity_type == "story_arc_issue":
        row = db.select_one(select(storyarcs).where(storyarcs.c.IssueArcID == entity_id))
        mode = "story_arc" if row is not None else None
    else:
        row, mode, _oneoff = search._search_source_for_issue(entity_id, entity_type=entity_type)
    expected_mode = {"issue": "want", "annual": "want_ann", "story_arc_issue": "story_arc"}[entity_type]
    if row is None or mode != expected_mode:
        return None, {"success": False, "status_code": 404, "error": "Tracked item not found"}
    if entity_type in {"issue", "annual"}:
        series_id = row.get("ComicID")
    else:
        series_id = row.get("ComicID") or row.get("StoryArcID")
    return {"entity_type": entity_type, "entity_id": entity_id, "series_id": series_id}, None


def _provider_plan(ctx):
    return effective_provider_plan(
        ctx.config,
        is_blocked=helpers.block_provider_check,
    )


def start_search(ctx, *, actor, browser_session, entity_type, entity_id):
    """Validate one tracked item, create polling state, and start collection."""

    entity, error = _resolve_entity(entity_type, entity_id)
    if error:
        return error
    route_health = _search_route_health(ctx)
    if not route_health.get("success"):
        return {
            "success": False,
            "status_code": 409,
            "status": "blocked",
            "error": route_health.get("error") or "No complete acquisition route is ready",
            "routes": route_health.get("routes") or {},
        }
    plan = _provider_plan(ctx)
    executable = [provider for provider in plan if not provider.blocked]
    if not executable:
        return {
            "success": False,
            "status_code": 409,
            "status": "blocked",
            "error": "No enabled search provider is currently available",
        }
    initial_failures = [
        {"provider": provider.name, "code": "temporarily_blocked", "detail": "Provider is temporarily blocked"}
        for provider in plan
        if provider.blocked
    ]
    pending = create_pending_session(
        db.get_engine(),
        actor=actor,
        browser_session=browser_session,
        entity_type=entity["entity_type"],
        entity_id=entity["entity_id"],
        series_id=entity["series_id"],
        provider_total=len(plan),
        provider_failures=initial_failures,
    )
    try:
        start_background_thread(
            _collect,
            kwargs={
                "session_id": pending["session_id"],
                "entity": entity,
                "initial_failures": initial_failures,
                "provider_total": len(plan),
            },
            name="InteractiveReleaseSearch",
            registry=getattr(ctx, "background_workers", None),
        )
    except Exception as e:
        update_search_progress(
            db.get_engine(),
            session_id=pending["session_id"],
            state="failed",
            provider_failures=initial_failures
            + [{"provider": "Search", "code": "worker_unavailable", "detail": redact_sensitive_text(e)}],
        )
        return {"success": False, "status_code": 503, "error": "Interactive search worker is unavailable"}
    pending["success"] = True
    return pending


def _collect(*, session_id, entity, initial_failures, provider_total):
    evaluations = []
    failures = list(initial_failures)
    completed = set()
    engine = db.get_engine()

    def publish_progress(provider=None):
        update_search_progress(
            engine,
            session_id=session_id,
            state="running",
            provider_completed=min(provider_total, len(completed) + len(initial_failures)),
            current_provider=provider,
            provider_failures=failures,
        )

    def on_evaluations(values):
        evaluations.extend(values)

    def on_complete(provider):
        completed.add(provider.casefold())
        publish_progress(provider)

    def on_failure(provider, code, detail):
        failures.append(
            {
                "provider": provider,
                "code": code,
                "detail": redact_sensitive_text(detail),
            }
        )
        publish_progress(provider)

    publish_progress()
    try:
        # The legacy provider loop owns one global search lock. Manual mode
        # evaluates matches but never invokes verification/searcher handoff.
        with (
            _WORKER_LOCK,
            search_filer.interactive_collection(
                on_evaluations=on_evaluations,
                on_provider_complete=on_complete,
                on_provider_failure=on_failure,
            ),
        ):
            result = search.searchforissue(
                issueid=entity["entity_id"],
                manual=True,
                entity_type=entity["entity_type"] if entity["entity_type"] != "story_arc_issue" else None,
            )
        if isinstance(result, dict) and result.get("status") == "IN PROGRESS":
            failures.append(
                {"provider": "Search", "code": "search_busy", "detail": "Another search is already running"}
            )
    except Exception as e:
        logger.error("[INTERACTIVE-SEARCH] Collection failed: %s" % redact_sensitive_text(e))
        failures.append({"provider": "Search", "code": "collection_failed", "detail": redact_sensitive_text(e)})
        update_search_progress(
            engine,
            session_id=session_id,
            state="failed",
            provider_completed=min(provider_total, len(completed) + len(initial_failures)),
            provider_failures=failures,
        )
        return
    complete_search_session(
        engine,
        session_id=session_id,
        evaluations=evaluations,
        provider_completed=provider_total,
        provider_failures=failures,
    )


def get_search(*, session_id, actor, browser_session):
    return read_session(
        db.get_engine(),
        session_id=session_id,
        actor=actor,
        browser_session=browser_session,
    )
