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

import os
import queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import comicarr
from comicarr.app.common.placement import OnExisting, PlacementError, Purpose
from tests.conftest import placement_result

# Ensure LOG_LEVEL is set for tests
if comicarr.LOG_LEVEL is None:
    comicarr.LOG_LEVEL = 0

from comicarr.postprocessor import (
    PostProcessor,
    log_scan_summary,
    numbered_by_volume,
    summarize_scan_matches,
    volume_identifies_file,
    volume_match_settles_year,
)


def test_scan_summary_emits_one_bounded_line_without_candidate_chatter():
    selected = [{"ComicID": "42", "ComicName": "Saga"}]
    with patch("comicarr.postprocessor.logger.fdebug") as fdebug:
        log_scan_summary("[PP] ", "Saga 1.cbz", 3, selected, 1, True)

    fdebug.assert_called_once()
    message = fdebug.call_args.args[0]
    assert "candidates=3" in message
    assert "selected=42/Saga" in message
    assert "annual_or_special=1" in message
    assert "story_arc=True" in message
    assert "Now checking" not in message


def test_scan_summary_reports_a_selected_story_arc_after_matching():
    normal = [{"ComicID": "42", "ComicName": "Saga"}]
    arc = [{"ComicID": "42", "ComicName": "Saga: Compendium One", "IssueArcID": "S7"}]

    selected, annual_count, story_arc = summarize_scan_matches(normal, arc)

    assert selected == normal + arc
    assert annual_count == 0
    assert story_arc is True


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
        with (
            patch.object(pp, "_process_manga", return_value=None) as mock_pm,
            patch("comicarr.postprocessor.db") as mock_db,
        ):
            mock_db.select_one.return_value = {"ComicID": "md-abc123", "ContentType": "manga"}
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

    def test_comicvine_manga_row_triggers_manga_branch(self):
        pp, _mock_queue = _make_pp(
            nzb_name="Solo Leveling v01.cbz",
            nzb_folder="/tmp/downloads",
            comicid="134064",
            apicall=True,
        )
        with (
            patch.object(pp, "_process_manga", return_value=None) as mock_pm,
            patch("comicarr.postprocessor.db") as mock_db,
        ):
            mock_db.select_one.return_value = {"ComicID": "134064", "ContentType": "manga"}
            pp.Process()

        mock_pm.assert_called_once()

    def test_explicit_comic_kind_overrides_mangadex_prefix(self):
        pp, _mock_queue = _make_pp(
            nzb_name="Example 001.cbz",
            nzb_folder="/tmp/downloads",
            comicid="md-example",
            issueid="issue-1",
            apicall=True,
        )
        with (
            patch.object(pp, "_process_manga") as mock_pm,
            patch("comicarr.postprocessor.filechecker") as mock_fc,
            patch("comicarr.postprocessor.db") as mock_db,
        ):
            mock_db.select_one.return_value = {"ComicID": "md-example", "ContentType": "comic"}
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


class TestProcessMangaHealsMisplacedLocation:
    """An already-manga series whose ComicLocation still sits under the comics
    dest used to be refused forever. Heal the path on this import and continue.
    """

    def test_repoints_comics_location_then_places(self, tmp_path):
        cbz = tmp_path / "Berserk v1.cbz"
        cbz.write_bytes(b"fake cbz")
        comics_dir = tmp_path / "comics" / "Berserk (2003)"
        comics_dir.mkdir(parents=True)
        manga_dest = tmp_path / "manga"

        pp, mock_queue = _make_pp(
            nzb_name="Berserk v1.cbz",
            nzb_folder=str(tmp_path),
            comicid="160294",
        )

        comic_row = {
            "ComicID": "160294",
            "ComicName": "Berserk",
            "ComicLocation": str(comics_dir),
            "ContentType": "manga",
        }

        with (
            patch("comicarr.postprocessor.get_manga_destination", return_value=str(manga_dest)),
            patch("comicarr.postprocessor.db") as mock_db,
            patch("comicarr.app.series.queries.update_comic_content_kind") as update,
        ):
            mock_db.select_one.side_effect = [comic_row, None, None, None]
            with patch("comicarr.postprocessor.place", return_value=placement_result()) as placer:
                pp._process_manga()

        expected = os.path.join(str(manga_dest), "Berserk")
        update.assert_called_once_with("160294", "manga", comic_location=expected)
        placer.assert_called_once()
        assert expected in placer.call_args[0][1]
        result = mock_queue.put.call_args[0][0]
        assert "outside manga destination" not in result[0]["self.log"]

    def test_still_refuses_when_name_cannot_build_a_folder(self, tmp_path):
        cbz = tmp_path / "chapter.cbz"
        cbz.write_bytes(b"fake cbz")
        comics_dir = tmp_path / "comics" / "unknown"
        comics_dir.mkdir(parents=True)
        manga_dest = tmp_path / "manga"

        pp, mock_queue = _make_pp(
            nzb_name="chapter.cbz",
            nzb_folder=str(tmp_path),
            comicid="160294",
        )

        comic_row = {
            "ComicID": "160294",
            "ComicName": "???",
            "ComicLocation": str(comics_dir),
            "ContentType": "manga",
        }

        with (
            patch("comicarr.postprocessor.get_manga_destination", return_value=str(manga_dest)),
            patch("comicarr.postprocessor.db") as mock_db,
            patch("comicarr.app.series.queries.update_comic_content_kind") as update,
        ):
            mock_db.select_one.return_value = comic_row
            pp._process_manga()

        update.assert_not_called()
        mock_queue.put.assert_called_once()
        result = mock_queue.put.call_args[0][0]
        assert result[0]["mode"] == "stop"
        assert "outside manga destination" in result[0]["self.log"]


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
        # `place` is mocked here, so nothing else in this test reads CONFIG --
        # the post-import folder tidy does, and it runs on the success path.
        config = MagicMock()
        config.FILE_OPTS = "move"
        config.ENABLE_META = False

        with (
            patch.object(comicarr, "CONFIG", config),
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


class TestMangaTidiesTheEmptiedDownloadFolder:
    """A `move` import consumes the file and must not leave the folder behind.

    The comic path calls `tidyup(del_nzbdir=True)`, which removes the download
    directory once `move` has emptied it. `_process_manga` never called it, so
    every completed manga release left a permanently empty directory in the
    downloader's completed dir. Nothing sweeps them: the folder monitor only
    looks for files, and the journal row is already terminal, so the count only
    ever grows.

    The guards match the comic path exactly, and each has a test below,
    because a cleanup that fires when any one of them should have stopped it
    deletes a download the operator still needs:

      * only under FILE_OPTS `move` -- copy/hardlink/softlink deliberately
        leave the source, so the folder is legitimately non-empty;
      * never for a `Manual Run`, whose folder is an operator-chosen directory
        that may hold anything, not a per-release download folder;
      * only when the folder is EMPTY -- a leftover file means something was
        not imported, and that is exactly the evidence needed to find out why;
      * only when at least one file matched, so a release that imported
        nothing keeps its source for a retry.
    """

    def _run(self, tmp_path, file_opts="move", nzb_name="Chainsaw Man 165.cbz", extra_file=None, matched=True):
        release_dir = tmp_path / "completed" / "Chainsaw.Man.165"
        release_dir.mkdir(parents=True)
        (release_dir / "Chainsaw Man 165.cbz").write_bytes(b"fake cbz")
        if extra_file is not None:
            (release_dir / extra_file).write_bytes(b"leftover")

        dest_dir = tmp_path / "manga" / "Chainsaw Man"
        dest_dir.mkdir(parents=True)

        pp, mock_queue = _make_pp(nzb_name=nzb_name, nzb_folder=str(release_dir), comicid="md-csm")

        config = MagicMock()
        config.FILE_OPTS = file_opts
        config.ARC_FILEOPS = file_opts
        config.ARC_FILEOPS_SOFTLINK_RELATIVE = False
        config.IGNORE_SEARCH_WORDS = []

        comic_row = {"ComicName": "Chainsaw Man", "ComicLocation": str(dest_dir)}
        issue_row = {"IssueID": "md-csm-ch165", "ChapterNumber": "165", "ComicID": "md-csm"}
        have_count = {"count_1": 5}
        mock_conn = MagicMock()

        if matched:
            lookups = [comic_row, issue_row, have_count]
        else:
            lookups = [comic_row, None, None, None]

        config.ENABLE_META = False

        with (
            patch.object(comicarr, "CONFIG", config),
            patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")),
            patch("comicarr.app.downloads.journal.record_transition", return_value=True),
            patch("comicarr.postprocessor.db") as mock_db,
        ):
            mock_db.select_one.side_effect = lookups
            mock_db.get_engine.return_value.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.get_engine.return_value.begin.return_value.__exit__ = MagicMock(return_value=False)

            pp._process_manga()

        return release_dir, dest_dir / "Chainsaw Man 165.cbz", mock_queue

    def test_move_removes_the_emptied_release_folder(self, tmp_path):
        release_dir, placed, _ = self._run(tmp_path)

        assert placed.exists(), "the volume must still reach the library"
        assert not release_dir.exists(), "the emptied download folder must not be left behind"

    @pytest.mark.parametrize("file_opts", ("copy", "hardlink", "softlink"))
    def test_a_non_move_mode_keeps_the_folder(self, tmp_path, file_opts):
        release_dir, placed, _ = self._run(tmp_path, file_opts=file_opts)

        assert placed.exists()
        assert release_dir.exists(), "%s keeps the source, so its folder is not ours to delete" % file_opts

    def test_a_manual_run_keeps_the_folder(self, tmp_path):
        release_dir, placed, _ = self._run(tmp_path, nzb_name="Manual Run")

        assert placed.exists()
        assert release_dir.exists(), "a Manual Run folder is operator-chosen, not a per-release download folder"

    def test_a_folder_still_holding_a_file_is_kept(self, tmp_path):
        release_dir, placed, _ = self._run(tmp_path, extra_file="Chainsaw Man 165.nfo")

        assert placed.exists()
        assert release_dir.exists(), "a non-empty folder is evidence something did not import"
        assert (release_dir / "Chainsaw Man 165.nfo").exists()

    def test_a_release_that_matched_nothing_keeps_its_folder(self, tmp_path):
        release_dir, _placed, mock_queue = self._run(tmp_path, matched=False)

        assert release_dir.exists(), "nothing was filed, so the source must survive for a retry"
        result = mock_queue.put.call_args[0][0]
        assert "0 files matched" in result[0]["self.log"]


class TestVolumeIdentifiesFile:
    """Which series number their scanned files by volume rather than issue.

    A manga volume file carries no issue number, so without a volume arm the
    folder scan derives no number, compares the file against every issue in
    the series and selects none of them.
    """

    def test_manga_series_is_identified_by_volume(self):
        assert volume_identifies_file({"Type": "Digital", "Total": 33, "IsManga": True}) is True

    def test_manga_arm_does_not_depend_on_the_series_length(self):
        """A single-volume manga is still numbered by volume."""
        assert volume_identifies_file({"Type": "Digital", "Total": 1, "IsManga": True}) is True

    def test_comic_series_of_the_same_type_is_still_identified_by_issue(self):
        assert volume_identifies_file({"Type": "Digital", "Total": 33, "IsManga": False}) is False

    @pytest.mark.parametrize("series_type", ["TPB", "HC", "GN"])
    def test_collected_editions_keep_their_volume_numbering(self, series_type):
        assert volume_identifies_file({"Type": series_type, "Total": 5, "IsManga": False}) is True
        assert volume_identifies_file({"Type": series_type, "Total": 1, "IsManga": False}) is False

    def test_one_shots_keep_their_volume_numbering(self):
        assert volume_identifies_file({"Type": "One-Shot", "Total": 1, "IsManga": False}) is True
        assert volume_identifies_file({"Type": "One-Shot", "Total": 2, "IsManga": False}) is False

    def test_a_row_without_the_manga_flag_is_read_as_a_comic(self):
        """One-off rows build WatchValues without IsManga and must not raise."""
        assert volume_identifies_file({"Type": "Digital", "Total": 0}) is False


class TestNumberedByVolume:
    """Which series are exempt from the checks that assume an issue number.

    The weekly-pull cross-check, the "no issue number" rejection and the
    default-to-1 fallback all skip series whose files are named by volume.
    Manga must be exempt for the same reason collected editions are.
    """

    def test_manga_series_is_exempt(self):
        assert numbered_by_volume({"Type": "Digital", "Total": 33, "IsManga": True}) is True

    def test_comic_series_of_the_same_type_is_not_exempt(self):
        assert numbered_by_volume({"Type": "Digital", "Total": 33, "IsManga": False}) is False

    @pytest.mark.parametrize("series_type", ["TPB", "HC", "GN", "One-Shot"])
    def test_collected_editions_stay_exempt_regardless_of_run_length(self, series_type):
        """Exemption is a property of the type alone, unlike locating a file."""
        assert numbered_by_volume({"Type": series_type, "Total": 1, "IsManga": False}) is True
        assert numbered_by_volume({"Type": series_type, "Total": 9, "IsManga": False}) is True

    def test_a_single_entry_tpb_is_exempt_but_is_not_located_by_volume(self):
        """The two predicates deliberately disagree here; that split is the point."""
        watch_values = {"Type": "TPB", "Total": 1, "IsManga": False}
        assert numbered_by_volume(watch_values) is True
        assert volume_identifies_file(watch_values) is False

    def test_a_row_without_the_manga_flag_is_read_as_a_comic(self):
        assert numbered_by_volume({"Type": "Digital", "Total": 0}) is False


class TestVolumeMatchSettlesYear:
    """A matched manga volume makes the filename's year irrelevant.

    Providers date the licensed English printing while releases carry the
    volume's original year, so the two routinely disagree by a year.
    """

    def test_matched_manga_volume_overrides_a_year_mismatch(self):
        assert volume_match_settles_year({"IsManga": True}, True) is True

    def test_an_unmatched_volume_never_overrides_the_year(self):
        """Without a volume match there is no identity to trust instead."""
        assert volume_match_settles_year({"IsManga": True}, False) is False

    def test_a_comic_year_mismatch_still_decides(self):
        assert volume_match_settles_year({"IsManga": False}, True) is False

    def test_collected_editions_are_not_covered(self):
        """A TPB year mismatch can still mean the wrong edition."""
        assert volume_match_settles_year({"Type": "TPB", "Total": 5}, True) is False


class TestMangaVolumeForIssue:
    """A licensed manga's catalogued "issues" are its English volumes.

    The tag must name the volume the file is, and carry no issue number, or a
    reader groups every volume as a chapter of one volume named for the series.
    """

    @staticmethod
    def _resolve(issue_row, comic_row, issueid="446055"):
        from comicarr import cmtag

        rows = [issue_row, comic_row]
        with patch("comicarr.db.select_one", side_effect=lambda *a, **k: rows.pop(0)):
            return cmtag.manga_volume_for_issue(issueid)

    def test_a_manga_issue_resolves_to_its_volume_number(self):
        assert self._resolve({"ComicID": "71856", "VolumeNumber": "7"}, {"ContentType": "manga"}) == "7"

    def test_the_number_is_canonicalised_by_the_ledger(self):
        """Reuses normalize_volume_number rather than restating the format."""
        assert self._resolve({"ComicID": "71856", "VolumeNumber": 7.0}, {"ContentType": "manga"}) == "7"

    def test_a_comic_series_keeps_the_periodical_shape(self):
        assert self._resolve({"ComicID": "17993", "VolumeNumber": "2"}, {"ContentType": "comic"}) is None

    def test_a_ledger_without_volume_numbers_falls_back(self):
        """MangaDex-backed rows carry chapters only; tagging must still run."""
        assert self._resolve({"ComicID": "71856", "VolumeNumber": None}, {"ContentType": "manga"}) is None

    def test_a_missing_issue_row_falls_back(self):
        assert self._resolve(None, None) is None

    def test_no_issueid_never_queries(self):
        from comicarr import cmtag

        with patch("comicarr.db.select_one", side_effect=AssertionError("must not query")):
            assert cmtag.manga_volume_for_issue(None) is None

    def test_a_lookup_failure_never_breaks_tagging(self):
        """Best-effort enrichment: a DB error tags as a periodical, not 'fail'."""
        from comicarr import cmtag

        with patch("comicarr.db.select_one", side_effect=RuntimeError("boom")):
            assert cmtag.manga_volume_for_issue("446055") is None


class TestRestoreTaggedFileMode:
    """Tagging is a round trip and must not change how readable a file is.

    ComicTagger cannot write into an existing archive, so it builds a NEW file
    with tempfile semantics (0600) instead of inheriting the library file's
    mode. Left alone, a tagged issue ends up less readable than every untagged
    issue beside it, and nothing logs it -- invisible while the reader runs as
    root, and a silent breakage the moment it does not.
    """

    @staticmethod
    def _cfg(enforce=False):
        return SimpleNamespace(ENFORCE_PERMS=enforce)

    def test_a_mode_tagging_reduced_is_restored(self, tmp_path):
        from comicarr import cmtag

        f = tmp_path / "One-Punch Man v01.cbz"
        f.write_bytes(b"x")
        os.chmod(f, 0o600)
        with patch.object(comicarr, "CONFIG", self._cfg()):
            assert cmtag.restore_tagged_file_mode(str(f), 0o644) is True
        assert os.stat(f).st_mode & 0o7777 == 0o644

    def test_an_unchanged_mode_is_left_alone(self, tmp_path):
        from comicarr import cmtag

        f = tmp_path / "a.cbz"
        f.write_bytes(b"x")
        os.chmod(f, 0o644)
        with patch.object(comicarr, "CONFIG", self._cfg()):
            assert cmtag.restore_tagged_file_mode(str(f), 0o644) is False
        assert os.stat(f).st_mode & 0o7777 == 0o644

    def test_enforce_perms_defers_to_the_existing_owner(self, tmp_path):
        """CHMOD_FILE has an owner already; this must not become a second one."""
        from comicarr import cmtag

        f = tmp_path / "a.cbz"
        f.write_bytes(b"x")
        with patch.object(comicarr, "CONFIG", self._cfg(enforce=True)):
            with patch.object(cmtag.filechecker, "setperms") as setperms:
                assert cmtag.restore_tagged_file_mode(str(f), 0o644) is True
        setperms.assert_called_once_with(str(f))

    def test_an_uncapturable_original_mode_changes_nothing(self, tmp_path):
        """A stat failure before tagging must not invent a mode."""
        from comicarr import cmtag

        f = tmp_path / "a.cbz"
        f.write_bytes(b"x")
        os.chmod(f, 0o600)
        with patch.object(comicarr, "CONFIG", self._cfg()):
            assert cmtag.restore_tagged_file_mode(str(f), None) is False
        assert os.stat(f).st_mode & 0o7777 == 0o600

    def test_a_chmod_failure_never_breaks_tagging(self, tmp_path):
        """Best-effort: a tagged file is still worth returning."""
        from comicarr import cmtag

        f = tmp_path / "a.cbz"
        f.write_bytes(b"x")
        os.chmod(f, 0o600)
        with patch.object(comicarr, "CONFIG", self._cfg()):
            with patch("os.chmod", side_effect=OSError("read-only fs")):
                assert cmtag.restore_tagged_file_mode(str(f), 0o644) is False

    def test_current_file_mode_reads_the_bits(self, tmp_path):
        from comicarr import cmtag

        f = tmp_path / "a.cbz"
        f.write_bytes(b"x")
        os.chmod(f, 0o640)
        assert cmtag.current_file_mode(str(f)) == 0o640

    def test_current_file_mode_of_a_missing_path_is_none(self, tmp_path):
        """The .cbr is deleted by the .cbz conversion under FILE_OPTS = move."""
        from comicarr import cmtag

        assert cmtag.current_file_mode(str(tmp_path / "gone.cbr")) is None


class TestRestoreTaggedFileModeWiring:
    """The helper is only useful if run() captures early and applies late."""

    @staticmethod
    def _run_source():
        import inspect

        from comicarr import cmtag

        return inspect.getsource(cmtag.run)

    def test_run_captures_the_mode_before_tagging(self):
        src = self._run_source()
        assert "og_file_mode = current_file_mode(og_filepath)" in src, (
            "run() no longer captures the pre-tag mode; it must be read before "
            "the .cbr -> .cbz conversion deletes the original"
        )

    def test_run_restores_the_mode_on_the_success_path(self):
        src = self._run_source()
        assert "restore_tagged_file_mode(filepath, og_file_mode, module)" in src, (
            "run() no longer restores the file mode before returning the tagged path"
        )

    def test_the_capture_precedes_the_restore(self):
        src = self._run_source()
        assert src.index("og_file_mode = current_file_mode(") < src.index(
            "restore_tagged_file_mode("
        ), "the mode must be captured before it can be restored"


class TestMangaTagShapeWiring:
    """The resolver is only useful if run() actually consults it."""

    @staticmethod
    def _run_source():
        import inspect

        from comicarr import cmtag

        return inspect.getsource(cmtag.run)

    def test_run_resolves_a_manga_volume(self):
        assert "manga_volume_for_issue(issueid)" in self._run_source(), (
            "the meta-tagger no longer resolves a manga volume; manga would be "
            "tagged with the series volume label and an issue number again"
        )

    def test_a_manga_volume_clears_the_issue_number_after_tagging(self):
        """-m cannot do it: the online overlay runs after -m and puts it back."""
        source = self._run_source()
        assert "clear_issue_number(comictagger_cmd, filepath, module)" in source, (
            "manga volumes would keep the issue number ComicVine catalogues them "
            "under, and a reader would file every volume as a chapter"
        )

    def test_the_clear_runs_before_the_file_leaves_the_cache(self):
        """Both passes must land while the file is still the tagging copy."""
        source = self._run_source()
        assert source.index("clear_issue_number(") < source.index("restore_tagged_file_mode("), (
            "the issue number would be cleared after the mode was restored, "
            "reducing a library file's permissions again"
        )

    def test_the_tag_options_no_longer_carry_a_doomed_issue_clear(self):
        """One owner for the clear -- a second, silently-ignored one is a lie."""
        tline = self._run_source().split("tline = ")[1].splitlines()[0]
        assert "iline" not in tline


class TestClearIssueNumber:
    """The clear only works as a SECOND, offline pass.

    ComicTagger applies -m before the ComicVine overlay, so an issue= sent with
    the tagging run is overwritten by the number ComicVine supplies. Re-applying
    it with no -o is what actually removes <Number>.
    """

    @staticmethod
    def _cfg(cr=True, cbl=False):
        return SimpleNamespace(CT_TAG_CR=cr, CT_TAG_CBL=cbl, CT_SETTINGSPATH="/config/ct")

    @staticmethod
    def _popen(out="Save complete\n"):
        proc = MagicMock()
        proc.communicate.return_value = (out, "")
        return MagicMock(return_value=proc)

    def _run(self, cfg, popen):
        from comicarr import cmtag

        with patch.object(comicarr, "CONFIG", cfg):
            with patch.object(cmtag.subprocess, "Popen", popen):
                return cmtag.clear_issue_number("/app/comictagger.py", "/cache/OPM v07.cbz")

    def test_the_clear_pass_never_goes_online(self):
        """A second -o would refetch the very number being removed."""
        popen = self._popen()
        assert self._run(self._cfg(), popen) is True
        cmd = popen.call_args[0][0]
        assert "-o" not in cmd, "the online overlay would rewrite the issue number"
        assert "--id" not in cmd

    def test_the_clear_pass_saves_an_empty_issue_for_the_written_style(self):
        popen = self._popen()
        self._run(self._cfg(), popen)
        cmd = popen.call_args[0][0]
        assert "-s" in cmd
        assert cmd[cmd.index("--type") + 1] == "cr"
        assert cmd[cmd.index("-m") + 1] == "issue="
        assert cmd[-1] == "/cache/OPM v07.cbz"

    def test_every_written_tag_style_is_cleared(self):
        """A style left untouched keeps the number in its own tag block."""
        popen = self._popen()
        assert self._run(self._cfg(cr=True, cbl=True), popen) is True
        assert [c[0][0][c[0][0].index("--type") + 1] for c in popen.call_args_list] == ["cr", "cbl"]

    def test_nothing_runs_when_no_tag_style_is_written(self):
        popen = self._popen()
        assert self._run(self._cfg(cr=False, cbl=False), popen) is False
        popen.assert_not_called()

    def test_a_refused_save_is_reported_not_raised(self):
        """Best-effort: an extra number beats losing the tags entirely."""
        popen = self._popen(out="Sorry, but this is not a comic archive!\n")
        assert self._run(self._cfg(), popen) is False

    def test_a_subprocess_failure_never_breaks_tagging(self):
        from comicarr import cmtag

        with patch.object(comicarr, "CONFIG", self._cfg()):
            with patch.object(cmtag.subprocess, "Popen", side_effect=OSError("no interpreter")):
                assert cmtag.clear_issue_number("/app/comictagger.py", "/cache/a.cbz") is False
