#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Originally based on Mylar3 (https://github.com/mylar3/mylar3).
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
Unit tests for get_manga_destination() fallback chain in comicarr/config.py.
"""

from unittest.mock import MagicMock, patch

import comicarr

# Ensure LOG_LEVEL is set for tests
if comicarr.LOG_LEVEL is None:
    comicarr.LOG_LEVEL = 0

from comicarr.config import get_manga_destination


class TestGetMangaDestination:
    """Tests for the get_manga_destination() fallback chain."""

    def test_returns_manga_destination_dir_when_set(self):
        """MANGA_DESTINATION_DIR takes highest priority."""
        mock_config = MagicMock()
        mock_config.MANGA_DESTINATION_DIR = "/manga/destination"
        mock_config.MANGA_DIR = "/manga/library"
        mock_config.DESTINATION_DIR = "/downloads"

        with patch.object(comicarr, "CONFIG", mock_config):
            result = get_manga_destination()

        assert result == "/manga/destination"

    def test_falls_back_to_manga_dir_when_manga_destination_dir_unset(self):
        """MANGA_DIR is used when MANGA_DESTINATION_DIR is not set."""
        mock_config = MagicMock()
        mock_config.MANGA_DESTINATION_DIR = None
        mock_config.MANGA_DIR = "/manga/library"
        mock_config.DESTINATION_DIR = "/downloads"

        with patch.object(comicarr, "CONFIG", mock_config):
            result = get_manga_destination()

        assert result == "/manga/library"

    def test_falls_back_to_destination_dir_when_both_manga_dirs_unset(self):
        """DESTINATION_DIR is used when both manga-specific dirs are unset."""
        mock_config = MagicMock()
        mock_config.MANGA_DESTINATION_DIR = None
        mock_config.MANGA_DIR = None
        mock_config.DESTINATION_DIR = "/downloads"

        with patch.object(comicarr, "CONFIG", mock_config):
            result = get_manga_destination()

        assert result == "/downloads"

    def test_returns_none_when_all_dirs_unset(self):
        """Returns None when no directories are configured."""
        mock_config = MagicMock()
        mock_config.MANGA_DESTINATION_DIR = None
        mock_config.MANGA_DIR = None
        mock_config.DESTINATION_DIR = None

        with patch.object(comicarr, "CONFIG", mock_config):
            result = get_manga_destination()

        assert result is None

    def test_ignores_empty_string_manga_destination_dir(self):
        """Empty string MANGA_DESTINATION_DIR is treated as unset."""
        mock_config = MagicMock()
        mock_config.MANGA_DESTINATION_DIR = ""
        mock_config.MANGA_DIR = "/manga/library"
        mock_config.DESTINATION_DIR = "/downloads"

        with patch.object(comicarr, "CONFIG", mock_config):
            result = get_manga_destination()

        assert result == "/manga/library"

    def test_ignores_empty_string_manga_dir(self):
        """Empty string MANGA_DIR is treated as unset, falls through to DESTINATION_DIR."""
        mock_config = MagicMock()
        mock_config.MANGA_DESTINATION_DIR = ""
        mock_config.MANGA_DIR = ""
        mock_config.DESTINATION_DIR = "/downloads"

        with patch.object(comicarr, "CONFIG", mock_config):
            result = get_manga_destination()

        assert result == "/downloads"
