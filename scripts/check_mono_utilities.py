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

"""CI gate: exact ``.mono-label`` / ``.mono-meta`` duplicates stay gone.

``.mono-label`` is 10px mono, uppercase, ``0.08em`` tracking, muted.
``.mono-meta`` is 11px mono, muted. Hand-rolling those class tokens
reproduces the utilities and is how tracking drifted across tables.

Exact duplicates must use the utilities. Remaining
``font-mono text-[10px] uppercase`` near-variants (other tracking or
colour) are a shrink-only count — new copies fail; lowering the number
is required when one is converted.

Contributor-facing only — no changeset (CLAUDE.md).

Wire-in: ``npm run lint:guards``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

TOKEN_RE = re.compile(r"[A-Za-z0-9_./:[\]%-]+")

LABEL_TOKS = frozenset(
    {
        "font-mono",
        "text-[10px]",
        "uppercase",
        "tracking-[0.08em]",
        "text-muted-foreground",
    }
)
META_TOKS = frozenset({"font-mono", "text-[11px]", "text-muted-foreground"})
TEN_PX_UPPER_TOKS = frozenset({"font-mono", "text-[10px]", "uppercase"})

# Remaining ``font-mono text-[10px] uppercase`` lines after exact
# ``.mono-label`` replacements. This number only ever shrinks.
MAX_TEN_PX_UPPERCASE = 29


def _scan() -> tuple[list[str], list[str], list[str]]:
    labels: list[str] = []
    metas: list[str] = []
    ten_upper: list[str] = []
    for path in sorted(SRC.rglob("*.tsx")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(text.splitlines(), 1):
            toks = set(TOKEN_RE.findall(line))
            loc = f"  {rel}:{lineno}"
            if LABEL_TOKS <= toks:
                labels.append(f"{loc}: exact .mono-label duplicate — use mono-label")
            if META_TOKS <= toks:
                metas.append(f"{loc}: exact .mono-meta duplicate — use mono-meta")
            if TEN_PX_UPPER_TOKS <= toks:
                ten_upper.append(loc)
    return labels, metas, ten_upper


def main() -> int:
    labels, metas, ten_upper = _scan()
    failed = False
    if labels or metas:
        print(
            "Exact .mono-label / .mono-meta duplicates — use the utilities:",
            file=sys.stderr,
        )
        print("\n".join(labels + metas), file=sys.stderr)
        failed = True
    count = len(ten_upper)
    if count > MAX_TEN_PX_UPPERCASE:
        print(
            f"font-mono text-[10px] uppercase rose to {count} "
            f"(max {MAX_TEN_PX_UPPERCASE}). Use .mono-label or a named "
            "tracking variant.",
            file=sys.stderr,
        )
        print("\n".join(ten_upper), file=sys.stderr)
        failed = True
    elif count < MAX_TEN_PX_UPPERCASE:
        print(
            f"font-mono text-[10px] uppercase fell to {count}; lower "
            f"MAX_TEN_PX_UPPERCASE from {MAX_TEN_PX_UPPERCASE} in "
            "scripts/check_mono_utilities.py.",
            file=sys.stderr,
        )
        failed = True
    if failed:
        print("", file=sys.stderr)
        print("See DESIGN.md -> Typography.", file=sys.stderr)
        return 1
    print(f"Mono utility guard: ok (exact duplicates empty; {count} ten-px uppercase near-variants)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
