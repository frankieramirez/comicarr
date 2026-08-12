#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for scripts/check_fail_reason_registry.py — the fail_reason completeness gate (#527).

The gate AST-scans the tree for every literal ``fail_reason`` base token that can be
written to ``pipeline_journal`` and fails CI if any is missing from the actionability
registry in ``comicarr/app/attention/_policy.py``. It also carries a narrow, deliberately
scoped ``PASS_THROUGH_WRITERS`` exemption for the one seam where the reason really is
dynamic (``entry.reason`` inside ``_record_on_connection``) — these tests pin that the
exemption stays keyed to that exact (file, function[, attribute]) seam and does not widen
to any same-named function elsewhere in the tree.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_fail_reason_registry.py"

# A minimal but well-formed stand-in for comicarr/app/attention/_policy.py: one
# admitted literal ("known_reason") and empty exclusion buckets so _load_registry's
# EXCLUDE/RECONCILIATION cross-check has nothing to complain about.
_FAKE_REGISTRY = (
    'REASON_PHRASES = {"known_reason": "a known reason"}\n'
    "NON_ACTIONABLE_FLAT = frozenset()\n"
    "NON_ACTIONABLE_COMPOSITE = frozenset()\n"
    "RECONCILIATION = frozenset()\n"
)


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("check_fail_reason_registry", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _write_fake_registry(root: Path) -> Path:
    path = root / "comicarr" / "app" / "attention" / "_policy.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_FAKE_REGISTRY)
    return path


def _point_at_fake_tree(guard, monkeypatch, root: Path) -> None:
    monkeypatch.setattr(guard, "ROOT", root)
    monkeypatch.setattr(guard, "REASONS_PATH", root / "comicarr" / "app" / "attention" / "_policy.py")


def test_real_tree_is_registry_clean(guard):
    """The repository is clean today — the regression gate for #527 itself."""
    assert guard.main() == 0


def test_unclassified_literal_reason_is_caught(guard, tmp_path, monkeypatch):
    _write_fake_registry(tmp_path)
    module = tmp_path / "comicarr" / "app" / "foo.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(
        'from comicarr.app.attention import Failure\nFailure(release_key="x", reason="unclassified_reason")\n'
    )
    _point_at_fake_tree(guard, monkeypatch, tmp_path)

    assert guard.main() == 1


def test_classified_literal_reason_is_accepted(guard, tmp_path, monkeypatch):
    _write_fake_registry(tmp_path)
    module = tmp_path / "comicarr" / "app" / "foo.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text('from comicarr.app.attention import Failure\nFailure(release_key="x", reason="known_reason")\n')
    _point_at_fake_tree(guard, monkeypatch, tmp_path)

    assert guard.main() == 0


def test_pass_through_exemption_applies_at_the_intended_seam(guard, tmp_path, monkeypatch):
    """``entry.reason`` inside the real _record_on_connection seam is exempt."""
    _write_fake_registry(tmp_path)
    recording = tmp_path / "comicarr" / "app" / "attention" / "_recording.py"
    recording.parent.mkdir(parents=True, exist_ok=True)
    recording.write_text(
        "def _record_on_connection(entry, conn):\n"
        "    from comicarr.app.downloads import journal\n"
        "    journal.mark_failed(entry.release_key, entry.reason, conn=conn)\n"
    )
    _point_at_fake_tree(guard, monkeypatch, tmp_path)

    assert guard.main() == 0


def test_pass_through_exemption_does_not_follow_the_function_name_to_another_file(guard, tmp_path, monkeypatch):
    """A same-named ``_record_on_connection`` elsewhere must NOT inherit the exemption.

    Regression for review finding #10: the exemption used to be keyed on the bare
    function name, so any function named ``_record_on_connection`` (or ``record``,
    etc.) anywhere in the tree could smuggle a dynamic ``.reason`` past the gate.
    """
    _write_fake_registry(tmp_path)
    decoy = tmp_path / "comicarr" / "app" / "other" / "_recording.py"
    decoy.parent.mkdir(parents=True, exist_ok=True)
    decoy.write_text(
        "def _record_on_connection(entry, conn):\n"
        "    from comicarr.app.downloads import journal\n"
        "    journal.mark_failed(entry.release_key, entry.reason, conn=conn)\n"
    )
    _point_at_fake_tree(guard, monkeypatch, tmp_path)

    assert guard.main() == 1


def test_pass_through_writers_are_keyed_by_file_not_bare_name(guard):
    """Pin the data shape the narrowing depends on: (file, function) tuples."""
    assert guard.PASS_THROUGH_WRITERS, "PASS_THROUGH_WRITERS parsed empty — allowlist has drifted"
    for entry in guard.PASS_THROUGH_WRITERS:
        assert isinstance(entry, tuple) and len(entry) == 2, (
            "PASS_THROUGH_WRITERS must be (relative file path, function name) tuples, not bare names"
        )


def test_dynamic_reason_attr_seam_is_the_narrow_entry_reason_seam(guard):
    """Pin the one seam this exemption is allowed to cover."""
    assert guard.DYNAMIC_REASON_ATTR_SEAM == (
        "comicarr/app/attention/_recording.py",
        "_record_on_connection",
        "entry",
    )
