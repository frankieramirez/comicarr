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

"""CI gate: nothing outside Attention imports an Attention private submodule.

ADR-0003 gives ``comicarr.app.attention`` a deliberately small public seam —
``read``, ``resolve``, ``record``, plus the contract types — enumerated in
``comicarr/app/attention/__init__.py``'s ``__all__``. Reason predicates,
grouping and count helpers, serializers, action-specific resolvers, and the
reconciliation functions are implementation details, and the ADR says so.

Nothing enforced that. A seam that is only declared is a seam that drifts:
every caller that reaches past ``__all__`` into ``_policy`` or ``_read``
reconstructs a second copy of the actionability rule, which is precisely the
split ADR-0003 was written to end.

The gate is an AST scan rather than a regex because these crossings hide
inside function bodies (``journal.py`` imports its post-transition hook at the
call site to avoid an import cycle), and a line-oriented scan of module headers
would miss them entirely.

Legitimate and temporary crossings live in ``ALLOWLIST`` below, keyed on
``(relative file path, private module name)``. The list is **shrink-only**: an
entry that no longer matches a real import is itself an error, so deleting a
deprecated shim forces the deletion of its waiver in the same change.

Contributor-facing only — no changeset (CLAUDE.md).

Wire-in: ``npm run lint:guards``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ATTENTION_PKG = "comicarr.app.attention"

# The module's own package owns its internals; only crossings from outside it
# are seam violations.
ATTENTION_DIR = "comicarr/app/attention/"

# Only the backend package. Tests exercise private behaviour on purpose, and
# doing so does not put a second copy of the policy on a production path.
SCAN_GLOBS = ("comicarr/**/*.py",)

SKIP_DIR_NAMES = {"_vendor", "__pycache__", ".venv", "node_modules"}

# --------------------------------------------------------------------------
# Permanent internal hooks.
#
# These are not shims awaiting deletion. Each is a call site that must reach a
# private Attention entry point because routing it through the public seam
# would be wrong, not merely inconvenient. Removal trigger: only a redesign
# that gives Attention a public equivalent of the hook.
# --------------------------------------------------------------------------
PERMANENT_HOOKS = {
    # journal.py's immutable-payload-conflict quarantine is itself a terminal
    # transition, so it cannot call attention.record() — that would re-enter
    # the journal recursively. ADR-0003 names this private post-transition
    # hook explicitly; the call site's own comment explains the transaction
    # asymmetry. Removal trigger: none short of restructuring the quarantine
    # transition itself.
    ("comicarr/app/downloads/journal.py", "_reconciliation"): (
        "post-transition reconciliation hook for the immutable-payload-conflict "
        "quarantine, which cannot call attention.record() recursively (ADR-0003, #541)"
    ),
    # recovery.py runs the boot-time idempotent sweep over rows stranded by
    # excluded fail_reasons written before clause-2 reconciliation existed.
    # It is a one-shot repair, not an operator-facing recording path, so it
    # has no public counterpart. Removal trigger: retiring the sweep once no
    # supported upgrade path can still carry pre-#541 rows.
    ("comicarr/app/downloads/recovery.py", "_reconciliation"): (
        "boot-time idempotent sweep of pre-#541 excluded rows; a startup repair, not a recording path (#541)"
    ),
}

# --------------------------------------------------------------------------
# Deprecated compatibility shims — REMOVED NEXT RELEASE.
#
# ADR-0003 keeps the old Activity/Downloads routes alive for exactly one
# release as serialization-only adapters, and the PR body and changeset both
# promise they go away in the immediately following release. When a shim goes,
# its entry here must go with it — the stale-entry check makes that a prompted
# action rather than a forgotten one.
# --------------------------------------------------------------------------
DEPRECATED_SHIMS = {
    # Compatibility re-export module: comicarr.app.activity.reasons forwards
    # the reason policy Attention now owns. Removal trigger: deleting
    # comicarr/app/activity/reasons.py next release.
    ("comicarr/app/activity/reasons.py", "_policy"): (
        "deprecated re-export of the reason policy Attention now owns; "
        "delete with comicarr/app/activity/reasons.py next release"
    ),
    # Compatibility re-export module: comicarr.app.activity.reconcile forwards
    # the reconciliation entry points. Removal trigger: deleting
    # comicarr/app/activity/reconcile.py next release.
    ("comicarr/app/activity/reconcile.py", "_reconciliation"): (
        "deprecated re-export of Attention's reconciliation entry points; "
        "delete with comicarr/app/activity/reconcile.py next release"
    ),
    # Activity read projections still join against Attention's row reader and
    # unresolved predicate rather than composing GET /api/attention.
    # Removal trigger: retiring the deprecated GET /api/activity/band adapter
    # next release.
    ("comicarr/app/activity/queries.py", "_read"): (
        "deprecated /api/activity/band projection reusing Attention's row reader "
        "and unresolved predicate; delete with the band adapter next release"
    ),
    # Activity serialises Attention groups into the legacy band wire shape.
    # Removal trigger: as above — the band adapter's removal next release.
    ("comicarr/app/activity/queries.py", "_serialization"): (
        "deprecated band wire-shape serialization; delete with the /api/activity/band adapter next release"
    ),
    ("comicarr/app/activity/service.py", "_serialization"): (
        "deprecated band wire-shape serialization in the Activity read service; "
        "delete with the /api/activity/band adapter next release"
    ),
    # _batch_order backs the deprecated POST /api/downloads/needs-attention/*
    # adapters, whose compatibility tests pin the legacy result ordering.
    # Removal trigger: deleting those routes next release.
    ("comicarr/app/downloads/service.py", "_resolution"): (
        "deprecated needs-attention batch adapter reusing Attention's result "
        "ordering; delete with the /api/downloads/needs-attention routes next release"
    ),
}

ALLOWLIST = {**PERMANENT_HOOKS, **DEPRECATED_SHIMS}


def _iter_source_files():
    seen = set()
    for glob in SCAN_GLOBS:
        for path in sorted(ROOT.glob(glob)):
            if not path.is_file() or path.suffix != ".py":
                continue
            # Repository-relative parts only: a checkout that happens to live
            # under a directory named .venv or node_modules must not skip the
            # entire tree.
            if SKIP_DIR_NAMES.intersection(path.relative_to(ROOT).parts):
                continue
            if path in seen:
                continue
            seen.add(path)
            yield path


def _package_of(rel: str) -> str:
    """Dotted package containing ``rel`` — the base for relative imports."""
    # Dropping the final segment yields the containing package for both
    # ``pkg/mod.py`` and ``pkg/__init__.py``.
    return ".".join(rel[: -len(".py")].split("/")[:-1])


def _resolve_module(node: ast.ImportFrom, rel: str) -> str:
    """Absolute dotted module for an ``ImportFrom``, resolving relative levels."""
    module = node.module or ""
    if not node.level:
        return module
    base = _package_of(rel).split(".")
    # level 1 is the containing package, level 2 its parent, and so on.
    trimmed = base[: len(base) - (node.level - 1)]
    parts = [p for p in trimmed if p]
    if module:
        parts.append(module)
    return ".".join(parts)


def _private_submodule(dotted: str) -> str | None:
    """First path segment under the Attention package, when it is private."""
    if not dotted.startswith(ATTENTION_PKG + "."):
        return None
    head = dotted[len(ATTENTION_PKG) + 1 :].split(".", 1)[0]
    return head if head.startswith("_") else None


class UnreadableSource(Exception):
    """A scanned file could not be read or parsed.

    Returning "no crossings" for such a file would let the gate print its OK
    line for a file it never inspected — silent-pass behaviour in a gate whose
    only job is catching silent drift. The scan surfaces the failure instead.
    """


def _crossings(path: Path, rel: str) -> list[tuple[int, str]]:
    """(lineno, private module) for every Attention-private import in the file.

    Walks the whole tree, not just module-level nodes: several real crossings
    are function-local imports placed there to break an import cycle.

    Raises ``UnreadableSource`` when the file cannot be read or parsed.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise UnreadableSource("%s: %s" % (rel, exc)) from exc

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            dotted = _resolve_module(node, rel)
            private = _private_submodule(dotted)
            if private is not None:
                found.append((node.lineno, private))
                continue
            # ``from comicarr.app.attention import _read`` reaches the same
            # submodule by a different spelling.
            if dotted == ATTENTION_PKG:
                for alias in node.names:
                    if alias.name.startswith("_"):
                        found.append((node.lineno, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                private = _private_submodule(alias.name)
                if private is not None:
                    found.append((node.lineno, private))
    return found


def main() -> int:
    violations: list[tuple[str, int, str]] = []
    unreadable: list[str] = []
    matched: set[tuple[str, str]] = set()

    for path in _iter_source_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(ATTENTION_DIR):
            continue  # the module owns its own internals
        try:
            crossings = _crossings(path, rel)
        except UnreadableSource as exc:
            unreadable.append(str(exc))
            continue
        for lineno, private in crossings:
            key = (rel, private)
            if key in ALLOWLIST:
                matched.add(key)
                continue
            violations.append((rel, lineno, private))

    stale = sorted(set(ALLOWLIST) - matched)

    if violations:
        print("Private Attention submodule imported from outside %s:" % ATTENTION_DIR, file=sys.stderr)
        for rel, lineno, private in violations:
            print("  %s:%d: %s.%s" % (rel, lineno, ATTENTION_PKG, private), file=sys.stderr)
        print("", file=sys.stderr)
        print("ADR-0003 gives Attention one public seam — read, resolve, record, plus", file=sys.stderr)
        print("the contract types listed in comicarr/app/attention/__init__.py __all__.", file=sys.stderr)
        print("Reaching past it rebuilds the policy drift the module was created to end.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Call the public seam. If a crossing is genuinely unavoidable, add it to", file=sys.stderr)
        print("PERMANENT_HOOKS or DEPRECATED_SHIMS in scripts/check_attention_seam.py", file=sys.stderr)
        print("with the reason it exists and the trigger that removes it.", file=sys.stderr)

    if stale:
        if violations:
            print("", file=sys.stderr)
        print("Stale Attention seam allowlist entry — no such import in the tree:", file=sys.stderr)
        for rel, private in stale:
            print("  %s -> %s.%s" % (rel, ATTENTION_PKG, private), file=sys.stderr)
        print("", file=sys.stderr)
        print("The allowlist only ever shrinks. The crossing this entry covered is gone,", file=sys.stderr)
        print("so delete the entry from scripts/check_attention_seam.py.", file=sys.stderr)

    if unreadable:
        if violations or stale:
            print("", file=sys.stderr)
        print("Could not parse — the seam was NOT checked in these files:", file=sys.stderr)
        for message in unreadable:
            print("  %s" % message, file=sys.stderr)
        print("", file=sys.stderr)
        print("This is not a seam violation: the gate could not read the file at all,", file=sys.stderr)
        print("so it cannot say whether the file crosses the seam. Fix the file so it", file=sys.stderr)
        print("parses, then re-run scripts/check_attention_seam.py.", file=sys.stderr)

    if violations or stale or unreadable:
        return 1

    print("Attention seam OK: %d allowlisted crossing(s), no new ones" % len(ALLOWLIST))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
