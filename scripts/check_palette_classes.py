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

"""CI gate: no new raw Tailwind palette classes in the frontend.

Comicarr ships light and dark. A palette literal — ``text-green-400``,
``bg-red-500`` — is a fixed sRGB value with no dark-mode counterpart, so it
ignores ``.dark`` entirely: the component is legible in the theme its author
had open and wrong in the other. Unlike an unresolvable ``var()`` (see
``check_design_tokens.py``) this renders *something* in both themes, which is
why it accumulates without anyone filing a bug.

Semantic colour belongs to the ``--status-*`` family; ``--destructive`` and
``--muted-foreground`` cover the generic cases. Both are theme-aware.

This gate is a ratchet, not a cliff. 58 usages across 11 files predate it, so
the baseline below records the per-file count and the check fails when a count
*rises* or a new file appears. It also fails when a count *falls* without the
baseline being updated: a stale entry is a lie about the debt, and forcing the
edit is what makes the number monotonically decrease. Same contract as the
allowlist in ``check_attention_seam.py`` — the list only ever shrinks.

To clear an entry: replace the literals with tokens, then lower the number
here (or delete the line at zero).

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

SCAN_SUFFIXES = {".ts", ".tsx"}
SKIP_DIR_NAMES = {"node_modules", "dist", "__pycache__"}

# Longer directional suffixes first so `border-ss-red-500` is not eaten as `border-s`.
_UTILITIES = (
    r"(?:text|bg|from|to|via|decoration|outline|shadow|accent|caret|fill|stroke|placeholder)"
    r"|border(?:-ss|-se|-es|-ee|-tl|-tr|-bl|-br|-s|-e|-[trblxy])?"
    r"|divide(?:-[xy])?"
    r"|ring(?:-offset)?"
)
_PALETTES = (
    "gray|slate|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|"
    "teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose"
)
PALETTE_RE = re.compile(rf"\b(?:{_UTILITIES})-(?:{_PALETTES})-(?:50|[1-9]00|950)\b")

# Paths are relative to frontend/src. This list only ever shrinks.
BASELINE: dict[str, int] = {
    "components/ai/ActivityFeedEntry.tsx": 13,
    "components/import/ConfidenceBadge.tsx": 12,
    "components/import/ImportTable.tsx": 3,
    "components/import/MatchModal.tsx": 3,
    "components/migration/MigrationWizard.tsx": 9,
    "components/queue/BulkActionBar.tsx": 2,
    "components/settings/AiTab.tsx": 2,
    "components/storyarcs/ArcGenerator.tsx": 2,
    "components/storyarcs/ArcIssueRow.tsx": 7,
    "components/storyarcs/ArcIssueTable.tsx": 4,
    "pages/StoryArcDetailPage.tsx": 1,
}


def _scan() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(SRC.rglob("*")):
        if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
            continue
        if SKIP_DIR_NAMES.intersection(path.parts):
            continue
        try:
            found = PALETTE_RE.findall(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if found:
            counts[path.relative_to(SRC).as_posix()] = len(found)
    return counts


def _examples(rel: str, limit: int = 3) -> str:
    text = (SRC / rel).read_text(encoding="utf-8")
    seen: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for hit in PALETTE_RE.findall(line):
            if len(seen) < limit:
                seen.append(f"{rel}:{lineno}: {hit}")
    return "\n".join(f"      {s}" for s in seen)


def main() -> int:
    counts = _scan()
    regressions: list[str] = []
    stale: list[str] = []

    for rel, found in sorted(counts.items()):
        allowed = BASELINE.get(rel, 0)
        if found > allowed:
            label = f"{found} (baseline {allowed})" if allowed else f"{found}, file not in baseline"
            regressions.append(f"  {rel}: {label}")
            regressions.append(_examples(rel))
        elif found < allowed:
            stale.append(f"  {rel}: {found} now, baseline says {allowed} — lower it")

    for rel, allowed in sorted(BASELINE.items()):
        if rel not in counts:
            stale.append(f"  {rel}: clean now — delete the entry ({allowed} recorded)")

    if not regressions and not stale:
        print(f"Palette class guard: ok ({sum(counts.values())} legacy usages in {len(counts)} file(s), none new)")
        return 0

    if regressions:
        print("New raw Tailwind palette classes — these ignore dark mode:", file=sys.stderr)
        print("\n".join(regressions), file=sys.stderr)
        print("", file=sys.stderr)
        print("Use a --status-* token, or --destructive / --muted-foreground.", file=sys.stderr)
    if stale:
        if regressions:
            print("", file=sys.stderr)
        print("Stale baseline in scripts/check_palette_classes.py:", file=sys.stderr)
        print("\n".join(stale), file=sys.stderr)
        print("", file=sys.stderr)
        print("The baseline records real debt; update it so the count keeps falling.", file=sys.stderr)
    print("", file=sys.stderr)
    print("See DESIGN.md -> 'Anti-Patterns / What NOT to Do'.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
