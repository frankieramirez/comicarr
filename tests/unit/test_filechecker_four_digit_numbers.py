#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""A four-digit number too early to be a year is an issue or chapter number."""

from types import SimpleNamespace

import pytest

import comicarr
from comicarr.app.library import filechecker


@pytest.fixture(autouse=True)
def _filechecker_config(monkeypatch):
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(IGNORE_SEARCH_WORDS=[], ANNUALS_ON=False, READ2FILENAME=False, ENABLE_TORRENTS=False),
    )


def _parse(title):
    return filechecker.FileChecker(file=title).listFiles()


@pytest.mark.parametrize(
    "title, number",
    [
        ("Moon Garden 1195.cbz", "1195"),
        ("Moon Garden 1190 (Digital).cbz", "1190"),
        ("Moon Garden 1099.cbz", "1099"),
    ],
)
def test_a_four_digit_chapter_before_1900_is_the_issue_number(title, number):
    parsed = _parse(title)

    assert parsed["series_name"] == "Moon Garden"
    assert parsed["issue_number"] == number
    assert parsed["issue_year"] is None


@pytest.mark.parametrize(
    "title, number, year",
    [
        ("Sky Patrol 1 (1940).cbz", "1", "1940"),
        ("Sky Patrol 1050 (2023).cbz", "1050", "2023"),
        ("Sky Patrol 001 (2012).cbz", "001", "2012"),
    ],
)
def test_real_years_are_still_years(title, number, year):
    parsed = _parse(title)

    assert parsed["issue_number"] == number
    assert parsed["issue_year"] == year
