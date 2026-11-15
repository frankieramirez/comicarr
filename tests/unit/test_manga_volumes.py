#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Owned and grabbed manga volumes (#1278)."""

import pytest

import comicarr
from comicarr.app.manga import volumes
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import metadata


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if getattr(comicarr, "LOG_LEVEL", None) is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    metadata.create_all(get_engine())
    yield
    shutdown_engine()


def test_a_grab_then_the_file_landing_owns_the_volume():
    assert volumes.record_volume("md-x", "01", volumes.SNATCHED) == "md-x-v1"
    assert volumes.volume_states("md-x") == {"1": "Snatched"}
    assert volumes.covering_volumes(volumes.volume_states("md-x")) == set()

    volumes.record_volume("md-x", "1", volumes.DOWNLOADED, location="X v01.cbz")

    assert volumes.volume_states("md-x") == {"1": "Downloaded"}
    assert volumes.covering_volumes(volumes.volume_states("md-x")) == {"1"}


def test_a_later_grab_does_not_unown_a_downloaded_volume():
    volumes.record_volume("md-x", "1", volumes.DOWNLOADED, location="X v01.cbz")
    volumes.record_volume("md-x", "1", volumes.SNATCHED)
    assert volumes.volume_states("md-x") == {"1": "Downloaded"}


def test_no_volume_number_records_nothing():
    assert volumes.record_volume("md-x", None, volumes.SNATCHED) is None
    assert volumes.record_volume("md-x", "none", volumes.SNATCHED) is None
    assert volumes.volume_states("md-x") == {}
    assert volumes.volume_states(None) == {}


def test_volumes_are_kept_per_series():
    volumes.record_volume("md-x", "1", volumes.DOWNLOADED)
    volumes.record_volume("md-y", "2", volumes.SNATCHED)
    assert volumes.volume_states("md-x") == {"1": "Downloaded"}
    assert volumes.volume_states("md-y") == {"2": "Snatched"}
