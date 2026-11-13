#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for scripts/check_migration_checksums.py, the landed-revision pin.

Upgrade-matrix fixtures are built by upgrading to a revision, which is only
valid while landed revision files never change.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_migration_checksums.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("check_migration_checksums", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture
def landed(tmp_path, guard):
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "__init__.py").write_text("", encoding="utf-8")
    (versions / "0001_first.py").write_text("revision = '0001_first'\n", encoding="utf-8")
    (versions / "0002_second.py").write_text("revision = '0002_second'\n", encoding="utf-8")
    manifest = tmp_path / "landed_checksums.json"
    assert guard.record(versions, manifest) == ["0001_first.py", "0002_second.py"]
    return versions, manifest


def test_repository_revisions_match_their_recorded_checksums(guard):
    assert guard.problems() == []


def test_unchanged_revisions_pass(guard, landed):
    assert guard.problems(*landed) == []


def test_an_edited_landed_revision_fails(guard, landed):
    versions, manifest = landed
    (versions / "0001_first.py").write_text("revision = '0001_first'\n# edited\n", encoding="utf-8")

    assert guard.problems(versions, manifest) == [
        "0001_first.py: landed revision was edited; add a new revision instead"
    ]


def test_a_deleted_landed_revision_fails(guard, landed):
    versions, manifest = landed
    (versions / "0002_second.py").unlink()

    assert guard.problems(versions, manifest) == ["0002_second.py: landed revision was deleted"]


def test_a_new_revision_fails_until_recorded(guard, landed):
    versions, manifest = landed
    (versions / "0003_third.py").write_text("revision = '0003_third'\n", encoding="utf-8")

    assert guard.problems(versions, manifest) == [
        "0003_third.py: no checksum recorded; run scripts/check_migration_checksums.py --record"
    ]
    assert guard.record(versions, manifest) == ["0003_third.py"]
    assert guard.problems(versions, manifest) == []


def test_record_never_rewrites_an_existing_checksum(guard, landed):
    versions, manifest = landed
    (versions / "0001_first.py").write_text("revision = '0001_first'\n# edited\n", encoding="utf-8")

    assert guard.record(versions, manifest) == []
    assert guard.problems(versions, manifest) == [
        "0001_first.py: landed revision was edited; add a new revision instead"
    ]


def test_crlf_checkout_matches_the_recorded_checksum(guard, landed):
    versions, manifest = landed
    (versions / "0001_first.py").write_bytes(b"revision = '0001_first'\r\n")

    assert guard.problems(versions, manifest) == []
