#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import types
from types import SimpleNamespace

import pytest

import comicarr
from comicarr.app.downloads import postprocessing, pp_commands
from comicarr.postprocessor import FolderCheck


def _config(**overrides):
    values = {"CHECK_FOLDER": None, "ADDITIONAL_CHECK_FOLDERS": None}
    values.update(overrides)
    return SimpleNamespace(**values)


def test_monitored_folders_lists_check_folder_then_absolute_extras(tmp_path):
    main = str(tmp_path / "Comics")
    magazines = str(tmp_path / "Magazines")
    config = _config(
        CHECK_FOLDER=main,
        ADDITIONAL_CHECK_FOLDERS="%s\n\n  %s  \nrelative/path\n%s\n%s" % (magazines, magazines, main, "None"),
    )

    assert pp_commands.monitored_folders(config) == [main, magazines]


@pytest.mark.parametrize("check_folder", [None, "", "None"])
def test_extras_are_ignored_without_a_check_folder(tmp_path, check_folder):
    config = _config(CHECK_FOLDER=check_folder, ADDITIONAL_CHECK_FOLDERS=str(tmp_path))

    assert pp_commands.monitored_folders(config) == []


def test_extras_are_post_processing_roots(tmp_path):
    magazines = tmp_path / "Magazines"
    (magazines / "Wizard 001").mkdir(parents=True)
    config = _config(CHECK_FOLDER=str(tmp_path / "Comics"), ADDITIONAL_CHECK_FOLDERS=str(magazines))

    roots = pp_commands.configured_roots(config)

    assert magazines in roots
    assert pp_commands.validate_mapped_path(magazines / "Wizard 001", roots=roots) == (magazines / "Wizard 001")


@pytest.fixture
def monitor(monkeypatch):
    monkeypatch.setattr(comicarr, "IMPORTLOCK", False)
    monkeypatch.setattr(comicarr, "MONITOR_STATUS", "Waiting")
    updates = []
    monkeypatch.setattr("comicarr.helpers.job_management", lambda **kw: updates.append(kw))
    calls = []
    outcomes = {}

    def fake_run(request):
        calls.append(request)
        return types.SimpleNamespace(status=outcomes.get(request["nzb_folder"], "completed"))

    monkeypatch.setattr(postprocessing, "run", fake_run)
    return SimpleNamespace(updates=updates, calls=calls, outcomes=outcomes)


def test_monitor_scans_each_folder_and_skips_missing_ones(tmp_path, monkeypatch, monitor):
    main = tmp_path / "Comics"
    magazines = tmp_path / "Magazines"
    main.mkdir()
    magazines.mkdir()
    missing = tmp_path / "Gone"
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        _config(CHECK_FOLDER=str(main), ADDITIONAL_CHECK_FOLDERS="%s\n%s" % (missing, magazines)),
    )

    FolderCheck().run()

    assert [call["nzb_folder"] for call in monitor.calls] == [str(main), str(magazines)]
    assert all(call["source"] == "monitor" for call in monitor.calls)
    assert "last_run_completed" in monitor.updates[-1]


def test_only_check_folder_scans_it_once(tmp_path, monkeypatch, monitor):
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(CHECK_FOLDER=str(tmp_path)))

    FolderCheck().run()

    assert [call["nzb_folder"] for call in monitor.calls] == [str(tmp_path)]


def test_busy_processing_stops_the_pass_and_defers(tmp_path, monkeypatch, monitor):
    main = tmp_path / "Comics"
    magazines = tmp_path / "Magazines"
    main.mkdir()
    magazines.mkdir()
    monitor.outcomes[str(main)] = "busy"
    monkeypatch.setattr(comicarr, "CONFIG", _config(CHECK_FOLDER=str(main), ADDITIONAL_CHECK_FOLDERS=str(magazines)))

    result = FolderCheck().run()

    assert result == {"status": "IN PROGRESS"}
    assert [call["nzb_folder"] for call in monitor.calls] == [str(main)]
    assert comicarr.MONITOR_STATUS == "Waiting"
