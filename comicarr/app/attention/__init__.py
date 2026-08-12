#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Public interface for the Needs attention module."""

from comicarr.app.attention._read import read
from comicarr.app.attention._recording import record
from comicarr.app.attention._resolution import resolve
from comicarr.app.attention.contracts import (
    BATCH_CAP,
    PREVIEW_CAP,
    PROBLEM_STATUS,
    AttentionGroup,
    AttentionMember,
    AttentionView,
    Failure,
    ImportSource,
    InvalidAttentionRequest,
    ManualReview,
    RecordOutcome,
    ResolutionItem,
    ResolutionReport,
    ResolutionRequest,
    Scope,
)

__all__ = [
    "BATCH_CAP",
    "PREVIEW_CAP",
    "PROBLEM_STATUS",
    "AttentionView",
    "AttentionGroup",
    "AttentionMember",
    "Failure",
    "ImportSource",
    "InvalidAttentionRequest",
    "ManualReview",
    "RecordOutcome",
    "ResolutionItem",
    "ResolutionReport",
    "ResolutionRequest",
    "Scope",
    "read",
    "record",
    "resolve",
]
