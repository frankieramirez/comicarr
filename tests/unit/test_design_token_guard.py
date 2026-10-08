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


_THEME_CSS = (
    _MIN_CSS
    + """
@theme inline {
  --color-foreground: var(--foreground);
  --color-border: var(--border);
  --color-destructive: red;
  --color-destructive-foreground: white;
}
"""
)


def test_unregistered_color_utility_is_rejected(guard, tmp_path, monkeypatch, capsys):
    extra = {"Box.tsx": 'export const c = "text-not-a-token border-border";\n'}
    _point_at(guard, monkeypatch, tmp_path, _THEME_CSS, extra)
    assert guard.main() == 1
    err = capsys.readouterr().err
    assert "not-a-token" in err
    assert "Color utility" in err


def test_registered_palette_and_builtin_color_utilities_pass(guard, tmp_path, monkeypatch):
    extra = {"Box.tsx": 'export const c = "text-foreground border-border text-white bg-red-500";\n'}
    _point_at(guard, monkeypatch, tmp_path, _THEME_CSS, extra)
    assert guard.main() == 0


def _parse_color(value: str) -> tuple[int, int, int]:
    value = value.strip().rstrip(";")
    if value.startswith("#"):
        hexv = value[1:]
        if len(hexv) == 3:
            hexv = "".join(ch * 2 for ch in hexv)
        return tuple(int(hexv[i : i + 2], 16) for i in (0, 2, 4))
    if value.startswith("oklch("):
        inner = value[len("oklch(") : -1]
        parts = inner.replace("/", " ").split()
        L, C, H = (float(parts[0]), float(parts[1]), float(parts[2]))
        h = __import__("math").radians(H)
        a = C * __import__("math").cos(h)
        b = C * __import__("math").sin(h)
        l_ = L + 0.3963377774 * a + 0.2158037573 * b
        m_ = L - 0.1055613458 * a - 0.0638541728 * b
        s_ = L - 0.0894841775 * a - 1.2914855480 * b
        ell, m, s = l_**3, m_**3, s_**3
        r = +4.0767416621 * ell - 3.3077115913 * m + 0.2309699292 * s
        g = -1.2684380046 * ell + 2.6097574011 * m - 0.3413193965 * s
        bl = -0.0041960863 * ell - 0.7034186147 * m + 1.7076147010 * s

        def to_s(c: float) -> int:
            c = min(max(c, 0.0), 1.0)
            encoded = 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
            return round(encoded * 255)

        return to_s(r), to_s(g), to_s(bl)
    raise AssertionError(f"unsupported color: {value}")


def _contrast(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    def lum(rgb: tuple[int, int, int]) -> float:
        def channel(v: int) -> float:
            x = v / 255
            return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4

        r, g, b = (channel(v) for v in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    hi, lo = sorted((lum(c1), lum(c2)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_destructive_button_contrast_meets_aa(guard):
    css = guard.STYLESHEET.read_text(encoding="utf-8")
    root = guard._block(css, ":root")
    dark = guard._block(css, ".dark")
    assert "--destructive-foreground" in root
    assert "--destructive-foreground" in dark

    def value(block: dict[str, int], name: str) -> str:
        line = css.splitlines()[block[name] - 1]
        return line.split(":", 1)[1]

    light_bg = _parse_color(value(root, "--destructive"))
    light_fg = _parse_color(value(root, "--destructive-foreground"))
    dark_bg = _parse_color(value(dark, "--destructive"))
    dark_fg = _parse_color(value(dark, "--destructive-foreground"))
    assert _contrast(light_bg, light_fg) >= 4.5
    assert _contrast(dark_bg, dark_fg) >= 4.5


def test_destructive_foreground_is_registered(guard):
    stems = guard._theme_color_stems(guard.STYLESHEET.read_text(encoding="utf-8"))
    assert "destructive-foreground" in stems
    assert "destructive" in stems
    assert "border" in stems
    assert "card-border" not in stems
