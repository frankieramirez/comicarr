#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
"""Landed Alembic revisions keep importing after root modules move.

A landed revision can never be edited (``check_migration_checksums.py``), so
the ``comicarr`` names it imports are a compatibility contract. The
zero-legacy moves (#1402) relocate root modules under ``comicarr/app/``; this
test fails if a move breaks a name a landed revision still imports.
"""

import ast
import importlib
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _comicarr_imports():
    for path in sorted(VERSIONS.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "comicarr":
                for alias in node.names:
                    yield pytest.param(node.module, alias.name, id=f"{path.stem}:{node.module}.{alias.name}")


@pytest.mark.parametrize(("module", "name"), list(_comicarr_imports()))
def test_landed_revision_import_resolves(module, name):
    assert hasattr(importlib.import_module(module), name)
