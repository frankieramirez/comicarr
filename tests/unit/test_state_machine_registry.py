#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The state machine registry agrees with the code that enforces each machine.

``comicarr/app/common/state_machines.py`` declares every cross-layer state
vocabulary once and the frontend unions are generated from it. The registry is
a stdlib-only leaf, so it cannot import the enums and constants that enforce
those vocabularies at runtime. These tests are the link: adding, removing or
renaming a state on either side alone fails here.

Fix a failure by changing the other side to match, then run
``npm run lint:fix:generated``. See ``docs/architecture/state-machines.md``.
"""

import importlib.util
import sys
from pathlib import Path
from typing import get_args

import pytest

from comicarr.app.acquisition import policy
from comicarr.app.acquisition.models import AcquisitionIntent, DispatchState, Fulfillment, ItemOutcome, RunState
from comicarr.app.activity import events
from comicarr.app.common import state_machines
from comicarr.app.common.state_machines import REGISTRY, StateMachine, StateSubset, machine
from comicarr.app.downloads import journal
from comicarr.app.mcp import contracts
from comicarr.app.series import service as series_service
from comicarr.app.shelf import service as shelf_service

ROOT = Path(__file__).resolve().parents[2]


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_state_types", ROOT / "scripts" / "generate_state_types.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _values(enum_type):
    return tuple(member.value for member in enum_type)


@pytest.mark.parametrize(
    ("name", "enum_type"),
    [
        ("acquisition_intent", AcquisitionIntent),
        ("fulfillment", Fulfillment),
        ("search_run_dispatch_state", DispatchState),
        ("search_run_completion_state", RunState),
        ("search_run_item_state", ItemOutcome),
    ],
)
def test_enum_backed_machines_match_their_enum(name, enum_type):
    assert machine(name).states == _values(enum_type)


def test_fulfillment_subsets_match_the_enum_properties():
    fulfillment = machine("fulfillment")
    assert set(fulfillment.subset("owned")) == {f.value for f in Fulfillment if f.is_owned}
    assert set(fulfillment.subset("in_flight")) == {f.value for f in Fulfillment if f.is_in_flight}


def test_item_state_subsets_match_the_terminal_property():
    item = machine("search_run_item_state")
    terminal = {outcome.value for outcome in ItemOutcome if outcome.terminal}
    assert set(item.subset("terminal")) == terminal
    assert set(item.subset("in_flight")) == set(item.states) - terminal


def test_item_state_transitions_never_leave_a_terminal_state():
    item = machine("search_run_item_state")
    for state in item.subset("terminal"):
        assert item.transitions[state] == ()
        assert item.allows(state, "accepted") is False
    # RunLedger: claim, requeue, and record_outcome from either live state.
    assert item.allows("accepted", "running") is True
    assert item.allows("running", "accepted") is True
    for state in item.subset("in_flight"):
        for outcome in item.subset("terminal"):
            assert item.allows(state, outcome) is True


def test_run_completion_subsets_partition_the_states():
    completion = machine("search_run_completion_state")
    assert set(completion.subset("in_progress")) == {RunState.PENDING.value, RunState.RUNNING.value}
    assert set(completion.subset("in_progress")) | set(completion.subset("terminal")) == set(completion.states)
    assert not set(completion.subset("in_progress")) & set(completion.subset("terminal"))


def test_issue_status_matches_the_legacy_projection():
    statuses = machine("issue_status")
    assert {status.lower() for status in statuses.states} == set(policy._LEGACY_FULFILLMENT)
    assert set(statuses.subset("operator_settable")) == set(series_service._SETTABLE_ISSUE_STATUSES.values())


def test_issue_display_state_matches_the_service_and_mcp():
    display = machine("issue_display_state")
    assert display.states == series_service.ISSUE_DISPLAY_STATES
    assert display.states == get_args(contracts.IssueState)
    projected = {
        *series_service._DISPLAY_BY_FULFILLMENT.values(),
        *series_service._DISPLAY_BY_INTENT.values(),
        "Missing",
        "Unknown",
    }
    assert projected == set(display.states)


def test_series_status_matches_the_mcp_contract():
    assert machine("series_status").states == get_args(contracts.SeriesStatus)


def test_journal_stage_matches_the_rank_table():
    stage = machine("journal_stage")
    by_rank = tuple(sorted(journal.STAGE_RANK, key=journal.STAGE_RANK.get))
    assert stage.states == by_rank
    assert stage.subset("open") == journal.OPEN_STAGES
    assert stage.subset("terminal") == journal.TERMINAL_STAGES
    assert stage.subset("band") == journal.BAND_STAGES


def test_journal_resolution_matches_the_resolved_statuses():
    assert machine("journal_resolution").states == journal.RESOLVED_STATUSES


def test_activity_event_status_matches_the_event_vocabulary():
    status = machine("activity_event_status")
    assert set(status.states) == events.STATUSES
    assert set(status.subset("action_required")) == events.ACTION_REQUIRED_STATUSES


def test_shelf_copy_state_matches_the_shelf_service():
    assert machine("shelf_copy_state").states == shelf_service.STATES


def test_every_registered_machine_is_documented():
    doc = (ROOT / "docs" / "architecture" / "state-machines.md").read_text(encoding="utf-8")
    missing = [name for name in REGISTRY if "`%s`" % name not in doc]
    assert not missing, "add to docs/architecture/state-machines.md section 4: %s" % ", ".join(missing)


def test_registry_is_a_stdlib_only_leaf():
    """The generator loads the module by path on a bare interpreter."""
    source = (ROOT / "comicarr" / "app" / "common" / "state_machines.py").read_text(encoding="utf-8")
    assert "import comicarr" not in source
    assert "from comicarr" not in source


def test_generated_frontend_types_are_fresh():
    generator = _load_generator()
    assert generator.OUTPUT.read_text(encoding="utf-8") == generator.render()


def test_generated_types_export_every_named_machine_and_subset():
    rendered = _load_generator().render()
    for entry in REGISTRY.values():
        for ts_type in (entry.ts_type, *(subset.ts_type for subset in entry.subsets)):
            if ts_type:
                assert "export type %s =" % ts_type in rendered


def test_short_vocabularies_render_on_one_line():
    """Prettier keeps an array that fits the print width on one line."""
    generator = _load_generator()
    lines = generator._render_export("PairState", ("on", "off"), "A pair.")
    assert lines == [
        "/** A pair. */",
        'export const PAIR_STATE_VALUES = ["on", "off"] as const;',
        "export type PairState = (typeof PAIR_STATE_VALUES)[number];",
    ]


def _machine(**overrides):
    values = {
        "name": "sample",
        "summary": "A sample.",
        "states": ("a", "b"),
        "stored_in": None,
        "owner": "tests",
        "enforced_by": "none",
    }
    values.update(overrides)
    return StateMachine(**values)


@pytest.mark.parametrize(
    "machines",
    [
        (_machine(), _machine()),
        (_machine(states=("a", "a")),),
        (_machine(subsets=(StateSubset("odd", ("c",), "Not a state."),)),),
        (_machine(transitions={"a": ("b",)}),),
        (_machine(transitions={"a": ("c",), "b": ()}),),
        (_machine(ts_type="Same"), _machine(name="other", ts_type="Same")),
    ],
    ids=[
        "duplicate name",
        "repeated state",
        "subset outside the machine",
        "transition table missing a state",
        "transition to an unknown state",
        "duplicate TypeScript type",
    ],
)
def test_registry_rejects_a_malformed_entry(machines):
    with pytest.raises(ValueError):
        state_machines._build(machines)


def test_allows_is_undeclared_without_a_transition_table():
    assert machine("issue_status").allows("Wanted", "Downloaded") is None
