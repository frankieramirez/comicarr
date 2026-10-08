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

"""Tests for scripts/check_radius_literals.py — on-scale rounded-[Npx] ratchet."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_radius_literals.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_radius_literals", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_real_tree_passes():
    guard = _load()
    assert guard.main() == 0


def test_on_scale_literal_is_rejected(tmp_path, monkeypatch, capsys):
    guard = _load()
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "Box.tsx").write_text('export const c = "rounded-[6px]";\n', encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "SRC", src)
    assert guard.main() == 1
    err = capsys.readouterr().err
    assert "rounded-[6px]" in err
    assert "rounded-lg" in err


def test_five_px_button_step_is_not_flagged(tmp_path, monkeypatch):
    guard = _load()
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "Box.tsx").write_text('export const c = "rounded-[5px] rounded-lg";\n', encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "SRC", src)
    assert guard.main() == 0
