#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
"""send2read picks the issue or the annual when both match one number (#1522).

Before the move, this branch read two names that were never defined
(``pulldate`` and ``file``), so it raised NameError instead of choosing.
"""

from unittest.mock import MagicMock

import pytest

from comicarr.app.core import runtime
from comicarr.app.weekly import pull_list


@pytest.fixture
def both_match(monkeypatch):
    rows = iter(
        [
            {"IssueID": "issue-1", "ReleaseDate": "2026-08-12"},
            {"IssueID": "annual-1", "ReleaseDate": "2025-08-12"},
        ]
    )
    monkeypatch.setattr(pull_list.db, "select_one", lambda _stmt: next(rows))
    monkeypatch.setattr(runtime.current(), "config", MagicMock(SEND2READ=True))
    reading = MagicMock()
    monkeypatch.setattr(pull_list.readinglist, "Readinglist", reading)
    return reading


def test_issue_year_matching_the_pull_date_wins(both_match):
    pull_list.send2read("c1", None, "1", pulldate="2026-08-12", file="Example 001.cbz")
    both_match.assert_called_once_with(IssueID="issue-1")


def test_annual_named_file_wins_when_years_do_not_decide(both_match):
    pull_list.send2read("c1", None, "1", pulldate=None, file="Example Annual 001.cbz")
    both_match.assert_called_once_with(IssueID="annual-1")


def test_unclear_match_adds_nothing(both_match):
    pull_list.send2read("c1", None, "1")
    both_match.assert_not_called()
