#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Characterization tests for the series rescan seam (#1205).

They pin what ``updater.forceRescan`` does today when ``comicarr/app/`` calls it
through ``comicarr.app.series.rescan``. The real FileChecker reads a temp folder;
nothing touches the network.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select

import comicarr
from comicarr import db, updater
from comicarr.app.series import rescan
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
        CHGROUP=None,
        CHMOD_DIR="0777",
        CHMOD_FILE="0660",
        CHOWNER=None,
        ENABLE_TORRENTS=False,
        IGNORE_SEARCH_WORDS=[],
        READ2FILENAME=False,
    )


@pytest.fixture
def engine(monkeypatch):
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(comicarr, "CONFIG", _config(), raising=False)
    yield engine
    engine.dispose()


def _seed_comic(engine, folder, *, status="Active", issue_rows=()):
    with engine.begin() as conn:
        conn.execute(
            comics.insert(),
            {
                "ComicID": "4050",
                "ComicName": "Wizard",
                "ComicPublisher": "Wizard Press",
                "ComicYear": "1991",
                "ComicLocation": str(folder),
                "Type": "Print",
                "Status": status,
                "Total": len(issue_rows),
            },
        )
        for issue_id, number, issue_status, location in issue_rows:
            conn.execute(
                issues.insert(),
                {
                    "IssueID": issue_id,
                    "ComicID": "4050",
                    "ComicName": "Wizard",
                    "Issue_Number": number,
                    "Int_IssueNumber": int(number) * 1000,
                    "IssueDate": "1991-0%s-01" % number,
                    "Status": issue_status,
                    "Location": location,
                },
            )


def _issue_rows(engine):
    with engine.connect() as conn:
        return {row["IssueID"]: row for row in conn.execute(select(issues)).mappings()}


def _have(engine):
    with engine.connect() as conn:
        return conn.execute(select(comics.c.Have).where(comics.c.ComicID == "4050")).scalar_one()


def test_a_file_that_appears_marks_its_wanted_issue_downloaded(engine, tmp_path):
    folder = tmp_path / "Wizard (1991)"
    folder.mkdir()
    (folder / "Wizard 001 (1991).cbz").write_bytes(b"issue one")
    _seed_comic(engine, folder, issue_rows=[("wiz-1", "1", "Wanted", None), ("wiz-2", "2", "Wanted", None)])

    rescan.rescan_series("4050")

    rows = _issue_rows(engine)
    assert rows["wiz-1"]["Status"] == "Downloaded"
    assert rows["wiz-1"]["Location"] == "Wizard 001 (1991).cbz"
    assert rows["wiz-1"]["ComicSize"] == str(len(b"issue one"))
    assert rows["wiz-2"]["Status"] == "Wanted"
    assert _have(engine) == 1


def test_a_file_found_in_an_archive_folder_is_marked_archived(engine, tmp_path):
    folder = tmp_path / "Wizard (1991)"
    folder.mkdir()
    archive = tmp_path / "inbox"
    archive.mkdir()
    (archive / "Wizard 002 (1991).cbz").write_bytes(b"issue two")
    _seed_comic(engine, folder, issue_rows=[("wiz-1", "1", "Wanted", None), ("wiz-2", "2", "Wanted", None)])

    rescan.rescan_series("4050", archive=str(archive))

    rows = _issue_rows(engine)
    assert rows["wiz-2"]["Status"] == "Archived"
    assert rows["wiz-2"]["Location"] == "Wizard 002 (1991).cbz"
    assert rows["wiz-1"]["Status"] == "Wanted"


def test_a_file_that_disappears_moves_its_downloaded_issue_to_archived(engine, tmp_path):
    folder = tmp_path / "Wizard (1991)"
    folder.mkdir()
    (folder / "Wizard 001 (1991).cbz").write_bytes(b"issue one")
    _seed_comic(
        engine,
        folder,
        issue_rows=[
            ("wiz-1", "1", "Downloaded", "Wizard 001 (1991).cbz"),
            ("wiz-2", "2", "Downloaded", "Wizard 002 (1991).cbz"),
            ("wiz-3", "3", "Wanted", None),
        ],
    )

    rescan.rescan_series("4050")

    rows = _issue_rows(engine)
    assert rows["wiz-1"]["Status"] == "Downloaded"
    assert rows["wiz-2"]["Status"] == "Archived"
    # The location of the vanished file is kept, not cleared.
    assert rows["wiz-2"]["Location"] == "Wizard 002 (1991).cbz"
    # Only Downloaded issues move; a Wanted issue without a file stays Wanted.
    assert rows["wiz-3"]["Status"] == "Wanted"
    # Archived issues still count toward Have.
    assert _have(engine) == 2


def test_a_paused_series_keeps_the_status_of_an_issue_whose_file_disappeared(engine, tmp_path):
    folder = tmp_path / "Wizard (1991)"
    folder.mkdir()
    (folder / "Wizard 001 (1991).cbz").write_bytes(b"issue one")
    _seed_comic(
        engine,
        folder,
        status="Paused",
        issue_rows=[
            ("wiz-1", "1", "Downloaded", "Wizard 001 (1991).cbz"),
            ("wiz-2", "2", "Downloaded", "Wizard 002 (1991).cbz"),
        ],
    )

    rescan.rescan_series("4050")

    rows = _issue_rows(engine)
    assert rows["wiz-1"]["Status"] == "Downloaded"
    assert rows["wiz-2"]["Status"] == "Downloaded"


def test_a_manga_series_is_rematched_by_the_manga_rescan_not_filechecker(engine, tmp_path, monkeypatch):
    (tmp_path / "Naruto 12.cbz").write_bytes(b"volume twelve")
    with engine.begin() as conn:
        conn.execute(
            comics.insert(),
            {
                "ComicID": "md-naruto",
                "ComicName": "Naruto",
                "ComicPublisher": "Shueisha",
                "ComicYear": "1999",
                "ComicLocation": str(tmp_path),
                "Type": "Print",
                "Status": "Active",
                "ContentType": "manga",
                "BareNumberMode": "volumes",
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
                "IssueDate": "2001-01-01",
                "Status": "Wanted",
            },
        )
    monkeypatch.setattr(
        updater.filechecker,
        "FileChecker",
        MagicMock(side_effect=AssertionError("manga rescan must not use FileChecker")),
    )

    rescan.rescan_series("md-naruto")

    with engine.connect() as conn:
        row = conn.execute(select(issues).where(issues.c.IssueID == "md-naruto-ch100")).mappings().one()
    assert row["Status"] == "Downloaded"
    assert row["Location"] == "Naruto 12.cbz"


def test_the_seam_passes_archive_only_when_given(monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "forceRescan", lambda *args, **kwargs: calls.append((args, kwargs)))

    rescan.rescan_series("4050")
    rescan.rescan_series("4050", archive="/inbox")

    assert calls == [(("4050",), {}), (("4050",), {"archive": "/inbox"})]


def test_the_seam_lets_a_rescan_failure_propagate(monkeypatch):
    monkeypatch.setattr(updater, "forceRescan", MagicMock(side_effect=RuntimeError("disk gone")))

    with pytest.raises(RuntimeError, match="disk gone"):
        rescan.rescan_series("4050")
