#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Regression coverage for MAL manga refresh/rescan/cover failures reported in issue #298."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select

import comicarr
from comicarr import importer, updater
from comicarr.tables import comics, issues, metadata


class TestAddComictoDBMangaRouting:
    """Defect 2a: addComictoDB must route mal-/md- IDs to the manga importer, not ComicVine."""

    @patch("comicarr.importer.cv.getComic")
    @patch("comicarr.importer.addMangaToDB_MAL")
    def test_mal_id_routes_to_mal_importer(self, mock_mal, mock_getcomic):
        sentinel = {"status": "complete", "comicid": "mal-161890"}
        mock_mal.return_value = sentinel

        result = importer.addComictoDB("mal-161890")

        assert result is sentinel
        mock_mal.assert_called_once_with("mal-161890", imported=None, calledfrom=None)
        mock_getcomic.assert_not_called()

    @patch("comicarr.importer.cv.getComic")
    @patch("comicarr.importer.addMangaToDB")
    def test_md_id_routes_to_mangadex_importer(self, mock_md, mock_getcomic):
        sentinel = {"status": "complete", "comicid": "md-abc"}
        mock_md.return_value = sentinel

        result = importer.addComictoDB("md-abc")

        assert result is sentinel
        mock_md.assert_called_once_with("md-abc", imported=None, calledfrom=None)
        mock_getcomic.assert_not_called()


class TestDbUpdateMangaShortCircuit:
    """Defect 2b: dbUpdate must refresh manga through the manga importer and skip the
    CV issuedata reconciliation that deletes issue rows and expects issuedata."""

    def test_manga_refresh_skips_cv_reconciliation(self, monkeypatch):
        engine = create_engine("sqlite://")
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(
                comics.insert(),
                {
                    "ComicID": "mal-161890",
                    "ComicName": "Test Manga",
                    "ComicYear": "2020",
                    "Status": "Active",
                    "LastUpdated": None,
                },
            )

        monkeypatch.setattr(updater.db, "get_engine", lambda: engine)
        monkeypatch.setattr(comicarr, "IMPORTLOCK", False, raising=False)
        monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(CV_ONLY=True, CV_ONETIMER=1), raising=False)
        monkeypatch.setattr(comicarr, "GLOBAL_MESSAGES", {}, raising=False)

        mock_add = MagicMock(return_value={"status": "complete", "comicid": "mal-161890", "content_type": "manga"})
        mock_rescan = MagicMock()
        monkeypatch.setattr(comicarr.importer, "addComictoDB", mock_add)
        monkeypatch.setattr(updater, "forceRescan", mock_rescan)

        updater.dbUpdate(["mal-161890"], calledfrom="refresh")

        # Manga branch calls addComictoDB positionally (no annload/csyear kwargs) and
        # then re-matches files via forceRescan -- never the CV delete-and-reload path.
        mock_add.assert_called_once_with("mal-161890", "no")
        mock_rescan.assert_called_once_with("mal-161890")
        assert comicarr.GLOBAL_MESSAGES["status"] == "success"


class TestForceRescanNullIssueDate:
    """Defect 1: forceRescan must not crash when a manga chapter row has a NULL IssueDate."""

    def test_null_issuedate_does_not_crash(self, monkeypatch, tmp_path):
        engine = create_engine("sqlite://")
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(
                comics.insert(),
                {
                    "ComicID": "mal-161890",
                    "ComicName": "Test Manga",
                    "ComicPublisher": "Unknown",
                    "ComicYear": "2020",
                    "ComicLocation": str(tmp_path),
                    "AlternateSearch": None,
                    "Type": "Manga",
                    "Corrected_Type": None,
                    "Status": "Active",
                },
            )
            conn.execute(
                issues.insert(),
                {
                    "IssueID": "issue-1",
                    "ComicID": "mal-161890",
                    "Issue_Number": "1",
                    "Int_IssueNumber": 1000,
                    "IssueName": "Chapter 1",
                    "IssueDate": None,  # the crash trigger
                    "Status": "Skipped",
                    "forced_file": None,
                },
            )

        monkeypatch.setattr(updater.db, "get_engine", lambda: engine)
        monkeypatch.setattr(
            comicarr,
            "CONFIG",
            SimpleNamespace(
                ANNUALS_ON=False,
                MULTIPLE_DEST_DIRS=None,
                DUPECONSTRAINT="filesize",
                IGNORE_HAVETOTAL=False,
                IGNORE_TOTAL=False,
                SNATCHED_HAVETOTAL=False,
                ENFORCE_PERMS=False,
                AUTOWANT_ALL=False,
            ),
            raising=False,
        )

        fake_filecheck = MagicMock()
        fake_filecheck.listFiles.return_value = {
            "comiccount": 1,
            "comiclist": [
                {
                    "ComicFilename": "Test Manga 001.cbz",
                    "ComicLocation": str(tmp_path),
                    "ComicSize": 1234,
                    "JusttheDigits": "1",
                    "AnnualComicID": None,
                    "SeriesVolume": None,
                }
            ],
        }
        monkeypatch.setattr(updater.filechecker, "FileChecker", lambda **kwargs: fake_filecheck)

        try:
            updater.forceRescan("mal-161890")
        except TypeError as e:
            if "subscriptable" in str(e):
                pytest.fail("forceRescan crashed on NULL IssueDate: %s" % e)
            raise

    def test_empty_year_does_not_resolve_duplicate_issue_numbers(self, monkeypatch, tmp_path):
        """Same-number rows with NULL IssueDate must not year-match via empty substring.

        ``"" in filename`` is always true, so without a nonempty-year guard the first
        duplicate candidate would claim the file and overwrite its status/location.
        """
        engine = create_engine("sqlite://")
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(
                comics.insert(),
                {
                    "ComicID": "mal-161890",
                    "ComicName": "Test Manga",
                    "ComicPublisher": "Unknown",
                    "ComicYear": "2020",
                    "ComicLocation": str(tmp_path),
                    "AlternateSearch": None,
                    "Type": "Manga",
                    "Corrected_Type": None,
                    "Status": "Active",
                },
            )
            for issue_id in ("issue-a", "issue-b"):
                conn.execute(
                    issues.insert(),
                    {
                        "IssueID": issue_id,
                        "ComicID": "mal-161890",
                        "Issue_Number": "1",
                        "Int_IssueNumber": 1000,
                        "IssueName": "Chapter 1",
                        "IssueDate": None,
                        "Status": "Skipped",
                        "Location": None,
                        "forced_file": None,
                    },
                )

        monkeypatch.setattr(updater.db, "get_engine", lambda: engine)
        monkeypatch.setattr(
            comicarr,
            "CONFIG",
            SimpleNamespace(
                ANNUALS_ON=False,
                MULTIPLE_DEST_DIRS=None,
                DUPECONSTRAINT="filesize",
                IGNORE_HAVETOTAL=False,
                IGNORE_TOTAL=False,
                SNATCHED_HAVETOTAL=False,
                ENFORCE_PERMS=False,
                AUTOWANT_ALL=False,
            ),
            raising=False,
        )

        fake_filecheck = MagicMock()
        fake_filecheck.listFiles.return_value = {
            "comiccount": 1,
            "comiclist": [
                {
                    "ComicFilename": "Test Manga 001.cbz",
                    "ComicLocation": str(tmp_path),
                    "ComicSize": 1234,
                    "JusttheDigits": "1",
                    "AnnualComicID": None,
                    "SeriesVolume": None,
                }
            ],
        }
        monkeypatch.setattr(updater.filechecker, "FileChecker", lambda **kwargs: fake_filecheck)

        updater.forceRescan("mal-161890")

        with engine.connect() as conn:
            rows = (
                conn.execute(select(issues).where(issues.c.ComicID == "mal-161890").order_by(issues.c.IssueID))
                .mappings()
                .all()
            )

        assert len(rows) == 2
        # Leave the duplicate unresolved rather than binding the file to an arbitrary row.
        assert all(row["Status"] == "Skipped" for row in rows)
        assert all(not row["Location"] for row in rows)


def _mal_details(cover_url="https://cdn.myanimelist.net/images/manga/2/253146l.jpg"):
    return {
        "name": "One Piece",
        "alt_titles": [],
        "description": "Pirates",
        "year": "1997",
        "status": "ongoing",
        "last_chapter": None,
        "author": "Oda",
        "cover_url": cover_url,
        "url": "https://myanimelist.net/manga/13",
    }


class TestMangaCoverCachePath:
    """Defect 3b: a successful cover download repoints ComicImage at the local cache path
    (CSP-safe), while ComicImageURL keeps the external URL for the /art fallback."""

    def _add(self, monkeypatch, getimage_status):
        engine = create_engine("sqlite://")
        metadata.create_all(engine)
        monkeypatch.setattr(importer.db, "get_engine", lambda: engine)
        monkeypatch.setattr(comicarr, "COMICSORT", None, raising=False)
        monkeypatch.setattr(
            comicarr,
            "CONFIG",
            SimpleNamespace(CREATE_FOLDERS=False, FOLDER_FORMAT="$Series ($Year)"),
            raising=False,
        )

        monkeypatch.setattr("comicarr.myanimelist.get_manga_details", lambda _id: _mal_details())
        monkeypatch.setattr("comicarr.mangadex.find_by_mal_id", lambda *a, **k: "uuid-1")
        monkeypatch.setattr("comicarr.config.get_manga_destination", lambda: None)
        monkeypatch.setattr(importer.helpers, "getImage", lambda *a, **k: {"status": getimage_status})
        monkeypatch.setattr(importer, "_populate_manga_chapters", lambda *a, **k: None)
        monkeypatch.setattr(importer.helpers, "ComicSort", lambda **k: None)

        importer.addMangaToDB_MAL("mal-13")

        with engine.connect() as conn:
            return conn.execute(select(comics).where(comics.c.ComicID == "mal-13")).mappings().one()

    def test_success_points_comicimage_at_cache(self, monkeypatch):
        row = self._add(monkeypatch, "success")
        assert row["ComicImage"] == "cache/mal-13.jpg"
        assert row["ComicImageURL"] == "https://cdn.myanimelist.net/images/manga/2/253146l.jpg"

    def test_failed_download_leaves_external_url(self, monkeypatch):
        row = self._add(monkeypatch, "failed")
        assert row["ComicImage"] == "https://cdn.myanimelist.net/images/manga/2/253146l.jpg"


# Defect 3a (the MAL cover CDN must be in the CSP img-src allowlist) is now
# pinned structurally in tests/unit/test_image_hosts.py: the CSP is derived from
# the same allowlist the SSRF guard uses, so a host can no longer be in one and
# not the other.


class TestMangaRefreshPreservesLibraryState:
    """Review findings: Refresh must not destroy name, status, or location."""

    def _seed_existing_mal(self, engine, *, status="Active", location="/library/One Piece (1997)"):
        with engine.begin() as conn:
            conn.execute(
                comics.insert(),
                {
                    "ComicID": "mal-13",
                    "ComicName": "One Piece",
                    "ComicYear": "1997",
                    "Status": status,
                    "ComicLocation": location,
                    "Type": "Manga",
                },
            )
            conn.execute(
                issues.insert(),
                {
                    "IssueID": "mal-13-ch1",
                    "ComicID": "mal-13",
                    "Issue_Number": "1",
                    "Int_IssueNumber": 1000,
                    "IssueName": "Chapter 1",
                    "Status": "Downloaded",
                    "Location": "One Piece 001.cbz",
                    "forced_file": None,
                },
            )

    def test_fetch_failure_preserves_existing_name_and_status(self, monkeypatch):
        engine = create_engine("sqlite://")
        metadata.create_all(engine)
        self._seed_existing_mal(engine, status="Paused")
        monkeypatch.setattr(importer.db, "get_engine", lambda: engine)
        monkeypatch.setattr("comicarr.myanimelist.get_manga_details", lambda _id: None)

        result = importer.addMangaToDB_MAL("mal-13")

        assert result["status"] == "incomplete"
        with engine.connect() as conn:
            row = conn.execute(select(comics).where(comics.c.ComicID == "mal-13")).mappings().one()
        assert row["ComicName"] == "One Piece"
        assert row["Status"] == "Paused"

    def test_fetch_failure_placeholder_only_for_new_series(self, monkeypatch):
        engine = create_engine("sqlite://")
        metadata.create_all(engine)
        monkeypatch.setattr(importer.db, "get_engine", lambda: engine)
        monkeypatch.setattr("comicarr.myanimelist.get_manga_details", lambda _id: None)

        result = importer.addMangaToDB_MAL("mal-999")

        assert result["status"] == "incomplete"
        with engine.connect() as conn:
            row = conn.execute(select(comics).where(comics.c.ComicID == "mal-999")).mappings().one()
        assert "Fetch failed" in row["ComicName"]
        assert row["Status"] == "Active"

    def test_refresh_preserves_comiclocation_when_manga_dest_set(self, monkeypatch, tmp_path):
        engine = create_engine("sqlite://")
        metadata.create_all(engine)
        existing = str(tmp_path / "existing-library")
        self._seed_existing_mal(engine, location=existing)
        monkeypatch.setattr(importer.db, "get_engine", lambda: engine)
        monkeypatch.setattr(comicarr, "COMICSORT", None, raising=False)
        monkeypatch.setattr(
            comicarr,
            "CONFIG",
            SimpleNamespace(CREATE_FOLDERS=False, FOLDER_FORMAT="$Series ($Year)"),
            raising=False,
        )
        monkeypatch.setattr("comicarr.myanimelist.get_manga_details", lambda _id: _mal_details())
        monkeypatch.setattr("comicarr.mangadex.find_by_mal_id", lambda *a, **k: None)
        monkeypatch.setattr("comicarr.config.get_manga_destination", lambda: str(tmp_path / "manga-dest"))
        monkeypatch.setattr(importer.helpers, "getImage", lambda *a, **k: {"status": "failed"})
        monkeypatch.setattr(importer, "_populate_manga_chapters", lambda *a, **k: None)
        monkeypatch.setattr(importer.helpers, "ComicSort", lambda **k: None)

        importer.addMangaToDB_MAL("mal-13")

        with engine.connect() as conn:
            row = conn.execute(select(comics).where(comics.c.ComicID == "mal-13")).mappings().one()
        assert row["ComicLocation"] == existing

    def test_populate_preserves_existing_chapter_status(self, monkeypatch):
        engine = create_engine("sqlite://")
        metadata.create_all(engine)
        self._seed_existing_mal(engine)
        monkeypatch.setattr(importer.db, "get_engine", lambda: engine)
        monkeypatch.setattr(
            comicarr,
            "CONFIG",
            SimpleNamespace(AUTOWANT_ALL=False, MANGADEX_LANGUAGES="en"),
            raising=False,
        )
        monkeypatch.setattr(
            "comicarr.mangadex.get_all_chapters",
            lambda _id: [{"chapter": "1", "title": "Romance Dawn", "publish_at": "1997-07-22T00:00:00"}],
        )
        monkeypatch.setattr("comicarr.mangadex.get_total_chapter_count", lambda _id: 1)

        importer._populate_manga_chapters(
            "mal-13",
            "One Piece",
            mangadex_uuid="uuid-1",
            mal_num_chapters=None,
            controlValueDict={"ComicID": "mal-13"},
        )

        with engine.connect() as conn:
            row = conn.execute(select(issues).where(issues.c.IssueID == "mal-13-ch1")).mappings().one()
        assert row["Status"] == "Downloaded"
        assert row["Location"] == "One Piece 001.cbz"
        assert row["IssueName"] == "Romance Dawn"


class TestMangaRefreshForceRescanErrors:
    """#4: forceRescan exceptions must not report Refresh success."""

    def test_forcerescan_exception_sets_failure_message(self, monkeypatch):
        engine = create_engine("sqlite://")
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(
                comics.insert(),
                {
                    "ComicID": "mal-161890",
                    "ComicName": "Test Manga",
                    "ComicYear": "2020",
                    "Status": "Active",
                    "LastUpdated": None,
                },
            )

        monkeypatch.setattr(updater.db, "get_engine", lambda: engine)
        monkeypatch.setattr(comicarr, "IMPORTLOCK", False, raising=False)
        monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(CV_ONLY=True, CV_ONETIMER=1), raising=False)
        monkeypatch.setattr(comicarr, "GLOBAL_MESSAGES", {}, raising=False)
        monkeypatch.setattr(
            comicarr.importer,
            "addComictoDB",
            MagicMock(return_value={"status": "complete", "comicid": "mal-161890"}),
        )
        monkeypatch.setattr(updater, "forceRescan", MagicMock(side_effect=RuntimeError("disk gone")))

        updater.dbUpdate(["mal-161890"], calledfrom="refresh")

        assert comicarr.GLOBAL_MESSAGES["status"] == "failure"
        assert "rescanning" in comicarr.GLOBAL_MESSAGES["message"].lower()
