#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for scripts/check_legacy_seams.py, the legacy module boundary gate (ADR-0005)."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_legacy_seams.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("check_legacy_seams", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


ROOT_MODULES = ("updater", "search", "getimage", "logger", "db")


def _tree(guard, monkeypatch, tmp_path, files, foundations=None, router=None, deferred=None):
    """Write a fake tree with a few root modules plus ``files`` and point the guard at it."""
    for name in ROOT_MODULES:
        path = tmp_path / "comicarr" / ("%s.py" % name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    for rel, source in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "FOUNDATIONS_ALLOWLIST", foundations or {})
    monkeypatch.setattr(guard, "ROUTER_ALLOWLIST", router or {})
    monkeypatch.setattr(guard, "DEFERRED_ALLOWLIST", deferred or {})
    monkeypatch.setattr(
        guard,
        "ALLOWLISTS",
        {
            "foundations": guard.FOUNDATIONS_ALLOWLIST,
            "router": guard.ROUTER_ALLOWLIST,
            "deferred": guard.DEFERRED_ALLOWLIST,
        },
    )


def test_real_tree_passes(guard):
    assert guard.main() == 0


def test_every_allowlist_entry_gives_a_reason_and_removal_trigger(guard):
    for entries in guard.ALLOWLISTS.values():
        for reason, trigger in entries.values():
            assert reason.strip() and trigger.strip()


def test_router_allowlist_holds_todays_crossings(guard):
    assert set(guard.ROUTER_ALLOWLIST) == {
        ("comicarr/app/series/router.py", "mangasync"),
        ("comicarr/app/series/router.py", "comicsync"),
        ("comicarr/app/opds/router.py", "getimage"),
        ("comicarr/app/opds/router.py", "readinglist"),
    }


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("from comicarr import updater\n", id="top-level from-import"),
        pytest.param("import comicarr.updater\n", id="top-level import"),
        pytest.param("from comicarr.updater import forceRescan\n", id="from submodule"),
        pytest.param("def f():\n    from comicarr import updater\n    updater.forceRescan(1)\n", id="function-local"),
        pytest.param("from ... import updater\n", id="relative"),
        pytest.param("import comicarr\n\ndef f():\n    comicarr.updater.forceRescan(1)\n", id="attribute access"),
    ],
)
def test_foundations_crossing_outside_its_seam_fails(guard, tmp_path, monkeypatch, source):
    _tree(guard, monkeypatch, tmp_path, {"comicarr/app/series/leaf.py": source})
    assert guard.main() == 1


def test_seam_module_may_import_its_legacy_module(guard, tmp_path, monkeypatch):
    _tree(guard, monkeypatch, tmp_path, {"comicarr/app/series/rescan.py": "from comicarr import updater\n"})
    assert guard.main() == 0


def test_new_deferred_crossing_fails(guard, tmp_path, monkeypatch):
    _tree(guard, monkeypatch, tmp_path, {"comicarr/app/series/leaf.py": "from comicarr import search\n"})
    assert guard.main() == 1


def test_router_importing_deferred_legacy_fails(guard, tmp_path, monkeypatch):
    _tree(guard, monkeypatch, tmp_path, {"comicarr/app/opds/router.py": "from comicarr import getimage\n"})
    assert guard.main() == 1


def test_mcp_tool_layer_follows_the_router_rule(guard, tmp_path, monkeypatch):
    _tree(guard, monkeypatch, tmp_path, {"comicarr/app/mcp/tools.py": "from comicarr import search\n"})
    assert guard.main() == 1


def test_router_importing_a_seamed_module_fails_even_from_a_seam_path(guard, tmp_path, monkeypatch):
    # Being a router wins: the deferred or foundations allowlists do not cover it.
    _tree(
        guard,
        monkeypatch,
        tmp_path,
        {"comicarr/app/series/router.py": "from comicarr import updater\n"},
        foundations={("comicarr/app/series/router.py", "updater"): ("r", "t")},
    )
    assert guard.main() == 1


def test_infrastructure_and_package_globals_pass(guard, tmp_path, monkeypatch):
    source = "import comicarr\nfrom comicarr import db, logger\n\nX = comicarr.CONFIG\n"
    _tree(guard, monkeypatch, tmp_path, {"comicarr/app/opds/router.py": source})
    assert guard.main() == 0


def test_allowlisted_crossing_passes(guard, tmp_path, monkeypatch):
    _tree(
        guard,
        monkeypatch,
        tmp_path,
        {"comicarr/app/opds/router.py": "from comicarr import getimage\n"},
        router={("comicarr/app/opds/router.py", "getimage"): ("r", "t")},
    )
    assert guard.main() == 0


@pytest.mark.parametrize("kind", ["foundations", "router", "deferred"])
def test_stale_allowlist_entry_fails(guard, tmp_path, monkeypatch, kind):
    entry = {("comicarr/app/series/leaf.py", "search"): ("r", "t")}
    _tree(guard, monkeypatch, tmp_path, {"comicarr/app/series/leaf.py": "x = 1\n"}, **{kind: entry})
    assert guard.main() == 1


def test_unparseable_file_fails(guard, tmp_path, monkeypatch):
    _tree(guard, monkeypatch, tmp_path, {"comicarr/app/series/leaf.py": "def (\n"})
    assert guard.main() == 1
