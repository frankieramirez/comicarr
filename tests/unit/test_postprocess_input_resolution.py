#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import comicarr
from comicarr.postprocessor import PostProcessor


def _processor(folder, *, ddl=False, name="Saga.001", config, use_sab=0, use_nzbget=0):
    queue = MagicMock()
    queue.put.return_value = "queued"
    apilock = MagicMock()
    apilock.locked.return_value = False
    with (
        patch.object(comicarr, "APILOCK", apilock),
        patch.object(comicarr, "CONFIG", config),
        patch.object(comicarr, "USE_SABNZBD", use_sab),
        patch.object(comicarr, "USE_NZBGET", use_nzbget),
    ):
        processor = PostProcessor(name, str(folder), comicid="md-saga", queue=queue, ddl=ddl)
    return processor, queue


def _config(tmp_path, **overrides):
    values = {
        "FILE_OPTS": "move",
        "IGNORE_SEARCH_WORDS": [],
        "SAB_DIRECT_UNPACK": True,
        "SAB_DIRECTORY": str(tmp_path / "sab"),
        "NZBGET_DIRECTORY": str(tmp_path / "nzbget"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _run(processor, config, *, use_sab=0, use_nzbget=0):
    with (
        patch.object(comicarr, "CONFIG", config),
        patch.object(comicarr, "USE_SABNZBD", use_sab),
        patch.object(comicarr, "USE_NZBGET", use_nzbget),
        patch.object(processor, "_process_manga", return_value="manga") as manga,
        patch("comicarr.postprocessor.db") as mock_db,
    ):
        mock_db.select_one.return_value = {"ComicID": "md-saga", "ContentType": "manga"}
        result = processor.Process()
    return result, manga


def test_sab_resolution_prefers_configured_job_directory(tmp_path):
    config = _config(tmp_path)
    resolved = tmp_path / "sab" / "Saga.001"
    resolved.mkdir(parents=True)
    processor, _queue = _processor(tmp_path / "incoming", config=config, use_sab=1)

    result, manga = _run(processor, config, use_sab=1)

    assert result == "manga"
    assert processor.nzb_folder == str(resolved)
    manga.assert_called_once_with()


def test_sab_resolution_keeps_passed_folder_when_job_is_nested_there(tmp_path):
    config = _config(tmp_path)
    incoming = tmp_path / "incoming"
    (incoming / "Saga.001").mkdir(parents=True)
    processor, _queue = _processor(incoming, config=config, use_sab=1)

    result, _manga = _run(processor, config, use_sab=1)

    assert result == "manga"
    assert processor.nzb_folder == str(incoming)


def test_sab_resolution_falls_back_to_incoming_basename(tmp_path):
    config = _config(tmp_path)
    incoming = tmp_path / "completed" / "random-job-id"
    resolved = tmp_path / "sab" / incoming.name
    resolved.mkdir(parents=True)
    processor, _queue = _processor(incoming, config=config, use_sab=1)

    result, _manga = _run(processor, config, use_sab=1)

    assert result == "manga"
    assert processor.nzb_folder == str(resolved)


def test_missing_sab_paths_stop_before_processing(tmp_path):
    config = _config(tmp_path)
    processor, queue = _processor(tmp_path / "missing", config=config, use_sab=1)

    result, manga = _run(processor, config, use_sab=1)

    assert result == "queued"
    assert processor.valreturn[-1]["mode"] == "stop"
    queue.put.assert_called_once_with(processor.valreturn)
    manga.assert_not_called()


def test_nzbget_resolution_preserves_existing_override_order(tmp_path):
    config = _config(tmp_path)
    sab_path = tmp_path / "sab" / "Saga.001"
    sab_path.mkdir(parents=True)
    processor, _queue = _processor(tmp_path / "incoming", config=config, use_sab=1, use_nzbget=1)

    result, _manga = _run(processor, config, use_sab=1, use_nzbget=1)

    assert result == "manga"
    assert processor.nzb_folder == str(tmp_path / "nzbget" / "Saga.001")


def test_manual_and_ddl_runs_skip_downloader_path_resolution(tmp_path):
    config = _config(tmp_path)
    manual_folder = tmp_path / "manual"
    manual, _queue = _processor(manual_folder, name="Manual Run", config=config, use_sab=1, use_nzbget=1)
    ddl_folder = tmp_path / "ddl"
    ddl, _queue = _processor(ddl_folder, ddl=True, config=config, use_sab=1, use_nzbget=1)

    manual_result, _manga = _run(manual, config, use_sab=1, use_nzbget=1)
    ddl_result, _manga = _run(ddl, config, use_sab=1, use_nzbget=1)

    assert manual_result == "manga"
    assert manual.nzb_folder == str(manual_folder)
    assert ddl_result == "manga"
    assert ddl.nzb_folder == str(ddl_folder)


def test_disabled_downloaders_do_not_require_config_for_manga_branch(tmp_path):
    config = _config(tmp_path)
    processor, _queue = _processor(tmp_path / "incoming", config=config)

    result, manga = _run(processor, None)

    assert result == "manga"
    manga.assert_called_once_with()
