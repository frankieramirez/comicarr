#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Call-shape characterization for the post-processor's placement sites.

These five sites had **zero** line coverage before this suite: no test in the
repo called `Process_next` or `nzb_or_oneoff_pp`, and
`test_pp_complete_ordering.py:579` says why -- "full Process_next needs
extensive series fixtures". One site did not justify building them. Five does.

Two things are pinned per site, and the second is the valuable one:

1. **The call shape** -- the exact `(source, destination, purpose, on_existing)`
   handed to the placement stage. A silent change of purpose or policy would
   change which config key is read and what happens to an occupied destination.
2. **The caller's reaction to a failure** -- which is where these five sites
   genuinely differ, and where an asymmetry nobody chose is written down for the
   first time. Sites that put `mode: stop` on the queue halt post-processing;
   sites that `return` bare leave the queue empty, and `process.py:83`'s
   `if not ppqueue.empty()` guard means the worker then carries on as though
   post-processing had succeeded. That is preserved here under the map's
   standing constraint, not fixed -- but it is no longer invisible.
"""

import ast
import pathlib
import queue as queuelib
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import postprocessor
from comicarr.app.common.placement import OnExisting, PlacementError, Purpose
from comicarr.db import get_engine, shutdown_engine
from comicarr.postprocessor import PostProcessor
from comicarr.tables import comics, issues, metadata


class Config:
    """Real values for what the path branches on; False for everything else.

    A MagicMock cannot stand in here: its attributes are truthy mocks, so every
    `if CONFIG.X == "..."` branch silently takes the wrong arm and the run
    diverges long before it reaches a placement.
    """

    def __init__(self, **overrides):
        self.__dict__.update(
            dict(
                FILE_OPTS="move",
                ARC_FILEOPS="copy",
                ARC_FILEOPS_SOFTLINK_RELATIVE=False,
                RENAME_FILES=False,
                ENFORCE_PERMS=False,
                IGNORE_SEARCH_WORDS=[],
                FILE_FORMAT="",
                LOWERCASE_FILENAMES=False,
                REPLACE_SPACES=False,
                REPLACE_CHAR="_",
                POST_PROCESSING=True,
                HIGHCOUNT=0,
                ZERO_LEVEL=False,
                ZERO_LEVEL_N="none",
                CHMOD_FILE="0644",
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
    monkeypatch.setattr(comicarr, "GLOBAL_MESSAGES", None, raising=False)
    metadata.create_all(get_engine())
    yield
    shutdown_engine()


@pytest.fixture
def library(tmp_path):
    """A seeded series with one snatched issue sitting in a download folder."""
    download = tmp_path / "download"
    download.mkdir()
    series_folder = tmp_path / "library" / "Saga"
    series_folder.mkdir(parents=True)
    grabbed = download / "Saga 001.cbz"
    grabbed.write_bytes(b"grabbed")

    with get_engine().begin() as conn:
        conn.execute(
            insert(comics).values(
                ComicID="C1",
                ComicName="Saga",
                ComicLocation=str(series_folder),
                ComicYear="2012",
                ComicVersion=None,
                Type="None",
                ComicPublisher="Image",
                ComicPublished="2012-2018",
                ComicImageURL="",
                Corrected_SeriesYear="2012",
            )
        )
        conn.execute(
            insert(issues).values(
                IssueID="I1",
                ComicID="C1",
                ComicName="Saga",
                Issue_Number="1",
                Status="Snatched",
                IssueDate="2012-03-14",
                ReleaseDate="2012-03-14",
                IssueName="Chapter One",
                Location="Saga 001.cbz",
                ComicSize="1000",
            )
        )

    return {
        "download": download,
        "series_folder": series_folder,
        "grabbed": grabbed,
    }


def _post_processor(download, **kwargs):
    apilock = MagicMock()
    apilock.locked.return_value = False
    with patch.object(comicarr, "APILOCK", apilock), patch.object(comicarr, "CONFIG", Config()):
        return PostProcessor(
            nzb_name="Saga 001.cbz",
            nzb_folder=str(download),
            comicid="C1",
            issueid="I1",
            queue=MagicMock(spec=queuelib.Queue),
            **kwargs,
        )


def _drive_process_next(library, monkeypatch, *, config=None, place=None, ml=None):
    """Run Process_next to completion, capturing every placement call.

    Everything downstream of placement -- library totals, search bookkeeping,
    notifications -- is stubbed. This suite is about what reaches the stage and
    what the caller does when it raises, not about the DB facts that follow.
    """
    pp = _post_processor(library["download"])
    calls = []
    real_place = postprocessor.place

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        if place is not None:
            return place(*args, **kwargs)
        return real_place(*args, **kwargs)

    monkeypatch.setattr(postprocessor, "place", spy)

    with (
        patch.object(comicarr, "CONFIG", config or Config()),
        patch("comicarr.updater.totals"),
        patch("comicarr.updater.foundsearch"),
        patch.object(postprocessor, "notifiers", MagicMock()),
    ):
        pp.Process_next("C1", "I1", "1", ml=ml)

    return pp, calls


class TestNonManualSeriesPlacement:
    """postprocessor.py -- Process_next, the primary non-manual path."""

    def test_places_the_grab_into_the_series_folder_as_a_series_file(self, library, monkeypatch):
        pp, calls = _drive_process_next(library, monkeypatch)

        assert len(calls) == 1
        (source, destination, purpose), keywords = calls[0]
        assert source == str(library["grabbed"])
        assert destination == str(library["series_folder"] / "Saga 001.cbz")
        assert purpose is Purpose.SERIES
        assert keywords["on_existing"] is OnExisting.UNGUARDED
        assert "multiple" not in keywords

    def test_the_file_actually_lands_and_the_move_consumes_the_source(self, library, monkeypatch):
        _drive_process_next(library, monkeypatch)

        assert (library["series_folder"] / "Saga 001.cbz").read_bytes() == b"grabbed"
        assert not library["grabbed"].exists()

    @pytest.mark.parametrize("file_opts", ("copy", "hardlink", "softlink"))
    def test_the_mode_is_read_from_config_at_call_time(self, library, monkeypatch, file_opts):
        _drive_process_next(library, monkeypatch, config=Config(FILE_OPTS=file_opts))

        assert library["grabbed"].exists(), "%s must not consume the download" % file_opts
        assert (library["series_folder"] / "Saga 001.cbz").exists()

    def test_a_failed_placement_stops_post_processing(self, library, monkeypatch):
        """This site signals the queue worker. Compare the story-arc sites."""

        def boom(*_args, **_kwargs):
            raise PlacementError("disk full")

        pp, calls = _drive_process_next(library, monkeypatch, place=boom)

        assert len(calls) == 1
        pp.queue.put.assert_called_once()
        payload = pp.queue.put.call_args[0][0]
        assert payload[0]["mode"] == "stop"

    def test_a_failed_placement_leaves_the_download_alone(self, library, monkeypatch):
        def boom(*_args, **_kwargs):
            raise PlacementError("disk full")

        _drive_process_next(library, monkeypatch, place=boom)

        assert library["grabbed"].exists()
        assert not (library["series_folder"] / "Saga 001.cbz").exists()


def _manual_list(library):
    """A watchlist story-arc match, which is what puts Process_next on its
    manual-run branch."""
    return {
        "ComicID": "C1",
        "IssueID": "I1",
        "IssueArcID": "A1",
        "ForcedMatch": False,
        "ComicLocation": str(library["grabbed"]),
    }


class TestManualRunSeriesPlacement:
    """postprocessor.py -- Process_next, the manual-run branch (`ml` is not None)."""

    def test_places_as_a_series_file_with_the_same_intent_as_the_automatic_path(self, library, monkeypatch):
        pp, calls = _drive_process_next(library, monkeypatch, ml=_manual_list(library))

        series_calls = [c for c in calls if c[0][2] is Purpose.SERIES]
        assert series_calls, "the manual-run branch must place the grab"
        (source, destination, purpose), keywords = series_calls[0]
        assert source == str(library["grabbed"])
        assert destination == str(library["series_folder"] / "Saga 001.cbz")
        assert purpose is Purpose.SERIES
        assert keywords["on_existing"] is OnExisting.UNGUARDED

    def test_a_failed_placement_stops_post_processing_and_counts_a_failure(self, library, monkeypatch):
        """Unlike the automatic path, this site also increments failed_files."""

        def boom(*_args, **_kwargs):
            raise PlacementError("disk full")

        pp, _calls = _drive_process_next(library, monkeypatch, place=boom, ml=_manual_list(library))

        pp.queue.put.assert_called_once()
        assert pp.queue.put.call_args[0][0][0]["mode"] == "stop"
        assert pp.failed_files == 1


class TestStoryArcDirectoryPlacement:
    """postprocessor.py -- Process_next's COPY2ARCDIR secondary placement.

    A second, arc-shaped placement of the file the primary placement just put in
    the series folder. It reads ARC_FILEOPS rather than FILE_OPTS, and its arc
    mechanics keep the series file (a `move` degrades to a copy) -- which is why
    it carries Purpose.ARC and not Purpose.SERIES.
    """

    @pytest.fixture
    def arc(self, library, tmp_path):
        from comicarr.tables import storyarcs

        arc_root = tmp_path / "arcs"
        arc_root.mkdir()
        with get_engine().begin() as conn:
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
                    Status="Snatched",
                )
            )
        return arc_root

    def test_the_arc_copy_carries_arc_intent(self, library, monkeypatch, arc):
        config = Config(COPY2ARCDIR=True, STORYARCDIR=True, STORYARC_LOCATION=str(arc), ARC_FOLDERFORMAT="$arc")
        _pp, calls = _drive_process_next(library, monkeypatch, config=config, ml=_manual_list(library))

        arc_calls = [c for c in calls if c[0][2] is Purpose.ARC]
        assert arc_calls, "COPY2ARCDIR must place the file into the arc directory"
        (source, destination, _purpose), keywords = arc_calls[0]
        assert source == str(library["series_folder"] / "Saga 001.cbz"), (
            "the arc copy must come from the series folder, so a hard/soft link points at the library"
        )
        assert str(arc) in destination
        assert keywords["on_existing"] is OnExisting.UNGUARDED

    def test_the_primary_placement_still_happens_first(self, library, monkeypatch, arc):
        config = Config(COPY2ARCDIR=True, STORYARCDIR=True, STORYARC_LOCATION=str(arc), ARC_FOLDERFORMAT="$arc")
        _pp, calls = _drive_process_next(library, monkeypatch, config=config, ml=_manual_list(library))

        purposes = [c[0][2] for c in calls]
        assert purposes.index(Purpose.SERIES) < purposes.index(Purpose.ARC)

    def test_a_failed_arc_copy_returns_without_signalling_the_queue(self, library, monkeypatch, arc):
        """Preserved, not endorsed.

        This site swallows the failure: it returns without putting `mode: stop`
        on the queue, so `process.py:83`'s `if not ppqueue.empty()` guard leaves
        the worker believing post-processing succeeded. The automatic and
        manual-run sites both signal. Nobody chose this asymmetry; the map's
        standing constraint keeps it, and this test makes it visible.
        """
        config = Config(COPY2ARCDIR=True, STORYARCDIR=True, STORYARC_LOCATION=str(arc), ARC_FOLDERFORMAT="$arc")
        real_place = postprocessor.place

        def boom_on_arc(source, destination, purpose, **kwargs):
            if purpose is Purpose.ARC:
                raise PlacementError("arc directory is read-only")
            return real_place(source, destination, purpose, **kwargs)

        pp, calls = _drive_process_next(
            library, monkeypatch, config=config, place=boom_on_arc, ml=_manual_list(library)
        )

        assert any(c[0][2] is Purpose.ARC for c in calls)
        pp.queue.put.assert_not_called()


def _drive_nzb_or_oneoff(library, monkeypatch, *, config=None, place=None, tinfo_overrides=None):
    config = config or Config(GRABBAG_DIR=str(library["series_folder"]))
    pp = _post_processor(library["download"])
    calls = []
    real_place = postprocessor.place

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        if place is not None:
            return place(*args, **kwargs)
        return real_place(*args, **kwargs)

    monkeypatch.setattr(postprocessor, "place", spy)

    tinfo = {
        "issueid": "I1",
        "comicid": "C1",
        "comicname": "Saga",
        "seriesyear": "2012",
        "seriesvolume": None,
        "issuenumber": "1",
        "publisher": "Image",
        "sarc": None,
        "oneoff": True,
        "comiclocation": str(library["grabbed"]),
        "name": "Saga 001.cbz",
        "modcomicname": "Saga",
        "annchk": "no",
        "issuearcid": None,
    }
    tinfo.update(tinfo_overrides or {})

    with (
        patch.object(comicarr, "CONFIG", config),
        patch("comicarr.updater.totals"),
        patch("comicarr.updater.foundsearch"),
        patch.object(postprocessor.db, "upsert"),
        patch.object(postprocessor, "notifiers", MagicMock()),
    ):
        pp.nzb_or_oneoff_pp(tinfo=tinfo)

    return pp, calls


class TestOneOffAndGrabBagPlacement:
    """postprocessor.py -- nzb_or_oneoff_pp, the one-off / grab-bag path."""

    def test_places_with_series_intent(self, library, monkeypatch):
        _pp, calls = _drive_nzb_or_oneoff(library, monkeypatch)

        assert calls, "nzb_or_oneoff_pp must place the grab"
        (_source, _destination, purpose), keywords = calls[0]
        assert purpose is Purpose.SERIES
        assert keywords["on_existing"] is OnExisting.UNGUARDED

    def test_a_failed_placement_stops_post_processing(self, library, monkeypatch):
        def boom(*_args, **_kwargs):
            raise PlacementError("disk full")

        pp, calls = _drive_nzb_or_oneoff(library, monkeypatch, place=boom)

        assert calls
        pp.queue.put.assert_called_once()
        assert pp.queue.put.call_args[0][0][0]["mode"] == "stop"


class TestOneOffStoryArcPlacementCallShape:
    """postprocessor.py -- Process()'s one-off story-arc placement.

    **This site has no behavioural test.** Reaching it means driving `Process()`
    far enough to build `manual_arclist`, which requires the whole file-matching
    phase -- FileChecker over a download tree, watchlist match verification,
    story-arc reading-order lookups -- not just the placement phase that
    `Process_next` and `nzb_or_oneoff_pp` expose. That was beyond the fixture
    budget for this migration, and #336 decided the tiebreak in advance: the site
    migrates anyway, because leaving one of eight on the legacy helper is worse
    than migrating it without a behavioural test.

    What is left is a source-level pin. It cannot catch a runtime bug, but it
    does catch the two things a careless edit would change silently: the intent
    handed to the stage, and whether a failure reaches the queue worker.
    """

    @staticmethod
    def _placement_calls():
        source = pathlib.Path(postprocessor.__file__).read_text()
        tree = ast.parse(source)
        return [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "place"
        ]

    def test_every_placement_names_its_policy_explicitly(self):
        calls = self._placement_calls()

        assert len(calls) == 6, "expected six placements in postprocessor.py, found %d" % len(calls)
        for call in calls:
            keywords = {kw.arg for kw in call.keywords}
            assert "on_existing" in keywords, "a placement at line %d names no policy" % call.lineno

    def test_the_one_off_site_passes_one_off_intent_and_the_multiple_flag(self):
        one_off = [
            call
            for call in self._placement_calls()
            if any(
                isinstance(arg, ast.Attribute) and arg.attr == "ONE_OFF"
                for arg in call.args
                if isinstance(arg, ast.Attribute)
            )
        ]

        assert len(one_off) == 1, "expected exactly one ONE_OFF placement"
        keywords = {kw.arg: kw.value for kw in one_off[0].keywords}
        assert isinstance(keywords["on_existing"], ast.Attribute)
        assert keywords["on_existing"].attr == "UNGUARDED"
        assert isinstance(keywords["multiple"], ast.Name), "the one-off site must forward the multiple-arc flag"
        assert keywords["multiple"].id == "mult_count"

    def test_the_one_off_site_swallows_failure_without_signalling_the_queue(self):
        """Preserved, not endorsed -- the same asymmetry the arc site has.

        `Process()` returns bare here, so `process.py:83`'s empty-queue guard
        leaves the worker believing post-processing succeeded. Pinned at source
        level so a change is deliberate rather than accidental.
        """
        source = pathlib.Path(postprocessor.__file__).read_text()
        tree = ast.parse(source)

        one_off_handlers = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            names = {
                arg.attr
                for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "place"
                for arg in call.args
                if isinstance(arg, ast.Attribute)
            }
            if "ONE_OFF" in names:
                one_off_handlers.extend(node.handlers)

        assert one_off_handlers, "the one-off placement must stay inside a try"
        returns = [n for handler in one_off_handlers for n in ast.walk(handler) if isinstance(n, ast.Return)]
        assert returns, "the one-off failure path must return"
        assert all(r.value is None for r in returns), (
            "the one-off site returns bare today, signalling nothing to the queue worker; "
            "changing that is a behaviour change and needs its own decision"
        )
