#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""Tests for scripts/check_palette_classes.py — shrink-only raw Tailwind palette ratchet."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_palette_classes.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("check_palette_classes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def test_real_tree_passes(guard):
    """The repository matches the recorded baseline — no new palette literals."""
    assert guard.main() == 0


@pytest.mark.parametrize(
    "cls",
    [
        "text-red-500",
        "bg-green-400",
        "border-red-500",
        "border-t-red-500",
        "border-x-red-500",
        "divide-red-500",
        "divide-x-red-500",
        "ring-red-500",
        "ring-offset-red-500",
        "placeholder-red-500",
        "border-ss-rose-50",
    ],
)
def test_palette_re_matches_supported_color_utilities(guard, cls):
    assert guard.PALETTE_RE.search(cls), cls


@pytest.mark.parametrize(
    "cls",
    [
        "border-t-2",
        "ring-offset-2",
        "text-primary",
        "bg-status-active",
        "placeholder",
    ],
)
def test_palette_re_ignores_non_palette_utilities(guard, cls):
    assert not guard.PALETTE_RE.search(cls), cls
