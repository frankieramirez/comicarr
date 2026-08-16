#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Pure intent, fulfillment, and release eligibility policy."""

import datetime
from dataclasses import dataclass

from comicarr.app.acquisition.models import AcquisitionIntent, Fulfillment, StateProjection

_LEGACY_FULFILLMENT = {
    "wanted": Fulfillment.MISSING,
    "skipped": Fulfillment.MISSING,
    "ignored": Fulfillment.MISSING,
    "reserved": Fulfillment.RESERVED,
    "snatched": Fulfillment.SNATCHED,
    "downloaded": Fulfillment.DOWNLOADED,
    "archived": Fulfillment.ARCHIVED,
    "failed": Fulfillment.FAILED,
}

_LEGACY_EXPLICIT_STATUS = {
    AcquisitionIntent.WANTED: "Wanted",
    AcquisitionIntent.SKIPPED: "Skipped",
    AcquisitionIntent.IGNORED: "Ignored",
}


@dataclass(frozen=True)
class EligibilityInput:
    series_active: bool
    intent: AcquisitionIntent
    fulfillment: Fulfillment
    release_date: str | datetime.date | None = None
    digital_date: str | datetime.date | None = None
    issue_date: str | datetime.date | None = None
    paused: bool = False


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reason: str
    selected_date: datetime.date | None = None
    date_source: str | None = None


def _enum_value(enum_type, value, default):
    if isinstance(value, enum_type):
        return value
    if value is None:
        return default
    try:
        return enum_type(str(value).strip().lower())
    except ValueError:
        return default


def project_legacy_state(acquisition_intent, legacy_status):
    """Dual-read old rows without inventing evidence of explicit user intent.

    ``Status`` remains useful operational compatibility data, but historical
    rows do not say whether a user or a policy wrote it. Only the additive
    ``AcquisitionIntent`` column is treated as auditable explicit intent.
    """

    intent = _enum_value(AcquisitionIntent, acquisition_intent, AcquisitionIntent.POLICY)
    explicit = intent in {
        AcquisitionIntent.WANTED,
        AcquisitionIntent.SKIPPED,
        AcquisitionIntent.IGNORED,
    }
    normalized_status = str(legacy_status).strip().lower() if legacy_status is not None else ""
    fulfillment = _LEGACY_FULFILLMENT.get(normalized_status, Fulfillment.UNKNOWN)
    return StateProjection(intent=intent, fulfillment=fulfillment, intent_is_explicit=explicit)


def explicit_intent_values(intent, audit_identity):
    """Return the dual-write fields for a future audited user action.

    The audit record itself belongs to the calling domain. Requiring its
    identity here makes it hard for a new action to silently manufacture
    explicit intent from legacy state.
    """

    intent = _enum_value(AcquisitionIntent, intent, AcquisitionIntent.POLICY)
    if not audit_identity or not str(audit_identity).strip():
        raise ValueError("explicit intent changes require an audit identity")
    if intent is AcquisitionIntent.POLICY:
        raise ValueError("policy intent is derived and cannot be set by an explicit action")
    return {
        "AcquisitionIntent": intent.value,
        "Status": _LEGACY_EXPLICIT_STATUS[intent],
    }


def _parse_date(value):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if value is None or not str(value).strip():
        return None
    try:
        return datetime.date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        return None


def _select_date(item):
    supplied = False
    for source in ("release_date", "digital_date", "issue_date"):
        raw = getattr(item, source)
        supplied = supplied or (raw is not None and str(raw).strip() != "")
        parsed = _parse_date(raw)
        if parsed is not None:
            return parsed, source, supplied
    return None, None, supplied


def evaluate_eligibility(item, today=None):
    """Apply the shared released/missing acquisition policy."""

    today = today or datetime.date.today()
    if not item.series_active:
        return EligibilityDecision(False, "series_inactive")
    if item.paused:
        return EligibilityDecision(False, "paused")
    if item.fulfillment.is_owned:
        return EligibilityDecision(False, "owned")
    if getattr(item.fulfillment, "is_covered", False):
        return EligibilityDecision(False, "covered")
    if item.fulfillment.is_in_flight:
        return EligibilityDecision(False, "in_flight")
    if item.intent is AcquisitionIntent.SKIPPED:
        return EligibilityDecision(False, "intent_skipped")
    if item.intent is AcquisitionIntent.IGNORED:
        return EligibilityDecision(False, "intent_ignored")

    selected_date, source, supplied = _select_date(item)
    if selected_date is None:
        return EligibilityDecision(False, "invalid_date" if supplied else "missing_date")
    if selected_date > today:
        return EligibilityDecision(False, "future", selected_date, source)
    return EligibilityDecision(True, "released", selected_date, source)
