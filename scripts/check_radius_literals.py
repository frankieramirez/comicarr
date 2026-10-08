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

"""CI gate: no on-scale ``rounded-[Npx]`` literals in the frontend.

``rounded-[6px]`` is ``rounded-lg``. ``rounded-[4px]`` is ``rounded-md``.
``rounded-[2px]`` is ``rounded-sm``. ``rounded-[10px]`` is ``rounded-xl``.
``rounded-[14px]`` is ``rounded-2xl``. Pixel literals bypass ``--radius``, so
turning the one dial in ``index.css`` leaves those surfaces behind.

``rounded-[5px]`` is the named compact/toolbar Button step, not an on-scale
duplicate, and is not in this scan.

Contributor-facing only — no changeset (CLAUDE.md).

Wire-in: ``npm run lint:guards``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

# Same pattern as issue #994 acceptance grep (tsx only).
RADIUS_RE = re.compile(r"rounded(?:-[a-z]{1,2})?-\[(?:2|4|6|10|14)px\]")
SCALE = {"2": "sm", "4": "md", "6": "lg", "10": "xl", "14": "2xl"}


def _hits() -> list[str]:
    found: list[str] = []
    for path in sorted(SRC.rglob("*.tsx")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in RADIUS_RE.finditer(line):
                token = match.group(0)
                px = token[token.rfind("[") + 1 : token.rfind("px")]
                named = SCALE.get(px, "?")
                found.append(f"  {rel}:{lineno}: {token} — use rounded-{named}")
    return found


def main() -> int:
    found = _hits()
    if not found:
        print("Radius literal guard: ok (on-scale rounded-[Npx] is empty)")
        return 0
    print("On-scale rounded-[Npx] literals — use the radius scale:", file=sys.stderr)
    print("\n".join(found), file=sys.stderr)
    print("", file=sys.stderr)
    print("See DESIGN.md -> Radius.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
