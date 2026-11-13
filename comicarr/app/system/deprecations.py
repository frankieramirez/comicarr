#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The deprecation registry (ADR-0006).

One entry per deprecated feature. An operator hears about an entry only when
its ``in_use()`` says this install relies on it: one warning in the log at
startup, and a row in Activity > Health through ``GET /api/system/deprecations``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from comicarr import logger


@dataclass(frozen=True)
class Deprecation:
    id: str
    name: str
    announced_in: str
    removable_from: str
    replacement: str
    docs_url: str
    in_use: Callable[[], bool]

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "announced_in": self.announced_in,
            "removable_from": self.removable_from,
            "replacement": self.replacement,
            "docs_url": self.docs_url,
        }


REGISTRY: list[Deprecation] = []


def deprecations_in_use() -> list[Deprecation]:
    """Entries this install relies on. A predicate that raises counts as not in use."""
    found = []
    for entry in REGISTRY:
        try:
            if entry.in_use():
                found.append(entry)
        except Exception as e:
            logger.error("[DEPRECATION] Could not tell whether %s is in use: %s" % (entry.id, e))
    return found


def warn_deprecations_in_use() -> None:
    """Log one warning per entry in use. Called once at startup."""
    for entry in deprecations_in_use():
        logger.warn(
            "[DEPRECATION] %s is deprecated since %s and may be removed from %s. Use instead: %s. See %s"
            % (entry.name, entry.announced_in, entry.removable_from, entry.replacement, entry.docs_url)
        )
