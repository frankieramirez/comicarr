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
from comicarr.app.manga import add as manga_add


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(FOLDER_FORMAT="$Series ($Year)"), raising=False)


def test_an_existing_plain_title_folder_is_reused(tmp_path):
    (tmp_path / "Moon Garden").mkdir()

    assert manga_add._manga_series_folder(str(tmp_path), "Moon Garden", "2019") == str(tmp_path / "Moon Garden")


def test_the_formatted_folder_is_used_when_nothing_exists(tmp_path):
    assert manga_add._manga_series_folder(str(tmp_path), "Moon Garden", "2019") == str(tmp_path / "Moon Garden (2019)")


def test_an_existing_formatted_folder_wins_over_a_plain_one(tmp_path):
    (tmp_path / "Moon Garden").mkdir()
    (tmp_path / "Moon Garden (2019)").mkdir()

    assert manga_add._manga_series_folder(str(tmp_path), "Moon Garden", "2019") == str(tmp_path / "Moon Garden (2019)")


def test_a_title_that_climbs_out_of_the_destination_is_not_reused(tmp_path):
    dest = tmp_path / "manga"
    dest.mkdir()
    (tmp_path / "outside").mkdir()

    assert manga_add._manga_series_folder(str(dest), "../outside", "2019").startswith(str(dest))
