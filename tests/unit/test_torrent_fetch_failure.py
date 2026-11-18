#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Torrent .torrent-fetch failures stay on the clean pre-submission path (#566).

`torsend2client` catches any exception from the .torrent fetch, and used to
fall through into code that dereferences the unbound response — a `NameError`
raised out of the sender. `perform_handoff` treats a raising sender as
*submission outcome unknown* (the "it may already have landed" lane) and files
it for manual review, which is wrong for a failure that never touched the
download client, and — because `manual_review` is terminal — wedges every later
grab on that release_key.

All five torrent routes share this sender, so the contract pinned here is:
a fetch exception returns "fail", and "fail" lands in Failed Download Handling
rather than manual review.
"""

import types
from unittest.mock import MagicMock, patch

import pytest
import requests
from sqlalchemy import select

import comicarr
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.core.db import get_engine, shutdown_engine
from comicarr.app.core.tables import metadata, pipeline_journal
from comicarr.app.downloads import handoff, journal
from comicarr.app.search import rss_feeds as rsscheck

# ---------------------------------------------------------------------------
# torsend2client — the sender itself
# ---------------------------------------------------------------------------


@pytest.fixture
def torrent_client_configured(tmp_path, monkeypatch):
    """Minimal globals for torsend2client's generic (non-32P/DEM/WWT) path."""
    monkeypatch.setattr(comicarr, "USE_QBITTORRENT", True, raising=False)
    monkeypatch.setattr(comicarr, "USE_UTORRENT", False, raising=False)
    monkeypatch.setattr(comicarr, "USE_RTORRENT", False, raising=False)
    monkeypatch.setattr(comicarr, "USE_TRANSMISSION", False, raising=False)
    monkeypatch.setattr(comicarr, "USE_DELUGE", False, raising=False)
    monkeypatch.setattr(comicarr, "USE_WATCHDIR", False, raising=False)
    config = MagicMock()
    config.CACHE_DIR = str(tmp_path)
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)
    return tmp_path


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError("connection refused"),
        requests.exceptions.Timeout("read timed out"),
        requests.exceptions.SSLError("certificate verify failed"),
        ValueError("malformed response"),
    ],
)
def test_fetch_exception_returns_fail(torrent_client_configured, error):
    with patch.object(rsscheck.cfscrape, "create_scraper", side_effect=error):
        result = rsscheck.torsend2client(
            "Some Series",
            "1",
            "2020",
            "https://tracker.example/download/abc.torrent",
            "SomeTracker",
        )

    assert result == "fail"


def test_fetch_exception_does_not_raise_nameerror(torrent_client_configured):
    """The regression itself: falling through left `r` unbound."""
    scraper = MagicMock()
    scraper.get.side_effect = requests.exceptions.ConnectionError("connection refused")

    with patch.object(rsscheck.cfscrape, "create_scraper", return_value=scraper):
        result = rsscheck.torsend2client(
            "Some Series",
            "1",
            "2020",
            "https://tracker.example/download/abc.torrent",
            "SomeTracker",
        )

    assert result == "fail"


def test_fetch_exception_writes_no_torrent_file(torrent_client_configured):
    cache_dir = torrent_client_configured
    scraper = MagicMock()
    scraper.get.side_effect = requests.exceptions.ConnectionError("connection refused")

    with patch.object(rsscheck.cfscrape, "create_scraper", return_value=scraper):
        rsscheck.torsend2client(
            "Some Series",
            "1",
            "2020",
            "https://tracker.example/download/abc.torrent",
            "SomeTracker",
        )

    assert list(cache_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# perform_handoff — where a "fail" lands versus where a raise lands
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if not hasattr(comicarr, "LOG_LEVEL") or comicarr.LOG_LEVEL is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(HIGHCOUNT=0, POST_PROCESSING=False),
        raising=False,
    )
    engine = get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready
    yield
    shutdown_engine()


def _journal_row(key):
    with get_engine().connect() as conn:
        row = conn.execute(select(pipeline_journal).where(pipeline_journal.c.release_key == key)).fetchone()
        return dict(row._mapping) if row else None


def test_fail_return_lands_on_the_failed_path_not_manual_review(isolated_db):
    key = "I1|qbittorrent"

    response, acceptance = handoff.perform_handoff(key, "qbittorrent", lambda: "fail")

    row = _journal_row(key)
    assert response == "fail"
    assert acceptance.restart_safe is False
    assert acceptance.manual_review is False
    assert row["stage"] == journal.FAILED
    assert row["stage"] != journal.MANUAL_REVIEW
    assert not str(row["fail_reason"]).startswith("submission_outcome_unknown")


def test_a_raising_sender_is_still_the_ambiguity_lane(isolated_db):
    """The behaviour the fix routes *away* from — unchanged, and deliberately so.

    A sender that raises genuinely may have reached the client, so manual review
    remains correct there. #566 is about not reaching this lane by accident.
    """
    key = "I2|qbittorrent"

    def raising_sender():
        raise NameError("name 'r' is not defined")

    with pytest.raises(NameError):
        handoff.perform_handoff(key, "qbittorrent", raising_sender)

    row = _journal_row(key)
    assert row["stage"] == journal.MANUAL_REVIEW
    assert row["fail_reason"] == "submission_outcome_unknown:NameError"
