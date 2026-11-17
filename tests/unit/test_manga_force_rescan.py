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
from comicarr.tables import comics, issues, manga_volumes, metadata


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


def _volume_rows(engine):
    with engine.connect() as conn:
        return {row["VolumeNumber"]: dict(row) for row in conn.execute(select(manga_volumes)).mappings()}


def test_force_rescan_volume_bare_file_records_the_volume(monkeypatch, tmp_path):
    """A volume file is a volume (ADR-0004), recorded like post-processing records it."""
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
        comic = conn.execute(select(comics).where(comics.c.ComicID == "md-naruto")).mappings().one()
    volume = _volume_rows(engine)["12"]
    assert volume["Status"] == "Downloaded"
    assert volume["Location"] == "Naruto 12.cbr"
    # The chapter is not a file of its own: it reads Covered through volume 12.
    assert row["Status"] == "Wanted"
    assert row["Location"] is None
    assert comic["Have"] == 1


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


def test_force_rescan_hands_an_old_volume_location_back_to_the_volume(monkeypatch, tmp_path):
    """An older rescan stored the volume file on the chapter; metatag later made it .cbz."""
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
    volume = _volume_rows(engine)["12"]
    assert volume["Status"] == "Downloaded"
    assert volume["Location"] == "Naruto 12.cbz"
    assert row["Status"] == "Skipped"
    assert row["Location"] is None
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

    assert count == 1
    with engine.connect() as conn:
        row = conn.execute(select(issues).where(issues.c.IssueID == "md-naruto-ch100")).mappings().one()
        comic = conn.execute(select(comics).where(comics.c.ComicID == "md-naruto")).mappings().one()
    assert row["Status"] == "Downloaded"
    assert row["Location"] == "Naruto c100.cbz"
    assert comic["Have"] == 1
    assert _volume_rows(engine)["12"]["Location"] == "Naruto v12.cbz"


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
    volume = _volume_rows(engine)["12"]
    assert volume["Location"] == "Naruto 12.cbz"
    assert row["Status"] == "Skipped"
    assert row["Location"] is None
    assert comic["Have"] == 1


def test_volume_file_with_no_listed_chapters_is_recorded_not_dropped(monkeypatch, tmp_path):
    """MangaDex lists no chapters for many volumes; their files must still count."""
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    _seed_manga(engine, tmp_path)
    monkeypatch.setattr(updater.db, "get_engine", lambda: engine)

    count = mark_parsed_files_downloaded(
        "md-naruto",
        [(str(tmp_path / "Naruto v30.cbz"), {"chapter_number": None, "volume_number": 30})],
        directory=str(tmp_path),
    )

    assert count == 1
    volume = _volume_rows(engine)["30"]
    assert volume["Status"] == "Downloaded"
    assert volume["Location"] == "Naruto v30.cbz"


def test_rescanned_volume_leaves_the_search_frontier(monkeypatch, tmp_path):
    """Before, a rescanned volume was owned only through its chapters, so blended search kept looking for it."""
    from comicarr.app.manga.acquisition import search_plan_for_series
    from comicarr.app.manga.volumes import volume_states

    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    _seed_manga(engine, tmp_path)
    monkeypatch.setattr(updater.db, "get_engine", lambda: engine)

    mark_parsed_files_downloaded(
        "md-naruto",
        [(str(tmp_path / "Naruto v12.cbz"), {"chapter_number": None, "volume_number": 12})],
        directory=str(tmp_path),
    )

    with engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(select(issues)).mappings()]
    targets = search_plan_for_series({"MonitorMode": "blended"}, rows, volume_states("md-naruto"))
    assert {"kind": "volume", "number": "12"} not in targets
    assert not [target for target in targets if target["kind"] == "chapter"]


def test_rescan_twice_counts_a_volume_once(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    _seed_manga(engine, tmp_path)
    monkeypatch.setattr(updater.db, "get_engine", lambda: engine)
    files = [(str(tmp_path / "Naruto v12.cbz"), {"chapter_number": None, "volume_number": 12})]

    assert mark_parsed_files_downloaded("md-naruto", files, directory=str(tmp_path)) == 1
    assert mark_parsed_files_downloaded("md-naruto", files, directory=str(tmp_path)) == 0
