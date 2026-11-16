#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for scripts/check_root_modules.py, the shrink-only package root gate (ADR-0007)."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_root_modules.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("check_root_modules", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _tree(guard, monkeypatch, tmp_path, modules=(), packages=(), vendor=()):
    package = tmp_path / "comicarr"
    (package / "app").mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for name in modules:
        (package / ("%s.py" % name)).write_text("", encoding="utf-8")
    for name in packages:
        (package / name).mkdir()
    if vendor:
        vendor_dir = package / "_vendor"
        vendor_dir.mkdir(exist_ok=True)
        (vendor_dir / "__init__.py").write_text("", encoding="utf-8")
        (vendor_dir / "provenance.py").write_text("", encoding="utf-8")
        for name in vendor:
            if name.endswith(".py"):
                (vendor_dir / name).write_text("", encoding="utf-8")
            else:
                (vendor_dir / name).mkdir()
    monkeypatch.setattr(guard, "ROOT", tmp_path)


def test_real_tree_is_clean(guard):
    assert guard.check() == []


def test_listed_tree_passes(guard, monkeypatch, tmp_path):
    _tree(guard, monkeypatch, tmp_path, modules=["search"], packages=["torrent", "_vendor"], vendor=["rtorrent"])
    monkeypatch.setattr(guard, "ROOT_MODULES", {"search": 1})
    monkeypatch.setattr(guard, "ROOT_PACKAGES", {"torrent": 1, "_vendor": 1})
    monkeypatch.setattr(guard, "VENDOR_ROOTS", {"rtorrent": 1})
    assert guard.check() == []


def test_new_root_module_fails(guard, monkeypatch, tmp_path):
    _tree(guard, monkeypatch, tmp_path, modules=["search", "brand_new"])
    monkeypatch.setattr(guard, "ROOT_MODULES", {"search": 1})
    monkeypatch.setattr(guard, "ROOT_PACKAGES", {})
    monkeypatch.setattr(guard, "VENDOR_ROOTS", {})
    problems = guard.check()
    assert len(problems) == 1
    assert problems[0].startswith("new: comicarr/brand_new.py")


def test_new_root_package_fails(guard, monkeypatch, tmp_path):
    _tree(guard, monkeypatch, tmp_path, packages=["plugins"])
    monkeypatch.setattr(guard, "ROOT_MODULES", {})
    monkeypatch.setattr(guard, "ROOT_PACKAGES", {})
    monkeypatch.setattr(guard, "VENDOR_ROOTS", {})
    assert guard.check() == ["new: comicarr/plugins/ is not in ROOT_PACKAGES; put new code under comicarr/app/"]


def test_new_vendor_root_fails(guard, monkeypatch, tmp_path):
    _tree(guard, monkeypatch, tmp_path, vendor=["requests_old"])
    monkeypatch.setattr(guard, "ROOT_MODULES", {})
    monkeypatch.setattr(guard, "ROOT_PACKAGES", {"_vendor": 1})
    monkeypatch.setattr(guard, "VENDOR_ROOTS", {})
    problems = guard.check()
    assert problems == ["new: comicarr/_vendor/requests_old is not in VENDOR_ROOTS; put new code under comicarr/app/"]


def test_deleted_module_still_listed_is_stale(guard, monkeypatch, tmp_path):
    _tree(guard, monkeypatch, tmp_path)
    monkeypatch.setattr(guard, "ROOT_MODULES", {"parseit": 1404})
    monkeypatch.setattr(guard, "ROOT_PACKAGES", {})
    monkeypatch.setattr(guard, "VENDOR_ROOTS", {})
    assert guard.check() == ["stale: comicarr/parseit.py is gone; delete it from ROOT_MODULES (retired by #1404)"]


def test_vendor_dir_gone_leaves_vendor_roots_stale(guard, monkeypatch, tmp_path):
    _tree(guard, monkeypatch, tmp_path)
    monkeypatch.setattr(guard, "ROOT_MODULES", {})
    monkeypatch.setattr(guard, "ROOT_PACKAGES", {})
    monkeypatch.setattr(guard, "VENDOR_ROOTS", {"rtorrent": 1413})
    assert guard.check() == ["stale: comicarr/_vendor/rtorrent is gone; delete it from VENDOR_ROOTS (retired by #1413)"]


def test_main_exit_codes(guard, monkeypatch, tmp_path, capsys):
    _tree(guard, monkeypatch, tmp_path, modules=["stray"])
    monkeypatch.setattr(guard, "ROOT_MODULES", {})
    monkeypatch.setattr(guard, "ROOT_PACKAGES", {})
    monkeypatch.setattr(guard, "VENDOR_ROOTS", {})
    assert guard.main() == 1
    assert "only shrinks" in capsys.readouterr().err
