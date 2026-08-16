#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Pure acquisition intent, fulfillment, and release-date policy tests."""

import datetime

import pytest

from comicarr.app.acquisition.models import AcquisitionIntent, Fulfillment
from comicarr.app.acquisition.policy import (
    EligibilityInput,
    evaluate_eligibility,
    explicit_intent_values,
    project_legacy_state,
)


@pytest.mark.parametrize(
    ("legacy_status", "fulfillment"),
    [
        (None, Fulfillment.UNKNOWN),
        ("Wanted", Fulfillment.MISSING),
        ("Skipped", Fulfillment.MISSING),
        ("Ignored", Fulfillment.MISSING),
        ("Snatched", Fulfillment.SNATCHED),
        ("Downloaded", Fulfillment.DOWNLOADED),
        ("Archived", Fulfillment.ARCHIVED),
        ("Failed", Fulfillment.FAILED),
    ],
)
def test_legacy_status_projects_fulfillment_but_never_explicit_intent(legacy_status, fulfillment):
    projection = project_legacy_state(None, legacy_status)

    assert projection.intent is AcquisitionIntent.POLICY
    assert projection.fulfillment is fulfillment
    assert projection.intent_is_explicit is False


def test_explicit_intent_survives_owned_fulfillment():
    projection = project_legacy_state("skipped", "Downloaded")

    assert projection.intent is AcquisitionIntent.SKIPPED
    assert projection.fulfillment is Fulfillment.DOWNLOADED
    assert projection.intent_is_explicit is True


@pytest.mark.parametrize("raw_intent", [None, "", "policy", "legacy-garbage"])
def test_only_auditable_action_values_are_explicit_intent(raw_intent):
    projection = project_legacy_state(raw_intent, "Wanted")

    assert projection.intent is AcquisitionIntent.POLICY
    assert projection.intent_is_explicit is False


def test_explicit_intent_write_requires_audit_identity_and_dual_writes_legacy_status():
    with pytest.raises(ValueError, match="audit"):
        explicit_intent_values(AcquisitionIntent.WANTED, audit_identity="")

    assert explicit_intent_values(AcquisitionIntent.IGNORED, audit_identity="owner:42") == {
        "AcquisitionIntent": "ignored",
        "Status": "Ignored",
    }


def test_release_date_precedence_and_eligibility_are_deterministic():
    decision = evaluate_eligibility(
        EligibilityInput(
            series_active=True,
            intent=AcquisitionIntent.WANTED,
            fulfillment=Fulfillment.MISSING,
            release_date="2026-07-09",
            digital_date="2026-07-08",
            issue_date="2026-07-01",
        ),
        today=datetime.date(2026, 7, 10),
    )

    assert decision.eligible is True
    assert decision.date_source == "release_date"
    assert decision.selected_date == datetime.date(2026, 7, 9)
    assert decision.reason == "released"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"release_date": "2026-07-11"}, "future"),
        (
            {"release_date": "not-a-date", "digital_date": "also-bad", "issue_date": "still-bad"},
            "invalid_date",
        ),
        ({"series_active": False}, "series_inactive"),
        ({"intent": AcquisitionIntent.SKIPPED}, "intent_skipped"),
        ({"fulfillment": Fulfillment.SNATCHED}, "in_flight"),
        ({"fulfillment": Fulfillment.DOWNLOADED}, "owned"),
        ({"fulfillment": Fulfillment.COVERED}, "covered"),
    ],
)
def test_policy_defers_non_actionable_work(changes, reason):
    values = {
        "series_active": True,
        "intent": AcquisitionIntent.WANTED,
        "fulfillment": Fulfillment.MISSING,
        "issue_date": "2026-07-01",
    }
    values.update(changes)

    decision = evaluate_eligibility(EligibilityInput(**values), today=datetime.date(2026, 7, 10))

    assert decision.eligible is False
    assert decision.reason == reason
