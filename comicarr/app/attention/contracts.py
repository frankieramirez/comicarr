#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Dependency-neutral contracts for the Needs attention module."""

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

AttentionAction = Literal["retry", "search_again", "import", "stop_wanting"]

BATCH_CAP = 25

PREVIEW_CAP = 5


@dataclass(frozen=True, slots=True)
class Scope:
    """Optional library scope applied before attention rows are grouped."""

    type: str
    id: str


@dataclass(frozen=True, slots=True)
class AttentionMember:
    """One durable obligation inside an Attention group."""

    release_key: str
    issue_label: str
    issue_id: str | None
    stage: str
    available_actions: tuple[AttentionAction, ...]
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class AttentionGroup:
    """One operator problem grouped by series identity and base reason."""

    group_key: str
    comic_id: str | None
    series_label: str
    base_reason: str | None
    reason_phrase: str
    member_count: int
    newest_updated_at: str | None
    oldest_updated_at: str | None
    stage: str
    available_actions: tuple[AttentionAction, ...]
    members: tuple[AttentionMember, ...]


@dataclass(frozen=True, slots=True)
class AttentionView:
    """One consistent, immutable view of actionable obligations."""

    groups: tuple[AttentionGroup, ...]
    total: int
    member_total: int


@dataclass(frozen=True, slots=True)
class ImportSource:
    """Optional source override for one manually imported obligation."""

    nzb_name: str | None = None
    nzb_folder: str | None = None


@dataclass(frozen=True, slots=True)
class ResolutionRequest:
    """One operator command applied to one or many obligations."""

    action: AttentionAction | str
    release_keys: Sequence[str]
    actor: str
    import_source: ImportSource | None = None


ResolutionProblem = Literal[
    "row_not_found",
    "not_in_attention",
    "already_resolved",
    "action_not_allowed",
    "missing_issue",
    "search_blocked",
    "search_failed",
    "missing_import_source",
    "invalid_import_source",
    "import_failed",
]

PROBLEM_STATUS: Mapping[ResolutionProblem, int] = {
    "row_not_found": 404,
    "not_in_attention": 409,
    "already_resolved": 409,
    "action_not_allowed": 409,
    "missing_issue": 400,
    "search_blocked": 409,
    "search_failed": 500,
    "missing_import_source": 400,
    "invalid_import_source": 400,
    "import_failed": 500,
}


@dataclass(frozen=True, slots=True)
class ResolutionItem:
    """Observable outcome for one requested release key."""

    release_key: str
    ok: bool
    status: str | None
    problem: ResolutionProblem | None = None
    message: str | None = None
    issue_id: str | None = None
    run_id: str | None = None
    stamp_written: bool | None = None


@dataclass(frozen=True, slots=True)
class ResolutionReport:
    """Best-effort summary for a normalized, capped command."""

    action: AttentionAction
    requested: int
    processed: int
    succeeded: int
    failed: int
    capped: bool
    skipped_for_cap: int
    cap: int
    results: tuple[ResolutionItem, ...] = field(default_factory=tuple)

    @property
    def success(self):
        return self.succeeded > 0

    @property
    def partial(self):
        return self.succeeded > 0 and self.failed > 0


class InvalidAttentionRequest(ValueError):
    """Raised when a caller supplies a structurally invalid command."""


@dataclass(frozen=True, slots=True)
class _TroubleEntry:
    """Shared durable identity carried by typed terminal entries."""

    release_key: str
    reason: str
    payload: Mapping[str, Any] | str | None = None
    issue_id: str | None = None
    provider: str | None = None
    downloader_type: str | None = None
    nzb_name: str | None = None
    release_id: str | None = None
    download_hash: str | None = None
    comic_id: str | None = None
    comic_name: str | None = None
    issue_number: str | None = None


@dataclass(frozen=True, slots=True)
class Failure(_TroubleEntry):
    """Terminal failure and its reconciliation identity."""

    resolved_as: Literal["retried"] | None = None


@dataclass(frozen=True, slots=True)
class ManualReview(_TroubleEntry):
    """Terminal uncertainty that requires an operator decision."""


@dataclass(frozen=True, slots=True)
class RecordOutcome:
    """Observable result of recording and reconciling terminal trouble."""

    transition_won: bool
    base_reason: str | None
    actionable: bool
    reconciliation: str
