#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Bounded, browser-owned persistence for Interactive release search.

The browser receives only opaque ids and the matcher's sanitized public
projection.  The server-side reconstruction record is a deliberately narrow
allowlist: it can identify the current provider configuration and candidate,
but cannot replay a request by itself and never stores credentials or URLs.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import re
import secrets
import threading
from collections.abc import Mapping, Sequence

from sqlalchemy import delete, exists, insert, select, update

from comicarr import logger
from comicarr.app.common.redaction import redact_sensitive_text
from comicarr.db import get_engine
from comicarr.tables import interactive_search_candidates, interactive_search_sessions

SESSION_TTL_SECONDS = 10 * 60
MAX_CANDIDATES = 200
MAX_SESSION_BYTES = 512 * 1024
MAX_RECORD_BYTES = 64 * 1024
CLEANUP_BATCH_SIZE = 500
CLAIM_LEASE_SECONDS = 60 * 60
JOB_ID = "interactive_search_retention"
JOB_NAME = "Interactive Search Retention"

_ENTITY_TYPES = frozenset({"issue", "annual", "story_arc_issue", "series"})
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_SAFE_PROVIDER_TYPE = re.compile(r"^[a-z0-9_-]{1,32}$")
_URL_PATTERN = re.compile(r"(?i)https?://[^\s]+")
_CREATE_LOCK = threading.Lock()


class InteractiveSearchSessionError(RuntimeError):
    """Base class for safe Interactive release search persistence errors."""


class InteractiveSearchAuthorizationError(InteractiveSearchSessionError):
    """An opaque session is unavailable to the authenticated browser."""


class InteractiveSearchExpired(InteractiveSearchAuthorizationError):
    """The authenticated browser's Interactive search session expired."""


class InteractiveSearchLimitError(InteractiveSearchSessionError):
    """A session exceeded its fixed candidate or serialized-size bound."""


class InteractiveCandidateConflict(InteractiveSearchSessionError):
    """A selected candidate cannot start another handoff."""


def _now(value=None):
    value = value or datetime.datetime.now(datetime.timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _digest(value):
    return hashlib.sha256(str(value).encode("utf-8", "replace")).hexdigest()


def _slot_digest(actor, browser_session, entity_type, entity_id):
    return _digest("\0".join((str(actor), _digest(browser_session), entity_type, entity_id)))


def _bounded_json(value, *, label):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise InteractiveSearchSessionError("%s is not serializable" % label) from e
    if len(encoded.encode("utf-8")) > MAX_RECORD_BYTES:
        raise InteractiveSearchLimitError("%s exceeds the per-record storage limit" % label)
    return encoded


def _decode_object(value, *, label):
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError) as e:
        raise InteractiveSearchSessionError("stored %s is malformed" % label) from e
    if not isinstance(decoded, dict):
        raise InteractiveSearchSessionError("stored %s is malformed" % label)
    return decoded


def _sanitize_public(value):
    """Recursively redact credential syntax and entire URLs from public data."""

    if isinstance(value, Mapping):
        return {str(key): _sanitize_public(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_public(item) for item in value]
    if isinstance(value, str):
        return _URL_PATTERN.sub("[redacted URL]", redact_sensitive_text(value))[:4096]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize_public(str(value))


def _safe_identifier(value):
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    candidate = str(value).strip()
    if not _SAFE_IDENTIFIER.fullmatch(candidate):
        return None
    if any(marker in candidate.lower() for marker in ("apikey", "api_key", "password", "passkey", "token")):
        return None
    return candidate


def _entry_value(entry, key):
    try:
        return entry.get(key)
    except AttributeError:
        try:
            return entry[key]
        except Exception:
            return None


def _candidate_reconstruction(evaluation, public):
    """Build the credential-free server reconstruction allowlist."""

    legacy = getattr(evaluation, "legacy_match", None) or {}
    hint = getattr(evaluation, "reconstruction_hint", None) or {}
    hint = hint if isinstance(hint, dict) else {}
    provider_stat = legacy.get("provider_stat") if isinstance(legacy, dict) else None
    provider_stat = provider_stat if isinstance(provider_stat, dict) else {}
    entry = legacy.get("entry") if isinstance(legacy, dict) else None
    # The pre-match provider identity is stable across accepted and overridden
    # evaluations. A generated legacy nzbid may instead derive from a link and
    # change merely because the same rejection was explicitly overridden.
    raw_identity = hint.get("provider_item_id")
    if raw_identity in (None, ""):
        raw_identity = _entry_value(entry, "id")
    if raw_identity in (None, "") and isinstance(legacy, dict):
        raw_identity = legacy.get("nzbid")
    if raw_identity in (None, "") and isinstance(legacy, dict):
        raw_identity = legacy.get("link")
    provider_type = str(provider_stat.get("type") or hint.get("provider_type") or "").lower()
    if not _SAFE_PROVIDER_TYPE.fullmatch(provider_type):
        provider_type = "unknown"
    provider_config_id = provider_stat.get("id")
    if provider_config_id is None:
        provider_config_id = hint.get("provider_config_id")
    if not isinstance(provider_config_id, int):
        provider_config_id = _safe_identifier(provider_config_id)

    candidate = public.get("candidate") or {}
    verdict = public.get("verdict") or {}
    reconstruction = {
        "provider_config_id": provider_config_id,
        "provider_type": provider_type,
        "provider_name": str(candidate.get("provider") or "Search provider")[:255],
        "source_kind": str(candidate.get("source_kind") or "unknown")[:32],
        "provider_item_id": _safe_identifier(raw_identity),
        "provider_item_digest": _digest(raw_identity or ""),
        "match_kind": str(verdict.get("match_kind") or "none")[:32],
        "pack": bool(candidate.get("pack")),
    }
    if hint.get("search_mode") == "unfiltered":
        # An unfiltered-mode candidate must be revalidated under the same
        # bare-title pass, so the mode is part of the safe reconstruction.
        reconstruction["search_mode"] = "unfiltered"
    satisfies = getattr(evaluation, "satisfies", None) or public.get("satisfies")
    if isinstance(satisfies, list) and satisfies and isinstance(satisfies[0], Mapping):
        anchor_type = str(satisfies[0].get("entity_type") or "").strip().lower()
        anchor_id = str(satisfies[0].get("entity_id") or "").strip()
        if anchor_type in {"issue", "annual", "story_arc_issue"} and anchor_id:
            reconstruction["anchor_entity_type"] = anchor_type
            reconstruction["anchor_entity_id"] = anchor_id[:255]
    # The digest is useful when an unsafe identity must be re-found under the
    # current provider config; it is not reversible and grants no access.
    return reconstruction


def evaluation_reconstruction(evaluation):
    """Return the same safe identity projection used by persisted candidates."""

    public = _sanitize_public(evaluation.as_dict())
    return _candidate_reconstruction(evaluation, public)


def _evaluation_record(evaluation, ordinal, expires_at, created_at):
    public = _sanitize_public(evaluation.as_dict())
    if not isinstance(public, dict) or not isinstance(public.get("candidate"), dict):
        raise InteractiveSearchSessionError("release candidate public projection is malformed")
    if not isinstance(public.get("verdict"), dict):
        raise InteractiveSearchSessionError("release candidate verdict is malformed")
    reconstruction = _candidate_reconstruction(evaluation, public)
    public_json = _bounded_json(public, label="release candidate public projection")
    reconstruction_json = _bounded_json(reconstruction, label="release candidate reconstruction")
    fingerprint = _digest(public_json + "\0" + reconstruction_json)
    verdict = public["verdict"]
    available = bool(verdict.get("accepted") or verdict.get("overrideable"))
    return {
        "candidate_id": secrets.token_urlsafe(24),
        "ordinal": ordinal,
        "state": "available" if available else "unavailable",
        "public_json": public_json,
        "reconstruction_json": reconstruction_json,
        "fingerprint": fingerprint,
        "created_at": created_at,
        "updated_at": created_at,
        "expires_at": expires_at,
    }


def _validate_owner(actor, browser_session):
    if actor in (None, "") or browser_session in (None, ""):
        raise ValueError("interactive search requires an authenticated browser session")


def create_session(
    engine,
    *,
    actor,
    browser_session,
    entity_type,
    entity_id,
    evaluations: Sequence,
    series_id=None,
    now=None,
    ttl_seconds=SESSION_TTL_SECONDS,
    initial_state="ready",
    provider_total=0,
    provider_failures=None,
):
    """Replace one actor/browser/item slot with a bounded ready session.

    Replacement and candidate insertion share one transaction, so readers see
    either the previous complete session or the new complete session.  A new
    opaque id invalidates every URL from the superseded search.
    """

    _validate_owner(actor, browser_session)
    entity_type = str(entity_type)
    entity_id = str(entity_id or "")
    if entity_type not in _ENTITY_TYPES or not entity_id or len(entity_id) > 255:
        raise ValueError("interactive search requires a supported tracked item")
    if len(evaluations) > MAX_CANDIDATES:
        raise InteractiveSearchLimitError("interactive search candidate count exceeds %s" % MAX_CANDIDATES)
    if not 1 <= int(ttl_seconds) <= SESSION_TTL_SECONDS:
        raise ValueError("interactive search TTL must be between 1 and %s seconds" % SESSION_TTL_SECONDS)

    created = _now(now)
    created_at = created.isoformat()
    expires_at = (created + datetime.timedelta(seconds=int(ttl_seconds))).isoformat()
    records = [
        _evaluation_record(evaluation, ordinal, expires_at, created_at)
        for ordinal, evaluation in enumerate(evaluations)
    ]
    total_bytes = sum(
        len(record["public_json"].encode("utf-8")) + len(record["reconstruction_json"].encode("utf-8"))
        for record in records
    )
    if total_bytes > MAX_SESSION_BYTES:
        raise InteractiveSearchLimitError("interactive search session exceeds the storage limit")

    opaque_id = secrets.token_urlsafe(24)
    slot = _slot_digest(actor, browser_session, entity_type, entity_id)
    safe_failures = _bounded_failures(provider_failures)
    session_values = {
        "session_id": opaque_id,
        "slot_digest": slot,
        "actor_digest": _digest(actor),
        "browser_digest": _digest(browser_session),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "series_id": str(series_id)[:255] if series_id not in (None, "") else None,
        "state": str(initial_state)[:32],
        "candidate_count": len(records),
        "provider_total": max(0, int(provider_total)),
        "provider_completed": 0,
        "current_provider": None,
        "provider_failures_json": _bounded_json(safe_failures, label="provider failures"),
        "created_at": created_at,
        "updated_at": created_at,
        "expires_at": expires_at,
    }

    # Comicarr runs one application process by default. The lock closes the
    # absent-row race inside that process; the unique slot remains the durable
    # backstop if deployment topology changes.
    with _CREATE_LOCK:
        purge_expired_sessions(engine, now=created)
        with engine.begin() as conn:
            previous_id = conn.execute(
                select(interactive_search_sessions.c.session_id).where(
                    interactive_search_sessions.c.slot_digest == slot
                )
            ).scalar_one_or_none()
            if previous_id is None:
                conn.execute(insert(interactive_search_sessions).values(**session_values))
            else:
                active_claim = conn.execute(
                    select(interactive_search_candidates.c.candidate_id)
                    .where(interactive_search_candidates.c.session_id == previous_id)
                    .where(interactive_search_candidates.c.state == "submitting")
                    .where(
                        interactive_search_candidates.c.updated_at
                        > (created - datetime.timedelta(seconds=CLAIM_LEASE_SECONDS)).isoformat()
                    )
                    .limit(1)
                ).scalar_one_or_none()
                if active_claim is not None:
                    raise InteractiveCandidateConflict("release candidate handoff is already in progress")
                conn.execute(
                    delete(interactive_search_candidates).where(
                        interactive_search_candidates.c.session_id == previous_id
                    )
                )
                conn.execute(
                    update(interactive_search_sessions)
                    .where(interactive_search_sessions.c.slot_digest == slot)
                    .values(**session_values)
                )
            if records:
                conn.execute(
                    insert(interactive_search_candidates),
                    [dict(record, session_id=opaque_id) for record in records],
                )
        return read_session(
            engine,
            session_id=opaque_id,
            actor=actor,
            browser_session=browser_session,
            now=created,
        )


def create_pending_session(
    engine,
    *,
    actor,
    browser_session,
    entity_type,
    entity_id,
    series_id=None,
    provider_total=0,
    provider_failures=None,
    now=None,
):
    """Create an opaque polling resource before provider collection starts."""

    result = create_session(
        engine,
        actor=actor,
        browser_session=browser_session,
        entity_type=entity_type,
        entity_id=entity_id,
        evaluations=[],
        series_id=series_id,
        now=now,
        initial_state="queued",
        provider_total=provider_total,
        provider_failures=provider_failures,
    )
    return result


def update_search_progress(
    engine,
    *,
    session_id,
    state="running",
    provider_completed=None,
    current_provider=None,
    provider_failures=None,
    now=None,
):
    """Persist one sanitized worker progress snapshot."""

    values = {
        "state": str(state)[:32],
        "current_provider": _sanitize_public(current_provider)[:255] if current_provider else None,
        "updated_at": _now(now).isoformat(),
    }
    if provider_completed is not None:
        values["provider_completed"] = max(0, int(provider_completed))
    if provider_failures is not None:
        safe_failures = _bounded_failures(provider_failures)
        values["provider_failures_json"] = _bounded_json(safe_failures, label="provider failures")
    with engine.begin() as conn:
        result = conn.execute(
            update(interactive_search_sessions)
            .where(interactive_search_sessions.c.session_id == str(session_id))
            .where(interactive_search_sessions.c.expires_at > _now(now).isoformat())
            .values(**values)
        )
    return bool(result.rowcount)


def complete_search_session(
    engine,
    *,
    session_id,
    evaluations: Sequence,
    provider_completed,
    provider_failures=None,
    now=None,
):
    """Atomically publish all collected candidates and terminal progress."""

    completed = _now(now)
    completed_at = completed.isoformat()
    with engine.begin() as conn:
        session = (
            conn.execute(
                select(interactive_search_sessions).where(interactive_search_sessions.c.session_id == str(session_id))
            )
            .mappings()
            .first()
        )
        if (
            session is None
            or session["state"] not in {"queued", "running"}
            or completed >= _now(datetime.datetime.fromisoformat(session["expires_at"]))
        ):
            return False
        records = []
        total_bytes = 0
        for evaluation in evaluations[:MAX_CANDIDATES]:
            record = _evaluation_record(evaluation, len(records), session["expires_at"], completed_at)
            record_bytes = len(record["public_json"].encode("utf-8")) + len(
                record["reconstruction_json"].encode("utf-8")
            )
            if total_bytes + record_bytes > MAX_SESSION_BYTES:
                break
            records.append(record)
            total_bytes += record_bytes
        if len(records) < len(evaluations):
            # The candidate/byte bounds are deliberate, but hitting them must
            # never read as "that was everything" (#767). Prepended so the
            # failure-list bound cannot drop the notice itself.
            provider_failures = [
                {
                    "provider": "Search",
                    "code": "results_truncated",
                    "detail": "Showing %d of %d collected results; the session storage bound dropped the rest"
                    % (len(records), len(evaluations)),
                }
            ] + list(provider_failures or [])
        safe_failures = _bounded_failures(provider_failures)
        result = conn.execute(
            update(interactive_search_sessions)
            .where(interactive_search_sessions.c.session_id == str(session_id))
            .where(interactive_search_sessions.c.state.in_(("queued", "running")))
            .values(
                state="complete",
                candidate_count=len(records),
                provider_completed=max(0, int(provider_completed)),
                current_provider=None,
                provider_failures_json=_bounded_json(safe_failures, label="provider failures"),
                updated_at=completed_at,
            )
        )
        if not result.rowcount:
            return False
        conn.execute(
            delete(interactive_search_candidates).where(interactive_search_candidates.c.session_id == str(session_id))
        )
        if records:
            conn.execute(
                insert(interactive_search_candidates),
                [dict(record, session_id=str(session_id)) for record in records],
            )
    return bool(result.rowcount)


def _bounded_failures(provider_failures):
    failures = []
    for failure in list(provider_failures or [])[:25]:
        if not isinstance(failure, Mapping):
            continue
        failures.append(
            {
                "provider": str(_sanitize_public(failure.get("provider") or "Search"))[:255],
                "code": str(_sanitize_public(failure.get("code") or "provider_error"))[:64],
                "detail": str(_sanitize_public(failure.get("detail") or "Provider search failed"))[:512],
            }
        )
    return failures


def _authorized_row(engine, *, session_id, actor, browser_session, now):
    _validate_owner(actor, browser_session)
    with engine.connect() as conn:
        row = (
            conn.execute(
                select(interactive_search_sessions).where(interactive_search_sessions.c.session_id == str(session_id))
            )
            .mappings()
            .first()
        )
    if row is None:
        raise InteractiveSearchAuthorizationError("interactive search session is not available to this browser")
    if not hmac.compare_digest(str(row["actor_digest"]), _digest(actor)):
        raise InteractiveSearchAuthorizationError("interactive search session is not available to this browser")
    if not hmac.compare_digest(str(row["browser_digest"]), _digest(browser_session)):
        raise InteractiveSearchAuthorizationError("interactive search session is not available to this browser")
    if _now(now) >= _now(datetime.datetime.fromisoformat(row["expires_at"])):
        raise InteractiveSearchExpired("interactive search session expired")
    return dict(row)


def read_session(engine, *, session_id, actor, browser_session, now=None):
    """Return only the opaque id and sanitized candidate projections."""

    row = _authorized_row(
        engine,
        session_id=session_id,
        actor=actor,
        browser_session=browser_session,
        now=now,
    )
    with engine.connect() as conn:
        candidate_rows = (
            conn.execute(
                select(interactive_search_candidates)
                .where(interactive_search_candidates.c.session_id == row["session_id"])
                .order_by(interactive_search_candidates.c.ordinal)
            )
            .mappings()
            .all()
        )
    candidates = []
    for candidate_row in candidate_rows:
        public = _decode_object(candidate_row["public_json"], label="release candidate projection")
        public["candidate_id"] = candidate_row["candidate_id"]
        public["state"] = candidate_row["state"]
        candidates.append(public)
    failures = json.loads(row.get("provider_failures_json") or "[]")
    if not isinstance(failures, list):
        failures = []
    return {
        "session_id": row["session_id"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "series_id": row["series_id"],
        "state": row["state"],
        "candidate_count": row["candidate_count"],
        "progress": {
            "provider_total": row.get("provider_total") or 0,
            "provider_completed": row.get("provider_completed") or 0,
            "current_provider": row.get("current_provider"),
        },
        "provider_failures": failures,
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "candidates": candidates,
    }


def read_server_candidate(
    engine,
    *,
    session_id,
    candidate_id,
    actor,
    browser_session,
    now=None,
):
    """Authorize one candidate and return its private reconstruction record.

    This is a server-only seam for the later safe-grab ticket. HTTP responses
    must continue to use :func:`read_session`.
    """

    session = _authorized_row(
        engine,
        session_id=session_id,
        actor=actor,
        browser_session=browser_session,
        now=now,
    )
    with engine.connect() as conn:
        row = (
            conn.execute(
                select(interactive_search_candidates)
                .where(interactive_search_candidates.c.session_id == session["session_id"])
                .where(interactive_search_candidates.c.candidate_id == str(candidate_id))
            )
            .mappings()
            .first()
        )
    if row is None:
        raise InteractiveSearchAuthorizationError("release candidate is not available to this browser")
    return {
        "candidate_id": row["candidate_id"],
        "session_id": row["session_id"],
        "state": row["state"],
        "fingerprint": row["fingerprint"],
        "public": _decode_object(row["public_json"], label="release candidate projection"),
        "reconstruction": _decode_object(
            row["reconstruction_json"],
            label="release candidate reconstruction",
        ),
    }


def claim_server_candidate(
    engine,
    *,
    session_id,
    candidate_id,
    actor,
    browser_session,
    now=None,
):
    """Atomically claim one available candidate for server-side handoff.

    Terminal outcomes are returned verbatim to make browser retries
    idempotent. An in-progress claim is never stolen: the download journal is
    the cross-process side-effect boundary, while this state prevents normal
    concurrent requests from reaching it twice.
    """

    session = _authorized_row(
        engine,
        session_id=session_id,
        actor=actor,
        browser_session=browser_session,
        now=now,
    )
    timestamp = _now(now).isoformat()
    with engine.begin() as conn:
        row = (
            conn.execute(
                select(interactive_search_candidates)
                .where(interactive_search_candidates.c.session_id == session["session_id"])
                .where(interactive_search_candidates.c.candidate_id == str(candidate_id))
            )
            .mappings()
            .first()
        )
        if row is None:
            raise InteractiveSearchAuthorizationError("release candidate is not available to this browser")
        reconstruction = _decode_object(
            row["reconstruction_json"],
            label="release candidate reconstruction",
        )
        if row["state"] in {"submitted", "failed", "manual_review"}:
            candidate = _server_candidate(row, reconstruction)
            candidate["entity_type"] = session["entity_type"]
            candidate["entity_id"] = session["entity_id"]
            return {
                "claimed": False,
                "state": row["state"],
                "outcome": reconstruction.get("selection_outcome"),
                "candidate": candidate,
            }
        if row["state"] == "submitting":
            raise InteractiveCandidateConflict("release candidate handoff is already in progress")
        if row["state"] != "available":
            raise InteractiveCandidateConflict("release candidate is not available for handoff")
        result = conn.execute(
            update(interactive_search_candidates)
            .where(interactive_search_candidates.c.candidate_id == row["candidate_id"])
            .where(interactive_search_candidates.c.session_id == session["session_id"])
            .where(interactive_search_candidates.c.state == "available")
            .where(interactive_search_candidates.c.expires_at > timestamp)
            .values(state="submitting", updated_at=timestamp)
        )
        if not result.rowcount:
            raise InteractiveCandidateConflict("release candidate handoff is already in progress")
    candidate = _server_candidate(row, reconstruction)
    candidate["state"] = "submitting"
    candidate["entity_type"] = session["entity_type"]
    candidate["entity_id"] = session["entity_id"]
    return {"claimed": True, "state": "submitting", "outcome": None, "candidate": candidate}


def _server_candidate(row, reconstruction):
    return {
        "candidate_id": row["candidate_id"],
        "session_id": row["session_id"],
        "state": row["state"],
        "fingerprint": row["fingerprint"],
        "public": _decode_object(row["public_json"], label="release candidate projection"),
        "reconstruction": reconstruction,
    }


def finish_candidate_claim(engine, *, candidate, state, outcome, now=None):
    """Persist one bounded terminal handoff outcome using the claim CAS."""

    if state not in {"submitted", "failed", "manual_review"}:
        raise ValueError("unsupported release candidate outcome")
    reconstruction = dict(candidate["reconstruction"])
    reconstruction["selection_outcome"] = _sanitize_public(outcome)
    encoded = _bounded_json(reconstruction, label="release candidate handoff outcome")
    with engine.begin() as conn:
        result = conn.execute(
            update(interactive_search_candidates)
            .where(interactive_search_candidates.c.candidate_id == candidate["candidate_id"])
            .where(interactive_search_candidates.c.session_id == candidate["session_id"])
            .where(interactive_search_candidates.c.fingerprint == candidate["fingerprint"])
            .where(interactive_search_candidates.c.state == "submitting")
            .values(
                state=state,
                reconstruction_json=encoded,
                updated_at=_now(now).isoformat(),
            )
        )
    if not result.rowcount:
        raise InteractiveCandidateConflict("release candidate claim changed before completion")
    return reconstruction["selection_outcome"]


def release_candidate_claim(engine, *, candidate, now=None):
    """Release a claim after a deterministic pre-handoff validation failure."""

    reconstruction = dict(candidate["reconstruction"])
    reconstruction.pop("selection_outcome", None)
    with engine.begin() as conn:
        result = conn.execute(
            update(interactive_search_candidates)
            .where(interactive_search_candidates.c.candidate_id == candidate["candidate_id"])
            .where(interactive_search_candidates.c.session_id == candidate["session_id"])
            .where(interactive_search_candidates.c.fingerprint == candidate["fingerprint"])
            .where(interactive_search_candidates.c.state == "submitting")
            .values(
                state="available",
                reconstruction_json=_bounded_json(reconstruction, label="release candidate reconstruction"),
                updated_at=_now(now).isoformat(),
            )
        )
    return bool(result.rowcount)


def purge_expired_sessions(engine, *, now=None, batch_size=CLEANUP_BATCH_SIZE):
    """Delete at most one bounded batch of expired sessions and candidates."""

    limit = max(1, min(int(batch_size), CLEANUP_BATCH_SIZE))
    cutoff = _now(now).isoformat()
    claim_cutoff = (_now(now) - datetime.timedelta(seconds=CLAIM_LEASE_SECONDS)).isoformat()
    active_claim = exists(
        select(interactive_search_candidates.c.candidate_id)
        .where(interactive_search_candidates.c.session_id == interactive_search_sessions.c.session_id)
        .where(interactive_search_candidates.c.state == "submitting")
        .where(interactive_search_candidates.c.updated_at > claim_cutoff)
    )
    with engine.begin() as conn:
        session_ids = list(
            conn.execute(
                select(interactive_search_sessions.c.session_id)
                .where(interactive_search_sessions.c.expires_at <= cutoff)
                .where(~active_claim)
                .order_by(interactive_search_sessions.c.expires_at)
                .limit(limit)
            ).scalars()
        )
        if not session_ids:
            return {"sessions": 0, "candidates": 0}
        candidates = conn.execute(
            delete(interactive_search_candidates).where(interactive_search_candidates.c.session_id.in_(session_ids))
        ).rowcount
        sessions = conn.execute(
            delete(interactive_search_sessions).where(interactive_search_sessions.c.session_id.in_(session_ids))
        ).rowcount
    return {"sessions": sessions or 0, "candidates": candidates or 0}


def run():
    """APScheduler entry point for the bounded daily expiry sweep."""

    try:
        summary = purge_expired_sessions(get_engine())
    except Exception as e:
        logger.error("[INTERACTIVE-SEARCH-RETENTION] Purge failed: %s" % e)
        raise
    logger.fdebug(
        "[INTERACTIVE-SEARCH-RETENTION] Deleted %s sessions and %s candidates"
        % (summary["sessions"], summary["candidates"])
    )
    return summary
