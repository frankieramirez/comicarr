#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Per-item post-processing functions (#1225, stage 6 of the migration map).

Each test drives ``process_comic_issue`` or ``process_manga_download`` directly
against a real SQLite database and real files, with the legacy collaborators
(tagger, totals, foundsearch, weekly hook) replaced by recording fakes.
"""

import threading
import types
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.common.placement import PlacementError, Purpose, place
from comicarr.app.downloads import journal, postprocessing
from comicarr.app.downloads.postprocess_pipeline import (
    ABORTED,
    COMPLETED,
    PostProcessComicMatch,
    PostProcessContext,
    PostProcessItemDeps,
    PostProcessJournalStage,
    PostProcessRun,
    process_comic_issue,
    process_manga_download,
)
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import annuals, comics, issues, metadata, nzblog, pipeline_journal, storyarcs


class Config:
    """Real values for what the path branches on; False for everything else."""

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
                ARC_FOLDERFORMAT="$arc",
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
    monkeypatch.setattr(comicarr, "ISSUE_EXCEPTIONS", [], raising=False)
    engine = get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready
    yield
    shutdown_engine()


@pytest.fixture
def library(tmp_path):
    download = tmp_path / "download"
    download.mkdir()
    series_folder = tmp_path / "library" / "Saga"
    series_folder.mkdir(parents=True)
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
            )
        )
        conn.execute(insert(nzblog).values(IssueID="I1", NZBName="Saga 001.cbz"))
    return types.SimpleNamespace(download=download, series_folder=series_folder, root=tmp_path)


class Fakes:
    """Recording stand-ins for the legacy collaborators."""

    def __init__(self, place_fn=place):
        self.placements = []
        self.found = []
        self.totals_calls = []
        self.weekly = []
        self._place = place_fn

    def deps(self, manga_destination=None):
        def _place(src, dst, purpose, **kwargs):
            self.placements.append((src, dst, purpose))
            return self._place(src, dst, purpose, **kwargs)

        return PostProcessItemDeps(
            place=_place,
            tag_file=MagicMock(side_effect=AssertionError("tagging is off")),
            validate_directory=lambda path, create, module=None: True,
            set_permissions=lambda path: True,
            weekly_check=lambda *a, **k: self.weekly.append((a, k)),
            totals=lambda *a, **k: self.totals_calls.append((a, k)),
            foundsearch=lambda *a, **k: self.found.append((a, k)),
            extract_cover=lambda *a, **k: {"ComicImage": None},
            manga_destination=lambda: manga_destination,
        )


def _run(download, *, comic_id="C1", issue_id="I1", release_key="rk-I1", nzb_name="Saga 001.cbz"):
    context = PostProcessContext(
        issue_id=issue_id,
        issue_arc_id=None,
        comic_id=comic_id,
        nzb_name=nzb_name,
        nzb_folder=str(download),
        api_call=False,
        ddl=False,
        canonical_release_key=release_key,
        log_module="[POST-PROCESSING]",
    )
    return PostProcessRun(context=context, nzb_name=nzb_name, nzb_folder=str(download))


def _stage(key):
    with get_engine().connect() as conn:
        row = conn.execute(select(pipeline_journal.c.stage).where(pipeline_journal.c.release_key == key)).fetchone()
    return row[0] if row else None


def _journal_rows():
    with get_engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(select(pipeline_journal))]


def _row(table, **where):
    stmt = select(table)
    for column, value in where.items():
        stmt = stmt.where(getattr(table.c, column) == value)
    with get_engine().connect() as conn:
        found = conn.execute(stmt).fetchone()
    return dict(found._mapping) if found else None


def _claim(key, issue_id):
    journal.record_transition(key, journal.POST_PROCESSING, issueid=issue_id)


# ---------------------------------------------------------------------------
# a comic issue
# ---------------------------------------------------------------------------


def test_a_comic_issue_is_placed_reconciled_and_completed(library):
    (library.download / "Saga 001.cbz").write_bytes(b"issue one")
    _claim("rk-I1", "I1")
    fakes = Fakes()
    run = _run(library.download)

    with patch.object(comicarr, "CONFIG", Config()):
        result = process_comic_issue(PostProcessComicMatch("C1", "I1", "1"), run, fakes.deps())

    placed = library.series_folder / "Saga 001.cbz"
    assert result.outcome == COMPLETED
    assert result.queued is True
    assert result.placed_path == str(placed)
    assert placed.read_bytes() == b"issue one"
    assert not (library.download / "Saga 001.cbz").exists()
    assert [p[2] for p in fakes.placements] == [Purpose.SERIES]
    assert fakes.found[0][0] == ("C1", "I1")
    assert fakes.found[0][1]["down"] == "True"
    assert _row(issues, IssueID="I1")["Status"] == "Downloaded"
    assert _row(nzblog, IssueID="I1") is None
    assert _stage("rk-I1") == journal.POST_PROCESSED
    assert run.messages[-1]["mode"] == "stop"
    assert run.messages[-1]["issueid"] == "I1"
    assert "Post Processing SUCCESSFUL!" in run.log


def test_a_failed_placement_stops_with_the_release_still_owed(library):
    (library.download / "Saga 001.cbz").write_bytes(b"issue one")
    _claim("rk-I1", "I1")

    def _refuse(*a, **k):
        raise PlacementError("library is read-only")

    run = _run(library.download)
    with patch.object(comicarr, "CONFIG", Config()):
        result = process_comic_issue(PostProcessComicMatch("C1", "I1", "1"), run, Fakes(_refuse).deps())

    assert result.outcome == "stopped"
    assert (library.download / "Saga 001.cbz").exists()
    assert _stage("rk-I1") == journal.POST_PROCESSING
    assert _row(nzblog, IssueID="I1") is not None


# ---------------------------------------------------------------------------
# an annual
# ---------------------------------------------------------------------------


def test_an_annual_is_reconciled_as_an_annual(library):
    with get_engine().begin() as conn:
        conn.execute(
            insert(annuals).values(
                IssueID="AN1",
                ComicID="C1",
                ComicName="Saga",
                ReleaseComicName="Saga Annual",
                Issue_Number="1",
                Status="Snatched",
                IssueDate="2013-06-01",
                ReleaseDate="2013-06-01",
                Deleted=0,
            )
        )
    (library.download / "Saga Annual 001.cbz").write_bytes(b"annual")
    _claim("rk-AN1", "AN1")
    fakes = Fakes()
    run = _run(library.download, issue_id="AN1", release_key="rk-AN1", nzb_name="Saga Annual 001.cbz")

    with patch.object(comicarr, "CONFIG", Config()):
        result = process_comic_issue(PostProcessComicMatch("C1", "AN1", "1"), run, fakes.deps())

    assert result.outcome == COMPLETED
    assert (library.series_folder / "Saga Annual 001.cbz").exists()
    assert fakes.found[0][1]["mode"] == "want_ann"
    assert _row(annuals, IssueID="AN1")["Status"] == "Downloaded"
    assert _row(issues, IssueID="I1")["Status"] == "Snatched"
    assert "Annual detected." in run.log
    assert _stage("rk-AN1") == journal.POST_PROCESSED


# ---------------------------------------------------------------------------
# a duplicate: the same release processed twice
# ---------------------------------------------------------------------------


def test_a_duplicate_run_writes_nothing_twice_and_notifies_once(library):
    _claim("rk-I1", "I1")
    notifiers = MagicMock()
    config = Config(SLACK_ENABLED=True)

    first = Fakes()
    (library.download / "Saga 001.cbz").write_bytes(b"issue one")
    with patch.object(comicarr, "CONFIG", config), patch("comicarr.app.notifications.service", notifiers):
        process_comic_issue(PostProcessComicMatch("C1", "I1", "1"), _run(library.download), first.deps())

        # What the real foundsearch records, and what marks the issue as
        # already reconciled when the same file comes back.
        placed = library.series_folder / "Saga 001.cbz"
        with get_engine().begin() as conn:
            conn.execute(issues.update().where(issues.c.IssueID == "I1").values(ComicSize=str(placed.stat().st_size)))

        # The same release arrives again (a re-grab, or a re-run after restart).
        library.download.mkdir(exist_ok=True)
        (library.download / "Saga 001.cbz").write_bytes(b"issue one")
        second = Fakes()
        result = process_comic_issue(PostProcessComicMatch("C1", "I1", "1"), _run(library.download), second.deps())

    assert result.outcome == COMPLETED
    assert notifiers.SLACK.return_value.notify.call_count == 1
    assert len(first.found) == 1
    assert second.found == [], "the second run must not reconcile the issue again"
    assert _stage("rk-I1") == journal.POST_PROCESSED


# ---------------------------------------------------------------------------
# an issue in a watched arc
# ---------------------------------------------------------------------------


@pytest.fixture
def arc(library):
    arc_root = library.root / "arcs"
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
        conn.execute(insert(nzblog).values(IssueID="SA1", NZBName="Saga 001.cbz"))
    return arc_root


def _arc_config(arc_root, **overrides):
    return Config(COPY2ARCDIR=True, STORYARCDIR=True, STORYARC_LOCATION=str(arc_root), **overrides)


def _arc_match(library):
    grabbed = library.download / "Saga 001.cbz"
    grabbed.write_bytes(b"issue one")
    return PostProcessComicMatch(
        "C1",
        "I1",
        "1",
        manual={
            "ComicID": "C1",
            "IssueID": "I1",
            "IssueArcID": "A1",
            "ForcedMatch": False,
            "ComicLocation": str(grabbed),
        },
    )


def _arc_key():
    return PostProcessJournalStage().release_key(_run(None).context, issue_arc_id="A1")


def test_an_arc_issue_is_copied_to_the_arc_under_its_own_journal_key(library, arc):
    _claim("rk-I1", "I1")
    fakes = Fakes()
    run = _run(library.download)

    with patch.object(comicarr, "CONFIG", _arc_config(arc)):
        result = process_comic_issue(_arc_match(library), run, fakes.deps())

    library_file = library.series_folder / "Saga 001.cbz"
    arc_file = arc / "The Chosen" / "Saga 001.cbz"
    assert result.outcome == COMPLETED
    assert [p[2] for p in fakes.placements] == [Purpose.SERIES, Purpose.ARC]
    assert fakes.placements[1][0] == str(library_file)
    assert library_file.exists() and arc_file.exists()

    arc_key = _arc_key()
    assert arc_key != "rk-I1"
    assert _stage("rk-I1") == journal.POST_PROCESSED
    assert _stage(arc_key) == journal.POST_PROCESSED
    arc_row = _row(storyarcs, IssueArcID="A1")
    assert arc_row["Status"] == "Downloaded"
    assert arc_row["Location"] == str(arc_file)


def _die_on_arc(src, dst, purpose, **kwargs):
    if purpose is Purpose.ARC:
        raise PlacementError("process killed")
    return place(src, dst, purpose, **kwargs)


def test_a_restart_before_the_arc_copy_finishes_it_on_recover(library, arc, monkeypatch):
    """The library issue completes, then the process dies before the arc copy.

    Recovery makes the copy from the placed library file: the download is gone
    and the library placement is not repeated.
    """
    _claim("rk-I1", "I1")
    fakes = Fakes(_die_on_arc)
    with patch.object(comicarr, "CONFIG", _arc_config(arc)):
        result = process_comic_issue(_arc_match(library), _run(library.download), fakes.deps())

    library_file = library.series_folder / "Saga 001.cbz"
    arc_file = arc / "The Chosen" / "Saga 001.cbz"
    arc_key = _arc_key()
    assert result.outcome == ABORTED
    assert _stage("rk-I1") == journal.POST_PROCESSED
    assert _stage(arc_key) == journal.POST_PROCESSING
    assert not arc_file.exists()
    assert not (library.download / "Saga 001.cbz").exists()

    library_stat = library_file.stat()
    executed = []
    monkeypatch.setattr(comicarr, "APILOCK", threading.Lock(), raising=False)
    with (
        patch.object(comicarr, "CONFIG", _arc_config(arc)),
        patch.object(postprocessing, "_execute", side_effect=lambda item: executed.append(item)),
    ):
        outcome = postprocessing.recover(arc_key)

    assert outcome.action == "arc-copy-finished"
    assert executed == [], "recovery must not re-run post-processing for the download"
    assert arc_file.read_bytes() == b"issue one"
    assert library_file.stat().st_ino == library_stat.st_ino, "the library file must not be placed again"
    assert _stage(arc_key) == journal.POST_PROCESSED
    assert _row(storyarcs, IssueArcID="A1")["Location"] == str(arc_file)


def test_recovering_an_arc_copy_already_made_only_records_it(library, arc, monkeypatch):
    """A crash after the arc copy's ``moved``: recovery records it, copies nothing."""
    _claim("rk-I1", "I1")
    with patch.object(comicarr, "CONFIG", _arc_config(arc)):
        process_comic_issue(_arc_match(library), _run(library.download), Fakes(_die_on_arc).deps())
    arc_key = _arc_key()
    arc_file = arc / "The Chosen" / "Saga 001.cbz"
    arc_file.parent.mkdir(parents=True, exist_ok=True)
    arc_file.write_bytes(b"made before the crash")
    journal.record_transition(
        arc_key, journal.MOVED, payload={"arc_copy": True, "arc_destination": str(arc_file)}, issueid="A1"
    )

    monkeypatch.setattr(comicarr, "APILOCK", threading.Lock(), raising=False)
    with (
        patch.object(comicarr, "CONFIG", _arc_config(arc)),
        patch("comicarr.app.common.placement.place", side_effect=AssertionError("must not copy again")),
    ):
        outcome = postprocessing.recover(arc_key)

    assert outcome.action == "arc-copy-finished"
    assert arc_file.read_bytes() == b"made before the crash"
    assert _stage(arc_key) == journal.POST_PROCESSED
    arc_row = _row(storyarcs, IssueArcID="A1")
    assert arc_row["Status"] == "Downloaded"
    assert arc_row["Location"] == str(arc_file)


# ---------------------------------------------------------------------------
# a manga chapter
# ---------------------------------------------------------------------------


def test_a_manga_chapter_is_placed_and_marked_downloaded(tmp_path):
    download = tmp_path / "download"
    download.mkdir()
    (download / "Chainsaw Man 165.cbz").write_bytes(b"chapter")
    manga_root = tmp_path / "manga"
    with get_engine().begin() as conn:
        conn.execute(
            insert(comics).values(
                ComicID="md-csm",
                ComicName="Chainsaw Man",
                ComicLocation=str(manga_root / "Chainsaw Man"),
                ComicYear="2018",
                ContentType="manga",
                ComicPublisher="Shueisha",
            )
        )
        conn.execute(
            insert(issues).values(
                IssueID="md-csm-ch165",
                ComicID="md-csm",
                ComicName="Chainsaw Man",
                Issue_Number="165",
                ChapterNumber="165",
                Status="Snatched",
                IssueDate="2024-04-01",
            )
        )
    _claim("rk-manga", None)
    fakes = Fakes()
    run = _run(download, comic_id="md-csm", issue_id=None, release_key="rk-manga", nzb_name="Chainsaw Man 165.cbz")

    with patch.object(comicarr, "CONFIG", Config(MANGA_DESTINATION_DIR=str(manga_root))):
        result = process_manga_download(run, fakes.deps(manga_destination=str(manga_root)))

    placed = manga_root / "Chainsaw Man" / "Chainsaw Man 165.cbz"
    assert result.outcome == COMPLETED
    assert result.issue_id == "md-csm-ch165"
    assert placed.read_bytes() == b"chapter"
    assert _row(issues, IssueID="md-csm-ch165")["Status"] == "Downloaded"
    assert fakes.found == [], "manga reconciles through the series queries, not foundsearch"
    assert _stage("rk-manga") == journal.POST_PROCESSED
    assert run.messages[-1] == {
        "self.log": run.log,
        "mode": "stop",
        "comicid": "md-csm",
        "issueid": "md-csm-ch165",
    }


def test_a_manga_download_with_no_destination_stops(tmp_path):
    download = tmp_path / "download"
    download.mkdir()
    (download / "Chainsaw Man 165.cbz").write_bytes(b"chapter")
    with get_engine().begin() as conn:
        conn.execute(insert(comics).values(ComicID="md-csm", ComicName="Chainsaw Man"))
    run = _run(download, comic_id="md-csm", issue_id=None, release_key="rk-manga")

    with patch.object(comicarr, "CONFIG", Config()):
        result = process_manga_download(run, Fakes().deps(manga_destination=None))

    assert result.outcome == "stopped"
    assert "No manga destination directory configured" in run.log
    assert (download / "Chainsaw Man 165.cbz").exists()
    assert _journal_rows() == []
