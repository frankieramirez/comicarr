#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""One sanitized source of truth for configured search-provider candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Iterable

from comicarr.app.search import prowlarr
from comicarr.app.search.provider_config import provider_enabled
from comicarr.app.search.routes import classify


@dataclass(frozen=True)
class ProviderCandidate:
    name: str
    kind: str
    execution_name: str
    entry: tuple | None = field(default=None, repr=False)
    blocked: bool = False

    @property
    def route(self) -> str:
        return classify(self)


def enabled_provider_entries(entries: Iterable[object]):
    for entry in entries or []:
        try:
            if provider_enabled(entry):
                yield tuple(entry)
        except TypeError:
            continue


def _sequence_key(value):
    text = str(value).strip()
    return (0, int(text), "") if text.isdigit() else (1, 0, text)


def ordered_provider_names(config) -> list[str]:
    """The saved global provider order, first searched first.

    ``PROVIDER_ORDER`` is a ``{"0": name, "1": name, ...}`` mapping at runtime
    and ``"0, name, 1, name"`` in the ini. Sequence numbers sort as numbers:
    sorted as text, "10" came before "2" and an install with more than ten
    providers searched them out of order.
    """
    configured = getattr(config, "PROVIDER_ORDER", None) or {}
    if isinstance(configured, str):
        parts = [part.strip() for part in configured.split(", ")]
        configured = dict(zip(parts[0::2], parts[1::2], strict=False))
    if isinstance(configured, dict):
        return [str(value) for _, value in sorted(configured.items(), key=lambda item: _sequence_key(item[0]))]
    return [str(value) for value in configured]


def _ordered(config, candidates):
    preferred = [name.casefold() for name in ordered_provider_names(config)]

    def position(candidate):
        names = {candidate.name.casefold(), candidate.execution_name.casefold()}
        # An exact name wins over a partial one, so "NZB" saved after
        # "NZBgeek" cannot pull NZBgeek forward, nor "Prowlarr" its Usenet side.
        for index, value in enumerate(preferred):
            if value in names:
                return index
        for index, value in enumerate(preferred):
            if any(value in name for name in names):
                return index
        return len(preferred)

    return sorted(candidates, key=lambda candidate: (position(candidate), candidate.name.casefold()))


def parse_provider_override(value) -> dict | None:
    """Read a Series provider override; empty or unreadable values mean none."""
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else None
        except ValueError:
            return None
    if not isinstance(value, dict):
        return None
    override = {}
    for key in ("order", "exclude"):
        names = value.get(key) or []
        if not isinstance(names, list):
            names = []
        override[key] = list(dict.fromkeys(str(name).strip() for name in names if str(name).strip()))
    if not override["order"] and not override["exclude"]:
        return None
    return override


def _with_override(plan, override):
    override = parse_provider_override(override)
    if override is None:
        return plan
    excluded = {name.casefold() for name in override["exclude"]}
    preferred = [name.casefold() for name in override["order"]]
    kept = [candidate for candidate in plan if candidate.name.casefold() not in excluded]

    def position(candidate):
        name = candidate.name.casefold()
        return preferred.index(name) if name in preferred else len(preferred)

    return sorted(kept, key=position)


def effective_provider_plan(
    config,
    *,
    is_blocked: Callable[[str], bool] | None = None,
    override: dict | str | None = None,
):
    """Return enabled providers in effective order without exposing secrets.

    A Series ``override`` moves its ``order`` names to the front and drops its
    ``exclude`` names; it can only reorder or remove enabled providers.
    """
    is_blocked = is_blocked or (lambda _name: False)
    candidates = []

    def add(name, kind, execution_name=None, entry=None):
        candidates.append(
            ProviderCandidate(
                name=name,
                kind=kind,
                execution_name=execution_name or name,
                entry=entry,
                blocked=bool(is_blocked(name)),
            )
        )

    if getattr(config, "ENABLE_DDL", False):
        if getattr(config, "ENABLE_GETCOMICS", False):
            add("DDL(GetComics)", "ddl")
        if getattr(config, "ENABLE_EXTERNAL_SERVER", False):
            add("DDL(External)", "ddl")
    # EXPERIMENTAL (NZBIndex) is retired: its search code is gone, so the
    # saved flag schedules nothing. Activity > Health shows the notice
    # ("removed-experimental-search" in app/system/deprecations.py).
    if getattr(config, "NEWZNAB", False):
        for index, entry in enumerate(enabled_provider_entries(getattr(config, "EXTRA_NEWZNABS", None)), start=1):
            name = str(entry[0]).strip() or "Newznab %s" % index
            add(name, "newznab", "newznab: %s" % name, entry)
    if prowlarr.usenet_enabled(config):
        name = prowlarr.PROWLARR_USENET_NAME
        add(name, "newznab", "newznab: %s" % name, prowlarr.usenet_provider_entry(config))
    if getattr(config, "ENABLE_TORRENT_SEARCH", False):
        if getattr(config, "ENABLE_32P", False):
            add("32p", "torrent")
        if getattr(config, "ENABLE_PUBLIC", False):
            add("public torrents", "torrent")
        if getattr(config, "ENABLE_TORZNAB", False):
            for index, entry in enumerate(enabled_provider_entries(getattr(config, "EXTRA_TORZNABS", None)), start=1):
                name = str(entry[0]).strip() or "Torznab %s" % index
                add(name, "torznab", "torznab: %s" % name, entry)
        if prowlarr.configured(config):
            name = prowlarr.PROWLARR_NAME
            add(name, "torznab", "torznab: %s" % name, prowlarr.provider_entry(config))
    return _with_override(_ordered(config, candidates), override)


def runtime_provider_entry(candidate: ProviderCandidate) -> tuple | None:
    """Return a legacy provider tuple with a safe identity for unnamed entries."""
    if candidate.entry is None:
        return None
    entry = list(candidate.entry)
    if not str(entry[0]).strip():
        entry[0] = candidate.name
    return tuple(entry)
