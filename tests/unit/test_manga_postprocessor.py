#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""
Unit tests for manga post-processing in comicarr/postprocessor.py.

Tests cover the _process_manga() method and the manga branch in Process().
"""

import queue
from unittest.mock import MagicMock, patch

import comicarr

# Ensure LOG_LEVEL is set for tests
if comicarr.LOG_LEVEL is None:
    comicarr.LOG_LEVEL = 0

from comicarr.postprocessor import PostProcessor


def _make_pp(nzb_name, nzb_folder, comicid=None, issueid=None, apicall=False):
    """Create a PostProcessor instance with mocks for queue and APILOCK."""
    mock_queue = MagicMock(spec=queue.Queue)
    mock_apilock = MagicMock()
    mock_apilock.locked.return_value = False

    mock_config = MagicMock()
    mock_config.FILE_OPTS = "move"
    mock_config.IGNORE_SEARCH_WORDS = []
    mock_config.PRE_SCRIPTS = None

    with patch.object(comicarr, "APILOCK", mock_apilock), \
         patch.object(comicarr, "CONFIG", mock_config):
        pp = PostProcessor(
            nzb_name=nzb_name,
            nzb_folder=nzb_folder,
            comicid=comicid,
            issueid=issueid,
            queue=mock_queue,
            apicall=apicall,
        )
    return pp, mock_queue


class TestMangaBranchDetection:
    """Tests for the manga branch guard in Process()."""

    def test_md_prefix_triggers_manga_branch(self):
        """ComicID starting with 'md-' should trigger _process_manga."""
        pp, mock_queue = _make_pp(
            nzb_name="Chainsaw Man 165.cbz",
            nzb_folder="/tmp/downloads",
            comicid="md-abc123",
            apicall=True,
        )
        with patch.object(pp, "_process_manga", return_value=None) as mock_pm:
            pp.Process()
            mock_pm.assert_called_once()

    def test_regular_comicid_skips_manga_branch(self):
        """A non-md ComicID should NOT call _process_manga."""
        pp, mock_queue = _make_pp(
            nzb_name="Batman 001.cbz",
            nzb_folder="/tmp/downloads",
            comicid="12345",
            issueid="67890",
            apicall=True,
        )
        with patch.object(pp, "_process_manga") as mock_pm, \
             patch("comicarr.postprocessor.filechecker") as mock_fc, \
             patch("comicarr.postprocessor.db") as mock_db:
            mock_db.select_one.return_value = {"ComicID": "12345"}
            mock_fc.FileChecker.return_value.listFiles.return_value = {
                "comiccount": 0, "comiclist": []
            }
            try:
                pp.Process()
            except Exception:
                pass
            mock_pm.assert_not_called()

    def test_none_comicid_skips_manga_branch(self):
        """When comicid is None, manga branch should be skipped."""
        pp, mock_queue = _make_pp(
            nzb_name="Manual Run",
            nzb_folder="/tmp/downloads",
            comicid=None,
            apicall=True,
        )
        with patch.object(pp, "_process_manga") as mock_pm:
            try:
                pp.Process()
            except Exception:
                pass
            mock_pm.assert_not_called()


class TestProcessMangaSeriesLookup:
    """Tests for the comic/series lookup in _process_manga."""

    def test_comic_not_found_returns_stop(self, tmp_path):
        """When series is not in the database, should return stop."""
        pp, mock_queue = _make_pp(
            nzb_name="Bleach v1.cbz",
            nzb_folder=str(tmp_path),
            comicid="md-bleach",
        )

        with patch("comicarr.postprocessor.db") as mock_db:
            mock_db.select_one.return_value = None
            pp._process_manga()

        mock_queue.put.assert_called_once()
        result = mock_queue.put.call_args[0][0]
        assert result[0]["mode"] == "stop"
        assert "Cannot find manga series" in result[0]["self.log"]


class TestProcessMangaNoFiles:
    """Tests for when no manga files are in the download directory."""

    def test_no_files_returns_stop(self, tmp_path):
        """When no manga files exist in download dir, should return stop."""
        (tmp_path / "readme.txt").write_text("not a manga")

        pp, mock_queue = _make_pp(
            nzb_name="something",
            nzb_folder=str(tmp_path),
            comicid="md-bleach",
        )

        comic_row = {"ComicName": "Bleach", "ComicLocation": "/manga/Bleach"}

        with patch("comicarr.postprocessor.db") as mock_db:
            mock_db.select_one.return_value = comic_row
            pp._process_manga()

        mock_queue.put.assert_called_once()
        result = mock_queue.put.call_args[0][0]
        assert result[0]["mode"] == "stop"
        assert "No manga files" in result[0]["self.log"]


class TestProcessMangaNoDestination:
    """Tests for when manga destination is not configured."""

    def test_no_manga_destination_returns_stop(self, tmp_path):
        """When get_manga_destination() returns None, should return stop."""
        cbz = tmp_path / "Bleach v1.cbz"
        cbz.write_bytes(b"fake cbz")

        pp, mock_queue = _make_pp(
            nzb_name="Bleach v1.cbz",
            nzb_folder=str(tmp_path),
            comicid="md-bleach",
        )

        comic_row = {"ComicName": "Bleach", "ComicLocation": None}

        with patch("comicarr.postprocessor.db") as mock_db, \
             patch("comicarr.postprocessor.get_manga_destination", return_value=None):
            mock_db.select_one.return_value = comic_row
            pp._process_manga()

        mock_queue.put.assert_called_once()
        result = mock_queue.put.call_args[0][0]
        assert result[0]["mode"] == "stop"
        assert "No manga destination" in result[0]["self.log"]


class TestProcessMangaFileMove:
    """Tests for file moving in _process_manga."""

    def test_moves_files_to_series_folder(self, tmp_path):
        """Should move manga files to the series folder."""
        cbz = tmp_path / "Bleach v1.cbz"
        cbz.write_bytes(b"fake cbz")

        dest_dir = tmp_path / "manga" / "Bleach"
        dest_dir.mkdir(parents=True)

        pp, mock_queue = _make_pp(
            nzb_name="Bleach v1.cbz",
            nzb_folder=str(tmp_path),
            comicid="md-bleach",
        )

        comic_row = {"ComicName": "Bleach", "ComicLocation": str(dest_dir)}

        with patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")), \
             patch("comicarr.postprocessor.db") as mock_db:
            # First call: comic lookup. Remaining: chapter/issue lookups return None
            mock_db.select_one.side_effect = [comic_row, None, None, None]
            pp.fileop = MagicMock()

            pp._process_manga()

        # fileop should have been called to move the file
        pp.fileop.assert_called_once()
        args = pp.fileop.call_args[0]
        assert args[0] == str(cbz)
        assert "Bleach v1.cbz" in args[1]

    def test_move_failure_continues(self, tmp_path):
        """When file move fails, should log error and continue."""
        cbz = tmp_path / "Bleach v1.cbz"
        cbz.write_bytes(b"fake cbz")

        dest_dir = tmp_path / "manga" / "Bleach"
        dest_dir.mkdir(parents=True)

        pp, mock_queue = _make_pp(
            nzb_name="Bleach v1.cbz",
            nzb_folder=str(tmp_path),
            comicid="md-bleach",
        )

        comic_row = {"ComicName": "Bleach", "ComicLocation": str(dest_dir)}

        with patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")), \
             patch("comicarr.postprocessor.db") as mock_db:
            mock_db.select_one.return_value = comic_row
            pp.fileop = MagicMock(side_effect=OSError("Permission denied"))

            pp._process_manga()

        mock_queue.put.assert_called_once()
        result = mock_queue.put.call_args[0][0]
        assert "0 files matched" in result[0]["self.log"]


class TestProcessMangaChapterMatch:
    """Tests for chapter matching and DB updates."""

    def test_matches_chapter_and_updates_status(self, tmp_path):
        """Should match file to chapter via db.select_one and update status."""
        cbz = tmp_path / "Chainsaw Man 165.cbz"
        cbz.write_bytes(b"fake cbz")

        dest_dir = tmp_path / "manga" / "Chainsaw Man"
        dest_dir.mkdir(parents=True)

        pp, mock_queue = _make_pp(
            nzb_name="Chainsaw Man 165.cbz",
            nzb_folder=str(tmp_path),
            comicid="md-csm",
        )

        comic_row = {"ComicName": "Chainsaw Man", "ComicLocation": str(dest_dir)}
        issue_row = {"IssueID": "md-csm-ch165", "ChapterNumber": "165", "ComicID": "md-csm"}
        have_count = {"count_1": 5}

        mock_conn = MagicMock()

        with patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")), \
             patch("comicarr.postprocessor.db") as mock_db:
            # select_one calls: 1) comic lookup, 2) chapter match, 3) have count
            mock_db.select_one.side_effect = [comic_row, issue_row, have_count]
            mock_db.get_engine.return_value.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.get_engine.return_value.begin.return_value.__exit__ = MagicMock(return_value=False)
            pp.fileop = MagicMock()

            pp._process_manga()

        # Should have updated issue status
        mock_db.upsert.assert_any_call(
            "issues",
            {"Status": "Downloaded", "Location": "Chainsaw Man 165.cbz"},
            {"IssueID": "md-csm-ch165"},
        )

        result = mock_queue.put.call_args[0][0]
        assert "Post Processing SUCCESSFUL" in result[0]["self.log"]

    def test_unmatched_file_logs_warning(self, tmp_path):
        """When no chapter matches, should log warning but not crash."""
        cbz = tmp_path / "Chainsaw Man 999.cbz"
        cbz.write_bytes(b"fake cbz")

        dest_dir = tmp_path / "manga" / "Chainsaw Man"
        dest_dir.mkdir(parents=True)

        pp, mock_queue = _make_pp(
            nzb_name="Chainsaw Man 999.cbz",
            nzb_folder=str(tmp_path),
            comicid="md-csm",
        )

        comic_row = {"ComicName": "Chainsaw Man", "ComicLocation": str(dest_dir)}

        with patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")), \
             patch("comicarr.postprocessor.db") as mock_db:
            # comic lookup succeeds, all chapter/issue lookups return None
            mock_db.select_one.side_effect = [comic_row, None, None, None]
            pp.fileop = MagicMock()

            pp._process_manga()

        result = mock_queue.put.call_args[0][0]
        assert "0 files matched" in result[0]["self.log"]
