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
Unit tests for comicarr/cmtag.py helpers.
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from comicarr import cmtag


class TestExportedFilename:
    def test_returns_basename_from_export_line(self):
        out = "ComicTagger: Archive exported successfully to: My Comic 001.cbz\n"
        assert cmtag.exported_filename(out) == "My Comic 001.cbz"

    def test_ignores_warning_lines_from_merged_stderr(self):
        # The metatagger merges stderr into stdout, so an interpreter warning
        # (e.g. SyntaxWarning on a .pyc-less install) lands in the same text.
        out = (
            "/opt/comicarr/comicarr/_vendor/comictaggerlib/settings.py:158:"
            " SyntaxWarning: invalid escape sequence '\\P'\n"
            '  if os.path.exists("C:\\Program Files\\WinRAR\\Rar.exe"):\n'
            "ComicTagger: Archive exported successfully to: My Comic 001.cbz\n"
        )
        assert cmtag.exported_filename(out) == "My Comic 001.cbz"

    def test_ignores_lines_after_the_export_line(self):
        out = "ComicTagger: Archive exported successfully to: My Comic 001.cbz\nsome trailing warning text\n"
        assert cmtag.exported_filename(out) == "My Comic 001.cbz"

    def test_strips_original_deleted_marker(self):
        out = "ComicTagger: Archive exported successfully to: My Comic 001.cbz (Original deleted) \n"
        assert cmtag.exported_filename(out) == "My Comic 001.cbz"

    def test_preserves_marker_text_inside_filename(self):
        out = "ComicTagger: Archive exported successfully to: My (Original deleted) Comic.cbz\n"
        assert cmtag.exported_filename(out) == "My (Original deleted) Comic.cbz"

    def test_returns_none_without_export_line(self):
        assert cmtag.exported_filename("Archive failed to export!") is None


class TestCbr2CbzOnly:
    """CBR2CBZ_ONLY writes no tag types, so the conversion pass must still run once."""

    @staticmethod
    def _run(tmp_path, *, cbr2cbz_only, ct_tag_cr=False):
        source = tmp_path / "library" / "issue 1.cbr"
        source.parent.mkdir()
        source.write_bytes(b"rar")
        cache = tmp_path / "cache"
        cache.mkdir()
        config = SimpleNamespace(
            CACHE_DIR=str(cache),
            FILE_OPTS="copy",
            CT_SETTINGSPATH=str(tmp_path / "ct"),
            CBR2CBZ_ONLY=cbr2cbz_only,
            CT_TAG_CR=ct_tag_cr,
            CT_TAG_CBL=False,
            CT_CBZ_OVERWRITE=False,
            COMICVINE_API="cv-key",
            CT_NOTES_FORMAT="Issue ID",
            ENFORCE_PERMS=False,
        )
        commands = []

        def popen(cmd, **_kwargs):
            commands.append(cmd)
            process = MagicMock()
            if "-e" in cmd:
                converted = os.path.join(os.path.dirname(cmd[-1]), "issue 1.cbz")
                with open(converted, "wb") as handle:
                    handle.write(b"cbz")
                process.communicate.return_value = (
                    "ComicTagger: Archive exported successfully to: issue 1.cbz\n",
                    None,
                )
            else:
                process.communicate.return_value = ("Save complete\n", None)
            return process

        with (
            patch.object(cmtag.comicarr, "CONFIG", config),
            patch.object(cmtag.comicarr, "CMTAGGER_PATH", str(tmp_path), create=True),
            patch.object(cmtag, "manga_volume_for_issue", return_value=None),
            patch.object(cmtag, "volume_metadata_field", return_value=None),
            patch.object(cmtag, "online_tag_options", return_value=[]),
            patch.object(cmtag, "sendnotify"),
            patch.object(cmtag, "logger"),
            patch.object(cmtag.subprocess, "check_output", return_value=b"ComicTagger 1.6.0 [abc]"),
            patch.object(cmtag.subprocess, "Popen", side_effect=popen),
        ):
            result = cmtag.run(str(source.parent), issueid="cv-1", filename=str(source), manualmeta=True)
        return result, commands

    def test_conversion_only_converts_the_cbr(self, tmp_path):
        result, commands = self._run(tmp_path, cbr2cbz_only=True)

        assert result.endswith("issue 1.cbz")
        assert open(result, "rb").read() == b"cbz"
        assert len(commands) == 1 and "-e" in commands[0], "one export pass, no tagging pass"

    def test_tagging_still_converts_then_tags(self, tmp_path):
        result, commands = self._run(tmp_path, cbr2cbz_only=False, ct_tag_cr=True)

        assert result.endswith("issue 1.cbz")
        assert len(commands) == 2
        assert "-e" in commands[0] and "cr" in commands[1]
