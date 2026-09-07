#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from types import SimpleNamespace

import pytest

import comicarr
from comicarr import filechecker


@pytest.fixture(autouse=True)
def _filechecker_config(monkeypatch):
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            IGNORE_SEARCH_WORDS=[],
            ANNUALS_ON=False,
            READ2FILENAME=False,
            ENABLE_TORRENTS=False,
        ),
    )


def _parse(title, watch):
    return filechecker.FileChecker(file=title, watchcomic=watch).listFiles()


def _match(title, watch):
    parsed = _parse(title, watch)
    matched = filechecker.FileChecker(watchcomic=watch).matchIT(parsed)
    return parsed, matched


@pytest.mark.parametrize(
    "title",
    [
        "Shepherdess Warriors Vol. 1 (2024)",
        "Shepherdess Warriors Vol 1 (2024)",
        "Shepherdess Warriors Volume 1 (2024)",
        "Shepherdess Warriors Vol. 1 (2024) (Digital)",
        "Shepherdess Warriors v1 (2024)",
    ],
)
def test_volume_token_is_stripped_from_series_name(title):
    parsed, matched = _match(title, "Shepherdess Warriors")

    assert parsed["parse_status"] == "success"
    assert parsed["series_name"] == "Shepherdess Warriors"
    assert parsed["series_volume"] == "v1"
    assert parsed["issue_number"] is None
    assert "One-Shot" in parsed["booktype"] or parsed["booktype"] in ("TPB", "HC", "GN")
    assert matched["process_status"] == "match"


def test_issue_number_after_volume_is_still_the_issue():
    parsed, matched = _match("Amazing Spider-Man Vol. 2 #15 (1999)", "Amazing Spider-Man")

    assert parsed["series_name"] == "Amazing Spider-Man"
    assert parsed["series_volume"] == "v2"
    assert parsed["issue_number"] == "15"
    assert matched["process_status"] == "match"
    assert matched["justthedigits"] == "15"


def test_hash_issue_is_unchanged():
    parsed, matched = _match("Shepherdess Warriors #1 (2024)", "Shepherdess Warriors")

    assert parsed["series_name"] == "Shepherdess Warriors"
    assert parsed["issue_number"] == "1"
    assert parsed["booktype"] == "issue"
    assert matched["process_status"] == "match"


def test_volume_word_in_series_title_does_not_capture_later_issue():
    parsed, matched = _match("The Volume Of Things #1 (2024)", "The Volume Of Things")

    assert parsed["series_name"] == "The Volume Of Things"
    assert parsed["series_volume"] is None
    assert parsed["issue_number"] == "1"
    assert parsed["booktype"] == "issue"
    assert matched["process_status"] == "match"
