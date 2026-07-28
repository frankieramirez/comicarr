#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The config key registry: one entry type, one definition per key.

Today `comicarr/config.py` holds `_CONFIG_DEFINITIONS`, and four more places
repeat slices of the same knowledge: `get_safe_config`'s `safe_keys` list and
`WRITABLE_CONFIG_KEYS` in `comicarr/app/system/service.py`, plus that module's
`SCHEDULER_JOB_INTERVALS` and `SCHEDULER_JOB_REQUIRED_CONFIG`. A key added in
one and forgotten in another is the failure mode. `ConfigKey` puts all of it on
one entry so the other four derive.

This module currently holds a deliberately awkward *sample* of the 411 keys --
the ones that would break a naive entry type. The bulk migration is separate.
"""

from __future__ import annotations

import copy
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

# The only types `Config.check_setting` and `Config.process_kwargs` coerce to.
COERCIBLE_TYPES = (str, int, bool)


@dataclass(frozen=True, slots=True)
class ConfigKey:
    """One config key, in every dimension the running system needs.

    `name` is the attribute name on the `Config` object and the uppercase key in
    `_CONFIG_DEFINITIONS`. Both the ini option and the name the frontend sees
    are `name.lower()` -- see `ini_key` / `wire_name`, and the module docstring
    of the sibling prototype for why those are derived rather than stored.

    `readable` and `writable` are independent and default-deny: 15 keys are
    write-only secrets and 10 are read-only, so a single "exposed" flag would
    leak the secrets onto the API.
    """

    name: str
    type: type
    section: str
    default: Any

    # Settings API exposure. Independent, default-deny.
    readable: bool = False
    writable: bool = False

    # Scheduler bindings. A key drives at most one job's cadence and gates at
    # most one job; `SCHEDULER_JOB_INTERVALS` and `SCHEDULER_JOB_REQUIRED_CONFIG`
    # are the inverses of these two fields.
    interval_for: str | None = None
    gates: str | None = None

    # `EXTRA_NEWZNABS` / `EXTRA_TORZNABS`. Declared `str`, but hold a list of
    # provider rows and take their own transaction path in `apply_transaction`
    # (`config.py:1628`) because provider and scalar writes cannot share one.
    provider_extra: bool = False

    # Free-form marker for the awkwardness a key carries, so the prototype can
    # show why this key is in the sample. Not load-bearing.
    note: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not self.name.isupper():
            raise ValueError("config key name must be uppercase: %r" % self.name)
        if self.type not in COERCIBLE_TYPES:
            raise ValueError("%s: type must be one of str/int/bool, got %r" % (self.name, self.type))
        if not self.section:
            raise ValueError("%s: section is required" % self.name)
        if self.provider_extra and self.type is not str:
            raise ValueError("%s: provider extras are declared str" % self.name)
        # `default` is deliberately NOT checked against `type`.
        # `IGNORE_SEARCH_WORDS` is declared `str` and defaults to `[]`, and
        # `check_setting` relies on that: the empty-list default is what makes
        # its `len(value) == 0` branch restore the list rather than a string.

    @property
    def ini_key(self) -> str:
        """The option name written into the ini file."""
        return self.name.lower()

    @property
    def wire_name(self) -> str:
        """The name the settings API and the frontend see."""
        return self.name.lower()

    @property
    def as_definition(self) -> tuple[type, str, Any]:
        """This key as a legacy `_CONFIG_DEFINITIONS` value.

        The default is copied. `frozen=True` stops the field being rebound but
        not a list default being mutated in place, and `check_setting` hands
        `v[2]` straight to `setattr`, so without this every `Config` built in
        the process would share one `IGNORE_SEARCH_WORDS` list -- and an
        `.append` anywhere would edit the registry's own default.
        """
        return (self.type, self.section, copy.copy(self.default))


# ---------------------------------------------------------------------------
# The awkward sample. Every entry here is a key that would break a naive shape.
# ---------------------------------------------------------------------------

_KEYS: tuple[ConfigKey, ...] = (
    # -- the easy baseline, for contrast -------------------------------------
    ConfigKey("ANNUALS_ON", bool, "General", False, readable=True, writable=True),
    # -- read-only: on the API, never settable -------------------------------
    ConfigKey("AUTHENTICATION", int, "Interface", 2, readable=True, note="read-only"),
    ConfigKey("CACHE_DIR", str, "General", None, readable=True, note="read-only, None default"),
    # -- write-only secrets: settable, never read back -----------------------
    ConfigKey("EMAIL_PASSWORD", str, "Email", "", writable=True, note="write-only secret"),
    ConfigKey("COMICVINE_API", str, "CV", None, writable=True, note="write-only secret, None default"),
    # -- neither: internal bookkeeping, special-cased in check_setting -------
    ConfigKey("CONFIG_VERSION", int, "General", 15, note="check_setting skips the normal coercion path"),
    # -- default does not match the declared type ----------------------------
    ConfigKey(
        "IGNORE_SEARCH_WORDS",
        str,
        "General",
        [],
        note="declared str, defaults to []; on neither allowlist — the ignore_search_words[] "
        "special case in process_kwargs is a legacy CherryPy form leftover",
    ),
    # -- the four legacy ini renames -----------------------------------------
    # These read from an OLD option name exactly once, then delete it; the live
    # ini key is `name.lower()` like every other key. That one-shot drain stays
    # in `_BAD_DEFINITIONS` -- it is migration, not definition.
    ConfigKey("ENABLE_PUBLIC", bool, "Torrents", False, note="legacy ini key enable_tpse, drained by _BAD_DEFINITIONS"),
    ConfigKey("PUBLIC_VERIFY", bool, "Torrents", True, note="legacy ini key tpse_verify"),
    ConfigKey("IGNORED_PUBLISHERS", str, "CV", "", note="legacy ini key blacklisted_publishers"),
    ConfigKey("SAB_DIRECT_UNPACK", bool, "SABnzbd", False, note="legacy ini key sab_to_mylar"),
    # -- scheduler-bound: drives a job's cadence -----------------------------
    ConfigKey(
        "RSS_CHECKINTERVAL",
        int,
        "Scheduler",
        20,
        readable=True,
        writable=True,
        interval_for="rss",
        note="also floored at 20 by SCHEDULER_INTERVAL_MINIMUMS",
    ),
    ConfigKey(
        "IMPORT_SCAN_INTERVAL",
        int,
        "Scheduler",
        30,
        readable=True,
        interval_for="importinbox",
        note="read-only despite driving a job",
    ),
    # -- scheduler-bound: gates a job ----------------------------------------
    ConfigKey(
        "CHECK_FOLDER",
        str,
        "PostProcess",
        None,
        readable=True,
        writable=True,
        gates="monitor",
        note="falsy value keeps the monitor job paused",
    ),
    ConfigKey("IMPORT_DIR", str, "Import", None, readable=True, gates="importinbox", note="read-only gate"),
    # -- provider extras: own transaction path -------------------------------
    ConfigKey("EXTRA_NEWZNABS", str, "Newznab", "", provider_extra=True),
    ConfigKey("EXTRA_TORZNABS", str, "Torznab", "", provider_extra=True),
)


def _build(keys: tuple[ConfigKey, ...]) -> OrderedDict[str, ConfigKey]:
    """Index the keys, refusing any collision.

    Building the dict straight from a comprehension would let a duplicate name
    silently drop a definition, and a duplicate `interval_for` / `gates` would
    silently rebind a scheduler job to whichever entry happened to come last.
    The bulk migration emits these 411 entries from a script, so a typo there
    has to fail at import rather than quietly lose a key.
    """
    registry: OrderedDict[str, ConfigKey] = OrderedDict()
    bindings: dict[str, dict[str, str]] = {"interval_for": {}, "gates": {}}

    for key in keys:
        if key.name in registry:
            raise ValueError("duplicate config key: %s" % key.name)
        registry[key.name] = key

        for attr, claimed in bindings.items():
            job = getattr(key, attr)
            if job is None:
                continue
            if job in claimed:
                raise ValueError("%s job %r claimed by both %s and %s" % (attr, job, claimed[job], key.name))
            claimed[job] = key.name

    return registry


REGISTRY: OrderedDict[str, ConfigKey] = _build(_KEYS)


# ---------------------------------------------------------------------------
# Derived views. Each replaces a hand-maintained literal elsewhere.
# ---------------------------------------------------------------------------


def as_legacy_definitions() -> OrderedDict[str, tuple[type, str, Any]]:
    """`_CONFIG_DEFINITIONS` rebuilt from the registry.

    `Config.check_setting`, `Config._define` and `comicarr/migration.py:426`
    index these tuples positionally, so the shape is fixed at 3 elements.
    """
    return OrderedDict((k.name, k.as_definition) for k in REGISTRY.values())


def readable_keys() -> set[str]:
    """Replaces the `safe_keys` literal in `get_safe_config`."""
    return {k.name for k in REGISTRY.values() if k.readable}


def writable_keys() -> set[str]:
    """Replaces the `WRITABLE_CONFIG_KEYS` literal."""
    return {k.name for k in REGISTRY.values() if k.writable}


def scheduler_job_intervals() -> dict[str, str]:
    """Replaces `SCHEDULER_JOB_INTERVALS` — job id to the key driving its cadence."""
    return {k.interval_for: k.name for k in REGISTRY.values() if k.interval_for}


def scheduler_job_required_config() -> dict[str, str]:
    """Replaces `SCHEDULER_JOB_REQUIRED_CONFIG` — job id to the key gating it."""
    return {k.gates: k.name for k in REGISTRY.values() if k.gates}


def provider_extra_fields() -> tuple[str, ...]:
    """Replaces `_PROVIDER_EXTRA_FIELDS`."""
    return tuple(k.name for k in REGISTRY.values() if k.provider_extra)
