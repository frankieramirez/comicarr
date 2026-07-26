#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Sanitized, restart-durable acquisition health projections."""

import datetime
import math
import os
import re
import time

import comicarr
from comicarr import db
from comicarr.app.search import queries
from comicarr.app.search.providers import effective_provider_plan, enabled_provider_entries, ordered_provider_names
from comicarr.db import get_engine

WORKER_PREFIX = "Worker: "
ROUTE_PREFIX = "Acquisition Route: "
_ROUTES = ("ddl", "nzb", "torrent")


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "running"}


def _timestamp(value):
    """Return a finite timestamp or ``None`` for legacy/malformed values."""
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return timestamp if math.isfinite(timestamp) and timestamp > 0 else None


def _sanitize(value, fallback=None):
    message = re.sub(r"\s+", " ", str(value or "")).strip()
    message = re.sub(
        r"(?i)(api[ _-]?key|authorization|password|token|passkey)\s*[=:]\s*[^\s,;]+",
        r"\1=[redacted]",
        message,
    )
    message = re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1[redacted]@", message)
    message = re.sub(r"(?i)([?&](?:apikey|api_key|token|password|passkey)=)[^&\s]+", r"\1[redacted]", message)
    return (message[:500] or fallback) if message or fallback else None


def _provider_names(config):
    return ordered_provider_names(config)


def _enabled_extra(entries):
    return any(enabled_provider_entries(entries))


def _route_for_provider(row):
    provider_type = str(row.get("type") or "").strip().lower()
    if provider_type.startswith("ddl"):
        return "ddl"
    if provider_type in {"torrent", "torznab"}:
        return "torrent"
    if provider_type in {"nzb", "newznab", "experimental"}:
        return "nzb"
    name = str(row.get("provider") or "").strip().lower()
    if name.startswith("ddl(") or "getcomics" in name:
        return "ddl"
    if "torznab" in name or name in {"32p", "public torrents", "torrent"}:
        return "torrent"
    return "nzb"


def route_for_site(site, config=None):
    """Classify a configured provider name without persisting its URL or credentials."""
    config = config or getattr(comicarr, "CONFIG", None)
    name = str(site or "").strip().lower()
    if name.startswith("ddl(") or "getcomics" in name or name == "external":
        return "ddl"
    if name in {"32p", "public torrents", "torrent"}:
        return "torrent"
    if config is not None:
        for entry in getattr(config, "EXTRA_TORZNABS", None) or []:
            candidates = [str(value or "").strip().lower() for value in entry[:2]]
            if name in candidates:
                return "torrent"
    return "nzb"


def _route_provider_names(config, provider_stats):
    names = {route: [] for route in _ROUTES}
    for row in provider_stats:
        name = str(row.get("provider") or "").strip()
        if name:
            names[_route_for_provider(row)].append(name)

    ordered = _provider_names(config)
    if not names["ddl"]:
        names["ddl"] = [name for name in ordered if name.lower().startswith("ddl(")]
    if not names["torrent"]:
        torznab_names = {
            str(entry[0] or entry[1]).lower()
            for entry in (getattr(config, "EXTRA_TORZNABS", None) or [])
            if len(entry) > 1
        }
        names["torrent"] = [
            name
            for name in ordered
            if name.lower() in torznab_names or name.lower() in {"32p", "public torrents", "torrent"}
        ]
    if not names["nzb"]:
        used = set(names["ddl"] + names["torrent"])
        names["nzb"] = [name for name in ordered if name not in used]
    return names


def _path_ready(path):
    return bool(path and os.path.isdir(os.path.realpath(os.path.expanduser(str(path)))))


def _downstream_readiness(config, route):
    if route == "ddl":
        return "local", True, _path_ready(getattr(config, "DDL_LOCATION", None)), True
    post_processing = bool(getattr(config, "POST_PROCESSING", False))
    if route == "nzb":
        downloader = int(getattr(config, "NZB_DOWNLOADER", 3) or 0)
        if downloader == 0:
            return (
                "sabnzbd",
                bool(getattr(config, "SAB_HOST", None) and getattr(config, "SAB_APIKEY", None)),
                not post_processing or _path_ready(getattr(config, "SAB_DIRECTORY", None)),
                True,
            )
        if downloader == 1:
            return (
                "nzbget",
                bool(getattr(config, "NZBGET_HOST", None)),
                not post_processing or _path_ready(getattr(config, "NZBGET_DIRECTORY", None)),
                True,
            )
        if downloader == 2:
            return "blackhole", True, _path_ready(getattr(config, "BLACKHOLE_DIR", None)), False
        return "disabled", False, False, False

    downloader = int(getattr(config, "TORRENT_DOWNLOADER", 0) or 0)
    clients = {
        0: ("watchfolder", "LOCAL_WATCHDIR", True),
        1: ("utorrent", "UTORRENT_HOST", False),
        2: ("rtorrent", "RTORRENT_HOST", False),
        3: ("transmission", "TRANSMISSION_HOST", False),
        4: ("deluge", "DELUGE_HOST", False),
        5: ("qbittorrent", "QBITTORRENT_HOST", False),
    }
    client, key, needs_path = clients.get(downloader, ("disabled", None, False))
    configured = getattr(config, key, None) if key else None
    # Every client with a monitor probe: uTorrent, rTorrent, Transmission,
    # Deluge, qBittorrent. Watchfolder (0) has no identity to poll.
    restart_safe = downloader in {1, 2, 3, 4, 5}
    client_ready = True if needs_path else bool(configured)
    path_keys = {
        2: "RTORRENT_DIRECTORY",
        3: "TRANSMISSION_DIRECTORY",
        4: "DELUGE_DOWNLOAD_DIRECTORY",
        5: "QBITTORRENT_FOLDER",
    }
    if needs_path:
        path_ready = _path_ready(configured)
    elif post_processing and downloader in path_keys:
        path_ready = _path_ready(getattr(config, path_keys[downloader], None))
    else:
        path_ready = True
    return client, client_ready, path_ready, restart_safe


def _route_enabled(config, route):
    if route == "ddl":
        return bool(
            getattr(config, "ENABLE_DDL", False)
            and (getattr(config, "ENABLE_GETCOMICS", False) or getattr(config, "ENABLE_EXTERNAL_SERVER", False))
        )
    if route == "nzb":
        providers = bool(
            getattr(config, "EXPERIMENTAL", False)
            or (getattr(config, "NEWZNAB", False) and _enabled_extra(getattr(config, "EXTRA_NEWZNABS", None)))
        )
        return providers and int(getattr(config, "NZB_DOWNLOADER", 3) or 0) != 3
    providers = bool(
        getattr(config, "ENABLE_PUBLIC", False)
        or getattr(config, "ENABLE_32P", False)
        or (getattr(config, "ENABLE_TORZNAB", False) and _enabled_extra(getattr(config, "EXTRA_TORZNABS", None)))
    )
    return bool(
        getattr(config, "ENABLE_TORRENT_SEARCH", False) and getattr(config, "ENABLE_TORRENTS", False) and providers
    )


def build_route_readiness(
    config,
    *,
    provider_stats=None,
    provider_blocklist=None,
    maintenance=None,
    route_history=None,
    now=None,
):
    """Build independent DDL/NZB/torrent readiness without exposing config values."""
    provider_stats = [dict(row) for row in (provider_stats or [])]
    provider_blocklist = list(provider_blocklist or [])
    route_history = route_history or {}
    maintenance = maintenance or {}
    now = float(now if now is not None else time.time())
    names = _route_provider_names(config, provider_stats)
    active_blocks = {}
    for entry in provider_blocklist:
        try:
            active = float(entry.get("resume") or 0) > now
        except (TypeError, ValueError):
            active = False
        site = str(entry.get("site") or "").strip()
        if active and site:
            active_blocks[site.casefold()] = site

    def is_active_blocked(name):
        return str(name).casefold() in active_blocks

    provider_plan = effective_provider_plan(
        config,
        is_blocked=is_active_blocked,
    )
    planned_by_route = {
        route: [candidate for candidate in provider_plan if candidate.route == route] for route in _ROUTES
    }
    stats_by_route = {route: [row for row in provider_stats if _route_for_provider(row) == route] for route in _ROUTES}
    routes = {}

    for route in _ROUTES:
        route_stats = stats_by_route[route]
        stats_by_name = {str(row.get("provider") or "").casefold(): row for row in route_stats}
        diagnostics = []
        for candidate in planned_by_route[route]:
            stat = stats_by_name.get(candidate.name.casefold()) or {}
            last_attempt = _timestamp(stat.get("lastrun"))
            diagnostics.append(
                {
                    "name": candidate.name,
                    "kind": candidate.kind,
                    "blocked": candidate.blocked,
                    "attempted": last_attempt is not None,
                    "last_attempt": last_attempt,
                }
            )
        if diagnostics:
            names[route] = list(dict.fromkeys(names[route] + [item["name"] for item in diagnostics]))
        enabled = _route_enabled(config, route)
        client, client_ready, path_ready, restart_safe = _downstream_readiness(config, route)
        downstream_ready = client_ready and path_ready
        route_blocks = []
        route_names = {name.lower() for name in names[route]}
        for site_key, site in active_blocks.items():
            if site_key in route_names:
                route_blocks.append(site)
        all_blocked = bool(route_names) and len({name.lower() for name in route_blocks}) >= len(route_names)
        maintenance_reason = maintenance.get("reason") if maintenance.get("blocked") else None
        history = route_history.get(route, {})
        blocked_until = _timestamp(history.get("next_run_timestamp"))
        history_blocked = bool(blocked_until and blocked_until > now and not route_blocks)
        all_blocked = all_blocked or history_blocked
        ready = bool(enabled and downstream_ready and restart_safe and not all_blocked and not maintenance_reason)
        if not enabled:
            reason = "disabled"
        elif maintenance_reason:
            reason = str(maintenance_reason)
        elif not restart_safe:
            reason = "unsupported_restart_correlation"
        elif not client_ready:
            reason = "client_not_ready"
        elif not path_ready:
            reason = "path_not_ready"
        elif all_blocked:
            reason = "providers_temporarily_blocked"
        else:
            reason = "ready"
        attempts = [timestamp for row in route_stats if (timestamp := _timestamp(row.get("lastrun"))) is not None]
        # A completed provider attempt is an operational route success even
        # when it returns zero matches. Acquisition matching is reported
        # separately by the run ledger's no_match/succeeded counters.
        latest_attempt = max(attempts) if attempts else None
        last_failure = _timestamp(history.get("last_failure_timestamp"))
        last_success = _timestamp(history.get("last_success_timestamp"))
        if latest_attempt is not None and (last_failure is None or latest_attempt >= last_failure):
            last_success = latest_attempt
        running = any(_truthy(row.get("active")) for row in route_stats)
        routes[route] = {
            "configured": bool(names[route]) or enabled,
            "enabled": enabled,
            "active": running,
            "running": running,
            "blocked": bool(route_blocks) or history_blocked or bool(maintenance_reason),
            "blocked_until": blocked_until,
            "blocked_provider_count": len(route_blocks),
            "downstream": client,
            "client_ready": client_ready,
            "path_ready": path_ready,
            "downstream_ready": downstream_ready,
            "restart_safe": restart_safe,
            "ready": ready,
            "reason": _sanitize(reason),
            "last_attempt": latest_attempt
            if latest_attempt is not None
            else _timestamp(history.get("prev_run_timestamp")),
            "last_success": last_success,
            "last_failure": last_failure,
            "last_error": _sanitize(history.get("last_error")),
            "configured_provider_count": len(diagnostics),
            "executable_provider_count": sum(1 for item in diagnostics if enabled and not item["blocked"]),
            "attempted_provider_count": sum(1 for item in diagnostics if item["attempted"]),
            "providers": diagnostics,
        }
    return routes


def has_viable_route(routes):
    """Return whether at least one centralized route is currently handoff-ready."""
    return any(bool(route.get("ready")) for route in routes.values())


def get_acquisition_health(engine=None):
    """Project dispatch and item completion independently for each command kind."""
    engine = engine or get_engine()
    rows = queries.get_acquisition_run_rows(engine)
    oldest = queries.get_oldest_acquisition_backlogs(engine)
    latest = {}
    for row in rows:
        latest.setdefault(row["command_kind"], row)

    result = {}
    for kind, row in latest.items():
        result[kind] = {
            "run_id": row["run_id"],
            "trigger": row["trigger"],
            "dispatch": {"state": row["dispatch_state"]},
            "completion": {"state": row["completion_state"], "completed_at": row["completed_at"]},
            "accepted": int(row["accepted_count"] or 0),
            "processed": int(row["terminal_count"] or 0),
            "matched": int(row["succeeded_count"] or 0),
            "no_match": int(row["no_match_count"] or 0),
            "deferred": int(row["blocked_count"] or 0),
            "failed": int(row["failed_count"] or 0),
            "oldest_backlog": oldest.get(kind),
            "updated_at": row["updated_at"],
        }
    return result


def _upsert_history(engine, job_name, values):
    with engine.begin() as conn:
        db.upsert_conn(conn, "jobhistory", values, {"JobName": job_name})


def record_route_outcome(route, *, success, error=None, timestamp=None, blocked_until=None, engine=None):
    """Persist sanitized route attempt/success/failure state for restart diagnostics."""
    route = str(route).strip().lower()
    if route not in _ROUTES:
        raise ValueError("unknown acquisition route")
    engine = engine or get_engine()
    timestamp = float(timestamp if timestamp is not None else time.time())
    values = {
        "status": "Ready" if success else "Error",
        "prev_run_timestamp": timestamp,
        "prev_run_datetime": datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc).isoformat(),
        "next_run_timestamp": float(blocked_until) if blocked_until is not None else None,
        "last_error": None if success else _sanitize(error, "Route attempt failed."),
    }
    if success:
        values["last_success_timestamp"] = timestamp
    else:
        values["last_failure_timestamp"] = timestamp
    _upsert_history(engine, ROUTE_PREFIX + route, values)


def clear_route_block(route, *, engine=None):
    """Clear only a temporary route block without fabricating a successful attempt."""
    route = str(route).strip().lower()
    if route not in _ROUTES:
        raise ValueError("unknown acquisition route")
    _upsert_history(
        engine or get_engine(),
        ROUTE_PREFIX + route,
        {"status": "Waiting", "next_run_timestamp": None, "last_error": None},
    )


def record_worker_heartbeat(worker, *, state, error=None, timestamp=None, engine=None):
    """Persist a bounded worker heartbeat so restarts do not erase the last outcome."""
    engine = engine or get_engine()
    timestamp = float(timestamp if timestamp is not None else time.time())
    when = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc).isoformat()
    values = {
        "status": str(state).strip().lower(),
        "prev_run_timestamp": timestamp,
        "prev_run_datetime": when,
        "last_error": _sanitize(error),
    }
    if error:
        values["last_failure_timestamp"] = timestamp
    elif str(state).strip().lower() in {"idle", "waiting", "succeeded"}:
        values["last_success_timestamp"] = timestamp
    _upsert_history(engine, WORKER_PREFIX + str(worker).strip().lower(), values)


def get_worker_health(engine=None, *, now=None, stale_after=120):
    """Return durable heartbeat state with an explicit current liveness projection."""
    now = float(now if now is not None else time.time())
    rows = queries.get_health_history_rows(engine, WORKER_PREFIX)
    result = {}
    for row in rows:
        worker = row["JobName"][len(WORKER_PREFIX) :]
        last = row.get("prev_run_timestamp")
        state = str(row.get("status") or "unknown").lower()
        fresh = last is not None and now - float(last) <= float(stale_after)
        alive = bool(fresh and state != "stopped")
        result[worker] = {
            "state": state,
            "alive": alive,
            "live": alive,
            "healthy": bool(alive and state != "failed"),
            "last_heartbeat": last,
            "last_success": row.get("last_success_timestamp"),
            "last_failure": row.get("last_failure_timestamp"),
            "last_error": _sanitize(row.get("last_error")),
        }
    return result


def get_maintenance_health(engine=None):
    """Return the persistent fence/drain state while remaining fail-closed."""
    try:
        from comicarr.app.acquisition.maintenance import MaintenanceController

        status = MaintenanceController(engine).status()
        return {
            "blocked": bool(status.active or getattr(comicarr, "ACQUISITION_WORKERS_BLOCKED", False)),
            "reason": status.reason or getattr(comicarr, "ACQUISITION_BLOCK_REASON", None),
            "owner": status.owner,
            "run_id": status.run_id,
            "epoch": status.epoch,
            "heartbeat_at": status.heartbeat_at,
            "active_leases": status.active_leases,
            "drained": status.drained,
        }
    except Exception as e:
        return {
            "blocked": True,
            "reason": "maintenance_health_unavailable",
            "owner": None,
            "run_id": None,
            "epoch": None,
            "heartbeat_at": None,
            "active_leases": None,
            "drained": False,
            "error": _sanitize(e),
        }


def get_search_health(config, *, engine=None, provider_blocklist=None):
    """Return the stable provider, route, run, worker, and maintenance contract."""
    engine = engine or get_engine()
    try:
        raw_provider_stats = queries.get_provider_stats(engine)
    except Exception:
        raw_provider_stats = []
    provider_stats = [
        {
            "id": row.get("id"),
            "provider": _sanitize(row.get("provider")),
            "type": _sanitize(row.get("type")),
            "lastrun": row.get("lastrun"),
            "active": row.get("active"),
            "hits": row.get("hits"),
        }
        for row in raw_provider_stats
    ]
    maintenance = get_maintenance_health(engine)
    try:
        route_rows = queries.get_health_history_rows(engine, ROUTE_PREFIX)
    except Exception:
        route_rows = []
    route_history = {row["JobName"][len(ROUTE_PREFIX) :].lower(): row for row in route_rows}
    routes = build_route_readiness(
        config,
        provider_stats=raw_provider_stats,
        provider_blocklist=provider_blocklist,
        maintenance=maintenance,
        route_history=route_history,
    )
    try:
        acquisition = get_acquisition_health(engine)
    except Exception as e:
        acquisition = {"unavailable": {"reason": "schema_unavailable", "error": _sanitize(e)}}
    try:
        workers = get_worker_health(engine)
    except Exception as e:
        workers = {
            "unavailable": {
                "state": "unavailable",
                "alive": False,
                "live": False,
                "healthy": False,
                "last_error": _sanitize(e),
            }
        }
    return {
        "providers": provider_stats,
        "routes": routes,
        "viable_route": has_viable_route(routes),
        "acquisition": acquisition,
        "workers": workers,
        "maintenance": maintenance,
        "blocked_producer_count": sum(
            item.get("deferred", 0) for item in acquisition.values() if isinstance(item, dict)
        ),
    }
