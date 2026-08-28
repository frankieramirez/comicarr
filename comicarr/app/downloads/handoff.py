#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Durable reservation and route-acceptance boundary for external handoffs."""

from dataclasses import dataclass

from comicarr import logger
from comicarr.app.attention import Failure, ManualReview, record


class HandoffError(RuntimeError):
    pass


class HandoffReservationError(HandoffError):
    pass


class HandoffAcceptanceError(HandoffError):
    pass


@dataclass(frozen=True)
class RouteAcceptance:
    route: str
    correlation_id: str | None
    restart_safe: bool
    manual_review: bool


_ROUTE_ALIASES = {
    "sab": "sabnzbd",
    "sabnzbd": "sabnzbd",
    "nzbget": "nzbget",
    "ddl": "ddl",
    "rtorrent": "rtorrent",
    "deluge": "deluge",
    "qbittorrent": "qbittorrent",
    "transmission": "transmission",
    "utorrent": "utorrent",
    "watchdir": "watchdir",
    "blackhole": "blackhole",
}
_RESTART_SAFE_ROUTES = frozenset(
    {"sabnzbd", "nzbget", "ddl", "rtorrent", "deluge", "qbittorrent", "transmission", "utorrent"}
)


def _record_route_health(route, success, error=None):
    family = (
        "nzb"
        if route in {"sabnzbd", "nzbget"}
        else (
            "torrent"
            if route in {"rtorrent", "deluge", "qbittorrent", "transmission", "utorrent", "watchdir"}
            else route
        )
    )
    if family not in {"nzb", "torrent", "ddl"}:
        return
    try:
        from comicarr.app.search.health import record_route_outcome

        record_route_outcome(family, success=success, error=error)
    except Exception as e:
        logger.fdebug("[HANDOFF] route health outcome could not be recorded: %s" % type(e).__name__)


def normalize_route(route):
    normalized = str(route or "").strip().lower()
    return _ROUTE_ALIASES.get(normalized, normalized or "unknown")


def is_restart_safe_route(route):
    """Return whether this route has a durable identity safe for restart replay."""

    return normalize_route(route) in _RESTART_SAFE_ROUTES


def reserve(release_key, route, payload=None, **fields):
    """Persist a new attempt before any externally visible side effect."""
    from comicarr.app.downloads import journal

    normalized = normalize_route(route)
    reservation = dict(payload or {})
    reservation["route"] = normalized
    won = journal.record_transition(
        release_key,
        journal.RESERVED,
        payload=reservation,
        downloader_type=normalized,
        **fields,
    )
    if not won:
        raise HandoffReservationError(_reservation_refusal(release_key))
    return normalized


def _reservation_refusal(release_key):
    """Explain a lost reservation using the row that blocked it.

    A refused reservation used to surface only as a bare
    HandoffReservationError, so the most common cause — an unresolved
    manual_review row holding the release_key terminal — read in the log as an
    unexplained handoff failure repeating every search cycle (#562). The row is
    the explanation, so read it once, here, where it is cheap.
    """
    from comicarr.app.downloads import journal

    default = "durable handoff reservation was not acquired"
    try:
        current = journal.read_one(release_key) or {}
    except Exception:
        return default
    stage = current.get("stage")
    if stage != journal.MANUAL_REVIEW:
        return default
    detail = "%s awaiting operator review (%s)" % (release_key, current.get("fail_reason") or "no reason recorded")
    logger.warn(
        "[HANDOFF] reservation refused: %s. This release stays blocked for this "
        "provider until the needs-attention band entry is resolved." % detail
    )
    return "handoff blocked: %s" % detail


def _acceptance_identity(route, response):
    response = response if isinstance(response, dict) else {}
    if route == "sabnzbd":
        return "nzo_id", response.get("nzo_id")
    if route == "nzbget":
        return "NZBID", response.get("NZBID")
    if route == "ddl":
        return "ddl_id", response.get("ddl_id") or response.get("id")
    if route in {"rtorrent", "deluge", "qbittorrent", "transmission", "utorrent", "watchdir"}:
        return "hash", response.get("hash")
    return None, None


def _attention_identity(fields, *, downloader_type):
    """Translate legacy handoff field names into Attention's typed entry."""

    return {
        "issue_id": fields.get("issueid"),
        "provider": fields.get("provider"),
        "downloader_type": downloader_type,
        "nzb_name": fields.get("nzbname"),
        "release_id": fields.get("release_id"),
        "download_hash": fields.get("hash"),
        "comic_id": fields.get("comicid"),
        "comic_name": fields.get("comicname"),
        "issue_number": fields.get("issue_number") or fields.get("issuenumber"),
    }


def record_acceptance(release_key, route, response, payload=None, **fields):
    """Persist the actual top-level sender identity before monitor handoff."""
    from comicarr.app.downloads import journal

    normalized = normalize_route(route)
    explicit_rejection = response is False or response == "fail"
    response = response if isinstance(response, dict) else {}
    if explicit_rejection or response.get("status") is False:
        record(
            Failure(
                release_key=release_key,
                reason="submission_rejected",
                payload={"route": normalized},
                **_attention_identity(fields, downloader_type=normalized),
            )
        )
        _record_route_health(normalized, False, "submission_rejected")
        return RouteAcceptance(normalized, None, False, False)

    identity_key, identity = _acceptance_identity(normalized, response)
    accepted_payload = dict(payload or {})
    accepted_payload["route"] = normalized
    accepted_payload["client"] = normalized
    if identity_key and identity not in (None, ""):
        accepted_payload[identity_key] = str(identity)
    acceptance_fields = dict(fields)
    if identity_key == "hash" and identity not in (None, ""):
        acceptance_fields.setdefault("hash", str(identity))

    restart_safe = normalized in _RESTART_SAFE_ROUTES and bool(identity)
    if not restart_safe:
        reason = (
            "route_not_restart_safe:%s" % normalized
            if normalized not in _RESTART_SAFE_ROUTES
            else "route_acceptance_missing_identity:%s" % normalized
        )
        record(
            ManualReview(
                release_key=release_key,
                reason=reason,
                payload=accepted_payload,
                **_attention_identity(acceptance_fields, downloader_type=normalized),
            )
        )
        _record_route_health(normalized, bool(identity), reason)
        return RouteAcceptance(normalized, str(identity) if identity else None, False, True)

    try:
        won = journal.record_transition(
            release_key,
            journal.SNATCHED,
            payload=accepted_payload,
            downloader_type=normalized,
            **acceptance_fields,
        )
    except Exception as e:
        logger.error("[HANDOFF] acceptance persistence failed for %s: %s" % (release_key, type(e).__name__))
        _record_route_health(normalized, False, "acceptance_persistence_failed")
        raise HandoffAcceptanceError("external acceptance could not be persisted") from e
    if not won:
        current = journal.read_one(release_key)
        if not current or current.get("stage") != journal.SNATCHED:
            raise HandoffAcceptanceError("external acceptance did not advance the reserved obligation")
    _record_route_health(normalized, True)
    return RouteAcceptance(normalized, str(identity), True, False)


def perform_handoff(
    release_key,
    route,
    sender,
    payload=None,
    owner="acquisition-handoff",
    finalizer=None,
    resume_accepted=False,
    **fields,
):
    """Hold a maintenance lease across reservation, send and acceptance."""
    from comicarr.app.acquisition.maintenance import MaintenanceController
    from comicarr.app.downloads import journal

    normalized = normalize_route(route)
    controller = MaintenanceController()
    with controller.handoff_lease(owner, release_key, normalized) as lease:
        outcome = "failed_before_submission"
        try:
            controller.assert_lease_current(lease)
            if resume_accepted:
                current = journal.read_one(release_key)
                if not current or current.get("stage") != journal.SNATCHED:
                    raise HandoffReservationError("accepted handoff cannot be resumed from its current stage")
            else:
                reserve(release_key, normalized, payload=payload, **fields)
            controller.assert_lease_current(lease)
            try:
                response = sender()
            except Exception as e:
                outcome = "submission_outcome_unknown"
                _record_route_health(normalized, False, "submission_outcome_unknown")
                try:
                    record(
                        ManualReview(
                            release_key=release_key,
                            reason="submission_outcome_unknown:%s" % type(e).__name__,
                            payload={"route": normalized},
                            **_attention_identity(fields, downloader_type=normalized),
                        )
                    )
                except Exception as record_error:
                    logger.error(
                        "[HANDOFF] ambiguous submission for %s could not be recorded for manual review: %s"
                        % (release_key, type(record_error).__name__)
                    )
                raise
            acceptance = record_acceptance(
                release_key,
                normalized,
                response,
                payload=payload,
                **fields,
            )
            if finalizer is not None:
                finalizer(response, acceptance)
            outcome = "accepted" if acceptance.restart_safe else "manual_review"
            return response, acceptance
        except Exception:
            if outcome == "failed_before_submission":
                outcome = "handoff_failed"
            raise
        finally:
            controller.complete_canary_handoff(lease, outcome)
