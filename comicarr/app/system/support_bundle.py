#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Deep Support bundle generator.

Public seam: ``generate_support_bundle(ctx) -> SupportBundleArtifact``.

The modern path never imports or instantiates the legacy collector.
All emitted values are allowlisted constants, closed enums, normalized
versions, one UTC timestamp, or SHA-256 digests.
"""

from __future__ import annotations

import hashlib
import io
import json
import platform
import re
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from typing import Any, Callable, Mapping, Optional

from jsonschema import Draft202012Validator
from sqlalchemy import func, select, text

from comicarr import logger
from comicarr.app.system.support_bundle_contract import read_contract_bytes

CONTRACT_VERSION = 1
FILENAME = "comicarr-support-bundle-v1.zip"
MEMBER_ORDER = ("README.txt", "manifest.json", "diagnostics.json")

README_MAX_BYTES = 16 * 1024
JSON_MEMBER_MAX_BYTES = 256 * 1024
TOTAL_UNCOMPRESSED_MAX_BYTES = 512 * 1024
ZIP_MAX_BYTES = 512 * 1024

_ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)
_ZIP_EXTERNAL_ATTR = 0o644 << 16
_ZIP_CREATE_SYSTEM = 3

_DEPENDENCY_NAMES = (
    "apscheduler",
    "fastapi",
    "sqlalchemy",
    "starlette",
    "urllib3",
    "uvicorn",
)

_COUNT_BUCKETS = (
    (0, "zero"),
    (1, "one"),
    (9, "2_9"),
    (99, "10_99"),
    (999, "100_999"),
    (9_999, "1k_9k"),
    (99_999, "10k_99k"),
)

_RECENCY_BOUNDS = (
    (300, "lt_5m"),
    (1_800, "5m_30m"),
    (7_200, "30m_2h"),
    (86_400, "2h_24h"),
    (604_800, "1d_7d"),
)

_NZB_CLIENTS = {0: "sabnzbd", 1: "nzbget", 2: "blackhole", 3: "disabled"}
_TORRENT_CLIENTS = {
    0: "watchfolder",
    1: "utorrent",
    2: "rtorrent",
    3: "transmission",
    4: "deluge",
    5: "qbittorrent",
}

_ROUTE_STATE_MAP = {
    "ready": "ready",
    "disabled": "disabled",
    "downloader_disabled": "disabled",
    "provider_disabled": "disabled",
    "provider_not_configured": "disabled",
    "client_not_ready": "client_not_ready",
    "path_not_ready": "path_not_ready",
    "providers_temporarily_blocked": "providers_blocked",
    "unsupported_restart_correlation": "restart_unsafe",
}

_SCHEDULER_STATE_MAP = {
    "running": "running",
    "waiting": "waiting",
    "queued": "waiting",
    "paused": "paused",
    "error": "failed",
    "failed": "failed",
    "missed": "failed",
    "max instances": "failed",
    "stopped": "stopped",
    "shutdown": "stopped",
}

_VERSION_RE = re.compile(r"^(?:0|[1-9][0-9]{0,4})\.(?:0|[1-9][0-9]{0,4})\.(?:0|[1-9][0-9]{0,4})$")

_GENERATION_LOCK = threading.Lock()

_ERROR_DETAILS = {
    "support_bundle_in_progress": ("Another support bundle is already being created. Try again in a moment."),
    "support_bundle_unavailable": ("Support bundle generation is temporarily unavailable. Try again later."),
    "support_bundle_validation_failed": (
        "Comicarr stopped the download because the bundle did not pass its safety checks. No file was downloaded."
    ),
    "support_bundle_generation_failed": ("Comicarr could not create the support bundle. Try again."),
}


class SupportBundleError(Exception):
    """Typed Support bundle failure with a fixed public code."""

    def __init__(self, code: str):
        if code not in _ERROR_DETAILS:
            code = "support_bundle_generation_failed"
        self.code = code
        self.detail = _ERROR_DETAILS[code]
        self.retryable = code != "support_bundle_validation_failed"
        super().__init__(self.code)


class SupportBundleInProgress(SupportBundleError):
    def __init__(self):
        super().__init__("support_bundle_in_progress")


class SupportBundleUnavailable(SupportBundleError):
    def __init__(self):
        super().__init__("support_bundle_unavailable")


class SupportBundleValidationFailed(SupportBundleError):
    def __init__(self):
        super().__init__("support_bundle_validation_failed")


class SupportBundleGenerationFailed(SupportBundleError):
    def __init__(self):
        super().__init__("support_bundle_generation_failed")


@dataclass(frozen=True)
class SupportBundleArtifact:
    content: bytes
    contract_version: int
    filename: str
    status: str


def error_body(code: str) -> dict[str, Any]:
    """Return the fixed JSON error body for a Support bundle code."""
    if code not in _ERROR_DETAILS:
        code = "support_bundle_generation_failed"
    return {
        "detail": _ERROR_DETAILS[code],
        "code": code,
        "retryable": code != "support_bundle_validation_failed",
    }


def generate_support_bundle(
    ctx,
    *,
    clock: Optional[Callable[[], datetime]] = None,
) -> SupportBundleArtifact:
    """Generate a validated in-memory Support bundle for the active runtime."""
    started = time.monotonic()
    if not _GENERATION_LOCK.acquire(blocking=False):
        raise SupportBundleInProgress()
    status = "unknown"
    size_bucket = "zero"
    try:
        if getattr(ctx, "disposed", False):
            raise SupportBundleUnavailable()
        generated_at = _capture_generated_at(clock)
        snapshot = _capture_runtime_snapshot(ctx)
        diagnostics, sources = _collect_diagnostics(ctx, snapshot, generated_at)
        status = (
            "complete"
            if sources["database"]["status"] == "available" and sources["health"]["status"] == "available"
            else "partial"
        )
        artifact = _build_and_validate_archive(
            diagnostics=diagnostics,
            sources=sources,
            bundle_status=status,
            generated_at=generated_at,
            product_version=diagnostics["build"]["release_version"],
        )
        size_bucket = _size_bucket(len(artifact.content))
        _log_outcome(
            code="success",
            status=artifact.status,
            duration_s=time.monotonic() - started,
            size_bucket=size_bucket,
        )
        return artifact
    except SupportBundleError as exc:
        _log_outcome(
            code=exc.code,
            status=status,
            duration_s=time.monotonic() - started,
            size_bucket=size_bucket,
            exception_class=type(exc).__name__,
        )
        raise
    except Exception as e:
        _log_outcome(
            code="support_bundle_generation_failed",
            status=status,
            duration_s=time.monotonic() - started,
            size_bucket=size_bucket,
            exception_class=type(e).__name__,
        )
        raise SupportBundleGenerationFailed() from e
    finally:
        _GENERATION_LOCK.release()


def _capture_generated_at(clock: Optional[Callable[[], datetime]]) -> datetime:
    if clock is not None:
        value = clock()
    else:
        value = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.replace(microsecond=0)


def _capture_runtime_snapshot(ctx) -> dict[str, Any]:
    """Copy only allowlisted config primitives while holding the runtime lock."""
    lock = getattr(ctx, "runtime_lock", None)
    if lock is None:
        return _snapshot_from_config(getattr(ctx, "config", None), ctx)
    with lock:
        return _snapshot_from_config(getattr(ctx, "config", None), ctx)


def _snapshot_from_config(config, ctx) -> dict[str, Any]:
    def flag(name: str) -> Any:
        if config is None:
            return None
        return getattr(config, name, None)

    return {
        "release_version": (getattr(ctx, "current_version_name", None) or getattr(ctx, "current_release_name", None)),
        "install_type": getattr(ctx, "install_type", None),
        "build_id": None,
        "build_verified": False,
        "build_declared_id": None,
        "POST_PROCESSING": flag("POST_PROCESSING"),
        "ENABLE_RSS": flag("ENABLE_RSS"),
        "CHECK_GITHUB": flag("CHECK_GITHUB"),
        "COMICVINE_ENABLED": flag("COMICVINE_ENABLED"),
        "COMICVINE_API": bool(flag("COMICVINE_API")),
        "USE_METRON_SEARCH": flag("USE_METRON_SEARCH"),
        "METRON_USERNAME": bool(flag("METRON_USERNAME")),
        "METRON_PASSWORD": bool(flag("METRON_PASSWORD")),
        "MANGADEX_ENABLED": flag("MANGADEX_ENABLED"),
        "MAL_ENABLED": flag("MAL_ENABLED"),
        "MAL_CLIENT_ID": bool(flag("MAL_CLIENT_ID")),
        "AI_BASE_URL": bool(flag("AI_BASE_URL")),
        "AI_API_KEY": bool(flag("AI_API_KEY")),
        "AI_MODEL": bool(flag("AI_MODEL")),
        "ENABLE_DDL": flag("ENABLE_DDL"),
        "ENABLE_GETCOMICS": flag("ENABLE_GETCOMICS"),
        "ENABLE_EXTERNAL_SERVER": flag("ENABLE_EXTERNAL_SERVER"),
        "EXPERIMENTAL": flag("EXPERIMENTAL"),
        "NEWZNAB": flag("NEWZNAB"),
        "EXTRA_NEWZNABS": _count_list(flag("EXTRA_NEWZNABS")),
        "NZB_DOWNLOADER": flag("NZB_DOWNLOADER"),
        "ENABLE_PUBLIC": flag("ENABLE_PUBLIC"),
        "ENABLE_32P": flag("ENABLE_32P"),
        "ENABLE_TORZNAB": flag("ENABLE_TORZNAB"),
        "EXTRA_TORZNABS": _count_list(flag("EXTRA_TORZNABS")),
        "ENABLE_TORRENT_SEARCH": flag("ENABLE_TORRENT_SEARCH"),
        "ENABLE_TORRENTS": flag("ENABLE_TORRENTS"),
        "TORRENT_DOWNLOADER": flag("TORRENT_DOWNLOADER"),
        "SAB_HOST": bool(flag("SAB_HOST")),
        "SAB_APIKEY": bool(flag("SAB_APIKEY")),
        "SAB_DIRECTORY": bool(flag("SAB_DIRECTORY")),
        "NZBGET_HOST": bool(flag("NZBGET_HOST")),
        "NZBGET_DIRECTORY": bool(flag("NZBGET_DIRECTORY")),
        "BLACKHOLE_DIR": bool(flag("BLACKHOLE_DIR")),
        "DDL_LOCATION": bool(flag("DDL_LOCATION")),
        "LOCAL_WATCHDIR": bool(flag("LOCAL_WATCHDIR")),
        "UTORRENT_HOST": bool(flag("UTORRENT_HOST")),
        "RTORRENT_HOST": bool(flag("RTORRENT_HOST")),
        "RTORRENT_DIRECTORY": bool(flag("RTORRENT_DIRECTORY")),
        "TRANSMISSION_HOST": bool(flag("TRANSMISSION_HOST")),
        "TRANSMISSION_DIRECTORY": bool(flag("TRANSMISSION_DIRECTORY")),
        "DELUGE_HOST": bool(flag("DELUGE_HOST")),
        "DELUGE_DOWNLOAD_DIRECTORY": bool(flag("DELUGE_DOWNLOAD_DIRECTORY")),
        "QBITTORRENT_HOST": bool(flag("QBITTORRENT_HOST")),
        "QBITTORRENT_FOLDER": bool(flag("QBITTORRENT_FOLDER")),
    }


def _count_list(value: Any) -> int:
    if not value:
        return 0
    try:
        return len(list(value))
    except Exception:
        return 0


def _collect_diagnostics(
    ctx, snapshot: Mapping[str, Any], generated_at: datetime
) -> tuple[dict[str, Any], dict[str, Any]]:
    sources: dict[str, Any] = {
        "build": {"status": "available"},
        "runtime": {"status": "available"},
        "configuration": {"status": "available"},
        "database": {"status": "available"},
        "health": {"status": "available"},
    }

    try:
        build = _collect_build(ctx, snapshot)
    except Exception as e:
        raise SupportBundleUnavailable() from e

    try:
        runtime = _collect_runtime(ctx)
    except Exception as e:
        raise SupportBundleUnavailable() from e

    try:
        configuration = _collect_configuration(snapshot)
    except Exception as e:
        raise SupportBundleUnavailable() from e

    diagnostics: dict[str, Any] = {
        "build": build,
        "runtime": runtime,
        "configuration": configuration,
    }

    database, db_reason = _collect_database(ctx)
    if database is None:
        sources["database"] = {
            "status": "unavailable",
            "reason": db_reason or "query_failed",
        }
        sources["health"] = {
            "status": "unavailable",
            "reason": "dependency_unavailable",
        }
    else:
        diagnostics["database"] = database
        health, health_reason = _collect_health(ctx, snapshot, generated_at)
        if health is None:
            sources["health"] = {
                "status": "unavailable",
                "reason": health_reason or "query_failed",
            }
        else:
            diagnostics["health"] = health

    return diagnostics, sources


def _collect_build(ctx, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    from comicarr.app.system import service as system_service

    release = _normalize_version(snapshot.get("release_version"))
    if release == "unknown":
        try:
            release = _normalize_version(importlib_metadata.version("comicarr"))
        except Exception:
            release = "unknown"

    try:
        identity_info = system_service.get_build_identity(ctx)
    except Exception:
        identity_info = {"verified": False, "id": None}

    verified = bool(identity_info.get("verified"))
    build_id = str(identity_info.get("id") or "").strip()
    if verified:
        if build_id in {release, f"v{release}"} and release != "unknown":
            identity = "verified_release"
        else:
            identity = "custom"
    else:
        identity = "unverified"

    install_raw = (
        str(snapshot.get("install_type") or getattr(ctx, "install_type", None) or _runtime_install_type() or "")
        .strip()
        .lower()
    )
    if install_raw == "docker":
        install_method = "docker"
    elif install_raw in {"git", "source"}:
        install_method = "source"
    elif install_raw in {"win", "package", "wheel"}:
        install_method = "package"
    else:
        install_method = "unknown"

    return {
        "release_version": release,
        "identity": identity,
        "install_method": install_method,
    }


def _runtime_install_type() -> Optional[str]:
    try:
        import comicarr

        return getattr(comicarr, "INSTALL_TYPE", None)
    except Exception:
        return None


def _collect_runtime(ctx) -> dict[str, Any]:
    os_family = _normalize_os_family(platform.system())
    architecture = _normalize_architecture(platform.machine())
    py = sys.version_info
    python_version = _normalize_version(f"{py.major}.{py.minor}.{py.micro}")

    dialect = "unknown"
    try:
        from comicarr.db import get_engine

        engine = get_engine()
        name = str(getattr(getattr(engine, "dialect", None), "name", "") or "").lower()
        if name.startswith("postgres"):
            dialect = "postgresql"
        elif name.startswith("mysql") or name.startswith("mariadb"):
            dialect = "mysql"
        elif name.startswith("sqlite"):
            dialect = "sqlite"
        elif name:
            dialect = "unknown"
    except Exception:
        dialect = "unknown"

    dependencies = {name: _normalize_installed_version(name) for name in _DEPENDENCY_NAMES}
    return {
        "os_family": os_family,
        "architecture": architecture,
        "python_version": python_version,
        "database_dialect": dialect,
        "dependencies": dependencies,
    }


def _collect_configuration(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "automation": {
            "post_processing": _toggle(snapshot.get("POST_PROCESSING")),
            "rss": _toggle(snapshot.get("ENABLE_RSS")),
            "update_checks": _toggle(snapshot.get("CHECK_GITHUB")),
        },
        "integrations": {
            "comicvine": _integration_comicvine(snapshot),
            "metron": _integration_metron(snapshot),
            "mangadex": _integration_mangadex(snapshot),
            "myanimelist": _integration_mal(snapshot),
            "ai": _integration_ai(snapshot),
        },
        "acquisition": {
            "ddl": _acquisition_ddl(snapshot),
            "nzb": _acquisition_nzb(snapshot),
            "torrent": _acquisition_torrent(snapshot),
        },
    }


def _integration_comicvine(snapshot: Mapping[str, Any]) -> str:
    enabled = snapshot.get("COMICVINE_ENABLED")
    if enabled is None:
        return "unknown"
    if not enabled:
        return "disabled"
    return "configured" if snapshot.get("COMICVINE_API") else "not_configured"


def _integration_metron(snapshot: Mapping[str, Any]) -> str:
    enabled = snapshot.get("USE_METRON_SEARCH")
    if enabled is None:
        return "unknown"
    if not enabled:
        return "disabled"
    if snapshot.get("METRON_USERNAME") and snapshot.get("METRON_PASSWORD"):
        return "configured"
    return "not_configured"


def _integration_mangadex(snapshot: Mapping[str, Any]) -> str:
    enabled = snapshot.get("MANGADEX_ENABLED")
    if enabled is None:
        return "unknown"
    return "configured" if enabled else "disabled"


def _integration_mal(snapshot: Mapping[str, Any]) -> str:
    enabled = snapshot.get("MAL_ENABLED")
    if enabled is None:
        return "unknown"
    if not enabled:
        return "disabled"
    return "configured" if snapshot.get("MAL_CLIENT_ID") else "not_configured"


def _integration_ai(snapshot: Mapping[str, Any]) -> str:
    if snapshot.get("AI_BASE_URL") and snapshot.get("AI_API_KEY") and snapshot.get("AI_MODEL"):
        return "configured"
    if (
        all(snapshot.get(key) is None for key in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL"))
        and snapshot.get("POST_PROCESSING") is None
    ):
        return "unknown"
    return "not_configured"


def _route_enabled_ddl(snapshot: Mapping[str, Any]) -> bool:
    return bool(
        snapshot.get("ENABLE_DDL") and (snapshot.get("ENABLE_GETCOMICS") or snapshot.get("ENABLE_EXTERNAL_SERVER"))
    )


def _route_enabled_nzb(snapshot: Mapping[str, Any]) -> bool:
    providers = bool(
        snapshot.get("EXPERIMENTAL") or (snapshot.get("NEWZNAB") and int(snapshot.get("EXTRA_NEWZNABS") or 0) > 0)
    )
    try:
        downloader = int(snapshot.get("NZB_DOWNLOADER") if snapshot.get("NZB_DOWNLOADER") is not None else 3)
    except (TypeError, ValueError):
        downloader = 3
    return bool(providers and downloader != 3)


def _route_enabled_torrent(snapshot: Mapping[str, Any]) -> bool:
    providers = bool(
        snapshot.get("ENABLE_PUBLIC")
        or snapshot.get("ENABLE_32P")
        or (snapshot.get("ENABLE_TORZNAB") and int(snapshot.get("EXTRA_TORZNABS") or 0) > 0)
    )
    return bool(snapshot.get("ENABLE_TORRENT_SEARCH") and snapshot.get("ENABLE_TORRENTS") and providers)


def _acquisition_ddl(snapshot: Mapping[str, Any]) -> dict[str, str]:
    enabled = _route_enabled_ddl(snapshot)
    if enabled:
        client = "local"
    else:
        client = "disabled" if snapshot.get("ENABLE_DDL") is not None else "unknown"
        if snapshot.get("ENABLE_DDL") is None:
            return {"enabled": "unknown", "client": "unknown"}
    return {"enabled": "enabled" if enabled else "disabled", "client": client}


def _acquisition_nzb(snapshot: Mapping[str, Any]) -> dict[str, str]:
    if snapshot.get("NZB_DOWNLOADER") is None and snapshot.get("ENABLE_DDL") is None:
        return {"enabled": "unknown", "client": "unknown"}
    try:
        raw = int(snapshot.get("NZB_DOWNLOADER") if snapshot.get("NZB_DOWNLOADER") is not None else 3)
    except (TypeError, ValueError):
        raw = -1
    client = _NZB_CLIENTS.get(raw, "unknown")
    enabled = _route_enabled_nzb(snapshot)
    return {"enabled": "enabled" if enabled else "disabled", "client": client}


def _acquisition_torrent(snapshot: Mapping[str, Any]) -> dict[str, str]:
    if snapshot.get("TORRENT_DOWNLOADER") is None and snapshot.get("ENABLE_TORRENTS") is None:
        return {"enabled": "unknown", "client": "unknown"}
    enabled = _route_enabled_torrent(snapshot)
    try:
        raw = int(snapshot.get("TORRENT_DOWNLOADER") if snapshot.get("TORRENT_DOWNLOADER") is not None else 0)
    except (TypeError, ValueError):
        raw = -1
    if not bool(snapshot.get("ENABLE_TORRENTS")) and snapshot.get("ENABLE_TORRENTS") is not None:
        client = _TORRENT_CLIENTS.get(raw, "disabled")
        if raw not in _TORRENT_CLIENTS:
            client = "disabled"
    else:
        client = _TORRENT_CLIENTS.get(raw, "unknown")
    return {"enabled": "enabled" if enabled else "disabled", "client": client}


def _collect_database(ctx) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    try:
        from comicarr.db import get_engine

        engine = get_engine()
    except Exception:
        return None, "query_failed"

    try:
        with engine.connect() as conn:
            schema_state, schema_version = _acquisition_schema(conn)
            result: dict[str, Any] = {
                "acquisition_schema_state": schema_state,
                "acquisition_schema_version": schema_version,
            }
            if schema_state == "ready":
                result["count_buckets"] = _count_buckets(conn)
            return result, None
    except Exception:
        return None, "query_failed"


def _acquisition_schema(conn) -> tuple[str, int]:
    try:
        from comicarr.app.acquisition.maintenance import SCHEMA_COMPONENT, SCHEMA_VERSION
        from comicarr.tables import acquisition_schema_versions

        row = conn.execute(
            select(func.max(acquisition_schema_versions.c.version)).where(
                acquisition_schema_versions.c.component == SCHEMA_COMPONENT
            )
        ).scalar()
        version = int(row or 0)
        if version >= SCHEMA_VERSION:
            return "ready", min(version, 65535)
        if version > 0:
            return "not_ready", min(version, 65535)
        return "not_ready", 0
    except Exception:
        try:
            conn.execute(text("SELECT 1 FROM acquisition_schema_versions LIMIT 1"))
            return "not_ready", 0
        except Exception:
            return "unknown", 0


def _count_buckets(conn) -> dict[str, str]:
    from comicarr.app.activity.queries import IN_FLIGHT_ITEM_STATES, OPEN_STAGES
    from comicarr.tables import acquisition_run_items, annuals, comics, issues, pipeline_journal

    def count(stmt) -> int:
        value = conn.execute(stmt).scalar()
        return int(value or 0)

    series = count(select(func.count()).select_from(comics))
    issue_count = count(select(func.count()).select_from(issues))
    annual_count = count(select(func.count()).select_from(annuals))
    wanted_issues = count(select(func.count()).select_from(issues).where(issues.c.Status == "Wanted"))
    wanted_annuals = count(select(func.count()).select_from(annuals).where(annuals.c.Status == "Wanted"))
    in_flight_items = count(
        select(func.count())
        .select_from(acquisition_run_items)
        .where(acquisition_run_items.c.state.in_(IN_FLIGHT_ITEM_STATES))
    )
    open_journal = count(
        select(func.count()).select_from(pipeline_journal).where(pipeline_journal.c.stage.in_(OPEN_STAGES))
    )
    recovery = count(
        select(func.count())
        .select_from(acquisition_run_items)
        .where(acquisition_run_items.c.state.in_(IN_FLIGHT_ITEM_STATES))
        .where(acquisition_run_items.c.recovery_count > 0)
    )
    return {
        "series": _bucket_count(series),
        "issues": _bucket_count(issue_count),
        "annuals": _bucket_count(annual_count),
        "wanted": _bucket_count(wanted_issues + wanted_annuals),
        "in_flight": _bucket_count(in_flight_items + open_journal),
        "recovery_pending": _bucket_count(recovery),
    }


def _collect_health(
    ctx, snapshot: Mapping[str, Any], generated_at: datetime
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    try:
        from comicarr.app.search.health import get_search_health
        from comicarr.db import get_engine

        config = getattr(ctx, "config", None)
        if config is None:
            return None, "dependency_unavailable"
        engine = get_engine()
        health = get_search_health(config, engine=engine)
        generated_ts = generated_at.timestamp()
        return _project_health(health, ctx, generated_ts), None
    except Exception:
        return None, "query_failed"


def _project_health(health: Mapping[str, Any], ctx, generated_ts: float) -> dict[str, Any]:
    maintenance_raw = health.get("maintenance") or {}
    if maintenance_raw.get("blocked"):
        maintenance = "blocked"
    elif "blocked" in maintenance_raw:
        maintenance = "clear"
    else:
        maintenance = "unknown"

    viable = bool(health.get("viable_route"))
    routes_raw = health.get("routes") or {}
    routes = {name: _project_route(routes_raw.get(name) or {}, generated_ts) for name in ("ddl", "nzb", "torrent")}

    workers = health.get("workers") or {}
    search_worker = _project_search_worker(workers.get("search") or workers)

    scheduler = _project_scheduler(ctx)

    overall = _project_overall(
        maintenance=maintenance,
        viable=viable,
        search_worker=search_worker,
        routes=routes,
        routes_raw=routes_raw,
    )
    return {
        "overall": overall,
        "maintenance": maintenance,
        "viable_route": viable,
        "search_worker": search_worker,
        "scheduler": scheduler,
        "routes": routes,
    }


def _project_route(route: Mapping[str, Any], generated_ts: float) -> dict[str, str]:
    reason = str(route.get("reason") or "").strip().lower()
    if route.get("ready"):
        state = "ready"
    elif reason in _ROUTE_STATE_MAP:
        state = _ROUTE_STATE_MAP[reason]
    elif "maintenance" in reason:
        state = "maintenance_blocked"
    elif not route.get("enabled", True) and reason in {"", "disabled"}:
        state = "disabled"
    elif reason:
        state = "unknown"
    elif not route.get("enabled", True):
        state = "disabled"
    else:
        state = "unknown"

    last_success = route.get("last_success")
    return {
        "state": state,
        "last_success_age": _recency(last_success, generated_ts),
    }


def _project_search_worker(worker: Mapping[str, Any]) -> str:
    if not worker:
        return "unknown"
    state = str(worker.get("state") or "").strip().lower()
    if state in {"failed"}:
        return "failed"
    if state in {"stopped"}:
        return "stopped"
    if worker.get("healthy") and worker.get("alive"):
        return "healthy"
    if worker.get("alive") is False and worker.get("last_heartbeat") is not None:
        return "stale"
    if state in {"idle", "waiting", "succeeded"} and worker.get("alive"):
        return "healthy"
    return "unknown"


def _project_scheduler(ctx) -> dict[str, str]:
    result = {
        "search": "unknown",
        "rss": "unknown",
        "weekly": "unknown",
        "import_scan": "unknown",
    }
    scheduler = getattr(ctx, "scheduler", None)
    if scheduler is None:
        return result

    job_map = {
        "search": "search",
        "rss": "rss",
        "weekly": "weekly",
        "dbupdater": "import_scan",
        "import_scan": "import_scan",
        "db update": "import_scan",
    }
    try:
        jobs = scheduler.get_jobs()
    except Exception:
        return result

    for job in jobs or []:
        job_id = str(getattr(job, "id", "") or "").strip().lower()
        name = str(getattr(job, "name", "") or "").strip().lower()
        key = job_map.get(job_id)
        if key is None:
            for needle, mapped in job_map.items():
                if needle in job_id or needle in name:
                    key = mapped
                    break
        if key is None or key not in result:
            continue
        try:
            pending = bool(getattr(job, "pending", False))
        except Exception:
            pending = False
        try:
            next_run = getattr(job, "next_run_time", None)
            if pending:
                state = "waiting"
            elif next_run is None:
                state = "paused"
            else:
                state = "waiting"
        except Exception:
            state = "unknown"
        history_status = _job_history_status(job_id or name)
        if history_status:
            state = history_status
        result[key] = state
    return result


def _job_history_status(job_key: str) -> Optional[str]:
    try:
        from comicarr import db as db_mod
        from comicarr.tables import jobhistory

        row = db_mod.select_one(select(jobhistory.c.Status).where(jobhistory.c.JobName == job_key))
        if not row:
            return None
        return _normalize_scheduler_state(row.get("Status"))
    except Exception:
        return None


def _normalize_scheduler_state(value: Any) -> str:
    text_value = str(value or "").strip().lower()
    if not text_value:
        return "unknown"
    if text_value in _SCHEDULER_STATE_MAP:
        return _SCHEDULER_STATE_MAP[text_value]
    if "max instance" in text_value:
        return "failed"
    return "unknown"


def _project_overall(
    *,
    maintenance: str,
    viable: bool,
    search_worker: str,
    routes: Mapping[str, Mapping[str, str]],
    routes_raw: Mapping[str, Any],
) -> str:
    if maintenance == "blocked" or not viable:
        return "blocked"
    nonready_enabled = False
    for name, projected in routes.items():
        raw = routes_raw.get(name) or {}
        if not raw.get("enabled", False):
            continue
        if projected.get("state") != "ready":
            nonready_enabled = True
            break
    if maintenance == "clear" and viable and search_worker == "healthy" and not nonready_enabled:
        return "healthy"
    if viable:
        return "degraded"
    return "unknown"


def _normalize_version(value: Any) -> str:
    if value is None:
        return "unknown"
    text_value = str(value).strip()
    if not text_value:
        return "unknown"
    if text_value.lower().startswith("v") and text_value[1:2].isdigit():
        text_value = text_value[1:]
    if any(ch in text_value for ch in ("+", "-", " ")):
        base = text_value.split("+", 1)[0].split("-", 1)[0].split(" ", 1)[0]
        if base != text_value:
            return "unknown"
    parts = text_value.split(".")
    if len(parts) < 1:
        return "unknown"
    nums: list[int] = []
    for part in parts[:3]:
        if not part.isdigit():
            return "unknown"
        number = int(part)
        if number > 65535:
            return "unknown"
        if len(part) > 1 and part.startswith("0"):
            return "unknown"
        nums.append(number)
    while len(nums) < 3:
        nums.append(0)
    rendered = f"{nums[0]}.{nums[1]}.{nums[2]}"
    if not _VERSION_RE.match(rendered) or len(rendered) > 17:
        return "unknown"
    return rendered


def _normalize_installed_version(dist_name: str) -> str:
    try:
        return _normalize_version(importlib_metadata.version(dist_name))
    except Exception:
        return "unknown"


def _normalize_os_family(system: str) -> str:
    value = str(system or "").strip()
    if not value:
        return "unknown"
    lower = value.lower()
    if lower == "linux":
        return "linux"
    if lower == "windows":
        return "windows"
    if lower == "darwin":
        return "macos"
    if lower.endswith("bsd"):
        return "bsd"
    return "other"


def _normalize_architecture(machine: str) -> str:
    value = str(machine or "").strip()
    if not value:
        return "unknown"
    lower = value.lower()
    if lower in {"x86_64", "amd64"}:
        return "x86_64"
    if lower in {"i386", "i486", "i586", "i686", "x86"}:
        return "x86"
    if lower in {"aarch64", "arm64"}:
        return "arm64"
    if lower.startswith("arm"):
        return "arm"
    return "other"


def _toggle(value: Any) -> str:
    if value is None:
        return "unknown"
    return "enabled" if bool(value) else "disabled"


def _bucket_count(value: int) -> str:
    if value < 0:
        value = 0
    for upper, label in _COUNT_BUCKETS:
        if value <= upper:
            return label
    return "100k_plus"


def _recency(timestamp: Any, generated_ts: float) -> str:
    if timestamp is None:
        return "never"
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return "unknown"
    if not (ts == ts) or ts in (float("inf"), float("-inf")):
        return "unknown"
    age = generated_ts - ts
    if age < -60:
        return "unknown"
    if age < 0:
        age = 0
    for upper, label in _RECENCY_BOUNDS:
        if age < upper:
            return label
    return "gt_7d"


def _size_bucket(size: int) -> str:
    return _bucket_count(size)


def _duration_bucket(seconds: float) -> str:
    if seconds < 1:
        return "lt_1s"
    if seconds < 5:
        return "1s_5s"
    if seconds < 30:
        return "5s_30s"
    return "gt_30s"


def _log_outcome(
    *,
    code: str,
    status: str,
    duration_s: float,
    size_bucket: str,
    exception_class: Optional[str] = None,
) -> None:
    payload = {
        "outcome": code,
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "duration_bucket": _duration_bucket(duration_s),
        "size_bucket": size_bucket,
    }
    if exception_class:
        payload["exception_class"] = exception_class
    logger.info("[SUPPORT-BUNDLE] %s" % payload)


def _canonical_json(value: Any) -> bytes:
    text_value = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (text_value + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads(read_contract_bytes(name).decode("utf-8"))


def _build_and_validate_archive(
    *,
    diagnostics: dict[str, Any],
    sources: dict[str, Any],
    bundle_status: str,
    generated_at: datetime,
    product_version: str,
) -> SupportBundleArtifact:
    readme_bytes = read_contract_bytes("README.txt")
    if len(readme_bytes) > README_MAX_BYTES or len(readme_bytes) < 1:
        raise SupportBundleValidationFailed()

    diagnostics_bytes = _canonical_json(diagnostics)
    if len(diagnostics_bytes) > JSON_MEMBER_MAX_BYTES:
        raise SupportBundleValidationFailed()

    try:
        Draft202012Validator(_load_schema("diagnostics.schema.json")).validate(diagnostics)
    except Exception as e:
        raise SupportBundleValidationFailed() from e

    manifest = {
        "bundle_status": bundle_status,
        "contract_version": CONTRACT_VERSION,
        "generated_at": generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "members": [
            {
                "name": "README.txt",
                "sha256": _sha256(readme_bytes),
                "size_bytes": len(readme_bytes),
            },
            {"name": "manifest.json"},
            {
                "name": "diagnostics.json",
                "sha256": _sha256(diagnostics_bytes),
                "size_bytes": len(diagnostics_bytes),
            },
        ],
        "operator_review_required": True,
        "product": "Comicarr",
        "product_version": product_version,
        "sources": sources,
    }
    manifest_bytes = _canonical_json(manifest)
    if len(manifest_bytes) > JSON_MEMBER_MAX_BYTES:
        raise SupportBundleValidationFailed()

    try:
        Draft202012Validator(_load_schema("manifest.schema.json")).validate(manifest)
    except Exception as e:
        raise SupportBundleValidationFailed() from e

    _validate_cross_document(manifest, diagnostics)

    members = {
        "README.txt": readme_bytes,
        "manifest.json": manifest_bytes,
        "diagnostics.json": diagnostics_bytes,
    }
    total = sum(len(v) for v in members.values())
    if total > TOTAL_UNCOMPRESSED_MAX_BYTES:
        raise SupportBundleValidationFailed()

    zip_bytes = _write_zip(members)
    if len(zip_bytes) > ZIP_MAX_BYTES or len(zip_bytes) < 1:
        raise SupportBundleValidationFailed()

    _validate_final_zip(zip_bytes, members, manifest)
    return SupportBundleArtifact(
        content=zip_bytes,
        contract_version=CONTRACT_VERSION,
        filename=FILENAME,
        status=bundle_status,
    )


def _validate_cross_document(manifest: Mapping[str, Any], diagnostics: Mapping[str, Any]) -> None:
    db_available = manifest["sources"]["database"]["status"] == "available"
    health_available = manifest["sources"]["health"]["status"] == "available"
    expected_status = "complete" if db_available and health_available else "partial"
    if manifest["bundle_status"] != expected_status:
        raise SupportBundleValidationFailed()
    if db_available != ("database" in diagnostics):
        raise SupportBundleValidationFailed()
    if health_available != ("health" in diagnostics):
        raise SupportBundleValidationFailed()
    if not db_available and health_available:
        pass
    if not db_available:
        reason = manifest["sources"]["database"].get("reason")
        if reason not in {
            "access_denied",
            "query_failed",
            "schema_unavailable",
            "dependency_unavailable",
            "unsupported",
        }:
            raise SupportBundleValidationFailed()
    if not health_available:
        reason = manifest["sources"]["health"].get("reason")
        if reason not in {
            "access_denied",
            "query_failed",
            "schema_unavailable",
            "dependency_unavailable",
            "unsupported",
        }:
            raise SupportBundleValidationFailed()
    if manifest["product_version"] != diagnostics["build"]["release_version"]:
        raise SupportBundleValidationFailed()
    if diagnostics.get("database", {}).get("acquisition_schema_state") == "ready":
        if "count_buckets" not in diagnostics["database"]:
            raise SupportBundleValidationFailed()
    elif "database" in diagnostics and "count_buckets" in diagnostics["database"]:
        raise SupportBundleValidationFailed()


def _write_zip(members: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in MEMBER_ORDER:
            info = zipfile.ZipInfo(filename=name, date_time=_ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = _ZIP_CREATE_SYSTEM
            info.external_attr = _ZIP_EXTERNAL_ATTR
            info.comment = b""
            info.extra = b""
            zf.writestr(info, members[name])
        zf.comment = b""
    return buffer.getvalue()


def _validate_final_zip(
    zip_bytes: bytes,
    expected_members: Mapping[str, bytes],
    manifest: Mapping[str, Any],
) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = zf.namelist()
            if names != list(MEMBER_ORDER):
                raise SupportBundleValidationFailed()
            if zf.comment:
                raise SupportBundleValidationFailed()
            for name in MEMBER_ORDER:
                info = zf.getinfo(name)
                if info.filename != name:
                    raise SupportBundleValidationFailed()
                if "\\" in info.filename or info.filename.startswith("/"):
                    raise SupportBundleValidationFailed()
                if info.date_time != _ZIP_DATE_TIME:
                    raise SupportBundleValidationFailed()
                if info.comment:
                    raise SupportBundleValidationFailed()
                if info.flag_bits & 0x1:
                    raise SupportBundleValidationFailed()
                data = zf.read(name)
                if data != expected_members[name]:
                    raise SupportBundleValidationFailed()
            manifest_obj = _loads_strict(zf.read("manifest.json"))
            diagnostics_obj = _loads_strict(zf.read("diagnostics.json"))
            Draft202012Validator(_load_schema("manifest.schema.json")).validate(manifest_obj)
            Draft202012Validator(_load_schema("diagnostics.schema.json")).validate(diagnostics_obj)
            _validate_cross_document(manifest_obj, diagnostics_obj)
            readme = zf.read("README.txt")
            diagnostics_bytes = zf.read("diagnostics.json")
            m0 = manifest_obj["members"][0]
            m2 = manifest_obj["members"][2]
            if m0["size_bytes"] != len(readme) or m0["sha256"] != _sha256(readme):
                raise SupportBundleValidationFailed()
            if m2["size_bytes"] != len(diagnostics_bytes) or m2["sha256"] != _sha256(diagnostics_bytes):
                raise SupportBundleValidationFailed()
            if readme != read_contract_bytes("README.txt"):
                raise SupportBundleValidationFailed()
            if manifest_obj.get("operator_review_required") is not True:
                raise SupportBundleValidationFailed()
            if manifest_obj.get("bundle_status") != manifest.get("bundle_status"):
                raise SupportBundleValidationFailed()
    except SupportBundleValidationFailed:
        raise
    except Exception as e:
        raise SupportBundleValidationFailed() from e


def _loads_strict(data: bytes) -> Any:
    if not data.endswith(b"\n"):
        raise SupportBundleValidationFailed()
    text_value = data.decode("utf-8")
    if "\ufeff" in text_value:
        raise SupportBundleValidationFailed()
    decoder = json.JSONDecoder()
    obj, idx = decoder.raw_decode(text_value)
    trailing = text_value[idx:]
    if trailing != "\n":
        raise SupportBundleValidationFailed()
    try:
        json.dumps(obj, allow_nan=False)
    except (ValueError, TypeError) as e:
        raise SupportBundleValidationFailed() from e
    return obj
