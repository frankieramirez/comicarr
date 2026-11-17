#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""One followed series with blank metadata must not stop the weekly pull check.

A series whose metadata never loaded has no ``ComicPublished`` (and sometimes
no readable ``LatestDate``). ``new_pullcheck`` tested ``"Present" in None``,
raised TypeError, and the whole weekly job failed before any followed series
was matched, so new issues never reached the library.
"""

import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import weeklypull
from comicarr.app.common import configured as configured
from comicarr.app.core import db
from comicarr.app.core.tables import comics, metadata, weekly
from comicarr.app.search import service as search_service
from comicarr.app.series import service as series_service


@pytest.fixture
def pull_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _series(comicid, name, dynamic, published, latest_date):
    return {
        "ComicID": comicid,
        "ComicName": name,
        "ComicName_Filesafe": name,
        "ComicYear": "2024",
        "ComicPublisher": "DC Comics",
        "ComicPublished": published,
        "LatestDate": latest_date,
        "LatestIssue": "23",
        "Status": "Active",
        "DynamicComicName": dynamic,
        "Type": "Print",
        "ForceContinuing": 0,
    }


def _seed(engine, series, pull_rows):
    with engine.begin() as conn:
        for row in series:
            conn.execute(insert(comics).values(**row))
        for comicid, name, dynamic, issue in pull_rows:
            conn.execute(
                insert(weekly).values(
                    COMIC=name,
                    ISSUE=issue,
                    PUBLISHER="DC Comics",
                    SHIPDATE="2026-11-04",
                    STATUS=None,
                    ComicID=comicid,
                    IssueID=None,
                    DynamicName=dynamic,
                    weeknumber="45",
                    year="2026",
                )
            )


def _patch(monkeypatch, pullist):
    config = MagicMock()
    config.ANNUALS_ON = False
    config.AUTOWANT_UPCOMING = False
    monkeypatch.setattr(comicarr, "CONFIG", config)
    monkeypatch.setattr(series_service, "listPull", lambda week, year: pullist)
    monkeypatch.setattr(series_service, "checkthepub", lambda comicid: 60)
    monkeypatch.setattr(search_service, "LoadAlternateSearchNames", lambda *_args: None)
    upcoming = MagicMock(return_value=None)
    monkeypatch.setattr(weeklypull.watchlist_match, "upcoming_update", upcoming, raising=False)
    monkeypatch.setattr(weeklypull.watchlist_match, "latest_update", MagicMock(), raising=False)
    swallowed = MagicMock()
    monkeypatch.setattr(configured, "log_that_exception", swallowed)
    return upcoming, swallowed


def _matched(upcoming):
    return sorted((c.kwargs["ComicName"], c.kwargs["IssueNumber"]) for c in upcoming.call_args_list)


def test_blank_published_series_does_not_stop_other_matches(pull_db, monkeypatch):
    recent = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    _seed(
        pull_db,
        [
            _series("140426", "Batgirls", "batgirls", None, "2023-08-01"),
            _series("160860", "Absolute Superman", "absolutesuperman", "November 2024 - Present", recent),
        ],
        [("160860", "Absolute Superman", "absolutesuperman", "25")],
    )
    upcoming, swallowed = _patch(monkeypatch, ["160860"])

    weeklypull.new_pullcheck(45, "2026")

    assert not swallowed.called, swallowed.call_args
    assert _matched(upcoming) == [("Absolute Superman", "25")]


def test_unreadable_latest_date_still_matches_when_on_the_pull_list(pull_db, monkeypatch):
    _seed(
        pull_db,
        [
            _series("160294", "Absolute Batman", "absolutebatman", "October 2024 - Present", None),
            _series("mal-13", "One Piece", "onepiece", "1997 - Present", "Unknown-Unknow-01"),
        ],
        [("160294", "Absolute Batman", "absolutebatman", "25")],
    )
    upcoming, swallowed = _patch(monkeypatch, ["160294"])

    weeklypull.new_pullcheck(45, "2026")

    assert not swallowed.called, swallowed.call_args
    assert _matched(upcoming) == [("Absolute Batman", "25")]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-01", datetime.date(2026, 10, 1)),
        ("2026-10", datetime.date(2026, 10, 1)),
        ("26-10", datetime.date(2026, 10, 1)),
        ("Unknown-Unknow-01", None),
        ("", None),
        (None, None),
    ],
)
def test_latest_issue_date_parses_known_forms(value, expected):
    assert weeklypull._latest_issue_date(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("October 2024 - Present", True), (None, False), ("", False), ("1999 - 2004", False)],
)
def test_published_now_treats_blank_as_not_continuing(value, expected):
    assert weeklypull._published_now(value) is expected
