#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Compatibility imports for reason policy now owned by Attention."""

from comicarr.app.attention._policy import (
    KNOWN_BASE_TOKENS,
    NON_ACTIONABLE_COMPOSITE,
    NON_ACTIONABLE_FLAT,
    REASON_PHRASES,
    RECONCILIATION,
    UNMAPPED_REASON_PHRASE,
    actionable_reason_condition,
    base_reason,
    is_actionable,
    reason_phrase,
    reconciliation_for,
)

__all__ = [
    "KNOWN_BASE_TOKENS",
    "NON_ACTIONABLE_COMPOSITE",
    "NON_ACTIONABLE_FLAT",
    "REASON_PHRASES",
    "RECONCILIATION",
    "UNMAPPED_REASON_PHRASE",
    "actionable_reason_condition",
    "base_reason",
    "is_actionable",
    "reason_phrase",
    "reconciliation_for",
]
