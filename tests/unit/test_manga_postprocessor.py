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

import pytest

import comicarr
from comicarr.app.common.placement import OnExisting, PlacementError, Purpose
from tests.conftest import placement_result

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

    with patch.object(comicarr, "APILOCK", mock_apilock), patch.object(comicarr, "CONFIG", mock_config):
        pp = PostProcessor(
            nzb_name=nzb_name,
            nzb_folder=nzb_folder,
            comicid=comicid,
            issueid=issueid,
            queue=mock_queue,
            apicall=apicall,
        )
    return pp, mock_queue


class TestMangaPlacementHonoursFileOpts:
    """The manga path used shutil.move for every mode except copy, so hardlink
    and softlink -- both of which are supposed to leave the download in place --
    destroyed the user's source file."""

    def _run(self, tmp_path, file_opts):
        cbz = tmp_path / "Chainsaw Man 165.cbz"
        cbz.write_bytes(b"fake cbz")
        dest_dir = tmp_path / "manga" / "Chainsaw Man"
        dest_dir.mkdir(parents=True)

        pp, _ = _make_pp(
            nzb_name="Chainsaw Man 165.cbz",
            nzb_folder=str(tmp_path),
            comicid="md-csm",
        )

        config = MagicMock()
        config.FILE_OPTS = file_opts
        config.ARC_FILEOPS = file_opts
        config.ARC_FILEOPS_SOFTLINK_RELATIVE = False
        config.IGNORE_SEARCH_WORDS = []

        comic_row = {"ComicName": "Chainsaw Man", "ComicLocation": str(dest_dir)}
        with (
            patch.object(comicarr, "CONFIG", config),
            patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")),
            patch("comicarr.postprocessor.db") as mock_db,
        ):
            mock_db.select_one.side_effect = [comic_row, None, None, None]
            pp._process_manga()

        return cbz, dest_dir / "Chainsaw Man 165.cbz"

    @pytest.mark.parametrize("file_opts", ("hardlink", "softlink", "copy"))
    def test_non_move_modes_leave_the_source_in_place(self, tmp_path, file_opts):
        source, placed = self._run(tmp_path, file_opts)

        assert source.exists(), "%s must not consume the downloaded file" % file_opts
        assert placed.exists()

    def test_move_mode_still_consumes_the_source(self, tmp_path):
        source, placed = self._run(tmp_path, "move")

        assert not source.exists()
        assert placed.exists()


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
        with (
            patch.object(pp, "_process_manga") as mock_pm,
            patch("comicarr.postprocessor.filechecker") as mock_fc,
            patch("comicarr.postprocessor.db") as mock_db,
        ):
            mock_db.select_one.return_value = {"ComicID": "12345"}
            mock_fc.FileChecker.return_value.listFiles.return_value = {"comiccount": 0, "comiclist": []}
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

        with (
            patch("comicarr.postprocessor.db") as mock_db,
            patch("comicarr.postprocessor.get_manga_destination", return_value=None),
        ):
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

        with (
            patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")),
            patch("comicarr.postprocessor.db") as mock_db,
        ):
            # First call: comic lookup. Remaining: chapter/issue lookups return None
            mock_db.select_one.side_effect = [comic_row, None, None, None]
            with patch("comicarr.postprocessor.place", return_value=placement_result()) as placer:
                pp._process_manga()

        # the placement stage should have been called for the file
        placer.assert_called_once()
        args = placer.call_args[0]
        assert args[0] == str(cbz)
        assert "Bleach v1.cbz" in args[1]
        assert args[2] is Purpose.SERIES
        assert placer.call_args[1]["on_existing"] is OnExisting.DISPLACE

    # The stage always raises on failure -- there is no falsy return to bridge
    # any more, which is the whole point of PlacementError. The `returns_false`
    # half of this parametrization is therefore gone: it pinned a shape the
    # interface no longer has. What it actually guarded -- a failed placement
    # never advancing the chapter -- is unchanged and still pinned below.
    @pytest.mark.parametrize(
        "placement_kwargs",
        ({"side_effect": PlacementError("Permission denied")},),
        ids=("raises",),
    )
    def test_move_failure_continues(self, tmp_path, placement_kwargs):
        """When placement fails, should log error and continue."""
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

        with (
            patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")),
            patch("comicarr.postprocessor.db") as mock_db,
        ):
            mock_db.select_one.return_value = comic_row
            with patch("comicarr.postprocessor.place", **placement_kwargs):
                pp._process_manga()

        mock_queue.put.assert_called_once()
        result = mock_queue.put.call_args[0][0]
        assert "0 files matched" in result[0]["self.log"]

    def test_failed_placement_never_marks_the_chapter_downloaded(self, tmp_path):
        """A raised PlacementError means the file was NOT placed. If the loop
        carried on it would upsert Status=Downloaded and terminalize the journal
        for a file still sitting in the download folder, which recovery would
        then never re-drive. This used to be pinned against a falsy return; the
        stage raises instead now, and the guarantee is identical."""
        cbz = tmp_path / "Bleach v1.cbz"
        cbz.write_bytes(b"fake cbz")

        dest_dir = tmp_path / "manga" / "Bleach"
        dest_dir.mkdir(parents=True)

        pp, _ = _make_pp(
            nzb_name="Bleach v1.cbz",
            nzb_folder=str(tmp_path),
            comicid="md-bleach",
        )

        comic_row = {"ComicName": "Bleach", "ComicLocation": str(dest_dir)}
        issue_row = {"IssueID": "md-bleach-v1", "Issue_Number": "1"}

        with (
            patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")),
            patch("comicarr.postprocessor.db") as mock_db,
        ):
            # a chapter match IS available -- only the falsy placement stops it
            mock_db.select_one.side_effect = [comic_row, issue_row, None, None]
            with patch("comicarr.postprocessor.place", side_effect=PlacementError("no space")):
                pp._process_manga()

        assert mock_db.upsert.call_count == 0, "an unplaced chapter must not be marked Downloaded"


class TestProcessMangaExistingDestination:
    """os.link and os.symlink refuse an existing destination with EEXIST, so an
    already-placed chapter would be skipped on every pass. The DISPLACE policy
    recognises or clears the destination first."""

    # The download folder and the manga destination are separate trees here: a
    # destination nested inside the download folder would be picked up by the
    # loop's own file walk as a second manga file.
    def _run(self, tmp_path, file_opts, seed_dest=None, source_bytes=b"fresh grab", placement=None):
        download_dir = tmp_path / "download"
        download_dir.mkdir(exist_ok=True)
        cbz = download_dir / "Chainsaw Man 165.cbz"
        if not cbz.exists():
            cbz.write_bytes(source_bytes)

        dest_dir = tmp_path / "manga" / "Chainsaw Man"
        dest_dir.mkdir(parents=True, exist_ok=True)
        placed = dest_dir / "Chainsaw Man 165.cbz"
        if seed_dest is not None:
            placed.write_bytes(seed_dest)

        pp, _ = _make_pp(
            nzb_name="Chainsaw Man 165.cbz",
            nzb_folder=str(download_dir),
            comicid="md-csm",
        )

        config = MagicMock()
        config.FILE_OPTS = file_opts
        config.ARC_FILEOPS = file_opts
        config.ARC_FILEOPS_SOFTLINK_RELATIVE = False
        config.IGNORE_SEARCH_WORDS = []

        comic_row = {"ComicName": "Chainsaw Man", "ComicLocation": str(dest_dir)}
        with (
            patch.object(comicarr, "CONFIG", config),
            patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")),
            patch("comicarr.postprocessor.db") as mock_db,
        ):
            mock_db.select_one.side_effect = [comic_row, None, None, None]
            if placement is None:
                pp._process_manga()
            else:
                with patch("comicarr.postprocessor.place", **placement):
                    pp._process_manga()

        return cbz, placed, pp

    @pytest.mark.parametrize(
        "placement",
        ({"side_effect": PlacementError("No space left on device")},),
        ids=("raises",),
    )
    def test_failed_replacement_restores_the_previous_chapter(self, tmp_path, placement):
        """The chapter already in the library is moved aside, not deleted, so a
        placement that fails mid-replacement leaves the library intact. Deleting
        first would strand the DB reporting Status=Downloaded for a chapter that
        is physically gone."""
        source, placed, pp = self._run(tmp_path, "copy", seed_dest=b"stale copy", placement=placement)

        assert placed.exists(), "a failed replacement must not destroy the chapter already in the library"
        assert placed.read_bytes() == b"stale copy"
        assert source.exists(), "the download must survive a failed placement"
        assert "Failed to move/copy manga file" in pp.log

    def test_successful_replacement_leaves_no_displaced_file_behind(self, tmp_path):
        """The moved-aside copy is cleaned up once placement succeeds, so it is
        never picked up by a later library scan."""
        _source, placed, _pp = self._run(tmp_path, "copy", seed_dest=b"stale copy")

        assert placed.read_bytes() == b"fresh grab"
        leftovers = sorted(p.name for p in placed.parent.iterdir())
        assert leftovers == ["Chainsaw Man 165.cbz"], leftovers

    @pytest.mark.parametrize("file_opts", ("hardlink", "softlink", "copy", "move"))
    def test_stale_destination_is_replaced(self, tmp_path, file_opts):
        """A repack of a chapter already in the library replaces it, as it did
        before placement moved to the shared stage. Under hardlink/softlink the bare
        os.link/os.symlink would have raised EEXIST and skipped the chapter."""
        source, placed, pp = self._run(tmp_path, file_opts, seed_dest=b"stale copy")

        assert placed.exists()
        assert placed.read_bytes() == b"fresh grab", "%s must overwrite the stale library file" % file_opts
        assert "Failed to move/copy manga file" not in pp.log
        if file_opts != "move":
            # replacing an existing chapter must not cost the download: under
            # softlink the download path is a symlink into the library, so this
            # also pins that it resolves to the file that actually landed.
            assert source.exists(), "%s must not consume the download when replacing" % file_opts

    def test_hardlink_rerun_is_idempotent(self, tmp_path):
        """The recovery finalizer re-drives a manga release in FULL. Under
        hardlink the source survives the first pass, so the second pass must
        recognise the already-linked chapter instead of failing on EEXIST."""
        source, placed, _ = self._run(tmp_path, "hardlink")
        assert source.exists() and placed.exists()
        assert source.stat().st_ino == placed.stat().st_ino

        # second pass over the same download folder, destination already linked
        source_again, placed_again, pp_again = self._run(tmp_path, "hardlink")

        # the re-drive must treat the already-linked chapter as placed, not as a
        # failed placement -- a `continue` here would leave it unmatched forever
        assert "Failed to move/copy manga file" not in pp_again.log
        assert source_again.exists(), "the re-drive must not consume the download"
        assert placed_again.exists(), "the re-drive must not lose the library file"
        assert source_again.stat().st_ino == placed_again.stat().st_ino
        assert placed_again.read_bytes() == b"fresh grab"


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

        # U9: the per-match nzblog-delete begin() block now CO-COMMITS the
        # journal `post_processed` transition (conn-mode). `db` is fully mocked
        # in this test (so the real journal write cannot run), and conn-mode
        # _journal_pp correctly RE-RAISES on failure — so stub the façade write
        # to a benign no-op here. This test pins the issues-upsert + success
        # log, not the journal seam (covered by test_pp_complete_ordering.py /
        # test_journal_pp_seam.py).
        with (
            patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")),
            patch("comicarr.app.downloads.journal.record_transition", return_value=True),
            patch("comicarr.postprocessor.place", return_value=placement_result()),
            patch("comicarr.postprocessor.db") as mock_db,
        ):
            # select_one calls: 1) comic lookup, 2) chapter match, 3) have count
            mock_db.select_one.side_effect = [comic_row, issue_row, have_count]
            mock_db.get_engine.return_value.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.get_engine.return_value.begin.return_value.__exit__ = MagicMock(return_value=False)

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

        with (
            patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")),
            patch("comicarr.postprocessor.place", return_value=placement_result()),
            patch("comicarr.postprocessor.db") as mock_db,
        ):
            # comic lookup succeeds, all chapter/issue lookups return None
            mock_db.select_one.side_effect = [comic_row, None, None, None]

            pp._process_manga()

        result = mock_queue.put.call_args[0][0]
        assert "0 files matched" in result[0]["self.log"]
