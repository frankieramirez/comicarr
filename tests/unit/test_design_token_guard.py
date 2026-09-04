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

"""Tests for scripts/check_design_tokens.py — unresolvable var() and invented --status-*."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_design_tokens.py"

_MIN_CSS = """\
:root {
  --foreground: black;
  --border: gray;
  --status-active: green;
}
.dark {
  --foreground: white;
  --border: silver;
  --status-active: lime;
}
"""


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("check_design_tokens", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _point_at(guard, monkeypatch, tmp_path, css, extra_files=None):
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "index.css").write_text(css, encoding="utf-8")
    for rel, content in (extra_files or {}).items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "SRC", src)
    monkeypatch.setattr(guard, "STYLESHEET", src / "index.css")


def test_real_tree_passes(guard):
    """The repository is clean — this is the regression gate for the token contract."""
    assert guard.main() == 0


def test_status_set_is_the_documented_exhaustive_list(guard):
    assert guard.STATUS_TOKENS == {
        f"--status-{stem}{suffix}"
        for stem in (
            "active",
            "wanted",
            "downloaded",
            "paused",
            "ended",
            "error",
            "skipped",
        )
        for suffix in ("", "-bg")
    }


def test_invented_status_token_defined_in_both_themes_is_rejected(guard, tmp_path, monkeypatch, capsys):
    """Assigning --status-success in :root and .dark is not enough to make it a token."""
    css = _MIN_CSS.replace(
        "  --status-active: green;\n",
        "  --status-active: green;\n  --status-success: lime;\n",
    ).replace(
        "  --status-active: lime;\n",
        "  --status-active: lime;\n  --status-success: lime;\n",
    )
    extra = {"Badge.tsx": 'export const c = "var(--status-success)";\n'}
    _point_at(guard, monkeypatch, tmp_path, css, extra)
    assert guard.main() == 1
    err = capsys.readouterr().err
    assert "--status-success" in err
    assert "Unknown `--status-*` token" in err


def test_multiline_var_reference_is_rejected(guard, tmp_path, monkeypatch, capsys):
    extra = {"Box.tsx": ("export const c = {\n  color: `var(\n    --no-such-token\n  )`,\n};\n")}
    _point_at(guard, monkeypatch, tmp_path, _MIN_CSS, extra)
    assert guard.main() == 1
    err = capsys.readouterr().err
    assert "--no-such-token" in err


def test_optional_fallback_form_is_not_flagged(guard, tmp_path, monkeypatch):
    extra = {"Box.tsx": 'export const c = "var(--border-soft, var(--border))";\n'}
    _point_at(guard, monkeypatch, tmp_path, _MIN_CSS, extra)
    assert guard.main() == 0
