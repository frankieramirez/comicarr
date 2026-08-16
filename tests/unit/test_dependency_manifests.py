#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from pathlib import Path

import yaml

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT_DIR = Path(__file__).resolve().parents[2]
SETUP_UV_ACTION = "astral-sh/setup-uv@ae62891fec2bb8e7d6c99fc78c9fec3a63790f8d"
ALTERNATE_PYTHON_MANIFESTS = (
    "requirements*.txt",
    "requirements*.in",
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "pdm.lock",
)


def test_python_dependencies_have_one_authoritative_lock():
    dependabot = yaml.safe_load((ROOT_DIR / ".github/dependabot.yml").read_text())
    root_ecosystems = {
        update["package-ecosystem"] for update in dependabot["updates"] if update["directory"] == "/"
    }

    alternate_manifests = sorted(
        path.name for pattern in ALTERNATE_PYTHON_MANIFESTS for path in ROOT_DIR.glob(pattern)
    )

    assert alternate_manifests == []
    assert "uv" in root_ecosystems
    assert "pip" not in root_ecosystems


def test_project_declares_a_setuptools_build_backend():
    pyproject = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text())

    assert pyproject["build-system"] == {
        "requires": ["setuptools>=61"],
        "build-backend": "setuptools.build_meta",
    }


def test_delivery_paths_install_from_the_committed_uv_lock():
    workflow = (ROOT_DIR / ".github/workflows/test.yml").read_text()
    dockerfile = (ROOT_DIR / "Dockerfile").read_text()

    assert workflow.count(SETUP_UV_ACTION) == 4
    assert "uv sync --locked --extra dev" in workflow
    assert workflow.count("uv sync --locked") >= 4
    assert "COMICARR_E2E_PYTHON: ${{ github.workspace }}/.venv/bin/python" in workflow
    assert "uv lock &&" not in dockerfile
    assert "uv sync --locked --no-dev --compile-bytecode" in dockerfile
