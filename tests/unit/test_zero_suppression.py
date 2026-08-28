#  Copyright (C) 2025–2026 Comicarr contributors
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

"""Regression tests for issue #796: zero-suppression prefix resolution.

Post-processing raised UnboundLocalError for every numeric issue when
ZERO_LEVEL was enabled but ZERO_LEVEL_N was unset (its registry default),
because the guard checked ``ZERO_LEVEL is None`` instead of
``ZERO_LEVEL_N is None``.
"""

import pytest

from comicarr.app.common.numbers import zero_suppression_prefix


class TestZeroSuppressionPrefix:
    def test_disabled_returns_empty(self):
        assert zero_suppression_prefix(False, "00x") == ""

    @pytest.mark.parametrize("level_n", [None, "none"])
    def test_enabled_with_unset_or_none_returns_empty(self, level_n):
        # The #796 case: ZERO_LEVEL enabled, ZERO_LEVEL_N never configured.
        assert zero_suppression_prefix(True, level_n) == ""

    def test_single_zero_padding(self):
        assert zero_suppression_prefix(True, "0x") == "0"

    def test_double_zero_padding(self):
        assert zero_suppression_prefix(True, "00x") == "00"

    def test_unknown_value_is_total_not_an_error(self):
        assert zero_suppression_prefix(True, "banana") == ""

    def test_zero_level_none_treated_as_disabled(self):
        assert zero_suppression_prefix(None, "00x") == ""
