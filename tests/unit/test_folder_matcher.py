#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""What the folder matcher finds in a manual folder scan.

Each scenario puts files in a folder and asks which library issue, story-arc
issue or one-off each one belongs to. The expected matches were recorded from
``PostProcessor.Process()`` before it was split into a matching function and
the pipeline, so they pin the inherited rules rather than describe new ones.
"""

import queue
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import comicarr
from comicarr import db
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.tables import annuals, comics, issues, metadata, storyarcs
from tests.fakes import pipeline


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CACHE_DIR", str(tmp_path / "cache"), raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        pipeline.default_config(
            MANUAL_PP_FOLDER=str(tmp_path / "downloads"),
            CHECK_FOLDER=None,
            ANNUALS_ON=True,
            FILE_OPTS="copy",
            ENABLE_META=False,
            CACHE_DIR=str(tmp_path / "cache"),
            DESTINATION_DIR=str(tmp_path / "library"),
            STORYARCDIR=False,
            COPY2ARCDIR=False,
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "USE_SABNZBD", False, raising=False)
    monkeypatch.setattr(comicarr, "USE_NZBGET", False, raising=False)
    monkeypatch.setattr(
        "comicarr.postprocessor.time", SimpleNamespace(time=lambda: time.time() + 60, sleep=lambda _s: None)
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    metadata.create_all(db.get_engine())
    assert ensure_acquisition_schema(db.get_engine()).ready
    yield tmp_path
    db.shutdown_engine()


@pytest.fixture
def library(tmp_path):
    series_root = tmp_path / "library" / "Absolute Batman (2024)"
    series_root.mkdir(parents=True)
    with db.get_engine().begin() as conn:
        conn.execute(comics.insert().values(**pipeline.comic_series_row(series_root)))
        conn.execute(issues.insert().values(**pipeline.comic_issue_row()))
    return series_root


def _download(tmp_path, name):
    return pipeline.write_download(tmp_path / "downloads" / name)


def _scan(folder):
    """The matches a manual scan of ``folder`` hands on, by kind."""
    from comicarr import postprocessor

    found = {"library": [], "arc_only": [], "one_off": []}

    def library_match(self, comicid, issueid, issuenumOG, ml=None, stat=None):
        found["library"].append((comicid, issueid, issuenumOG, ml["ComicLocation"]))

    def one_off(self, tinfo=None, manual=None):
        found["one_off"].append((tinfo["issueid"], tinfo["comiclocation"]))

    real_upsert = db.upsert

    def upsert(table, values, keys, *args, **kwargs):
        if table == "storyarcs":
            found["arc_only"].append((keys["IssueArcID"], values["Location"]))
            return None
        return real_upsert(table, values, keys, *args, **kwargs)

    with (
        patch.object(postprocessor.PostProcessor, "Process_next", library_match),
        patch.object(postprocessor.PostProcessor, "nzb_or_oneoff_pp", one_off),
        patch.object(postprocessor.db, "upsert", upsert),
        patch("comicarr.updater.foundsearch"),
        patch("comicarr.app.notifications.service"),
        patch("comicarr.helpers.duplicate_filecheck", return_value={"action": "write"}),
    ):
        postprocessor.PostProcessor("Manual Run", str(folder), queue=queue.Queue()).Process()
    return found


def test_a_library_issue_matches_its_series_and_issue(tmp_path, library):
    path = _download(tmp_path, pipeline.FILENAME)

    found = _scan(path.parent)

    assert found == {
        "library": [(pipeline.COMIC_ID, pipeline.ISSUE_ID, "1", str(path))],
        "arc_only": [],
        "one_off": [],
    }


def test_an_annual_matches_the_annual_row(tmp_path, library):
    with db.get_engine().begin() as conn:
        conn.execute(
            annuals.insert().values(
                IssueID="annual-1",
                ComicID=pipeline.COMIC_ID,
                ReleaseComicID="annual-series",
                ReleaseComicName="Absolute Batman Annual",
                ComicName="Absolute Batman Annual",
                Issue_Number="1",
                Int_IssueNumber=1000,
                Status="Wanted",
                ReleaseDate="2024-10-09",
                IssueDate="2024-12-01",
            )
        )
    path = _download(tmp_path, "Absolute Batman Annual 001 (2024).cbz")

    found = _scan(path.parent)

    assert found == {
        "library": [(pipeline.COMIC_ID, "annual-1", "1", str(path))],
        "arc_only": [],
        "one_off": [],
    }


def test_a_file_for_no_watched_series_matches_nothing(tmp_path, library):
    path = _download(tmp_path, "Saga 054 (2018).cbz")

    found = _scan(path.parent)

    assert found == {"library": [], "arc_only": [], "one_off": []}


def test_an_owned_issue_still_matches_so_the_duplicate_check_can_see_it(tmp_path, library):
    owned = library / pipeline.FILENAME
    pipeline.write_download(owned)
    with db.get_engine().begin() as conn:
        conn.execute(
            issues.update()
            .where(issues.c.IssueID == pipeline.ISSUE_ID)
            .values(Status="Downloaded", Location=pipeline.FILENAME, ComicSize=str(owned.stat().st_size))
        )
    path = _download(tmp_path, pipeline.FILENAME)

    found = _scan(path.parent)

    assert found == {
        "library": [(pipeline.COMIC_ID, pipeline.ISSUE_ID, "1", str(path))],
        "arc_only": [],
        "one_off": [],
    }


def test_a_file_in_a_watched_arc_and_no_watched_series_is_arc_only(tmp_path, library):
    with db.get_engine().begin() as conn:
        conn.execute(
            storyarcs.insert().values(
                StoryArcID="arc-1",
                IssueArcID="arc-1_issue",
                StoryArc="Zero Year",
                ComicName="Batman",
                DynamicComicName="batman",
                ComicID="other-series",
                IssueID="other-issue",
                IssueNumber="24",
                Int_IssueNumber=24000,
                IssueName="Zero Year",
                ReadingOrder=1,
                Status="Wanted",
                IssueDate="2013-10-01",
                ReleaseDate="2013-09-11",
                SeriesYear="2011",
                Publisher="DC Comics",
                IssuePublisher="DC Comics",
                IssueYEAR="2013",
                TotalIssues=12,
                Type="Print",
                Volume="v2",
                Manual=None,
            )
        )
    path = _download(tmp_path, "Batman 024 (2013).cbz")

    found = _scan(path.parent)

    assert found == {"library": [], "arc_only": [("arc-1_issue", str(path))], "one_off": []}


def test_a_manga_chapter_matches_its_chapter_row(tmp_path):
    series_root = tmp_path / "library" / pipeline.MANGA_SERIES
    series_root.mkdir(parents=True)
    with db.get_engine().begin() as conn:
        conn.execute(comics.insert().values(**pipeline.manga_series_row(series_root, LatestDate="2021-01-10", intLatestIssue=10000)))
        for row in pipeline.manga_chapter_rows():
            conn.execute(issues.insert().values(**row))
    path = _download(tmp_path, "%s c010.cbz" % pipeline.MANGA_SERIES)

    found = _scan(path.parent)

    assert found == {
        "library": [(pipeline.MANGA_ID, pipeline.manga_chapter_id("10"), "10", str(path))],
        "arc_only": [],
        "one_off": [],
    }
