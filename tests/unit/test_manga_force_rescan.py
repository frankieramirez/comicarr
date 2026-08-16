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


def _seed_manga(engine, tmp_path, *, bare_mode="volumes"):
    with engine.begin() as conn:
        conn.execute(
            comics.insert(),
            {
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
            },
        )
        conn.execute(
            issues.insert(),
            {
                "IssueID": "md-naruto-ch100",
                "ComicID": "md-naruto",
                "Issue_Number": "100",
                "Int_IssueNumber": 100000,
                "ChapterNumber": "100",
                "VolumeNumber": "12",
                "IssueName": "Chapter 100",
                "IssueDate": "2001-01-01",
                "Status": "Wanted",
                "forced_file": None,
            },
        )


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
