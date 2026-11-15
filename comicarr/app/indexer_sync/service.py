#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The Mylar3 API subset Prowlarr's Mylar application calls (#1140).

Prowlarr already knows how to push indexers into Mylar3: it calls
``GET /api?cmd=<command>&apikey=<key>`` and reads Mylar3's JSON envelope,
``{"success": true, "data": ...}`` or ``{"success": false, "error":
{"code": ..., "message": ...}}``, always with HTTP 200. Answering those same
five commands lets an operator add Comicarr in Prowlarr as a *Mylar*
application, so no Prowlarr change is needed.

``getVersion``
    Connection test.
``listProviders``
    Every Newznab and Torznab indexer, so Prowlarr can find the ones it owns.
``addProvider`` / ``changeProvider`` / ``delProvider``
    Write one indexer. Each write goes through
    :func:`comicarr.app.system.service.update_providers`, the same path the
    Settings page saves through, so ids, name clashes, credential encryption
    and persistence all behave as if the operator had typed the change.

Credentials are returned only for indexers Prowlarr itself wrote (named
``... (Prowlarr)`` with a ``/<id>/api`` host). Prowlarr compares that key with
its own to recognise its indexers; every other indexer's key stays private,
because the Comicarr API key never granted reading them before.
"""

from __future__ import annotations

import hmac
import re
import threading
from urllib.parse import urlsplit

from comicarr import logger
from comicarr.app.search.provider_config import SearchProvider, normalize_category_list, providers_from_config
from comicarr.app.system import service as system_service

ERROR_CODE = 1
COMMANDS = ("getVersion", "listProviders", "addProvider", "changeProvider", "delProvider")
PROVIDER_TYPES = ("newznab", "torznab")
ENABLED_KEYS = {"newznab": "NEWZNAB", "torznab": "ENABLE_TORZNAB"}

# Prowlarr names a synced indexer "<indexer> (Prowlarr)" and points it at
# "<prowlarr url>/<indexer id>/api".
_PROWLARR_NAME_SUFFIX = "(prowlarr)"
_PROWLARR_HOST_PATH = re.compile(r"/\d+/api/?$")

# One read-modify-write of a provider list at a time.
_write_lock = threading.Lock()


class MylarApiError(Exception):
    """A request Comicarr refuses, reported in Mylar3's error envelope."""


def success(data) -> dict:
    return {"success": True, "data": data}


def failure(message) -> dict:
    return {"success": False, "error": {"code": ERROR_CODE, "message": str(message)}}


def handle(ctx, params) -> dict:
    """Answer one Mylar3 API call. Never raises; the envelope says what happened."""
    params = {str(key): "" if value is None else str(value) for key, value in (params or {}).items()}
    command = params.pop("cmd", "")
    if not command:
        return failure("Missing parameter: cmd")
    supplied = params.pop("apikey", "")
    if not supplied:
        return failure("Missing API key")
    expected = getattr(ctx.config, "API_KEY", None) if ctx.config else None
    if not expected:
        return failure("API key not generated")
    if not hmac.compare_digest(supplied.encode(), str(expected).encode()):
        return failure("Incorrect API key")
    if command not in COMMANDS:
        return failure("Unknown command: %s" % command)
    handler = {
        "getVersion": _get_version,
        "listProviders": _list_providers,
        "addProvider": _add_provider,
        "changeProvider": _change_provider,
        "delProvider": _del_provider,
    }[command]
    try:
        return handler(ctx, params)
    except MylarApiError as e:
        logger.fdebug("[INDEXER-SYNC] %s refused: %s" % (command, e))
        return failure(e)
    except Exception as e:
        logger.error("[INDEXER-SYNC] %s failed: %s" % (command, type(e).__name__))
        return failure("Comicarr could not complete %s. Check the Comicarr log." % command)


def _get_version(_ctx, _params) -> dict:
    version = system_service.get_release_version()
    return success(
        {
            "current_version": version,
            "latest_version": version,
            "commits_behind": 0,
            "install_type": "comicarr",
            "git_path": None,
        }
    )


def is_prowlarr_managed(provider: SearchProvider) -> bool:
    """True for an indexer Prowlarr's Mylar application wrote."""
    try:
        path = urlsplit(provider.host).path
    except ValueError:
        return False
    return provider.name.strip().casefold().endswith(_PROWLARR_NAME_SUFFIX) and bool(_PROWLARR_HOST_PATH.search(path))


def _listed(provider: SearchProvider) -> dict:
    managed = is_prowlarr_managed(provider)
    row = {
        "name": provider.name,
        "host": provider.host if managed else system_service._safe_provider_host(provider.host),
        "apikey": provider.api_key if managed else "",
        "categories": ",".join(provider.categories),
        "enabled": provider.enabled,
        "id": provider.id,
    }
    if provider.kind == "newznab":
        row["uid"] = provider.rss_uid
    return row


def _list_providers(ctx, _params) -> dict:
    return success(
        {
            "newznabs": [_listed(record) for record in providers_from_config(ctx.config, "newznab")],
            "torznabs": [_listed(record) for record in providers_from_config(ctx.config, "torznab")],
        }
    )


def _provider_type(params) -> str:
    kind = params.get("providertype", "").strip().lower()
    if not kind:
        raise MylarApiError("No provider type provided")
    if kind not in PROVIDER_TYPES:
        raise MylarApiError("providertype %s is not a valid option. Options are `newznab` or `torznab`." % kind)
    return kind


def _enabled(value, default=True) -> bool:
    text = str(value).strip().lower()
    if text in ("", "true", "1", "yes", "on"):
        return default if text == "" else True
    if text in ("false", "0", "no", "off"):
        return False
    raise MylarApiError("`enabled` value must be `true` or `false`")


def _host(value) -> str:
    host = str(value or "").strip()
    try:
        parsed = urlsplit(host)
    except ValueError:
        parsed = None
    if parsed is None or parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise MylarApiError("host must be an http:// or https:// URL")
    return host


def _find(records, kind, params):
    """The record ``prov_id`` or ``name`` names, matching names case-insensitively."""
    prov_id = params.get("prov_id", "").strip()
    name = params.get("name", "").strip()
    if not prov_id and not name:
        raise MylarApiError("at least one of prov_id or name must be provided (cannot be blank)")
    for index, record in enumerate(records):
        if prov_id:
            if record.id is not None and str(record.id) == prov_id:
                return index
        elif record.name.strip().casefold() == name.casefold():
            return index
    raise MylarApiError("%s does not exist as a %s provider" % (name or prov_id, kind))


def _row(record: SearchProvider) -> dict:
    """A Settings-shaped row for :func:`update_providers`, credential included."""
    row = {
        "name": record.name,
        "host": record.host,
        "verify": record.verify,
        "api_key": record.api_key,
        "categories": ",".join(record.categories),
        "enabled": record.enabled,
        "rss_uid": record.rss_uid,
    }
    if record.id is not None:
        row["id"] = record.id
    return row


def _save(ctx, kind, records, turn_on=False) -> None:
    payload = {"type": kind, "providers": [_row(record) for record in records]}
    if turn_on and not getattr(ctx.config, ENABLED_KEYS[kind], False):
        # Prowlarr was told to sync indexers here; a synced indexer that never
        # searches because its whole kind is switched off would look broken.
        payload["enabled"] = True
    result = system_service.update_providers(ctx, payload)
    if not result.get("success"):
        raise MylarApiError(result.get("error") or "Comicarr could not save the %s provider list" % kind)


def _record_from(params, kind, base: SearchProvider | None = None) -> SearchProvider:
    name = params.get("altername", "").strip() or params.get("name", "").strip()
    if not name:
        raise MylarApiError("name given for provider cannot be None or blank")
    host = _host(params["host"]) if params.get("host", "").strip() else (base.host if base else None)
    if host is None:
        raise MylarApiError("Missing argument: host")
    if "prov_apikey" in params:
        api_key = params["prov_apikey"].strip()
    else:
        api_key = base.api_key if base else ""
    if "categories" in params:
        categories = tuple(normalize_category_list(params["categories"].replace("#", ",")))
    else:
        categories = base.categories if base else ()
    if "enabled" in params:
        enabled = _enabled(params["enabled"])
    else:
        enabled = base.enabled if base else True
    return SearchProvider(
        kind=kind,
        name=name,
        host=host,
        verify=host.lower().startswith("https://"),
        api_key=api_key,
        categories=categories,
        enabled=enabled,
        rss_uid=base.rss_uid if base else None,
        id=base.id if base else None,
    )


def _add_provider(ctx, params) -> dict:
    kind = _provider_type(params)
    missing = [key for key in ("name", "host", "prov_apikey") if not params.get(key, "").strip()]
    if missing:
        raise MylarApiError("Missing argument: %s" % ", ".join("`%s`" % key for key in missing))
    with _write_lock:
        records = providers_from_config(ctx.config, kind)
        name = params["name"].strip()
        existing = next(
            (index for index, record in enumerate(records) if record.name.strip().casefold() == name.casefold()),
            None,
        )
        if existing is not None and not is_prowlarr_managed(records[existing]):
            raise MylarApiError("%s already exists as a provider." % name)
        if existing is not None:
            # Prowlarr re-adds an indexer it lost track of (a restored or reset
            # Prowlarr). Take its settings instead of refusing the sync.
            records[existing] = _record_from(params, kind, base=records[existing])
            verb = "Updated"
        else:
            records.append(_record_from(params, kind))
            verb = "Added"
        _save(ctx, kind, records, turn_on=records[existing if existing is not None else -1].enabled)
    logger.info("[INDEXER-SYNC] %s %s provider %s" % (verb, kind, name))
    return success("Successfully added %s provider %s to the provider list" % (kind, name))


def _change_provider(ctx, params) -> dict:
    kind = _provider_type(params)
    with _write_lock:
        records = providers_from_config(ctx.config, kind)
        index = _find(records, kind, params)
        before = records[index]
        records[index] = _record_from({**params, "name": params.get("name") or before.name}, kind, base=before)
        _save(ctx, kind, records)
    logger.info("[INDEXER-SYNC] Changed %s provider %s" % (kind, records[index].name))
    return success("Successfully changed %s provider %s" % (kind, records[index].name))


def _del_provider(ctx, params) -> dict:
    kind = _provider_type(params)
    with _write_lock:
        records = providers_from_config(ctx.config, kind)
        removed = records.pop(_find(records, kind, params))
        _save(ctx, kind, records)
    logger.info("[INDEXER-SYNC] Removed %s provider %s" % (kind, removed.name))
    return success("Successfully removed %s provider %s" % (kind, removed.name))
