#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""A manga Series added over an existing plain-title folder uses that folder."""

from types import SimpleNamespace

import pytest

import comicarr
from comicarr import importer


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(FOLDER_FORMAT="$Series ($Year)"), raising=False)


def test_an_existing_plain_title_folder_is_reused(tmp_path):
    (tmp_path / "Moon Garden").mkdir()

    assert importer._manga_series_folder(str(tmp_path), "Moon Garden", "2019") == str(tmp_path / "Moon Garden")


def test_the_formatted_folder_is_used_when_nothing_exists(tmp_path):
    assert importer._manga_series_folder(str(tmp_path), "Moon Garden", "2019") == str(tmp_path / "Moon Garden (2019)")


def test_an_existing_formatted_folder_wins_over_a_plain_one(tmp_path):
    (tmp_path / "Moon Garden").mkdir()
    (tmp_path / "Moon Garden (2019)").mkdir()

    assert importer._manga_series_folder(str(tmp_path), "Moon Garden", "2019") == str(tmp_path / "Moon Garden (2019)")
