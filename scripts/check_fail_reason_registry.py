#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""CI completeness gate: every writable fail_reason base token is classified.

Hybrid AST scan (#527): equate base tokens declared in
``comicarr/app/attention/_policy.py`` with every base token the codebase can
write onto ``pipeline_journal.fail_reason`` via:

* ``attention.record(Failure(...))``
* ``attention.record(ManualReview(...))``
* temporary direct ``journal.mark_failed(...)`` / ``mark_manual_review(...)``
* the inline quarantine write at ``journal.py`` (immutable payload conflict)

Runtime stays fail-open (#523). Contributor-facing only — no changeset.

Wire-in: ``npm run lint:guards``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REASONS_PATH = ROOT / "comicarr" / "app" / "attention" / "_policy.py"

# Trees that can write pipeline_journal.fail_reason. Vendor and test fixtures
# are out of scope for the gate.
SCAN_GLOBS = (
    "comicarr/app/**/*.py",
    "comicarr/failed.py",
    "comicarr/process.py",
)

SKIP_DIR_NAMES = {"_vendor", "__pycache__", ".venv", "node_modules"}

# Functions that accept a variable reason and forward it. Callers must be
# scanned so concrete bases still surface. Adding a new dynamic writer without
# allowlisting fails with the unresolvable-site message.
#
# Keyed on (relative file path, function name) — never the bare function name
# — so a same-named function in an unrelated file (e.g. some other "record")
# can never ride along on this exemption.
PASS_THROUGH_WRITERS = frozenset(
    {
        ("comicarr/app/attention/_recording.py", "record"),
        ("comicarr/app/attention/_recording.py", "_record_on_connection"),
        ("comicarr/failed.py", "terminalize_failed_download"),
        ("comicarr/app/downloads/service.py", "_quarantine_postprocess_item"),
    }
)

MARK_ATTRS = frozenset({"Failure", "ManualReview", "mark_failed", "mark_manual_review"})

# Parameter names that indicate a pass-through body (the enclosing function
# is the allowlisted writer; callers supply the literal).
PASS_THROUGH_PARAM_NAMES = frozenset({"fail_reason", "reason"})

# The one seam where a *typed attribute access* (not a bare Name) carries a
# dynamic reason: ``entry.reason`` inside ``_record_on_connection``, where
# ``entry`` is a typed Failure/ManualReview instance. (file, function,
# attribute base name) — narrower than "any `.reason` inside an allowlisted
# function" so a second dynamic `.reason` read added later to an allowlisted
# function does not silently ride along.
DYNAMIC_REASON_ATTR_SEAM = ("comicarr/app/attention/_recording.py", "_record_on_connection", "entry")


def _base_token(value: str) -> str:
    token = value.strip()
    if not token:
        return token
    return token.split(":", 1)[0]


def _literal_set_from_assign(node: ast.Assign) -> set[str] | None:
    """Extract string members from NAME = frozenset({...}) / set / dict keys."""
    value = node.value
    # frozenset({...}) / set({...})
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        if value.func.id in ("frozenset", "set") and value.args:
            value = value.args[0]
    if isinstance(value, (ast.Set, ast.List, ast.Tuple)):
        out = set()
        for elt in value.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.add(elt.value)
            else:
                return None
        return out
    if isinstance(value, ast.Dict):
        out = set()
        for key in value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                out.add(key.value)
            else:
                return None
        return out
    return None


def _load_registry() -> set[str]:
    """Parse comicarr/app/attention/_policy.py via AST — no package import, no sqlalchemy needed."""
    tree = ast.parse(REASONS_PATH.read_text(encoding="utf-8"), filename=str(REASONS_PATH))
    buckets: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        members = _literal_set_from_assign(node)
        if members is None:
            continue
        for name in names:
            buckets[name] = members

    phrases = buckets.get("REASON_PHRASES", set())
    flat = buckets.get("NON_ACTIONABLE_FLAT", set())
    composite = buckets.get("NON_ACTIONABLE_COMPOSITE", set())
    recon = buckets.get("RECONCILIATION", set())
    known = buckets.get("KNOWN_BASE_TOKENS")
    if known is None:
        known = phrases | flat | composite

    for token in flat | composite:
        if token not in recon:
            raise SystemExit("Excluded base token %r has no RECONCILIATION entry in _policy.py" % token)
    for token in phrases:
        if token in flat or token in composite:
            raise SystemExit("Base token %r is both admitted (REASON_PHRASES) and excluded" % token)
    return set(known)


def _collect_module_string_constants(path: Path) -> dict[str, str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return {}
    out: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                out[target.id] = node.value.value
    return out


def _build_const_maps(files: list[Path]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for path in files:
        for name, value in _collect_module_string_constants(path).items():
            if "REASON" in name or name.startswith("FAIL_"):
                mapping[name] = _base_token(value)
    return mapping


def _const_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _string_from(node: ast.AST, const_map: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
            left = node.left.value
            if "%s" in left or "%(" in left:
                return left.split("%", 1)[0].rstrip(":")
            return left
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                break
        if parts:
            joined = "".join(parts)
            if joined.endswith(":"):
                return joined.rstrip(":")
            return joined.split(":", 1)[0] if ":" in joined else joined
    name = _const_name(node)
    if name and name in const_map:
        return const_map[name]
    return None


def _strings_from(node: ast.AST, const_map: dict[str, str], assigns: dict[str, ast.AST] | None = None) -> set[str]:
    """Resolve one or more base tokens from an expression (including ternaries / names)."""
    assigns = assigns or {}
    direct = _string_from(node, const_map)
    if direct is not None:
        return {_base_token(direct)}
    # Ternary: both branches are reason literals.
    if isinstance(node, ast.IfExp):
        return _strings_from(node.body, const_map, assigns) | _strings_from(node.orelse, const_map, assigns)
    # Local Name bound to a prior assignment in the same function (e.g. `reason = ...`).
    if isinstance(node, ast.Name) and node.id in assigns:
        return _strings_from(assigns[node.id], const_map, assigns)
    return set()


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _reason_arg(node: ast.Call, attr: str) -> ast.AST | None:
    if attr in {"Failure", "ManualReview"}:
        for kw in node.keywords:
            if kw.arg == "reason":
                return kw.value
        return None
    if attr == "mark_failed":
        if len(node.args) >= 2:
            return node.args[1]
        for kw in node.keywords:
            if kw.arg in ("fail_reason", "reason"):
                return kw.value
    if attr == "mark_manual_review":
        if len(node.args) >= 2:
            return node.args[1]
        for kw in node.keywords:
            if kw.arg in ("reason", "fail_reason"):
                return kw.value
    return None


def _enclosing_function_names(tree: ast.AST) -> dict[int, str]:
    """Map lineno → innermost function name for pass-through detection."""
    mapping: dict[int, str] = {}

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef):
            self.stack.append(node.name)
            for child in ast.walk(node):
                if child is not node and hasattr(child, "lineno"):
                    mapping[child.lineno] = node.name
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

    Visitor().visit(tree)
    return mapping


def _local_assigns(tree: ast.AST) -> dict[int, dict[str, ast.AST]]:
    """Per-function map of simple ``name = expr`` assignments, keyed by any
    lineno belonging to that function (so a call site can resolve locals)."""
    by_func: dict[str, dict[str, ast.AST]] = {}
    lineno_to_func: dict[int, str] = {}

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef):
            assigns: dict[str, ast.AST] = {}
            for child in ast.walk(node):
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            assigns[target.id] = child.value
                if child is not node and hasattr(child, "lineno"):
                    lineno_to_func[child.lineno] = node.name
            by_func[node.name] = assigns
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

    Visitor().visit(tree)
    # lineno → that function's assign map
    return {lineno: by_func[name] for lineno, name in lineno_to_func.items()}


def _scan_file(path: Path, const_map: dict[str, str]) -> tuple[set[str], list[str]]:
    rel = path.relative_to(ROOT).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError) as e:
        return set(), ["%s: cannot parse: %s" % (rel, e)]

    found: set[str] = set()
    errors: list[str] = []
    enclosing = _enclosing_function_names(tree)
    local_assigns = _local_assigns(tree)

    if rel.endswith("app/downloads/journal.py"):
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.startswith("immutable_payload_conflict"):
                    found.add(_base_token(node.value))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        attr = _call_name(node)
        if attr is None:
            continue
        if (rel, attr) in PASS_THROUGH_WRITERS:
            continue
        if attr not in MARK_ATTRS:
            continue

        reason_node = _reason_arg(node, attr)
        lineno = getattr(node, "lineno", "?")
        if reason_node is None:
            errors.append(_unresolvable_msg(rel, lineno))
            continue

        # Inside an allowlisted pass-through function body, a bare Name is OK.
        if isinstance(reason_node, ast.Name) and reason_node.id in PASS_THROUGH_PARAM_NAMES:
            parent = enclosing.get(lineno)
            if (rel, parent) in PASS_THROUGH_WRITERS:
                continue
        # The one dynamic-attribute seam (see DYNAMIC_REASON_ATTR_SEAM):
        # ``entry.reason`` inside ``_record_on_connection`` specifically, not
        # any ``.reason`` access inside any allowlisted function.
        if (
            isinstance(reason_node, ast.Attribute)
            and reason_node.attr == "reason"
            and isinstance(reason_node.value, ast.Name)
            and (rel, enclosing.get(lineno), reason_node.value.id) == DYNAMIC_REASON_ATTR_SEAM
        ):
            continue

        assigns = local_assigns.get(lineno, {}) if isinstance(lineno, int) else {}
        tokens = _strings_from(reason_node, const_map, assigns)
        if not tokens:
            errors.append(_unresolvable_msg(rel, lineno))
            continue
        found |= tokens

    return found, errors


def _unresolvable_msg(rel: str, lineno) -> str:
    return (
        "Cannot statically resolve fail_reason at %s:%s.\n"
        "Either pass a reasons.py constant / string literal, or add this site to\n"
        "PASS_THROUGH_WRITERS in scripts/check_fail_reason_registry.py and ensure\n"
        "every caller is scanned." % (rel, lineno)
    )


def _iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for pattern in SCAN_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            if SKIP_DIR_NAMES.intersection(path.parts):
                continue
            files.append(path)
    return sorted(set(files))


def main() -> int:
    registry = _load_registry()
    files = _iter_scan_files()
    const_map = _build_const_maps(files)

    writable: set[str] = set()
    errors: list[str] = []

    for path in files:
        found, file_errors = _scan_file(path, const_map)
        writable |= found
        errors.extend(file_errors)

    missing = sorted(writable - registry)

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
            print("", file=sys.stderr)

    if missing:
        for token in missing:
            print(
                "fail_reason base token not in the actionability registry:\n"
                "\n"
                "  token:  %s\n"
                "\n"
                "Every base token written to pipeline_journal must be classified in\n"
                "comicarr/app/attention/_policy.py before merge.\n"
                "\n"
                "You owe a verdict against the actionability test:\n"
                "  (1) ADMIT  — resolving needs info/authority/judgement the operator has\n"
                "               and the system does not\n"
                "  (2) EXCLUDE — only if the system reconciles the item (never leave\n"
                "               Status='Snatched'); record blocklist+re-want vs re-want only\n"
                "\n"
                "Also add the operator-facing phrase next to the verdict (band display).\n"
                "\n"
                "Unknown tokens are admitted at runtime (fail-open) so production does not\n"
                "strand issues — CI is the gate. See Wayfinder map #520 / issue #523." % token,
                file=sys.stderr,
            )
            print("", file=sys.stderr)

    if errors or missing:
        return 1

    print("fail_reason registry OK: %d known, %d writable bases matched" % (len(registry), len(writable)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
