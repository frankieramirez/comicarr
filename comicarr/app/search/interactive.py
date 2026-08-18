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
from contextlib import nullcontext

from sqlalchemy import select

from comicarr import db, helpers, logger, search, search_filer
from comicarr.app.common.redaction import redact_sensitive_text
from comicarr.app.core.workers import start_background_thread
from comicarr.app.search import routes as search_routes
from comicarr.app.search.interactive_sessions import (
    InteractiveCandidateConflict,
    claim_server_candidate,
    complete_search_session,
    create_pending_session,
    evaluation_reconstruction,
    finish_candidate_claim,
    read_session,
    release_candidate_claim,
    update_search_progress,
)
from comicarr.app.search.providers import effective_provider_plan
from comicarr.app.series import queries as series_queries
from comicarr.tables import comics, storyarcs

_ENTITY_TYPES = frozenset({"issue", "annual", "story_arc_issue", "series"})
_WORKER_LOCK = threading.Lock()
_GRAB_LOCK = threading.Lock()
MAX_SERIES_SEARCH_TARGETS = 8
_ISSUE_NUMBER_STEP = 1000


def _series_missing_items(ctx, series_id):
    """Eligible missing issues for a series-scoped Interactive release search."""

    from comicarr.app.search.bulk import selection_from_detail
    from comicarr.app.series.service import get_comic_detail

    return selection_from_detail(get_comic_detail(ctx, series_id))


def _ordered_missing(missing):
    from comicarr.helpers import issuedigits

    return sorted(
        missing or [],
        key=lambda item: (
            str(item.get("entity_type") or ""),
            issuedigits(item.get("issue_number")),
            str(item.get("entity_id") or ""),
        ),
    )


def _search_targets(missing, *, limit=MAX_SERIES_SEARCH_TARGETS):
    """Eligible missing items to query live, preferring each range start.

    Every eligible item is searched when the set fits the bound. Larger
    series keep range starts first so packs are still discovered.
    """

    from comicarr.helpers import issuedigits

    ordered = _ordered_missing(missing)
    starts = []
    previous_type = None
    previous_number = None
    for item in ordered:
        number = issuedigits(item.get("issue_number"))
        entity_type = item.get("entity_type")
        if previous_type != entity_type or previous_number is None or number - previous_number > _ISSUE_NUMBER_STEP:
            starts.append(item)
            if len(starts) >= limit:
                return starts
        previous_type = entity_type
        previous_number = number
    seen = {(item["entity_type"], str(item["entity_id"])) for item in starts}
    targets = list(starts)
    for item in ordered:
        key = (item["entity_type"], str(item["entity_id"]))
        if key in seen:
            continue
        targets.append(item)
        if len(targets) >= limit:
            break
    return targets


def _resolve_entity(entity_type, entity_id):
    entity_type = str(entity_type or "").strip().lower()
    entity_id = str(entity_id or "").strip()
    if entity_type not in _ENTITY_TYPES or not entity_id:
        return None, {"success": False, "status_code": 400, "error": "Unsupported tracked item"}
    if entity_type == "series":
        row = db.select_one(select(comics).where(comics.c.ComicID == entity_id))
        if row is None:
            return None, {"success": False, "status_code": 404, "error": "Tracked item not found"}
        return {
            "entity_type": "series",
            "entity_id": entity_id,
            "series_id": entity_id,
            "comic_name": row.get("ComicName"),
        }, None
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
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "series_id": series_id,
        "release_date": row.get("ReleaseDate"),
        "issue_date": row.get("IssueDate"),
        "digital_date": row.get("DigitalDate"),
    }, None


def _resolve_grab_entity(candidate):
    """Resolve the tracked item used to revalidate and hand off a candidate."""

    reconstruction = candidate.get("reconstruction") or {}
    if candidate.get("entity_type") == "series":
        anchor_type = reconstruction.get("anchor_entity_type")
        anchor_id = reconstruction.get("anchor_entity_id")
        if not anchor_type or not anchor_id:
            return None, {
                "success": False,
                "status_code": 409,
                "error": "Release candidate has no tracked issue to grab against",
            }
        return _resolve_entity(anchor_type, anchor_id)
    return _resolve_entity(candidate["entity_type"], candidate["entity_id"])


def _provider_plan(ctx):
    return effective_provider_plan(
        ctx.config,
        is_blocked=helpers.block_provider_check,
    )


def start_search(ctx, *, actor, browser_session, entity_type, entity_id):
    """Validate one tracked item or series, create polling state, and start collection."""

    entity, error = _resolve_entity(entity_type, entity_id)
    if error:
        return error
    if entity["entity_type"] == "series":
        missing = _series_missing_items(ctx, entity["entity_id"])
        if not missing:
            return {
                "success": False,
                "status_code": 409,
                "status": "blocked",
                "error": "No eligible missing issues remain to search",
            }
        entity["missing"] = missing
        entity["targets"] = _search_targets(missing)
    route_health = search_routes.route_health(ctx)
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
    provider_total = len(plan) * max(1, len(entity.get("targets") or [entity]))
    try:
        pending = create_pending_session(
            db.get_engine(),
            actor=actor,
            browser_session=browser_session,
            entity_type=entity["entity_type"],
            entity_id=entity["entity_id"],
            series_id=entity["series_id"],
            provider_total=provider_total,
            provider_failures=initial_failures,
        )
    except InteractiveCandidateConflict as e:
        return {
            "success": False,
            "status_code": 409,
            "status": "conflict",
            "error": str(e),
        }
    try:
        start_background_thread(
            _collect,
            kwargs={
                "session_id": pending["session_id"],
                "entity": entity,
                "initial_failures": initial_failures,
                "provider_total": provider_total,
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


def _evaluation_identity(evaluation):
    reconstruction = evaluation_reconstruction(evaluation)
    return tuple(
        str(reconstruction.get(key))
        for key in (
            "provider_config_id",
            "provider_type",
            "provider_name",
            "source_kind",
            "provider_item_digest",
            "pack",
        )
    )


def _satisfies_for_evaluation(evaluation, searched_item, eligible):
    legacy = evaluation.legacy_match or {}
    pack_info = legacy.get("pack_issuelist")
    found = []
    if legacy.get("pack") and isinstance(pack_info, dict):
        for issue in pack_info.get("issues") or []:
            issue_id = str(issue.get("issueid") or issue.get("IssueID") or "")
            match = eligible.get(("issue", issue_id))
            if match is None:
                continue
            found.append(
                {
                    "entity_type": "issue",
                    "entity_id": issue_id,
                    "issue_number": match.get("issue_number") or issue.get("issuenumber"),
                }
            )
        if found:
            return found
    match = eligible.get((searched_item["entity_type"], str(searched_item["entity_id"])))
    if match is None:
        return []
    return [
        {
            "entity_type": match["entity_type"],
            "entity_id": match["entity_id"],
            "issue_number": match.get("issue_number"),
        }
    ]


def _union_satisfies(existing, incoming):
    merged = list(existing.satisfies or [])
    seen = {(item["entity_type"], str(item["entity_id"])) for item in merged}
    for item in incoming.satisfies or []:
        key = (item["entity_type"], str(item["entity_id"]))
        if key in seen:
            continue
        merged.append(item)
        seen.add(key)
    existing.satisfies = merged


def _merge_series_evaluation(collected, evaluation):
    identity = _evaluation_identity(evaluation)
    existing = collected.get(identity)
    if existing is not None:
        _union_satisfies(existing, evaluation)
        return
    collected[identity] = evaluation


def _order_series_evaluations(collected):
    # Acceptance ranks above coverage and the pack flag: complete_search_session
    # truncates this ordered list, so rejected packs must never crowd out
    # grabbable releases.
    evaluations = list(collected.values())
    evaluations.sort(
        key=lambda evaluation: (
            0 if (evaluation.verdict or {}).get("accepted") else 1,
            -len(evaluation.satisfies or []),
            0 if evaluation.candidate.get("pack") else 1,
        )
    )
    return evaluations


def _collect(*, session_id, entity, initial_failures, provider_total):
    if entity.get("entity_type") == "series":
        _collect_series(
            session_id=session_id,
            entity=entity,
            initial_failures=initial_failures,
            provider_total=provider_total,
        )
        return
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


def _collect_series(*, session_id, entity, initial_failures, provider_total):
    collected = {}
    failures = list(initial_failures)
    completed_count = 0
    engine = db.get_engine()
    missing = entity.get("missing") or []
    targets = entity.get("targets") or _search_targets(missing)
    eligible = {(item["entity_type"], str(item["entity_id"])): item for item in missing}
    # provider_total counts every provider once per target, so blocked providers
    # (which never report completion) have to be offset per target too.
    blocked_offset = len(initial_failures) * max(1, len(targets))

    def publish_progress(provider=None):
        update_search_progress(
            engine,
            session_id=session_id,
            state="running",
            provider_completed=min(provider_total, completed_count + blocked_offset),
            current_provider=provider,
            provider_failures=failures,
        )

    publish_progress()

    def _bind_progress():
        finished_providers = set()

        def on_complete(provider):
            nonlocal completed_count
            key = provider.casefold()
            if key not in finished_providers:
                finished_providers.add(key)
                completed_count += 1
            publish_progress(provider)

        return on_complete

    target_failures = 0
    for target in targets:

        def on_evaluations(values, searched=target):
            for evaluation in values:
                evaluation.satisfies = _satisfies_for_evaluation(evaluation, searched, eligible)
                _merge_series_evaluation(collected, evaluation)

        def on_failure(provider, code, detail):
            failures.append(
                {
                    "provider": provider,
                    "code": code,
                    "detail": redact_sensitive_text(detail),
                }
            )
            publish_progress(provider)

        on_complete = _bind_progress()

        try:
            with (
                _WORKER_LOCK,
                search_filer.interactive_collection(
                    on_evaluations=on_evaluations,
                    on_provider_complete=on_complete,
                    on_provider_failure=on_failure,
                ),
            ):
                result = search.searchforissue(
                    issueid=target["entity_id"],
                    manual=True,
                    entity_type=target["entity_type"] if target["entity_type"] != "story_arc_issue" else None,
                )
            if isinstance(result, dict) and result.get("status") == "IN PROGRESS":
                failures.append(
                    {"provider": "Search", "code": "search_busy", "detail": "Another search is already running"}
                )
                target_failures += 1
        except Exception as e:
            logger.error("[INTERACTIVE-SEARCH] Series collection failed: %s" % redact_sensitive_text(e))
            failures.append({"provider": "Search", "code": "collection_failed", "detail": redact_sensitive_text(e)})
            target_failures += 1

    if target_failures == len(targets) and not collected:
        update_search_progress(
            engine,
            session_id=session_id,
            state="failed",
            provider_completed=min(provider_total, completed_count + blocked_offset),
            provider_failures=failures,
        )
        return
    complete_search_session(
        engine,
        session_id=session_id,
        evaluations=_order_series_evaluations(collected),
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


def _same_candidate_identity(stored, current):
    keys = (
        "provider_config_id",
        "provider_type",
        "provider_name",
        "source_kind",
        "provider_item_digest",
        "pack",
    )
    if any(str(stored.get(key)) != str(current.get(key)) for key in keys):
        return False
    stored_id = stored.get("provider_item_id")
    return stored_id in (None, "") or str(stored_id) == str(current.get("provider_item_id"))


def _revalidate_candidate(entity, *, override_reason=None):
    evaluations = []

    def on_evaluations(values):
        evaluations.extend(values)

    override = search_filer.interactive_candidate_override(override_reason) if override_reason else nullcontext()
    with (
        _WORKER_LOCK,
        override,
        search_filer.interactive_collection(
            on_evaluations=on_evaluations,
            on_provider_complete=lambda _provider: None,
            on_provider_failure=lambda _provider, _code, _detail: None,
        ),
    ):
        result = search.searchforissue(
            issueid=entity["entity_id"],
            manual=True,
            entity_type=entity["entity_type"] if entity["entity_type"] != "story_arc_issue" else None,
        )
    return evaluations, result


def _verification_info(match, entity_type):
    return {
        "foundc": {"status": False},
        "nzbprov": match["nzbprov"],
        "RSS": "no",
        "ComicName": match["ComicName"],
        "ComicID": match["ComicID"],
        "IssueID": match["IssueID"],
        "IssueNumber": match["IssueNumber"],
        "ComicYear": match["comyear"],
        "SARC": match.get("SARC"),
        "IssueArcID": match.get("IssueArcID"),
        "oneoff": match.get("oneoff", False),
        "smode": {
            "issue": "want",
            "annual": "want_ann",
            "story_arc_issue": "story_arc",
        }[entity_type],
    }


def _candidate_eligibility(entity):
    candidate = series_queries.get_search_candidate_state(
        entity["entity_id"],
        entity_type=entity["entity_type"],
    )
    if candidate is None:
        return {"status": False, "reason": "tracked item no longer exists"}
    return search.searchforissue_checker(
        entity["entity_id"],
        entity.get("release_date"),
        entity.get("issue_date"),
        entity.get("digital_date"),
        {
            "candidate": candidate,
            "entity_type": entity["entity_type"],
        },
    )


def _release_with_error(engine, candidate, *, error, status_code=409, code="candidate_changed"):
    release_candidate_claim(engine, candidate=candidate)
    return {
        "success": False,
        "status_code": status_code,
        "status": "blocked",
        "code": code,
        "error": error,
    }


def grab_candidate(
    ctx,
    *,
    session_id,
    candidate_id,
    actor,
    browser_session,
    override=False,
):
    """Re-find, revalidate, and journal-handoff one owned release candidate."""

    # Fail fast instead of queueing: a grab holds the lock for its whole
    # revalidation + handoff, and each waiter would park a worker thread from
    # the shared to_thread pool for that duration (#733).
    if not _GRAB_LOCK.acquire(blocking=False):
        return {
            "success": False,
            "status_code": 409,
            "status": "blocked",
            "code": "grab_busy",
            "error": "Another release grab is already being processed",
        }
    try:
        engine = db.get_engine()
        claim = claim_server_candidate(
            engine,
            session_id=session_id,
            candidate_id=candidate_id,
            actor=actor,
            browser_session=browser_session,
        )
        if not claim["claimed"]:
            outcome = dict(claim.get("outcome") or {"status": claim["state"]})
            outcome.update({"success": claim["state"] == "submitted", "idempotent": True})
            return outcome

        candidate = claim["candidate"]
        public = candidate["public"]
        verdict = public.get("verdict") or {}
        if not verdict.get("accepted"):
            if not verdict.get("overrideable"):
                return _release_with_error(
                    engine,
                    candidate,
                    error="Release candidate cannot be overridden",
                )
            if not override:
                return _release_with_error(
                    engine,
                    candidate,
                    error="Release candidate requires an explicit override",
                    code="override_required",
                )
            override_reason = verdict.get("reason_code")
        else:
            override_reason = None

        entity, error = _resolve_grab_entity(candidate)
        if error:
            return _release_with_error(engine, candidate, error=error["error"], status_code=error["status_code"])

        eligibility = _candidate_eligibility(entity)
        if not eligibility.get("status"):
            return _release_with_error(
                engine,
                candidate,
                error="Tracked item is no longer eligible for acquisition",
                code="item_not_eligible",
            )

        route_health = search_routes.route_health(ctx)
        if not route_health.get("success"):
            return _release_with_error(
                engine,
                candidate,
                error=route_health.get("error") or "No complete acquisition route is ready",
                code="route_unavailable",
            )
        if not any(not provider.blocked for provider in _provider_plan(ctx)):
            return _release_with_error(
                engine,
                candidate,
                error="No enabled search provider is currently available",
                code="provider_unavailable",
            )

        try:
            evaluations, search_result = _revalidate_candidate(entity, override_reason=override_reason)
        except Exception as e:
            logger.error("[INTERACTIVE-GRAB] Candidate revalidation failed: %s" % redact_sensitive_text(e))
            return _release_with_error(
                engine,
                candidate,
                error="Release candidate could not be revalidated",
                status_code=502,
                code="revalidation_failed",
            )
        if isinstance(search_result, dict) and search_result.get("status") == "IN PROGRESS":
            return _release_with_error(
                engine,
                candidate,
                error="Another search is already running",
                code="search_busy",
            )

        matches = [
            evaluation
            for evaluation in evaluations
            if _same_candidate_identity(
                candidate["reconstruction"],
                evaluation_reconstruction(evaluation),
            )
        ]
        if len(matches) != 1 or matches[0].legacy_match is None:
            return _release_with_error(
                engine,
                candidate,
                error="Release candidate is no longer uniquely available under the current provider configuration",
                code="candidate_changed",
            )

        match = dict(matches[0].legacy_match)
        match["downloadit"] = True
        info = _verification_info(match, entity["entity_type"])
        try:
            result = search.verification([match], info)
        except Exception as e:
            logger.error("[INTERACTIVE-GRAB] Handoff outcome is ambiguous: %s" % redact_sensitive_text(e))
            outcome = {
                "status": "manual_review",
                "candidate_id": candidate_id,
                "code": "handoff_outcome_ambiguous",
                "error": "Handoff outcome requires manual review",
                "status_code": 500,
            }
            finish_candidate_claim(engine, candidate=candidate, state="manual_review", outcome=outcome)
            return dict(outcome, success=False)

        found = (result or {}).get("foundc") or {}
        handoff = found.get("info") or {}
        if not found.get("status"):
            outcome = {
                "status": "failed",
                "candidate_id": candidate_id,
                "code": "handoff_rejected",
                "error": "Release handoff was not accepted",
                "status_code": 502,
            }
            finish_candidate_claim(engine, candidate=candidate, state="failed", outcome=outcome)
            return dict(outcome, success=False)

        outcome = {
            "status": "submitted",
            "candidate_id": candidate_id,
            "journal_release_key": handoff.get("journal_release_key"),
            "journal_managed": bool(handoff.get("journal_managed")),
        }
        outcome = finish_candidate_claim(engine, candidate=candidate, state="submitted", outcome=outcome)
        return dict(outcome, success=True, idempotent=False)
    finally:
        _GRAB_LOCK.release()
