#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The most SQL statements each main read endpoint may run per request.

``tests/unit/test_query_budgets.py`` enforces these against a small seeded
library, and checks that the count stays the same when the library doubles.
Each number is the count measured on the code as it was when the budget was
set, with no headroom.

Changing a budget: run the test, read the count it prints, and edit the
number here in the same pull request as the change that moved it. A lower
number needs no defence. A reviewer should question any increase: one more
statement per request is usually fine, but a new statement inside a loop is
an N+1, and the size check fails on that whatever the budget says. Never
raise a budget to get a growing count past the size check; file an issue and
fix the loop instead.
"""

BUDGETS = {
    # GET /api/series: the Library page.
    "library_list": 1,
    # GET /api/series/{id}: series, issues, provider override.
    "series_detail": 3,
    # GET /api/wanted/series: wanted rows, search state, RSS pacing.
    "wanted_by_series": 3,
    # GET /api/wanted?comic_id=...&limit=50: one series expanded on Wanted.
    "wanted_issues": 3,
    # GET /api/dashboard/library: totals, then manga, comic and magazine totals.
    "dashboard_library": 4,
    # GET /api/dashboard/activity: recent activity events.
    "dashboard_activity": 1,
    # GET /api/dashboard/upcoming: this week's pull, Needs attention, finished times.
    "dashboard_upcoming": 3,
}
