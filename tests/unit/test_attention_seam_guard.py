#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for scripts/check_attention_seam.py — the Attention public-seam gate (ADR-0003).

ADR-0003 gives ``comicarr.app.attention`` one narrow public interface and calls
everything else an implementation detail. The gate AST-scans ``comicarr/`` for imports
that reach past that seam into ``comicarr.app.attention._*`` and fails unless the
crossing is in the shrink-only ``ALLOWLIST``.

These tests pin both directions of the gate. A new unlisted crossing must fail, and a
listed crossing that no longer exists must *also* fail — that stale-entry check is the
whole reason the list can only shrink. They also pin that a function-local import (how
``journal.py`` actually reaches its post-transition hook) is caught, since a scan of
module-level nodes alone would miss most of the real crossings.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_attention_seam.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("check_attention_seam", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _tree(guard, monkeypatch, tmp_path, source, allowlist, rel="comicarr/app/leaf.py"):
    """Write a one-file fake tree and point the guard at it."""
    module = tmp_path / rel
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(source, encoding="utf-8")

    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "SCAN_GLOBS", ("comicarr/**/*.py",))
    monkeypatch.setattr(guard, "ALLOWLIST", allowlist)
    return module


def test_real_tree_passes(guard):
    """The repository is clean — this is the regression gate for the seam itself."""
    assert guard.main() == 0


def test_allowlist_is_the_union_of_its_two_categories(guard):
    """Adding a category dict without merging it would silently disable the waiver."""
    assert guard.ALLOWLIST == {**guard.PERMANENT_HOOKS, **guard.DEPRECATED_SHIMS}
    assert not set(guard.PERMANENT_HOOKS) & set(guard.DEPRECATED_SHIMS)
    assert all(reason.strip() for reason in guard.ALLOWLIST.values())


@pytest.mark.parametrize(
    "source",
    [
        "from comicarr.app.attention._policy import is_actionable\n",
        "import comicarr.app.attention._read\n",
        "import comicarr.app.attention._read as reader\n",
        # Same submodule, reached by importing the private name off the package.
        "from comicarr.app.attention import _serialization\n",
    ],
)
def test_unlisted_private_import_is_rejected(guard, tmp_path, monkeypatch, source):
    _tree(guard, monkeypatch, tmp_path, source, allowlist={})
    assert guard.main() == 1


@pytest.mark.parametrize(
    ("rel", "source", "expected"),
    [
        # comicarr/app/activity/x.py: `..attention` resolves to comicarr.app.attention.
        ("comicarr/app/activity/x.py", "from ..attention._resolution import _batch_order\n", 1),
        ("comicarr/app/downloads/sub/x.py", "from ...attention._policy import base_reason\n", 1),
        # comicarr/app/x.py: `..attention` is comicarr.attention — a different package.
        ("comicarr/app/x.py", "from ..attention._resolution import _batch_order\n", 0),
    ],
)
def test_relative_import_is_resolved_before_matching(guard, tmp_path, monkeypatch, rel, source, expected):
    """A relative spelling must not be a way around the gate — nor a false positive."""
    _tree(guard, monkeypatch, tmp_path, source, allowlist={}, rel=rel)
    assert guard.main() == expected


@pytest.mark.parametrize(
    "source",
    [
        "from comicarr.app.attention import read, record, resolve\n",
        "from comicarr.app.attention import AttentionView, Scope\n",
        "from comicarr.app.attention.contracts import Failure\n",
        "from comicarr.app.attention.router import router\n",
        # A public name bound to a private-looking local alias is still public:
        # the imported name is what crosses the seam, not what it is called here.
        "from comicarr.app.attention import read as _read\n",
        # Unrelated packages that merely share a private-module naming style.
        "from comicarr.app.downloads._journal import thing\n",
    ],
)
def test_public_seam_import_is_accepted(guard, tmp_path, monkeypatch, source):
    _tree(guard, monkeypatch, tmp_path, source, allowlist={})
    assert guard.main() == 0


def test_allowlisted_private_import_is_accepted(guard, tmp_path, monkeypatch):
    _tree(
        guard,
        monkeypatch,
        tmp_path,
        "from comicarr.app.attention._reconciliation import reconcile_excluded\n",
        allowlist={("comicarr/app/leaf.py", "_reconciliation"): "waived for this test"},
    )
    assert guard.main() == 0


def test_allowlist_entry_does_not_waive_a_different_file(guard, tmp_path, monkeypatch):
    """Entries are keyed on (file, module) so a waiver cannot travel to another caller."""
    _tree(
        guard,
        monkeypatch,
        tmp_path,
        "from comicarr.app.attention._reconciliation import reconcile_excluded\n",
        allowlist={
            ("comicarr/app/other.py", "_reconciliation"): "waived elsewhere",
            ("comicarr/app/leaf.py", "_policy"): "a different submodule",
        },
    )
    assert guard.main() == 1


def test_stale_allowlist_entry_is_reported(guard, tmp_path, monkeypatch, capsys):
    """A waiver whose crossing is gone fails too — that is what makes the list shrink-only."""
    _tree(
        guard,
        monkeypatch,
        tmp_path,
        "from comicarr.app.attention import read\n",
        allowlist={("comicarr/app/leaf.py", "_serialization"): "shim deleted last release"},
    )
    assert guard.main() == 1
    assert "Stale" in capsys.readouterr().err


def test_function_local_import_is_caught(guard, tmp_path, monkeypatch):
    """journal.py imports its hook inside the function body; a header-only scan would miss it."""
    source = (
        "def quarantine(conn):\n"
        "    from comicarr.app.attention._reconciliation import reconcile_excluded\n"
        "\n"
        "    return reconcile_excluded(conn)\n"
    )
    _tree(guard, monkeypatch, tmp_path, source, allowlist={})
    assert guard.main() == 1

    # ...and the same import is waivable once listed, at function scope too.
    monkeypatch.setattr(
        guard,
        "ALLOWLIST",
        {("comicarr/app/leaf.py", "_reconciliation"): "waived for this test"},
    )
    assert guard.main() == 0


def test_unparseable_file_is_reported_and_fails(guard, tmp_path, monkeypatch, capsys):
    """A file the gate cannot parse is not evidence of a clean tree.

    Swallowing the SyntaxError would let the gate print its OK line for a file it
    never inspected — exactly the silent pass the guard exists to prevent.
    """
    _tree(guard, monkeypatch, tmp_path, "def broken(:\n", allowlist={})
    assert guard.main() == 1

    err = capsys.readouterr().err
    assert "comicarr/app/leaf.py" in err
    assert "Could not parse" in err
    assert "invalid syntax" in err  # the parse error itself, not just the file name
    # Distinguishable from a seam violation, so a contributor can tell the two apart.
    assert "Private Attention submodule imported" not in err


def test_attention_package_may_use_its_own_internals(guard, tmp_path, monkeypatch):
    _tree(
        guard,
        monkeypatch,
        tmp_path,
        "from comicarr.app.attention._policy import is_actionable\n",
        allowlist={},
        rel="comicarr/app/attention/_read.py",
    )
    assert guard.main() == 0
