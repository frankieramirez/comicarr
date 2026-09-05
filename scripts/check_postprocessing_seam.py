#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""CI gate for the post-processing execution seam.

The post-processing module owns construction and execution of the legacy
``process.Process`` and ``postprocessor.PostProcessor`` implementations.  A
caller that constructs either directly bypasses journal claiming, maintenance
fencing, completion ordering, and lock ownership.  This AST gate catches
constructor calls while allowing imports used for metadata or type inspection.

The two implementation files are deliberately private exceptions: the new
coordinator adapter and the legacy ``process.py`` facade may construct the
legacy implementations.  Tests are outside the production tree and are not
scanned.

Wire-in: ``npm run lint:guards``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_GLOBS = ("comicarr/**/*.py",)
SKIP_DIR_NAMES = {"_vendor", "__pycache__", ".venv", "node_modules"}

ALLOWED_CONSTRUCTION_FILES = {
    "comicarr/app/downloads/postprocessing.py",
    "comicarr/process.py",
}

TARGET_MODULES = {
    "comicarr.process": "Process",
    "comicarr.postprocessor": "PostProcessor",
}


class UnreadableSource(Exception):
    """A production source file could not be read or parsed."""


def _iter_source_files():
    seen = set()
    for pattern in SCAN_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if not path.is_file() or path.suffix != ".py":
                continue
            if SKIP_DIR_NAMES.intersection(path.relative_to(ROOT).parts):
                continue
            if path not in seen:
                seen.add(path)
                yield path


def _dotted_name(node: ast.AST) -> str | None:
    """Resolve a syntactic dotted expression without evaluating it."""
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _package_of(rel: str) -> list[str]:
    return rel[: -len(".py")].split("/")[:-1]


def _resolve_import_module(node: ast.ImportFrom, rel: str) -> str:
    module = node.module or ""
    if not node.level:
        return module
    base = _package_of(rel)
    trimmed = base[: len(base) - (node.level - 1)]
    parts = [part for part in trimmed if part]
    if module:
        parts.append(module)
    return ".".join(parts)


def _bindings(tree: ast.AST, rel: str) -> dict[str, str]:
    """Map local names to the one of the two legacy target symbols they mean."""
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported = alias.name
                local = alias.asname or imported.split(".")[0]
                if imported == "comicarr":
                    bindings[local] = "comicarr"
                for module, symbol in TARGET_MODULES.items():
                    if imported == module:
                        bindings[local] = module
                    elif imported == f"{module}.{symbol}":
                        bindings[local] = f"{module}.{symbol}"
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_import_module(node, rel)
            if module in TARGET_MODULES:
                for alias in node.names:
                    if alias.name == TARGET_MODULES[module]:
                        bindings[alias.asname or alias.name] = f"{module}.{alias.name}"
            elif module == "comicarr":
                for alias in node.names:
                    if alias.name in {"process", "postprocessor"}:
                        bindings[alias.asname or alias.name] = f"comicarr.{alias.name}"
    return bindings


def _target_call(node: ast.Call, bindings: dict[str, str]) -> str | None:
    """Return the target symbol when a call constructs a legacy processor."""
    expression = _dotted_name(node.func)
    if expression is not None:
        parts = expression.split(".")
        bound_root = bindings.get(parts[0])
        if bound_root:
            expression = ".".join([bound_root, *parts[1:]])
        if expression in {"comicarr.process.Process", "comicarr.postprocessor.PostProcessor"}:
            return expression
    if isinstance(node.func, ast.Name):
        bound = bindings.get(node.func.id)
        return bound if bound in {"comicarr.process.Process", "comicarr.postprocessor.PostProcessor"} else None
    if isinstance(node.func, ast.Attribute):
        base = _dotted_name(node.func.value)
        bound_base = bindings.get(base or "")
        if bound_base in {"comicarr.process", "comicarr.postprocessor"}:
            expected = "Process" if bound_base.endswith("process") else "PostProcessor"
            return f"{bound_base}.{node.func.attr}" if node.func.attr == expected else None
        if base in {"comicarr.process", "comicarr.postprocessor"}:
            expected = "Process" if base.endswith("process") else "PostProcessor"
            return f"{base}.{node.func.attr}" if node.func.attr == expected else None
    return None


def _violations(path: Path, rel: str) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise UnreadableSource(f"{rel}: {exc}") from exc

    bindings = _bindings(tree, rel)
    # A raw call in the legacy module itself is still a construction of the
    # owned implementation. Definitions are not imports, so add this local
    # target explicitly rather than trusting every arbitrary local name.
    if rel == "comicarr/postprocessor.py":
        bindings["PostProcessor"] = "comicarr.postprocessor.PostProcessor"
    if rel == "comicarr/process.py":
        bindings["Process"] = "comicarr.process.Process"
    return [
        (node.lineno, target)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (target := _target_call(node, bindings)) is not None
    ]


def main() -> int:
    violations: list[tuple[str, int, str]] = []
    unreadable: list[str] = []

    for path in _iter_source_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED_CONSTRUCTION_FILES:
            continue
        try:
            found = _violations(path, rel)
        except UnreadableSource as exc:
            unreadable.append(str(exc))
            continue
        violations.extend((rel, lineno, target) for lineno, target in found)

    if violations:
        print("Direct legacy post-processing construction outside the owned seam:", file=sys.stderr)
        for rel, lineno, target in violations:
            print(f"  {rel}:{lineno}: {target}(...) ", file=sys.stderr)
        print("Route execution through comicarr.app.downloads.postprocessing.", file=sys.stderr)

    if unreadable:
        print("Could not parse — the post-processing seam was not checked:", file=sys.stderr)
        for message in unreadable:
            print(f"  {message}", file=sys.stderr)

    if violations or unreadable:
        return 1
    print("Post-processing seam OK: no direct legacy execution bypasses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
