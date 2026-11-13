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

import pathlib
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

import comicarr
from comicarr import db
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.tables import annuals, comics, issues, metadata, storyarcs
from tests.fakes import folder_request, pipeline


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

    refreshed = []
    matches = postprocessor.match_folder(
        "Manual Run",
        str(folder),
        refresh_series=refreshed.extend,
        rename=lambda src, dst: pathlib.Path(src).replace(dst),
    )
    assert matches.exit is None
    if matches.find_snatched is not None:
        matches = matches.find_snatched(matches.log)
    assert matches.exit is None
    return {
        "library": [(m.comic_id, m.issue_id, m.issue_number, m.location) for m in matches.library],
        "arc_only": [(m.issue_arc_id, m.location) for m in matches.arc_only],
        "one_off": [(s["issueid"], s["comiclocation"]) for s in matches.snatched],
    }


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
        conn.execute(
            comics.insert().values(
                **pipeline.manga_series_row(series_root, LatestDate="2021-01-10", intLatestIssue=10000)
            )
        )
        for row in pipeline.manga_chapter_rows():
            conn.execute(issues.insert().values(**row))
    path = _download(tmp_path, "%s c010.cbz" % pipeline.MANGA_SERIES)

    found = _scan(path.parent)

    assert found == {
        "library": [(pipeline.MANGA_ID, pipeline.manga_chapter_id("10"), "10", str(path))],
        "arc_only": [],
        "one_off": [],
    }


def _arc_row(**overrides):
    row = dict(
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
    row.update(overrides)
    return row


def _processed(folder):
    with (
        patch("comicarr.updater.foundsearch"),
        patch("comicarr.app.notifications.service"),
    ):
        return folder_request.process("Manual Run", folder)


def test_a_manual_scan_places_a_library_match_in_its_series_folder(tmp_path, library):
    path = _download(tmp_path, pipeline.FILENAME)

    messages = _processed(path.parent)

    assert messages[-1]["mode"] == "stop"
    assert (library / pipeline.FILENAME).exists()
    row = db.select_one(select(issues).where(issues.c.IssueID == pipeline.ISSUE_ID))
    assert row["Status"] == "Downloaded"


def test_a_manual_scan_copies_an_arc_only_file_into_its_arc_folder(tmp_path, library, monkeypatch):
    monkeypatch.setattr(comicarr.CONFIG, "STORYARCDIR", True)
    monkeypatch.setattr(comicarr.CONFIG, "COPY2ARCDIR", True)
    monkeypatch.setattr(comicarr.CONFIG, "ARC_FILEOPS", "copy", raising=False)
    with db.get_engine().begin() as conn:
        conn.execute(storyarcs.insert().values(**_arc_row()))
    path = _download(tmp_path, "Batman 024 (2013).cbz")

    _processed(path.parent)

    row = db.select_one(select(storyarcs).where(storyarcs.c.IssueArcID == "arc-1_issue"))
    assert row["Status"] == "Downloaded"
    assert row["Location"] is not None
    placed = pathlib.Path(row["Location"])
    assert placed.exists()
    assert placed.parent != path.parent
    assert "Zero Year" in str(placed.parent)


def test_only_the_facade_imports_the_folder_matcher_module():
    import ast

    root = pathlib.Path(__file__).resolve().parents[2]
    source = (root / "comicarr" / "postprocessor.py").read_text(encoding="utf-8")
    assert "class PostProcessor" not in source
    assert "class FolderCheck" not in source
    importers = set()
    for path in (root / "comicarr").rglob("*.py"):
        if "_vendor" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import) and any(a.name == "comicarr.postprocessor" for a in node.names):
                importers.add(path.relative_to(root).as_posix())
            elif isinstance(node, ast.ImportFrom) and (
                node.module == "comicarr.postprocessor"
                or (node.module == "comicarr" and any(a.name == "postprocessor" for a in node.names))
            ):
                importers.add(path.relative_to(root).as_posix())
    assert importers == {"comicarr/app/downloads/postprocessing.py"}


def test_the_snatch_lookup_runs_after_the_arc_only_files_are_placed(tmp_path, monkeypatch):
    """Placing an arc-only file can complete its snatch, so the lookup waits."""
    from comicarr import postprocessor
    from comicarr.app.downloads import postprocess_pipeline

    order = []
    monkeypatch.setattr(postprocess_pipeline, "place_arc_only_matches", lambda run, deps, arc_only: order.append("arc"))
    monkeypatch.setattr(
        postprocess_pipeline, "dispatch_library_matches", lambda run, deps, library, arc_only: order.append("library")
    )

    def matched(**fields):
        values = dict(
            library=(),
            arc_only=(),
            snatched=(),
            exit=None,
            nzb_folder=str(tmp_path),
            issue_id=None,
            issue_arc_id=None,
            comic_id=None,
            log="matched\n",
        )
        values.update(fields)
        return postprocessor.FolderMatches(**values)

    def find_snatched(log):
        order.append("snatch")
        return matched(log=log + "looked up\n")

    run = folder_request.folder_run("Manual Run", tmp_path)
    run.log = "matched\n"
    run.narrate("placed")
    postprocess_pipeline.process_folder_matches(run, None, matched(find_snatched=find_snatched))

    assert order == ["arc", "snatch", "library"]
    assert run.log == "matched\nplaced\nlooked up\n"


def _arc_folder_config(monkeypatch):
    monkeypatch.setattr(comicarr.CONFIG, "STORYARCDIR", True)
    monkeypatch.setattr(comicarr.CONFIG, "COPY2ARCDIR", True)
    monkeypatch.setattr(comicarr.CONFIG, "ARC_FILEOPS", "copy", raising=False)


def _arc_row_for(issue_arc_id):
    return db.select_one(select(storyarcs).where(storyarcs.c.IssueArcID == issue_arc_id))


def test_an_arc_only_file_whose_tagging_fails_is_still_copied(tmp_path, library, monkeypatch):
    from comicarr import postprocessor

    _arc_folder_config(monkeypatch)
    monkeypatch.setattr(comicarr.CONFIG, "ENABLE_META", True)
    monkeypatch.setattr(postprocessor, "_tag_file", lambda *a, **k: "fail")
    with db.get_engine().begin() as conn:
        conn.execute(storyarcs.insert().values(**_arc_row()))
    path = _download(tmp_path, "Batman 024 (2013).cbz")

    _processed(path.parent)

    row = _arc_row_for("arc-1_issue")
    assert row["Status"] == "Downloaded"
    assert pathlib.Path(row["Location"]).read_bytes() == path.read_bytes()


def test_two_arc_only_files_are_each_copied_from_their_own_source(tmp_path, library, monkeypatch):
    _arc_folder_config(monkeypatch)
    with db.get_engine().begin() as conn:
        conn.execute(storyarcs.insert().values(**_arc_row()))
        conn.execute(
            storyarcs.insert().values(
                **_arc_row(
                    IssueArcID="arc-1_issue2",
                    IssueID="other-issue-25",
                    IssueNumber="25",
                    Int_IssueNumber=25000,
                    ReadingOrder=2,
                    IssueDate="2013-11-01",
                )
            )
        )
    first = _download(tmp_path, "Batman 024 (2013).cbz")
    second = _download(tmp_path, "Batman 025 (2013).cbz")
    second.write_bytes(second.read_bytes() + b"second")

    _processed(first.parent)

    placed = {key: pathlib.Path(_arc_row_for(key)["Location"]) for key in ("arc-1_issue", "arc-1_issue2")}
    assert placed["arc-1_issue"] != placed["arc-1_issue2"]
    assert placed["arc-1_issue"].read_bytes() == first.read_bytes()
    assert placed["arc-1_issue2"].read_bytes() == second.read_bytes()


def test_the_arc_row_is_written_before_its_journal_row_completes(tmp_path, library, monkeypatch):
    from comicarr.app.downloads import _postprocess_completion

    _arc_folder_config(monkeypatch)
    with db.get_engine().begin() as conn:
        conn.execute(storyarcs.insert().values(**_arc_row()))
    path = _download(tmp_path, "Batman 024 (2013).cbz")
    seen = []
    real_complete = _postprocess_completion.complete

    def complete(context, **kwargs):
        seen.append(_arc_row_for("arc-1_issue")["Status"])
        return real_complete(context, **kwargs)

    monkeypatch.setattr(_postprocess_completion, "complete", complete)

    _processed(path.parent)

    assert seen == ["Downloaded"]
