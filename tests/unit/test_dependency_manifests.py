#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT_DIR = Path(__file__).resolve().parents[2]


def _dependency_names(requirements):
    return {canonicalize_name(Requirement(requirement).name) for requirement in requirements}


def _requirements_txt_names():
    names = set()

    for raw_line in (ROOT_DIR / "requirements.txt").read_text().splitlines():
        requirement = raw_line.strip()
        if requirement and not requirement.startswith("#"):
            names.add(canonicalize_name(Requirement(requirement).name))

    return names


def test_requirements_txt_contains_all_pyproject_runtime_dependencies():
    pyproject = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text())
    runtime_dependencies = _dependency_names(pyproject["project"]["dependencies"])

    assert runtime_dependencies - _requirements_txt_names() == set()
