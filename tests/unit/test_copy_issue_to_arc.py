#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""``copy_issue_to_arc``: the story-arc copy of a post-processed library issue."""

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr.app.common.placement import Outcome
from comicarr.app.storyarcs import ArcCopyError, ArcMembership, copy_issue_to_arc, service
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, issues, metadata, storyarcs


class Config:
    def __init__(self, **overrides):
        self.__dict__.update(
            dict(
                COPY2ARCDIR=True,
                ARC_FILEOPS="copy",
                ARC_FILEOPS_SOFTLINK_RELATIVE=False,
                READ2FILENAME=False,
                STORYARCDIR=True,
                STORYARC_LOCATION=None,
                ARC_FOLDERFORMAT="$arc ($spanyears)",
                DESTINATION_DIR=None,
                GRABBAG_DIR=None,
                REPLACE_SPACES=False,
                REPLACE_CHAR=".",
                MULTIPLE_DEST_DIRS="None",
                RENAME_FILES=False,
            )
        )
        self.__dict__.update(overrides)

    def __getattr__(self, name):
        return False


ARC = ArcMembership(story_arc="The Chosen", story_arc_id="SA1", issue_arc_id="A1", reading_order=7, publisher="Image")


@pytest.fixture
def library(tmp_path):
    series = tmp_path / "library" / "Saga"
    series.mkdir(parents=True)
    placed = series / "Saga 001.cbz"
    placed.write_bytes(b"in the library")
    return {"root": tmp_path, "placed": str(placed), "arcs": str(tmp_path / "arcs")}


def _copy(library, membership=ARC, **overrides):
    overrides.setdefault("STORYARC_LOCATION", library["arcs"])
    config = Config(**overrides)
    with patch.object(comicarr, "CONFIG", config):
        return copy_issue_to_arc(library["placed"], membership, span_years="2012", config=config)


@pytest.mark.parametrize(
    ("mode", "operation"), [("copy", "copy"), ("move", "copy"), ("hardlink", "hardlink"), ("softlink", "softlink")]
)
def test_each_arc_fileops_mode_places_the_arc_copy(library, mode, operation):
    result = _copy(library, ARC_FILEOPS=mode)

    expected = os.path.join(library["arcs"], "The Chosen (2012)", "Saga 001.cbz")
    assert (result.destination, result.operation, result.outcome) == (expected, operation, Outcome.PLACED)
    with open(expected, "rb") as handle:
        assert handle.read() == b"in the library"
    # An arc copy never takes the file out of the library, so "move" copies.
    assert os.path.exists(library["placed"])
    if mode == "softlink":
        assert os.readlink(expected) == library["placed"]
    if mode == "hardlink":
        assert os.stat(expected).st_ino == os.stat(library["placed"]).st_ino


def test_a_relative_softlink_points_back_into_the_library(library):
    result = _copy(library, ARC_FILEOPS="softlink", ARC_FILEOPS_SOFTLINK_RELATIVE=True)

    link = os.readlink(result.destination)
    assert not os.path.isabs(link)
    assert os.path.realpath(result.destination) == os.path.realpath(library["placed"])


@pytest.mark.parametrize(("reading_order", "prefix"), [(7, "007-"), (42, "042-"), (123, "123-")])
def test_the_reading_order_prefix_when_read2filename_is_on(library, reading_order, prefix):
    membership = ArcMembership("The Chosen", "SA1", "A1", reading_order, "Image")

    result = _copy(library, membership, READ2FILENAME=True)

    assert os.path.basename(result.destination) == f"{prefix}Saga 001.cbz"


def test_no_prefix_when_read2filename_is_off(library):
    assert os.path.basename(_copy(library, READ2FILENAME=False).destination) == "Saga 001.cbz"


@pytest.mark.parametrize(
    ("overrides", "folder"),
    [
        ({"ARC_FOLDERFORMAT": "$arc"}, "arcs/The Chosen"),
        ({"ARC_FOLDERFORMAT": "$publisher - $arc ($spanyears)"}, "arcs/Image - The Chosen (2012)"),
        ({"ARC_FOLDERFORMAT": ""}, "arcs/The Chosen (2012)"),
        ({"ARC_FOLDERFORMAT": "$arc", "REPLACE_SPACES": True}, "arcs/The.Chosen"),
        ({"STORYARC_LOCATION": None, "DESTINATION_DIR": "{root}/comics"}, "comics/StoryArcs/The Chosen (2012)"),
        ({"STORYARCDIR": False, "GRABBAG_DIR": "{root}/grabbag"}, "grabbag/The Chosen (2012)"),
    ],
)
def test_each_arc_folder_option(library, overrides, folder):
    overrides = {k: v.format(root=library["root"]) if isinstance(v, str) else v for k, v in overrides.items()}
    if "STORYARC_LOCATION" not in overrides:
        overrides["STORYARC_LOCATION"] = library["arcs"]

    result = _copy(library, **overrides)

    assert os.path.dirname(result.destination) == os.path.join(str(library["root"]), folder)


def test_with_copy2arcdir_off_the_arc_records_the_library_file(library):
    result = _copy(library, COPY2ARCDIR=False)

    assert (result.destination, result.operation, result.outcome) == (library["placed"], None, None)
    assert not os.path.exists(library["arcs"])


def test_a_folder_that_cannot_be_made_raises_and_places_nothing(library):
    config = Config(STORYARC_LOCATION=library["arcs"])
    with pytest.raises(ArcCopyError):
        copy_issue_to_arc(library["placed"], ARC, span_years="2012", config=config, create_directory=lambda _p: False)
    assert not os.path.exists(library["arcs"])


def test_a_full_disk_raises_before_placing(library):
    config = Config(STORYARC_LOCATION=library["arcs"])
    with patch.object(comicarr, "CONFIG", config), pytest.raises(ArcCopyError):
        copy_issue_to_arc(library["placed"], ARC, span_years="2012", config=config, free_space=lambda _p: False)
    assert os.listdir(os.path.join(library["arcs"], "The Chosen (2012)")) == []


def test_a_failed_placement_raises_an_arc_copy_error(library):
    config = Config(STORYARC_LOCATION=library["arcs"], ARC_FILEOPS="not-a-mode")
    with patch.object(comicarr, "CONFIG", config), pytest.raises(ArcCopyError):
        copy_issue_to_arc(library["placed"], ARC, span_years="2012", config=config)


def test_membership_falls_back_to_the_issue_publisher():
    row = {
        "StoryArc": "The Chosen",
        "StoryArcID": "SA1",
        "IssueArcID": "A1",
        "ReadingOrder": 3,
        "Publisher": None,
        "IssuePublisher": "Image",
    }
    assert ArcMembership.from_row(row).publisher == "Image"


# Legacy parity. ``updatearc_locs`` is the surviving legacy arc placement: it
# resolves the arc folder and reading-order name the same way the arc branch
# of ``PostProcessor.Process_next`` does, and records the path it chose.


@pytest.fixture
def arc_db(tmp_path, monkeypatch, library):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    metadata.create_all(get_engine())
    with get_engine().begin() as conn:
        conn.execute(
            insert(comics).values(ComicID="C1", ComicName="Saga", ComicLocation=os.path.dirname(library["placed"]))
        )
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
                ReadingOrder=7,
                Publisher=None,
                IssuePublisher="Image",
                IssueDate="2012-03-14",
                SeriesYear="2012",
                Manual="",
            )
        )
    yield
    shutdown_engine()


def _legacy_destination(library, config):
    arc_issues = [
        {
            "IssueID": "I1",
            "StoryArc": "The Chosen",
            "StoryArcID": "SA1",
            "Publisher": None,
            "IssuePublisher": "Image",
            "ComicID": "C1",
            "ComicName": "Saga",
            "IssueNumber": "1",
            "ReadingOrder": 7,
        }
    ]
    filechecker = MagicMock()
    filechecker.validateAndCreateDirectory.side_effect = lambda path, **_kw: os.makedirs(path, exist_ok=True) or True
    with patch.object(comicarr, "CONFIG", config), patch.object(comicarr, "filechecker", filechecker):
        service.updatearc_locs("SA1", arc_issues)
    with get_engine().connect() as conn:
        return conn.execute(
            select(storyarcs.c.Location).where(storyarcs.c.IssueID == "I1", storyarcs.c.Location.is_not(None))
        ).scalar_one()


@pytest.mark.parametrize(
    "overrides",
    [
        {"ARC_FOLDERFORMAT": "$arc ($spanyears)", "READ2FILENAME": False},
        {"ARC_FOLDERFORMAT": "$publisher - $arc", "READ2FILENAME": True},
        {"ARC_FOLDERFORMAT": "$arc", "READ2FILENAME": True, "REPLACE_SPACES": True, "ARC_FILEOPS": "softlink"},
        {"STORYARC_LOCATION": None, "READ2FILENAME": True},
    ],
)
def test_the_destination_matches_the_legacy_arc_placement(library, arc_db, overrides):
    overrides.setdefault("STORYARC_LOCATION", library["arcs"])
    overrides.setdefault("DESTINATION_DIR", str(library["root"] / "comics"))
    config = Config(**overrides)
    with get_engine().connect() as conn:
        row = dict(conn.execute(select(storyarcs).where(storyarcs.c.IssueArcID == "A1")).one()._mapping)
    with patch.object(comicarr, "CONFIG", config):
        ported = copy_issue_to_arc(library["placed"], ArcMembership.from_row(row), config=config)

    # The legacy placement skips a file already there, so it runs second.
    assert "2012" in ported.destination or "$spanyears" not in overrides.get("ARC_FOLDERFORMAT", "$spanyears")
    assert ported.destination == _legacy_destination(library, Config(**overrides))
