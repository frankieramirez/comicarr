#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""forceRescan rematches manga folders with BareNumberMode, not FileChecker."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy import create_engine, select

import comicarr
from comicarr import updater
from comicarr.app.manga.rescan import mark_parsed_files_downloaded
from comicarr.tables import comics, issues, metadata


def _config():
    return SimpleNamespace(
        ANNUALS_ON=False,
        MULTIPLE_DEST_DIRS=None,
        DUPECONSTRAINT="filesize",
        IGNORE_HAVETOTAL=False,
        IGNORE_TOTAL=False,
        SNATCHED_HAVETOTAL=False,
        ENFORCE_PERMS=False,
        AUTOWANT_ALL=False,
    )


def _seed_manga(engine, tmp_path, *, bare_mode="volumes", status="Wanted", location=None, have=None):
    comic_row = {
        "ComicID": "md-naruto",
        "ComicName": "Naruto",
        "ComicPublisher": "Shueisha",
        "ComicYear": "1999",
        "ComicLocation": str(tmp_path),
        "AlternateSearch": None,
        "Type": "Print",
        "Corrected_Type": None,
        "Status": "Active",
        "ContentType": "manga",
        "BareNumberMode": bare_mode,
    }
    if have is not None:
        comic_row["Have"] = have
    issue_row = {
        "IssueID": "md-naruto-ch100",
        "ComicID": "md-naruto",
        "Issue_Number": "100",
        "Int_IssueNumber": 100000,
        "ChapterNumber": "100",
        "VolumeNumber": "12",
        "IssueName": "Chapter 100",
        "IssueDate": "2001-01-01",
        "Status": status,
        "forced_file": None,
    }
    if location is not None:
        issue_row["Location"] = location
    with engine.begin() as conn:
        conn.execute(comics.insert(), comic_row)
        conn.execute(issues.insert(), issue_row)


def test_force_rescan_volume_bare_file_marks_chapters_in_that_volume(monkeypatch, tmp_path):
    (tmp_path / "Naruto 12.cbr").write_bytes(b"cbz")
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    _seed_manga(engine, tmp_path, bare_mode="volumes")

    monkeypatch.setattr(updater.db, "get_engine", lambda: engine)
    monkeypatch.setattr(comicarr, "CONFIG", _config(), raising=False)
    monkeypatch.setattr(
        updater.filechecker,
        "FileChecker",
        MagicMock(side_effect=AssertionError("manga forceRescan must not use FileChecker")),
    )

    updater.forceRescan("md-naruto")

    with engine.connect() as conn:
        row = conn.execute(select(issues).where(issues.c.IssueID == "md-naruto-ch100")).mappings().one()
    assert row["Status"] == "Downloaded"
    assert row["Location"] == "Naruto 12.cbr"


def test_force_rescan_empty_manga_folder_does_not_crash(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    _seed_manga(engine, tmp_path, bare_mode="auto")
    monkeypatch.setattr(updater.db, "get_engine", lambda: engine)
    monkeypatch.setattr(comicarr, "CONFIG", _config(), raising=False)

    updater.forceRescan("md-naruto")

    with engine.connect() as conn:
        row = conn.execute(select(issues).where(issues.c.IssueID == "md-naruto-ch100")).mappings().one()
    assert row["Status"] == "Wanted"


def test_force_rescan_repoints_location_when_cbr_became_cbz(monkeypatch, tmp_path):
    """Metatag exports .cbr to .cbz; an already-Downloaded row must follow the file."""
    (tmp_path / "Naruto 12.cbz").write_bytes(b"cbz")
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    _seed_manga(
        engine,
        tmp_path,
        bare_mode="volumes",
        status="Downloaded",
        location="Naruto 12.cbr",
        have=1,
    )

    monkeypatch.setattr(updater.db, "get_engine", lambda: engine)
    monkeypatch.setattr(comicarr, "CONFIG", _config(), raising=False)
    monkeypatch.setattr(
        updater.filechecker,
        "FileChecker",
        MagicMock(side_effect=AssertionError("manga forceRescan must not use FileChecker")),
    )

    updater.forceRescan("md-naruto")

    with engine.connect() as conn:
        row = conn.execute(select(issues).where(issues.c.IssueID == "md-naruto-ch100")).mappings().one()
        comic = conn.execute(select(comics).where(comics.c.ComicID == "md-naruto")).mappings().one()
    assert row["Status"] == "Downloaded"
    assert row["Location"] == "Naruto 12.cbz"
    assert comic["Have"] == 1


def test_mark_parsed_files_downloaded_repoints_stale_location_only(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    _seed_manga(
        engine,
        tmp_path,
        status="Downloaded",
        location="Naruto 100.cbr",
        have=1,
    )
    monkeypatch.setattr(updater.db, "get_engine", lambda: engine)

    count = mark_parsed_files_downloaded(
        "md-naruto",
        [(str(tmp_path / "Naruto 100.cbz"), {"chapter_number": 100, "volume_number": None})],
    )

    assert count == 0
    with engine.connect() as conn:
        row = conn.execute(select(issues).where(issues.c.IssueID == "md-naruto-ch100")).mappings().one()
        comic = conn.execute(select(comics).where(comics.c.ComicID == "md-naruto")).mappings().one()
    assert row["Status"] == "Downloaded"
    assert row["Location"] == "Naruto 100.cbz"
    assert comic["Have"] == 1


def test_mark_parsed_files_downloaded_skips_matching_downloaded_location(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    _seed_manga(
        engine,
        tmp_path,
        status="Downloaded",
        location="Naruto 100.cbz",
        have=1,
    )
    monkeypatch.setattr(updater.db, "get_engine", lambda: engine)

    count = mark_parsed_files_downloaded(
        "md-naruto",
        [(str(tmp_path / "Naruto 100.cbz"), {"chapter_number": 100, "volume_number": None})],
    )

    assert count == 0
    with engine.connect() as conn:
        row = conn.execute(select(issues).where(issues.c.IssueID == "md-naruto-ch100")).mappings().one()
        comic = conn.execute(select(comics).where(comics.c.ComicID == "md-naruto")).mappings().one()
    assert row["Status"] == "Downloaded"
    assert row["Location"] == "Naruto 100.cbz"
    assert comic["Have"] == 1


def test_mark_parsed_files_downloaded_keeps_chapter_location_when_volume_pack_matches(monkeypatch, tmp_path):
    (tmp_path / "Naruto c100.cbz").write_bytes(b"chapter")
    (tmp_path / "Naruto v12.cbz").write_bytes(b"volume")
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    _seed_manga(
        engine,
        tmp_path,
        status="Downloaded",
        location="Naruto c100.cbz",
        have=1,
    )
    monkeypatch.setattr(updater.db, "get_engine", lambda: engine)

    count = mark_parsed_files_downloaded(
        "md-naruto",
        [
            (str(tmp_path / "Naruto c100.cbz"), {"chapter_number": 100, "volume_number": None}),
            (str(tmp_path / "Naruto v12.cbz"), {"chapter_number": None, "volume_number": 12}),
        ],
    )

    assert count == 0
    with engine.connect() as conn:
        row = conn.execute(select(issues).where(issues.c.IssueID == "md-naruto-ch100")).mappings().one()
        comic = conn.execute(select(comics).where(comics.c.ComicID == "md-naruto")).mappings().one()
    assert row["Status"] == "Downloaded"
    assert row["Location"] == "Naruto c100.cbz"
    assert comic["Have"] == 1


def test_force_rescan_ignores_nested_leftover_cbr_when_root_is_cbz(monkeypatch, tmp_path):
    (tmp_path / "Naruto 12.cbz").write_bytes(b"cbz")
    leftover = tmp_path / "old"
    leftover.mkdir()
    (leftover / "Naruto 12.cbr").write_bytes(b"cbr")
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    _seed_manga(
        engine,
        tmp_path,
        bare_mode="volumes",
        status="Downloaded",
        location="Naruto 12.cbr",
        have=1,
    )

    monkeypatch.setattr(updater.db, "get_engine", lambda: engine)
    monkeypatch.setattr(comicarr, "CONFIG", _config(), raising=False)
    monkeypatch.setattr(
        updater.filechecker,
        "FileChecker",
        MagicMock(side_effect=AssertionError("manga forceRescan must not use FileChecker")),
    )

    updater.forceRescan("md-naruto")

    with engine.connect() as conn:
        row = conn.execute(select(issues).where(issues.c.IssueID == "md-naruto-ch100")).mappings().one()
        comic = conn.execute(select(comics).where(comics.c.ComicID == "md-naruto")).mappings().one()
    assert row["Status"] == "Downloaded"
    assert row["Location"] == "Naruto 12.cbz"
    assert comic["Have"] == 1
