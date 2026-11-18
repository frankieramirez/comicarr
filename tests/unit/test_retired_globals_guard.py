#  Tests for scripts/check_retired_globals.py — the retired-name gate (#488).
#
#  Deleting a global does not make its return an error: Python creates the
#  attribute on first assignment, so only a source scan fails at author time.
#  These tests pin both halves of the gate: a real reintroduction is caught,
#  and a longer identifier that merely contains a retired name is not. The
#  second half is why the release-evaluation global (#875) can be registered at
#  all — ComicInfo.xml is a permanent part of this domain, and the XML fixture
#  named after it is not the retired global.
#
#  Every case is built from the registry rather than written out, because this
#  file is itself inside a scanned tree: a literal retired name here would trip
#  the very guard under test. That also means new registry entries are covered
#  the day they are added.

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_retired_globals.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_retired_globals", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GUARD = _load()
RETIRED = sorted(GUARD.RETIRED_GLOBALS)


@pytest.fixture
def scan(tmp_path, monkeypatch):
    def run(source):
        module = tmp_path / "comicarr" / "leaf.py"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text(source + "\n")

        monkeypatch.setattr(GUARD, "ROOT", tmp_path)
        monkeypatch.setattr(GUARD, "SCAN_ROOTS", ("comicarr",))
        monkeypatch.setattr(GUARD, "SCAN_FILES", ())
        return GUARD.main()

    return run


def test_the_tree_is_clean():
    """The repository itself passes — the regression gate for the guard."""
    assert GUARD.main() == 0


def test_every_retired_name_is_registered_with_a_reason():
    assert GUARD.RETIRED_GLOBALS, "the registry parsed empty"
    assert all(reason.strip() for reason in GUARD.RETIRED_GLOBALS.values())
    assert set(GUARD.RETIRED_PATTERNS) == set(GUARD.RETIRED_GLOBALS)


@pytest.mark.parametrize("name", RETIRED)
@pytest.mark.parametrize("form", ["comicarr.%s = []", "if comicarr.%s:", "value = %s"])
def test_a_reintroduction_is_caught(scan, name, form):
    assert scan(form % name) == 1


@pytest.mark.parametrize("name", RETIRED)
@pytest.mark.parametrize("form", ["_%s_TEMPLATE = 1", "xml = _%s_TEMPLATE.format(title=title)", "value = %s_DEFAULT"])
def test_a_longer_identifier_is_not_a_violation(scan, name, form):
    assert scan(form % name) == 0


@pytest.mark.parametrize("name", RETIRED)
def test_a_comment_is_not_a_violation(scan, name):
    assert scan("#  comicarr.%s was retired; see the registry for the replacement." % name) == 0


def _scan_file(tmp_path, monkeypatch, relative, source):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source + "\n")
    monkeypatch.setattr(GUARD, "ROOT", tmp_path)
    monkeypatch.setattr(GUARD, "SCAN_ROOTS", ("tests",))
    monkeypatch.setattr(GUARD, "SCAN_FILES", ())
    return GUARD.main()


def test_a_historical_release_driver_may_name_runtime_fields(tmp_path, monkeypatch):
    """The upgrade-matrix builder drives old releases, whose globals are real."""
    name = sorted(GUARD._RUNTIME_FIELD_NAMES)[0]
    relative = sorted(GUARD.HISTORICAL_FILES)[0]
    assert _scan_file(tmp_path, monkeypatch, relative, "comicarr.%s = data_dir" % name) == 0


def test_a_historical_release_driver_is_still_checked_for_other_names(tmp_path, monkeypatch):
    other = sorted(set(GUARD.RETIRED_GLOBALS) - GUARD._RUNTIME_FIELD_NAMES)[0]
    relative = sorted(GUARD.HISTORICAL_FILES)[0]
    assert _scan_file(tmp_path, monkeypatch, relative, "comicarr.%s = []" % other) == 1


def test_the_runtime_field_exemption_is_limited_to_historical_files(tmp_path, monkeypatch):
    name = sorted(GUARD._RUNTIME_FIELD_NAMES)[0]
    assert _scan_file(tmp_path, monkeypatch, "tests/unit/test_new.py", "comicarr.%s = data_dir" % name) == 1
