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
# Routes whose acceptance yields an identity the monitor can poll after a
# restart. Every torrent client with a probe belongs here; watchdir and
# blackhole produce no client-side identity and so stay out.
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
        raise HandoffReservationError("durable handoff reservation was not acquired")
    return normalized


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


def record_acceptance(release_key, route, response, payload=None, **fields):
    """Persist the actual top-level sender identity before monitor handoff."""
    from comicarr.app.downloads import journal

    normalized = normalize_route(route)
    explicit_rejection = response is False or response == "fail"
    response = response if isinstance(response, dict) else {}
    if explicit_rejection or response.get("status") is False:
        journal.mark_failed(
            release_key,
            "submission_rejected",
            payload={"route": normalized},
            downloader_type=normalized,
            **fields,
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
        journal.mark_manual_review(
            release_key,
            reason,
            payload=accepted_payload,
            downloader_type=normalized,
            **acceptance_fields,
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
        # The sender already accepted. Never call it again here; the durable
        # reservation makes startup classify this as manual review.
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
                journal.mark_manual_review(
                    release_key,
                    "submission_outcome_unknown:%s" % type(e).__name__,
                    payload={"route": normalized},
                    downloader_type=normalized,
                    **fields,
                )
                _record_route_health(normalized, False, "submission_outcome_unknown")
                outcome = "submission_outcome_unknown"
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
            # A claimed canary is terminal regardless of the result. Never
            # re-open it for an automatic retry after an ambiguous side effect.
            controller.complete_canary_handoff(lease, outcome)
