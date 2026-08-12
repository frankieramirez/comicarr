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

from sqlalchemy import delete, insert, select, update

from comicarr import logger
from comicarr.app.common.redaction import redact_sensitive_text
from comicarr.db import get_engine
from comicarr.tables import interactive_search_candidates, interactive_search_sessions

SESSION_TTL_SECONDS = 10 * 60
MAX_CANDIDATES = 200
MAX_SESSION_BYTES = 512 * 1024
MAX_RECORD_BYTES = 64 * 1024
CLEANUP_BATCH_SIZE = 500
JOB_ID = "interactive_search_retention"
JOB_NAME = "Interactive Search Retention"

_ENTITY_TYPES = frozenset({"issue", "annual", "story_arc_issue"})
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
    raw_identity = None
    if isinstance(legacy, dict):
        raw_identity = legacy.get("nzbid")
    if raw_identity in (None, ""):
        raw_identity = _entry_value(entry, "id")
    if raw_identity in (None, "") and isinstance(legacy, dict):
        raw_identity = legacy.get("link")
    if raw_identity in (None, ""):
        raw_identity = hint.get("provider_item_id")

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
    # The digest is useful when an unsafe identity must be re-found under the
    # current provider config; it is not reversible and grants no access.
    return reconstruction


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
    session_values = {
        "session_id": opaque_id,
        "slot_digest": slot,
        "actor_digest": _digest(actor),
        "browser_digest": _digest(browser_session),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "series_id": str(series_id)[:255] if series_id not in (None, "") else None,
        "state": "ready",
        "candidate_count": len(records),
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
    return {
        "session_id": row["session_id"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "series_id": row["series_id"],
        "state": row["state"],
        "candidate_count": row["candidate_count"],
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


def purge_expired_sessions(engine, *, now=None, batch_size=CLEANUP_BATCH_SIZE):
    """Delete at most one bounded batch of expired sessions and candidates."""

    limit = max(1, min(int(batch_size), CLEANUP_BATCH_SIZE))
    cutoff = _now(now).isoformat()
    with engine.begin() as conn:
        session_ids = list(
            conn.execute(
                select(interactive_search_sessions.c.session_id)
                .where(interactive_search_sessions.c.expires_at <= cutoff)
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
