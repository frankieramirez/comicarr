#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Where the log level comes from: startup args, then the environment, then config.

`docs/architecture/logging-levels.md` fixes what each level *means*; this module
fixes where the number is *read from*. Three sources, highest first:

1. a startup argument (`--log-level`, or its `--verbose`/`--quiet` aliases)
2. the `COMICARR_LOG_LEVEL` environment variable
3. `LOG_LEVEL` in the config file (the Settings UI writes this one)

Each of them accepts the level in either notation -- `0`/`1`/`2` or
`warning`/`info`/`debug` -- and the integer is what gets stored, whichever form
was typed.

A source only counts when it *explicitly supplies* a value. That qualifier is
the whole point: Docker used to pass `--quiet` on every start, which pinned the
escape hatch permanently open and left an operator with no way to raise
verbosity (#610). An argument that was not passed must leave the layer below it
alone.

`COMICARR_LOG_LEVEL` is a deliberate one-off for this key, not the first step of
a general `COMICARR_<KEY>` override mechanism -- that raises precedence,
secrets, and UI-honesty questions of its own and is out of scope here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

ENV_VAR = "COMICARR_LOG_LEVEL"

MIN_LEVEL = 0
MAX_LEVEL = 2
DEFAULT_LEVEL = 1

LEVEL_NAMES = {"warning": 0, "info": 1, "debug": 2}
NAME_FOR_LEVEL = {level: name for name, level in LEVEL_NAMES.items()}

ACCEPTED_FORMS = "%s-%s or one of %s" % (MIN_LEVEL, MAX_LEVEL, ", ".join(LEVEL_NAMES))

SOURCE_ARGUMENT = "startup argument"
SOURCE_ENVIRONMENT = f"the {ENV_VAR} environment variable"
SOURCE_CONFIG = "the config file"
SOURCE_DEFAULT = "the built-in default"
SOURCE_SETTINGS = "the Settings page"


@dataclass
class LogLevelResolution:
    """The level to start with, where it came from, and what to tell the operator."""

    level: int
    source: str
    notices: list[str] = field(default_factory=list)


@dataclass
class EffectiveLogLevel:
    """What the process is logging at now, and what a restart would make of it.

    The Settings dial writes `config.ini`, the *bottom* of the chain, and the
    write applies live. So three numbers can disagree at once: the level running
    right now, the level saved in the config file, and the level the next start
    resolves to. `pinned` is the one an operator needs -- when it is true, a
    source the UI cannot edit wins the chain, and the dial's value will not
    survive a restart. That is the #610 failure said out loud instead of
    discovered later.
    """

    level: int
    saved: int
    restart_level: int
    restart_source: str

    @property
    def pinned(self) -> bool:
        """True when something above the config file decides the level."""
        return self.restart_source in (SOURCE_ARGUMENT, SOURCE_ENVIRONMENT)


def clamp_level(level: int) -> int:
    """Hold a level inside the dial's range, matching `threshold_for_level`."""
    return max(MIN_LEVEL, min(MAX_LEVEL, level))


def describe_level(level: int) -> str:
    """Render a level the way every operator-facing surface says it: `2 (debug)`.

    The number is what an operator's `config.ini` and compose file contain; the
    name is what `--help` and the Settings dial show them. Saying both keeps the
    two notations from drifting apart in anyone's head.
    """
    return "%s (%s)" % (level, NAME_FOR_LEVEL[clamp_level(level)])


def parse_level(raw, origin: str) -> tuple[int | None, list[str]]:
    """Read one source's value into a usable level.

    Both notations are accepted from every source -- `2` and `debug` are the same
    instruction, so an operator who reads `Debug` on the Settings dial can type
    `--log-level debug` and have it work. Names are matched case-insensitively
    and never need clamping; a number does.

    Returns `(None, notices)` when the source supplied nothing usable, so the
    caller falls through to the next layer rather than starting at a level
    nobody asked for. Out-of-range numbers are clamped rather than rejected: a
    compose file asking for `3` wants maximum verbosity, and refusing to boot
    over it helps nobody.
    """
    notices: list[str] = []
    if raw is None:
        return None, notices
    if isinstance(raw, bool):
        return None, [f"Ignoring {origin}: {raw!r} is not a log level."]
    if isinstance(raw, int):
        parsed = raw
    else:
        text = str(raw).strip()
        if not text:
            return None, notices
        named = LEVEL_NAMES.get(text.casefold())
        if named is not None:
            return named, notices
        try:
            parsed = int(text)
        except ValueError:
            return None, [f"Ignoring {origin}: {text!r} is not a log level. Expected {ACCEPTED_FORMS}."]
    clamped = clamp_level(parsed)
    if clamped != parsed:
        notices.append(f"Log level {parsed} from {origin} is out of range; using {describe_level(clamped)}.")
    return clamped, notices


_startup_argument: int | None = None


def record_startup_argument(level) -> None:
    """Remember the level a startup argument supplied, if one did."""
    global _startup_argument
    _startup_argument = level


def startup_argument() -> int | None:
    """The level the startup argument supplied, or None when none was passed."""
    return _startup_argument


def resolve_startup_log_level(
    argument_level=None,
    config_level=None,
    environ: Mapping[str, str] | None = None,
) -> LogLevelResolution:
    """Pick the level to start with from the three sources, highest priority first."""
    environ = os.environ if environ is None else environ
    notices: list[str] = []

    candidates = (
        (argument_level, SOURCE_ARGUMENT),
        (environ.get(ENV_VAR), SOURCE_ENVIRONMENT),
        (config_level, SOURCE_CONFIG),
    )

    supplied: list[tuple[int, str]] = []
    for raw, source in candidates:
        level, source_notices = parse_level(raw, source)
        notices.extend(source_notices)
        if level is not None:
            supplied.append((level, source))

    if not supplied:
        return LogLevelResolution(level=DEFAULT_LEVEL, source=SOURCE_DEFAULT, notices=notices)

    level, source = supplied[0]
    overridden = [
        f"{describe_level(other_level)} from {other_source}"
        for other_level, other_source in supplied[1:]
        if other_level != level
    ]
    if overridden:
        notices.append(f"Log level {describe_level(level)} from {source} overrides {', '.join(overridden)}.")
    return LogLevelResolution(level=level, source=source, notices=notices)


def resolve_effective_log_level(
    running_level,
    config_level=None,
    environ: Mapping[str, str] | None = None,
) -> EffectiveLogLevel:
    """Report the running level next to the one a restart would resolve to.

    The restart half is the startup chain run again, now: the argument is the
    recorded one, the environment and the config file are read fresh. Re-running
    it rather than replaying the boot resolution is what keeps the answer true
    after the operator saves a new level -- the chain's bottom rung has moved.
    """
    restart = resolve_startup_log_level(
        argument_level=startup_argument(),
        config_level=config_level,
        environ=environ,
    )
    saved, _ = parse_level(config_level, SOURCE_CONFIG)
    return EffectiveLogLevel(
        level=clamp_level(int(running_level or 0)),
        saved=DEFAULT_LEVEL if saved is None else saved,
        restart_level=restart.level,
        restart_source=restart.source,
    )
