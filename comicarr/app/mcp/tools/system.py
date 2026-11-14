#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""System health read tool.

Reports reachability and last run, last error and next run, never a
configured value: the services it reads already scrub hosts and keys out of
their errors, and this tool copies no setting into its output.
"""

import datetime
from typing import Annotated

from mcp_types import CallToolResult, ToolAnnotations

from comicarr.app.mcp.contracts import (
    ConnectionHealth,
    IndexerHealth,
    JobHealth,
    RouteHealth,
    SystemHealth,
    tool_result,
)
from comicarr.app.search import service as search_service
from comicarr.app.system import connections
from comicarr.app.system import service as system_service

ROUTES = ("ddl", "nzb", "torrent")


def _text(value):
    if value in (None, ""):
        return None
    return str(value)


def _when(value):
    """An ISO 8601 string for an epoch number or an already formatted time."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).isoformat()
    try:
        return datetime.datetime.fromtimestamp(float(value), datetime.timezone.utc).isoformat()
    except (TypeError, ValueError):
        return str(value)


def _truthy(value):
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _route(name, route) -> RouteHealth:
    return RouteHealth(
        route=name,
        enabled=bool(route.get("enabled")),
        ready=bool(route.get("ready")),
        reason=str(route.get("reason") or "unknown"),
        client=_text(route.get("downstream")),
        last_success=_when(route.get("last_success")),
        last_failure=_when(route.get("last_failure")),
        last_error=_text(route.get("last_error")),
    )


def _indexer(row) -> IndexerHealth:
    return IndexerHealth(
        name=str(row.get("provider") or ""),
        type=_text(row.get("type")),
        active=_truthy(row.get("active")),
        last_run=_when(row.get("lastrun")),
        hits=_int(row.get("hits")),
    )


def _connection(row) -> ConnectionHealth:
    return ConnectionHealth(
        key=str(row["key"]),
        label=str(row.get("label") or row["key"]),
        kind=str(row.get("kind") or ""),
        ok=row.get("ok"),
        result=_text(row.get("result")),
        checked_at=_when(row.get("checked_at")),
        latency_ms=row.get("latency_ms"),
        version=_text(row.get("version")),
    )


def _job(job) -> JobHealth:
    dispatch = job.get("dispatch") or {}
    return JobHealth(
        job_id=str(job["id"]),
        name=str(job.get("name") or job["id"]),
        status=str(job.get("status") or "Waiting"),
        next_run=_text(job.get("next_run_time")),
        last_run=_when(dispatch.get("last_attempt")),
        last_success=_when(dispatch.get("last_success")),
        last_failure=_when(dispatch.get("last_failure")),
        last_error=_text(dispatch.get("last_error")),
        result=_text(job.get("result")),
    )


def register(server, get_ctx):
    """Add the system health tool to ``server``."""

    @server.tool(
        name="get_system_health",
        title="Get system health",
        description=(
            "Whether Comicarr can search and download: each search route's readiness, the indexers, "
            "the last check of each download client and metadata provider, and the background jobs "
            "with their last and next run."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def get_system_health() -> Annotated[CallToolResult, SystemHealth]:
        ctx = get_ctx()
        search = search_service.get_health(ctx)
        routes = search.get("routes") or {}
        maintenance = search.get("maintenance") or {}
        jobs = system_service.get_job_info(ctx, include_acquisition=False).get("jobs") or []
        health = SystemHealth(
            can_search=bool(search.get("viable_route")),
            maintenance=_text(maintenance.get("reason") or "maintenance") if maintenance.get("blocked") else None,
            routes=[_route(name, routes[name]) for name in ROUTES if name in routes],
            indexers=[_indexer(row) for row in search.get("providers") or []],
            connections=[_connection(row) for row in connections.snapshot(getattr(ctx, "config", None))],
            jobs=[_job(job) for job in jobs],
        )
        ready = [route.route for route in health.routes if route.ready]
        failing = [c.label for c in health.connections if c.ok is False]
        summary = "Search routes ready: %s." % (", ".join(ready) if ready else "none")
        if failing:
            summary += " Failing checks: %s." % ", ".join(failing)
        if health.maintenance:
            summary += " Acquisition is paused for maintenance."
        return tool_result(health, summary)
