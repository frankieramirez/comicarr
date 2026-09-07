#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import datetime
import json
from types import SimpleNamespace

from sqlalchemy import create_engine

import comicarr
from comicarr import db
from comicarr.series_metadata import metadata_Series
from comicarr.tables import comics


def _run_metadata(tmp_path, monkeypatch, *, year):
    engine = create_engine("sqlite://")
    comics.create(engine)
    with engine.begin() as conn:
        conn.execute(
            comics.insert(),
            {
                "ComicID": "999001",
                "ComicName": "Edition Test",
                "ComicYear": str(year),
                "ComicPublisher": "Publisher",
                "ComicLocation": str(tmp_path),
                "ComicVersion": None,
                "Description": "A single issue with no edition clues.",
                "DescriptionEdit": None,
                "LatestDate": f"{year}-01-01",
                "NewPublish": False,
                "Collects": "None",
                "Type": "Print",
                "Total": 1,
                "Corrected_SeriesYear": None,
                "Corrected_Type": None,
            },
        )

    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(db, "upsert", lambda *args: None)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(CREATE_FOLDERS=False, SETDEFAULTVOLUME=True, SERIESJSON_FILE_PRIORITY=False),
        raising=False,
    )

    metadata_Series("999001").update_metadata()
    with (tmp_path / "series.json").open(encoding="utf-8") as stream:
        return json.load(stream)["metadata"]


def test_default_volume_is_written_without_turning_current_print_into_tpb(tmp_path, monkeypatch):
    metadata = _run_metadata(tmp_path, monkeypatch, year=datetime.date.today().year)

    assert metadata["booktype"] == "Print"
    assert metadata["volume"] == 1


def test_default_volume_does_not_suppress_past_year_one_shot_fallback(tmp_path, monkeypatch):
    metadata = _run_metadata(tmp_path, monkeypatch, year=datetime.date.today().year - 2)

    assert metadata["booktype"] == "One-Shot"
    assert metadata["volume"] == 1
