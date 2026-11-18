#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
"""Completed-download path mapping for SABnzbd and NZBGet (moved in #1526).

CDH_MAP rewrites the path a download client reports into the same file under
the folder Comicarr sees (SAB_DIRECTORY / NZBGET_DIRECTORY).
"""

from pathlib import PurePosixPath
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import comicarr
from comicarr.app.downloads import cdh_mapping


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(comicarr, "OS_DETECT", "Linux", raising=False)


def _sab_config(**overrides):
    values = dict(
        SAB_HOST="http://sab.example:8080",
        SAB_APIKEY="key",
        SAB_DIRECTORY="/mnt/comics-downloads",
        SAB_CATEGORY=None,
        SAB_VERSION="4.3.0",
        SAB_VERIFY=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_sab_without_category_keeps_the_job_folder(monkeypatch, linux):
    monkeypatch.setattr(comicarr, "CONFIG", _sab_config())
    cdh = cdh_mapping.CDH_MAP("/downloads/complete/Example.001/Example 001.cbz", sab=True)
    monkeypatch.setattr(cdh, "sendsab", lambda params: {"status": {"completedir": "/downloads/complete"}})

    assert cdh.the_sequence() == PurePosixPath("/mnt/comics-downloads/Example.001/Example 001.cbz")


def test_sab_category_without_job_folders_maps_the_file_only(monkeypatch, linux):
    monkeypatch.setattr(comicarr, "CONFIG", _sab_config(SAB_CATEGORY="comics"))
    cdh = cdh_mapping.CDH_MAP("/downloads/comics/Example 001.cbz", sab=True)

    def sendsab(params):
        if params["mode"] == "get_config":
            return {"config": {"categories": [{"name": "comics", "dir": "/downloads/comics*"}]}}
        return {"status": {"completedir": "/downloads/complete"}}

    monkeypatch.setattr(cdh, "sendsab", sendsab)

    assert cdh.the_sequence() == PurePosixPath("/mnt/comics-downloads/Example 001.cbz")


def test_nzbget_category_with_append_category_dir(monkeypatch, linux):
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(NZBGET_DIRECTORY="/mnt/nzb", NZBGET_CATEGORY="Comics"))
    server = MagicMock()
    server.config.return_value = [
        {"Name": "DestDir", "Value": "/downloads/dst"},
        {"Name": "AppendCategoryDir", "Value": "yes"},
        {"Name": "Category1.Name", "Value": "Comics"},
        {"Name": "Category1.DestDir", "Value": "/downloads/dst/Comics"},
    ]
    cdh = cdh_mapping.CDH_MAP("/downloads/dst/Comics/Example.001/Example 001.cbz", nzbget=True, nzbget_server=server)

    assert cdh.the_sequence() == PurePosixPath("/mnt/nzb/Example.001/Example 001.cbz")
