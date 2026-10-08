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

"""CI gate: no ``var()`` in the frontend resolves to nothing.

CSS fails open. A ``var(--x)`` naming a property that was never defined makes
the *entire declaration* invalid, so the browser drops it and falls back to the
inherited value. Nothing throws, nothing logs, and the element renders in a
plausible-looking wrong colour. That is the opposite of how the rest of the
codebase fails, and it is why every instance of this class shipped:

* ``--text-muted`` was defined in ``.dark`` only. 25 lines across 6 files asked
  for it; in light mode all 25 silently rendered at inherited contrast.
* ``--status-success`` and ``--status-warning`` were never tokens at all — the
  real names are ``--status-active`` and ``--status-paused``. 17 usages, and
  because most sat inside ``color-mix(in oklab, var(--status-success) 36%,
  transparent)``, an invalid inner var voided the whole colour: those borders
  and backgrounds disappeared in *both* themes.
* ``--card-shadow`` was undefined, so the ``.card-shadow`` utility applied to
  two card components had never drawn a shadow.

Five checks, one class:

1. Every custom property assigned in ``.dark`` is also assigned in ``:root``.
   A dark-only token is always a bug — it cannot resolve in light mode. The
   converse is fine: theme-invariant tokens (``--radius``, ``--font-mono``,
   ``--glassmorphism-blur``) legitimately live in ``:root`` alone.
2. Every ``var(--x)`` inside the stylesheet resolves, including across newlines
   (``var(\\n  --x\\n)`` is valid CSS and used to slip past a line-by-line scan).
3. Every ``var(--x)`` in component source resolves, same rule.
4. Every ``--status-*`` assignment and ``var(--status-*)`` reference is in the
   documented exhaustive set. Defining ``--status-success`` in both theme blocks
   used to satisfy checks 1–3 and still ship a name that is not a token.
5. Every color utility class (``text-*``, ``bg-*``, ``border-*``, …) names a
   stem registered as ``--color-*`` in ``@theme inline``, a Tailwind palette
   scale, or a builtin (``white`` / ``black`` / ``transparent`` / ``current`` /
   ``inherit``). ``border-card-border`` and ``text-destructive-foreground``
   compiled to nothing because the ``--color-*`` keys were missing; this check
   is what ``var()`` coverage cannot see.

Only the fallback-less form is checked. ``var(--x, var(--border))`` remains a
valid declaration when ``--x`` is undefined, so it is the sanctioned way to
reference an optional token — three call sites use it against ``--border-soft``
and are correct as written.

"Resolves" means the property is assigned *somewhere* in ``frontend/src`` —
stylesheet or component. Properties set inline on an element (``sidebar.tsx``
assigns ``--sidebar-width`` in a style object and reads it from descendants)
are picked up by that same assignment scan, so the cascade keeps working and
no allowlist is needed. There is deliberately no allowlist here: unlike the
palette-class backlog, this class is at zero and a regression is always a bug.

Rules and drift backlog: ``DESIGN.md``.

Contributor-facing only — no changeset (CLAUDE.md).

Wire-in: ``npm run lint:guards``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
STYLESHEET = SRC / "index.css"

SCAN_SUFFIXES = {".css", ".ts", ".tsx"}
SKIP_DIR_NAMES = {"node_modules", "dist", "__pycache__"}

# `--x:` as a CSS declaration or a JS style-object key ("--x": v / '--x': v).
ASSIGN_RE = re.compile(r"""["']?(--[A-Za-z0-9_-]+)["']?\s*:""")
# Only the fallback-less form is dangerous. `var(--x, var(--border))` stays
# valid when --x is undefined, so it is the sanctioned way to reference an
# optional token and is deliberately not flagged. `\s*` is why this must run
# over the whole file, not splitlines: `var(\n  --x\n)` is valid CSS.
USE_RE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*\)")

# DESIGN.md "Status" — exhaustive. There is no --status-success / --status-warning.
STATUS_STEMS = (
    "active",
    "wanted",
    "downloaded",
    "paused",
    "ended",
    "error",
    "skipped",
)
STATUS_TOKENS = frozenset(f"--status-{stem}{suffix}" for stem in STATUS_STEMS for suffix in ("", "-bg"))

THEME_COLOR_RE = re.compile(r"--color-([A-Za-z0-9_-]+)\s*:")

# Longer directional suffixes first so `border-ss-red-500` is not eaten as `border-s`.
_COLOR_UTILS = (
    r"(?:text|bg|from|to|via|decoration|outline|caret|fill|stroke|placeholder|accent)"
    r"|border(?:-ss|-se|-es|-ee|-tl|-tr|-bl|-br|-s|-e|-[trblxy])?"
    r"|divide(?:-[xy])?"
    r"|ring(?:-offset)?"
)
COLOR_UTIL_RE = re.compile(
    rf"(?:^|[^A-Za-z0-9_-])(?:[\w-]+:)*(?:{_COLOR_UTILS})-"
    rf"([A-Za-z][A-Za-z0-9_-]*?)(?:/\d+)?!?(?![A-Za-z0-9_-])"
)

PALETTE_STEM_RE = re.compile(
    r"^(?:gray|slate|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|"
    r"teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-(?:50|[1-9]00|950)$"
)
COLOR_BUILTINS = frozenset({"inherit", "current", "transparent", "black", "white"})
# Stems that are widths, styles, or typography — not `--color-*` keys.
NON_COLOR_STEMS = frozenset(
    {
        "xs",
        "sm",
        "md",
        "lg",
        "xl",
        "2xl",
        "3xl",
        "4xl",
        "5xl",
        "6xl",
        "7xl",
        "8xl",
        "9xl",
        "base",
        "left",
        "right",
        "center",
        "start",
        "end",
        "justify",
        "top",
        "bottom",
        "middle",
        "wrap",
        "nowrap",
        "balance",
        "pretty",
        "ellipsis",
        "clip",
        "truncate",
        "solid",
        "dashed",
        "dotted",
        "double",
        "none",
        "hidden",
        "collapse",
        "separate",
        "t",
        "b",
        "l",
        "r",
        "x",
        "y",
        "s",
        "e",
        "ss",
        "se",
        "es",
        "ee",
        "tl",
        "tr",
        "bl",
        "br",
        "cover",
        "contain",
        "fixed",
        "local",
        "scroll",
        "auto",
        "repeat",
        "inset",
        "inner",
        "current",
        "align",
        "transform",
        "radius",
        "width",
        "fill",
        "stroke",
        "color",
        "opacity",
        "spacing",
        "size",
        "shadow",
        "blur",
    }
)


def _line_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _block(css: str, selector: str) -> dict[str, int]:
    """Property name -> 1-based line number for one top-level block."""
    match = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}", css, re.S)
    if match is None:
        raise SystemExit(f"check_design_tokens: `{selector}` block not found in {STYLESHEET}")
    base = css[: match.start(1)].count("\n")
    found: dict[str, int] = {}
    for line_offset, line in enumerate(match.group(1).splitlines()):
        for name in ASSIGN_RE.findall(line):
            found.setdefault(name, base + line_offset + 1)
    return found


def _theme_color_stems(css: str) -> set[str]:
    """Stems registered as ``--color-*`` in the stylesheet (Tailwind v4 @theme)."""
    return set(THEME_COLOR_RE.findall(css))


_LAYOUT_STEM_RE = re.compile(r"^(?:gradient-to-|linear-to-|repeat-)|^(?:offset|[trblxyse]{1,2})-?\d*$")
# Arbitrary values (`border-[var(--ring)]`, `bg-[#fff]`) are not token names.
_ARBITRARY_RE = re.compile(r"\[[^\]\n]*\]")


def _unregistered_color_utilities(text: str, stems: set[str]) -> list[tuple[int, str]]:
    """Line + class stem for color utilities that would compile to nothing."""
    hits: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    # Strip arbitrary brackets so `border-[var(--ring)]` and
    # `transition-[box-shadow,border-color]` cannot look like token classes.
    scan = _ARBITRARY_RE.sub(lambda m: " " * len(m.group(0)), text)
    for match in COLOR_UTIL_RE.finditer(scan):
        stem = match.group(1)
        if stem.endswith("-"):
            continue
        if stem in stems or stem in COLOR_BUILTINS or stem in NON_COLOR_STEMS:
            continue
        if PALETTE_STEM_RE.match(stem) or _LAYOUT_STEM_RE.match(stem):
            continue
        lineno = _line_at(text, match.start())
        key = (lineno, stem)
        if key in seen:
            continue
        seen.add(key)
        hits.append(key)
    return hits


def _iter_sources():
    for path in sorted(SRC.rglob("*")):
        if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
            continue
        if SKIP_DIR_NAMES.intersection(path.parts):
            continue
        yield path


def main() -> int:
    if not STYLESHEET.is_file():
        raise SystemExit(f"check_design_tokens: {STYLESHEET} not found")

    css = STYLESHEET.read_text(encoding="utf-8")
    root_tokens = _block(css, ":root")
    dark_tokens = _block(css, ".dark")

    failures: list[str] = []

    # 1. dark-only tokens
    dark_only = sorted(set(dark_tokens) - set(root_tokens))
    if dark_only:
        failures.append("Defined in `.dark` but not `:root` — these vanish in light mode:")
        for name in dark_only:
            failures.append(f"  frontend/src/index.css:{dark_tokens[name]}: {name}")
        failures.append("  Give each a `:root` value, or delete it if nothing uses it.")

    # 2 & 3. unresolvable var() references. Scan the whole file so a var() that
    # wraps its name across newlines still counts — CSS allows that, and the
    # browser still drops the declaration if the name is undefined.
    assigned: set[str] = set()
    uses: list[tuple[str, int, str]] = []
    unknown_status: list[tuple[str, int, str]] = []
    seen_unknown: set[tuple[str, int, str]] = set()

    def _note_unknown_status(rel: str, lineno: int, name: str) -> None:
        if name.startswith("--status-") and name not in STATUS_TOKENS:
            key = (rel, lineno, name)
            if key not in seen_unknown:
                seen_unknown.add(key)
                unknown_status.append(key)

    for path in _iter_sources():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for match in ASSIGN_RE.finditer(text):
            name = match.group(1)
            assigned.add(name)
            _note_unknown_status(rel, _line_at(text, match.start()), name)
        for match in USE_RE.finditer(text):
            name = match.group(1)
            lineno = _line_at(text, match.start())
            uses.append((rel, lineno, name))
            _note_unknown_status(rel, lineno, name)

    if unknown_status:
        if failures:
            failures.append("")
        failures.append(
            "Unknown `--status-*` token — the set is exhaustive "
            f"({', '.join(STATUS_STEMS)} and their `-bg` pairs; see DESIGN.md):"
        )
        for rel, lineno, name in unknown_status:
            near = _suggest(name, STATUS_TOKENS)
            failures.append(f"  {rel}:{lineno}: {name}{near}")

    dangling = [
        (rel, lineno, name)
        for rel, lineno, name in uses
        if name not in assigned and (rel, lineno, name) not in seen_unknown
    ]
    if dangling:
        if failures:
            failures.append("")
        failures.append("`var()` on a property that is never assigned — the whole declaration is dropped:")
        for rel, lineno, name in dangling:
            near = _suggest(name, assigned)
            failures.append(f"  {rel}:{lineno}: {name}{near}")

    theme_stems = _theme_color_stems(css)
    unregistered: list[tuple[str, int, str]] = []
    for path in _iter_sources():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, stem in _unregistered_color_utilities(text, theme_stems):
            unregistered.append((rel, lineno, stem))
    if unregistered:
        if failures:
            failures.append("")
        failures.append(
            "Color utility naming a stem that is not a `--color-*` theme key "
            "(class compiles to nothing in Tailwind v4):"
        )
        for rel, lineno, stem in unregistered:
            near = _suggest(stem, theme_stems)
            failures.append(f"  {rel}:{lineno}: {stem}{near}")

    if not failures:
        print(
            f"Design token guard: ok ({len(root_tokens)} :root, {len(dark_tokens)} .dark, {len(uses)} var() references)"
        )
        return 0

    print("\n".join(failures), file=sys.stderr)
    print("", file=sys.stderr)
    print("CSS fails open: an unresolvable var() renders as inherited, not as an error.", file=sys.stderr)
    print("See DESIGN.md -> 'Tokens are the contract'.", file=sys.stderr)
    return 1


def _suggest(name: str, assigned: set[str] | frozenset[str]) -> str:
    """Offer the closest defined token — these bugs are usually near-misses."""
    import difflib

    close = difflib.get_close_matches(name, sorted(assigned), n=1, cutoff=0.7)
    return f" — did you mean {close[0]}?" if close else ""


if __name__ == "__main__":
    raise SystemExit(main())
