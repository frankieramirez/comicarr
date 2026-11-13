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
repo drove the per-issue path (`process_comic_issue`, once `Process_next`) or
the snatched-download path (`process_snatched_match`, once `nzb_or_oneoff_pp`),
and `test_pp_complete_ordering.py:579` says why -- "full Process_next needs
extensive series fixtures". One site did not justify building them. Five does.

Two things are pinned per site, and the second is the valuable one:

1. **The call shape** -- the exact `(source, destination, purpose, on_existing)`
   handed to the placement stage. A silent change of purpose or policy would
   change which config key is read and what happens to an occupied destination.
2. **The caller's reaction to a failure** -- which is where these five sites
   genuinely differ, and where an asymmetry nobody chose is written down for the
   first time. Sites that post `mode: stop` (`run.finish`) halt post-processing;
   sites that `run.abort()` post nothing, and `process.py:83`'s
   `if not ppqueue.empty()` guard means the worker then carries on as though
   post-processing had succeeded. That is preserved here under the map's
   standing constraint, not fixed -- but it is no longer invisible.
"""

import ast
import pathlib
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import postprocessor
from comicarr.app.common.placement import OnExisting, PlacementError, Purpose
from comicarr.app.downloads import postprocess_pipeline
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, issues, metadata
from tests.fakes import folder_request


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
    return folder_request.folder_run("Saga 001.cbz", download, "I1", comicid="C1", **kwargs)


def _drive_process_next(library, monkeypatch, *, config=None, place=None, ml=None, **pp_kwargs):
    """Run one library issue (the old Process_next) to completion, capturing every placement call.

    Everything downstream of placement -- library totals, search bookkeeping,
    notifications -- is stubbed. This suite is about what reaches the stage and
    what the caller does when it raises, not about the DB facts that follow.
    Returns the run, the placement calls, and how the item ended.
    """
    run = _post_processor(library["download"], **pp_kwargs)
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
        patch("comicarr.app.notifications.service", MagicMock()),
    ):
        deps = postprocessor.pipeline_deps()
        result = postprocess_pipeline._process_library_issue(run, deps, "C1", "I1", "1", ml)

    return run, calls, result


class TestNonManualSeriesPlacement:
    """postprocess_pipeline.py -- process_comic_issue (once Process_next), the primary non-manual path."""

    def test_places_the_grab_into_the_series_folder_as_a_series_file(self, library, monkeypatch):
        pp, calls, result = _drive_process_next(library, monkeypatch)

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

        pp, calls, result = _drive_process_next(library, monkeypatch, place=boom)

        assert len(calls) == 1
        assert result.queued is True
        assert len(pp.messages) == 1
        assert pp.messages[0]["mode"] == "stop"

    def test_a_denied_move_logs_release_paths_and_traceback(self, library, monkeypatch, capture_logs):
        def denied(*_args, **_kwargs):
            raise PermissionError("[Errno 13] Permission denied")

        _drive_process_next(library, monkeypatch, place=denied, journal_release_key="pp-release")

        failure = next(r for r in capture_logs.records if "Failed to move" in r.getMessage()).getMessage()
        assert "pp-release" in failure
        assert str(library["grabbed"]) in failure
        assert str(library["series_folder"] / "Saga 001.cbz") in failure
        assert "Traceback (most recent call last)" in failure
        assert "PermissionError" in failure

    def test_a_failed_placement_leaves_the_download_alone(self, library, monkeypatch):
        def boom(*_args, **_kwargs):
            raise PlacementError("disk full")

        _drive_process_next(library, monkeypatch, place=boom)

        assert library["grabbed"].exists()
        assert not (library["series_folder"] / "Saga 001.cbz").exists()


def _manual_list(library):
    """A watchlist story-arc match, which is what puts process_comic_issue on its
    manual-run branch."""
    return {
        "ComicID": "C1",
        "IssueID": "I1",
        "IssueArcID": "A1",
        "ForcedMatch": False,
        "ComicLocation": str(library["grabbed"]),
    }


class TestManualRunSeriesPlacement:
    """postprocess_pipeline.py -- process_comic_issue, the manual-run branch (`ml` is not None)."""

    def test_places_as_a_series_file_with_the_same_intent_as_the_automatic_path(self, library, monkeypatch):
        pp, calls, result = _drive_process_next(library, monkeypatch, ml=_manual_list(library))

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

        pp, _calls, result = _drive_process_next(library, monkeypatch, place=boom, ml=_manual_list(library))

        assert result.queued is True
        assert len(pp.messages) == 1
        assert pp.messages[0]["mode"] == "stop"
        assert pp.failed_files == 1


class TestStoryArcDirectoryPlacement:
    """postprocess_pipeline.py -- process_comic_issue's COPY2ARCDIR secondary placement.

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
        _pp, calls, result = _drive_process_next(library, monkeypatch, config=config, ml=_manual_list(library))

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
        _pp, calls, result = _drive_process_next(library, monkeypatch, config=config, ml=_manual_list(library))

        purposes = [c[0][2] for c in calls]
        assert purposes.index(Purpose.SERIES) < purposes.index(Purpose.ARC)

    def test_a_failed_arc_copy_returns_without_signalling_the_queue(self, library, monkeypatch, arc):
        """Preserved, not endorsed.

        This site swallows the failure: it returns `run.abort()` without posting
        `mode: stop`, so `process.py:83`'s `if not ppqueue.empty()` guard leaves
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

        pp, calls, result = _drive_process_next(
            library, monkeypatch, config=config, place=boom_on_arc, ml=_manual_list(library)
        )

        assert any(c[0][2] is Purpose.ARC for c in calls)
        assert result.queued is False
        assert pp.messages == []


def _drive_nzb_or_oneoff(library, monkeypatch, *, config=None, place=None, tinfo_overrides=None):
    """Run one snatched download (the old nzb_or_oneoff_pp) through ``process_snatched_match``."""
    config = config or Config(GRABBAG_DIR=str(library["series_folder"]))
    run = _post_processor(library["download"])
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
        patch.object(postprocess_pipeline.db, "upsert"),
        patch("comicarr.app.notifications.service", MagicMock()),
    ):
        deps = postprocessor.pipeline_deps()
        result = postprocess_pipeline.process_snatched_match(run, deps, tinfo=tinfo)

    return run, calls, result


class TestOneOffAndGrabBagPlacement:
    """postprocess_pipeline.py -- process_snatched_match (once nzb_or_oneoff_pp), the one-off / grab-bag path."""

    def test_places_with_series_intent(self, library, monkeypatch):
        _pp, calls, result = _drive_nzb_or_oneoff(library, monkeypatch)

        assert calls, "process_snatched_match must place the grab"
        (_source, _destination, purpose), keywords = calls[0]
        assert purpose is Purpose.SERIES
        assert keywords["on_existing"] is OnExisting.UNGUARDED

    def test_a_failed_placement_stops_post_processing(self, library, monkeypatch):
        def boom(*_args, **_kwargs):
            raise PlacementError("disk full")

        pp, calls, result = _drive_nzb_or_oneoff(library, monkeypatch, place=boom)

        assert calls
        assert result.queued is True
        assert len(pp.messages) == 1
        assert pp.messages[0]["mode"] == "stop"


class TestOneOffStoryArcPlacementCallShape:
    """postprocess_pipeline.py -- ``place_arc_only_matches``'s one-off story-arc placement.

    **This site has no behavioural test.** Reaching it means driving a whole
    request far enough to build `manual_arclist`, which requires the whole
    file-matching phase (`match_folder`) -- FileChecker over a download tree,
    watchlist match verification, story-arc reading-order lookups -- not just
    the placement phase that `process_comic_issue` and `process_snatched_match`
    expose. That was beyond the fixture budget for this migration, and #336
    decided the tiebreak in advance: the site migrates anyway, because leaving
    one of eight on the legacy helper is worse than migrating it without a
    behavioural test.

    What is left is a source-level pin. It cannot catch a runtime bug, but it
    does catch the two things a careless edit would change silently: the intent
    handed to the stage, and whether a failure reaches the queue worker.
    """

    @staticmethod
    def _is_placement(node):
        """A ``deps.place(...)`` call: the pipeline places only through its deps."""
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "place"

    @classmethod
    def _placement_calls(cls):
        tree = ast.parse(pathlib.Path(postprocess_pipeline.__file__).read_text())
        return [node for node in ast.walk(tree) if cls._is_placement(node)]

    def test_the_matcher_places_nothing(self):
        """Matching is pure; every placement site lives in the pipeline."""
        tree = ast.parse(pathlib.Path(postprocessor.__file__).read_text())
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "place")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "place")
            )
        ]

        assert calls == [], "postprocessor.py places at line(s) %s" % [c.lineno for c in calls]

    def test_every_pipeline_placement_names_its_policy_explicitly(self):
        """The two sites once in ``Process()`` joined the three per-item sites in the pipeline."""
        calls = self._placement_calls()

        assert len(calls) == 5, "expected five placements in postprocess_pipeline.py, found %d" % len(calls)
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

        The site returns ``run.abort()``, which posts no message, so
        `process.py:83`'s empty-queue guard leaves the worker believing
        post-processing succeeded. (``Process()`` returned bare here.) Pinned
        at source level so a change is deliberate rather than accidental.
        """
        tree = ast.parse(pathlib.Path(postprocess_pipeline.__file__).read_text())

        one_off_handlers = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            names = {
                arg.attr
                for call in ast.walk(node)
                if self._is_placement(call)
                for arg in call.args
                if isinstance(arg, ast.Attribute)
            }
            if "ONE_OFF" in names:
                one_off_handlers.extend(node.handlers)

        assert one_off_handlers, "the one-off placement must stay inside a try"
        returns = [n for handler in one_off_handlers for n in ast.walk(handler) if isinstance(n, ast.Return)]
        assert returns, "the one-off failure path must return"
        assert all(
            isinstance(r.value, ast.Call)
            and isinstance(r.value.func, ast.Attribute)
            and r.value.func.attr == "abort"
            and not r.value.args
            for r in returns
        ), (
            "the one-off site returns run.abort() today, signalling nothing to the queue worker; "
            "changing that is a behaviour change and needs its own decision"
        )
        assert not any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "finish"
            for handler in one_off_handlers
            for n in ast.walk(handler)
        ), "the one-off failure path must post no message"
