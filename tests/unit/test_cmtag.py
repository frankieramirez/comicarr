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

    def test_returns_none_without_export_line(self):
        assert cmtag.exported_filename("Archive failed to export!") is None
