#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The Acquisition route seam: one classifier, one published health read.

An Acquisition route is the delivery channel a Search provider serves --
``ddl``, ``nzb``, or ``torrent`` -- and every provider serves exactly one.
:func:`classify` is the single answer to "which route does this provider
serve": kind-based when the caller has a provider candidate, with name
heuristics surviving only as fallbacks for stats rows and bare site names
where the kind is not recorded.  :func:`route_health` is the published
route-readiness precheck that Needs attention, Interactive release search,
and the search commands share; readiness assembly stays in ``health.py``
as this module's implementation.
"""

from __future__ import annotations

import comicarr

ROUTES = ("ddl", "nzb", "torrent")


def classify(provider, config=None) -> str:
    """Return the Acquisition route a Search provider serves.

    Accepts a provider candidate (anything with a ``kind`` attribute), a
    provider-stats row (a dict), or a bare site name.  The kind rule is the
    ground truth; the row and name rules are historical fallbacks for
    surfaces that only recorded a name.
    """
    kind = getattr(provider, "kind", None)
    if kind is not None:
        return _from_kind(kind)
    if isinstance(provider, dict):
        return _from_stats_row(provider)
    return _from_site_name(provider, config)


def _from_kind(kind) -> str:
    if kind in {"torznab", "torrent"}:
        return "torrent"
    if kind in {"newznab", "experimental"}:
        return "nzb"
    return "ddl"


def _from_stats_row(row) -> str:
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


def _from_site_name(site, config=None) -> str:
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


def route_health(ctx):
    """Shared route-readiness precheck for anything that starts a search."""
    from comicarr.app.search.health import blocking_route_reason, get_search_health

    health = get_search_health(
        ctx.config,
        provider_blocklist=getattr(ctx, "provider_blocklist", None) or comicarr.PROVIDER_BLOCKLIST,
    )
    routes = health.get("routes") or {}
    viable = bool(health.get("viable_route")) or any(
        bool((routes.get(name) or {}).get("ready") or (routes.get(name) or {}).get("viable")) for name in ROUTES
    )
    if not viable:
        return {
            "success": False,
            "status": "blocked",
            "error": blocking_route_reason(routes),
            "message": "Search blocked: no complete acquisition route is ready",
            "routes": routes,
        }
    return {"success": True, "routes": routes, "health": health}
