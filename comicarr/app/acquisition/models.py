#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Dependency-neutral value vocabulary for Comicarr acquisition."""

from dataclasses import dataclass
from enum import Enum


class AcquisitionIntent(str, Enum):
    """Why Comicarr may acquire an issue, independent of file ownership."""

    POLICY = "policy"
    WANTED = "wanted"
    SKIPPED = "skipped"
    IGNORED = "ignored"


class Fulfillment(str, Enum):
    """Evidence-backed operational state, independent of acquisition intent."""

    UNKNOWN = "unknown"
    MISSING = "missing"
    RESERVED = "reserved"
    SNATCHED = "snatched"
    DOWNLOADED = "downloaded"
    ARCHIVED = "archived"
    FAILED = "failed"
    COVERED = "covered"

    @property
    def is_owned(self):
        return self in {self.DOWNLOADED, self.ARCHIVED}

    @property
    def is_covered(self):
        return self is self.COVERED

    @property
    def is_in_flight(self):
        return self in {self.RESERVED, self.SNATCHED}


class DispatchState(str, Enum):
    """Scheduler/command dispatch state; never implies work completion."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    ERROR = "error"
    MISSED = "missed"
    MAX_INSTANCES = "max_instances"


class ItemOutcome(str, Enum):
    """Durable lifecycle state for one accepted acquisition obligation."""

    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    NO_MATCH = "no_match"
    BLOCKED = "blocked"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    CANCELLED = "cancelled"

    @property
    def terminal(self):
        return self not in {self.ACCEPTED, self.RUNNING}


class RunState(str, Enum):
    """Completion projection derived only from accepted item outcomes."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class StateProjection:
    intent: AcquisitionIntent
    fulfillment: Fulfillment
    intent_is_explicit: bool


@dataclass(frozen=True)
class RouteReadiness:
    """Transport-neutral readiness result consumed by later route adapters."""

    ready: bool
    route: str | None
    reason: str
