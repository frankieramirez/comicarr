#  Copyright (C) 2026 Comicarr contributors
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

"""The series key post-processing and the pull list match on (#1416).

The values were recorded from ``FileChecker.dynamic_replace`` before it moved.
"""

import pytest

from comicarr import filechecker
from comicarr.app.common.series_names import dynamic_series_key, dynamic_series_name


@pytest.mark.parametrize(
    "series, key",
    [
        ("Saga", "saga"),
        ("The Amazing Spider-Man", "amazingspiderman"),
        ("Batman: Year One", "batmanyearone"),
        ("S.H.I.E.L.D. (2010)", "shield2010"),
        ("Tom Strong\u2019s Terrific Tales", "tomstrongsterrifictales"),
        # Inherited quirk, kept: "the" is blanked inside words too.
        ("Black Panther & the Crew", "blackpanrcrew"),
    ],
)
def test_series_key(series, key):
    assert dynamic_series_key(series) == key


def test_filechecker_still_answers_with_the_same_key():
    for series in ("Saga", "Batman: Year One", "Hack/Slash"):
        assert filechecker.FileChecker().dynamic_replace(series)["mod_seriesname"] == dynamic_series_name(series)
        assert filechecker.dynamic_series_key(series) == dynamic_series_key(series)
