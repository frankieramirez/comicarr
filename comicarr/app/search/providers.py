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

from dataclasses import dataclass, field
from typing import Callable, Iterable

from comicarr.app.search.provider_config import provider_enabled


@dataclass(frozen=True)
class ProviderCandidate:
    name: str
    kind: str
    execution_name: str
    entry: tuple | None = field(default=None, repr=False)
    blocked: bool = False

    @property
    def route(self) -> str:
        if self.kind in {"torznab", "torrent"}:
            return "torrent"
        if self.kind in {"newznab", "experimental"}:
            return "nzb"
        return "ddl"


def enabled_provider_entries(entries: Iterable[object]):
    for entry in entries or []:
        try:
            if provider_enabled(entry):
                yield tuple(entry)
        except TypeError:
            continue


def ordered_provider_names(config) -> list[str]:
    configured = getattr(config, "PROVIDER_ORDER", None) or {}
    if isinstance(configured, dict):
        return [str(value) for _, value in sorted(configured.items(), key=lambda item: str(item[0]))]
    return [str(value) for value in configured]


def _ordered(config, candidates):
    preferred = [name.casefold() for name in ordered_provider_names(config)]

    def position(candidate):
        names = {candidate.name.casefold(), candidate.execution_name.casefold()}
        for index, value in enumerate(preferred):
            if any(value == name or value in name for name in names):
                return index
        return len(preferred)

    return sorted(candidates, key=lambda candidate: (position(candidate), candidate.name.casefold()))


def effective_provider_plan(config, *, is_blocked: Callable[[str], bool] | None = None):
    """Return enabled providers in effective order without exposing secrets."""
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
    if getattr(config, "EXPERIMENTAL", False):
        add("experimental", "experimental")
    if getattr(config, "NEWZNAB", False):
        for index, entry in enumerate(enabled_provider_entries(getattr(config, "EXTRA_NEWZNABS", None)), start=1):
            name = str(entry[0]).strip() or "Newznab %s" % index
            add(name, "newznab", "newznab: %s" % name, entry)
    if getattr(config, "ENABLE_TORRENT_SEARCH", False):
        if getattr(config, "ENABLE_32P", False):
            add("32p", "torrent")
        if getattr(config, "ENABLE_PUBLIC", False):
            add("public torrents", "torrent")
        if getattr(config, "ENABLE_TORZNAB", False):
            for index, entry in enumerate(enabled_provider_entries(getattr(config, "EXTRA_TORZNABS", None)), start=1):
                name = str(entry[0]).strip() or "Torznab %s" % index
                add(name, "torznab", "torznab: %s" % name, entry)
    return _ordered(config, candidates)


def runtime_provider_entry(candidate: ProviderCandidate) -> tuple | None:
    """Return a legacy provider tuple with a safe identity for unnamed entries."""
    if candidate.entry is None:
        return None
    entry = list(candidate.entry)
    if not str(entry[0]).strip():
        entry[0] = candidate.name
    return tuple(entry)
