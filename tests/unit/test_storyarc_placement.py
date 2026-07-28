#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Characterization for the story-arc directory placement.

`updatearc_locs` had no test at all -- it was the one placement call site no
test in the repo ever executed. It carries the `SKIP` policy: anything already
sitting at the destination means no placement, and the location is recorded
either way.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr.app.common.placement import OnExisting, PlacementError, Purpose
from comicarr.app.storyarcs import service
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, issues, metadata, storyarcs


class Config:
    def __init__(self, **overrides):
        self.__dict__.update(
            dict(
                ARC_FILEOPS="copy",
                ARC_FILEOPS_SOFTLINK_RELATIVE=False,
                FILE_OPTS="move",
                MULTIPLE_DEST_DIRS="None",
                RENAME_FILES=False,
                READ2FILENAME=False,
                ARC_FOLDERFORMAT="$arc",
                STORYARCDIR=True,
            )
        )
        self.__dict__.update(overrides)

    def __getattr__(self, name):
        return False


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


@pytest.fixture
def arc(tmp_path):
    series_folder = tmp_path / "library" / "Saga"
    series_folder.mkdir(parents=True)
    arc_root = tmp_path / "arcs"
    arc_root.mkdir()
    placed = series_folder / "Saga 001.cbz"
    placed.write_bytes(b"in the library")

    with get_engine().begin() as conn:
        conn.execute(insert(comics).values(ComicID="C1", ComicName="Saga", ComicLocation=str(series_folder)))
        conn.execute(
            insert(issues).values(
                IssueID="I1",
                ComicID="C1",
                ComicName="Saga",
                Issue_Number="1",
                Status="Downloaded",
                Location="Saga 001.cbz",
            )
        )
        conn.execute(
            insert(storyarcs).values(
                StoryArcID="SA1",
                StoryArc="The Chosen",
                IssueArcID="A1",
                IssueID="I1",
                ComicID="C1",
                ComicName="Saga",
                IssueNumber="1",
                ReadingOrder=1,
                Publisher="Image",
                IssuePublisher="Image",
                IssueDate="2012-03-14",
                SeriesYear="2012",
            )
        )

    return {
        "series_folder": series_folder,
        "arc_root": arc_root,
        "placed": placed,
        "arc_issues": [
            {
                "IssueID": "I1",
                "StoryArc": "The Chosen",
                "StoryArcID": "SA1",
                "Publisher": "Image",
                "IssuePublisher": "Image",
                "ComicID": "C1",
                "ComicName": "Saga",
                "IssueNumber": "1",
                "ReadingOrder": 1,
            }
        ],
    }


def _run(arc, *, config=None, place=None):
    calls = []
    real_place = service.placement.place

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        if place is not None:
            return place(*args, **kwargs)
        return real_place(*args, **kwargs)

    cfg = config or Config(STORYARC_LOCATION=str(arc["arc_root"]))
    filechecker = MagicMock()
    # The real one creates the directory; a bare mock would leave the arc folder
    # missing and every placement would fail for the wrong reason.
    filechecker.validateAndCreateDirectory.side_effect = lambda path, **_kw: os.makedirs(path, exist_ok=True) or True
    with (
        patch.object(comicarr, "CONFIG", cfg),
        patch.object(comicarr, "filechecker", filechecker),
        patch.object(service.placement, "place", spy),
    ):
        service.updatearc_locs("SA1", arc["arc_issues"])

    with get_engine().connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(select(storyarcs))]
    return calls, rows


def test_the_arc_copy_carries_arc_intent_and_the_skip_policy(arc):
    calls, _rows = _run(arc)

    assert len(calls) == 1
    (source, destination, purpose), keywords = calls[0]
    assert source == str(arc["placed"]), "the source must be the series file, so a link resolves into the library"
    assert str(arc["arc_root"]) in destination
    assert purpose is Purpose.ARC
    assert keywords["on_existing"] is OnExisting.SKIP


def test_an_existing_destination_means_no_placement_and_no_error(arc):
    """The `if not os.path.isfile(pathdst)` guard, now expressed as SKIP."""
    calls, _rows = _run(arc)
    destination = calls[0][0][1]
    assert os.path.exists(destination)
    with open(destination, "rb") as handle:
        first_run = handle.read()

    # A second run finds the file already there and must neither fail nor
    # re-place it.
    calls_again, rows = _run(arc)

    assert len(calls_again) == 1
    result = calls_again[0]
    assert result[1]["on_existing"] is OnExisting.SKIP
    with open(destination, "rb") as handle:
        assert handle.read() == first_run
    assert rows, "the arc row must still be updated on a skipped placement"


def test_the_location_is_recorded_even_when_placement_is_skipped(arc):
    """Preserved, not endorsed.

    `updateloc = pathdst` sits outside the old guard, so the recorded location
    points at the arc path whether or not this run put a file there. Correct
    when an earlier run placed it; wrong when the file there is something else.
    """
    _calls, _rows = _run(arc)
    _calls_again, rows = _run(arc)

    locations = [r["Location"] for r in rows if r["IssueID"] == "I1"]
    assert any(str(arc["arc_root"]) in (loc or "") for loc in locations), locations


def test_a_failed_placement_skips_the_issue_without_raising(arc):
    """PlacementError subclasses OSError, so the narrow handler still catches."""

    def boom(*_args, **_kwargs):
        raise PlacementError("arc directory is read-only")

    calls, rows = _run(arc, place=boom)

    assert len(calls) == 1
    locations = [r["Location"] for r in rows if r["IssueID"] == "I1"]
    assert not any(str(arc["arc_root"]) in (loc or "") for loc in locations), (
        "a failed placement must not record the arc location"
    )
