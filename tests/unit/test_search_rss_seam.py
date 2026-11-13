#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Characterization tests for the RSS seam, ``comicarr.app.search.rss`` (#1204).

They pin what the legacy ``rsscheck`` / ``rsscheckit`` bodies do today when
``comicarr/app/`` calls them through the seam. Feed responses are recorded
fixtures below; HTTP and the downstream searches are faked, the database is a
real SQLite file.
"""

from types import SimpleNamespace

import pytest
import requests
from sqlalchemy import select

import comicarr
import comicarr.search
from comicarr import helpers, mangadex, rsscheck
from comicarr.app.search import rss
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, issues, metadata, rssdb

# A newznab /rss response as an indexer returns it (trimmed to two items).
NEWZNAB_RSS_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
  <channel>
    <title>nzb.example</title>
    <item>
      <title>Absolute Batman 012 (2025) (Digital) (Zone-Empire)</title>
      <link>https://nzb.example/getnzb/abc123.nzb&amp;i=42&amp;r=secretkey</link>
      <pubDate>Wed, 12 Nov 2025 10:00:00 +0000</pubDate>
      <enclosure url="https://nzb.example/getnzb/abc123.nzb" length="52428800" type="application/x-nzb"/>
    </item>
    <item>
      <title>Saga 070 (2025) (Digital)</title>
      <link>https://nzb.example/getnzb/def456.nzb&amp;i=42&amp;r=secretkey</link>
      <pubDate>Wed, 12 Nov 2025 09:00:00 +0000</pubDate>
      <newznab:attr name="size" value="31457280"/>
    </item>
  </channel>
</rss>
"""

# mangadex.get_all_chapters() output for one series, as the poll consumes it.
MANGADEX_CHAPTERS = [
    {"chapter": "1", "title": "Dog & Chainsaw", "volume": "1", "publish_at": "2020-10-01T00:00:00+00:00"},
    {"chapter": "2", "title": None, "volume": None, "publish_at": "2026-10-20T15:00:00+00:00"},
    {"chapter": None, "title": "Oneshot", "volume": None, "publish_at": "2026-10-21T15:00:00+00:00"},
]

NEWZNAB_HOST = ("nzb.example", "https://nzb.example", "1", "apikey123", "42#7030", "1")


@pytest.fixture
def rss_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if comicarr.LOG_LEVEL is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0)
    shutdown_engine()
    engine = get_engine()
    metadata.create_all(engine)
    yield engine
    shutdown_engine()


def _rows(engine, stmt):
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(stmt)]


class TestRunFeedCheck:
    """``run_feed_check`` runs ``rsscheckit.tehMain().run``: comic newznab feed."""

    @pytest.fixture
    def feed_env(self, rss_db, monkeypatch):
        monkeypatch.setattr(
            comicarr,
            "CONFIG",
            SimpleNamespace(
                RSS_CHECKINTERVAL=20,
                ENABLE_TORRENT_SEARCH=False,
                ENABLE_DDL=False,
                NEWZNAB=True,
                EXPERIMENTAL=False,
                EXTRA_NEWZNABS=[NEWZNAB_HOST],
                IGNORE_SEARCH_WORDS=[],
                ANNUALS_ON=False,
                READ2FILENAME=False,
                ENABLE_TORRENTS=False,
            ),
            raising=False,
        )
        monkeypatch.setattr(comicarr, "SCHED_RSS_LAST", None, raising=False)
        monkeypatch.setattr(comicarr, "RSS_STATUS", None, raising=False)

        env = SimpleNamespace(requests=[], searches=[], jobs=[])

        def fake_get(url, params=None, verify=None, headers=None, timeout=None):
            env.requests.append({"url": url, "params": params, "verify": verify})
            return SimpleNamespace(status_code=200, content=NEWZNAB_RSS_FEED)

        monkeypatch.setattr(rsscheck, "requests", SimpleNamespace(get=fake_get, exceptions=requests.exceptions))
        monkeypatch.setattr(comicarr.search, "searchforissue", lambda **kw: env.searches.append(kw))
        monkeypatch.setattr(helpers, "job_management", lambda **kw: env.jobs.append(kw))
        return env

    def test_a_forced_pass_indexes_the_feed_and_searches_the_watchlist(self, feed_env, rss_db):
        assert rss.run_feed_check(True) is True

        assert feed_env.requests == [
            {
                "url": "https://nzb.example/rss",
                "params": {"t": "7030", "dl": "1", "i": "42", "r": "apikey123", "num": "100"},
                "verify": True,
            }
        ]
        stored = {
            row["Title"]: row
            for row in _rows(
                rss_db,
                select(
                    rssdb.c.Title, rssdb.c.Link, rssdb.c.Site, rssdb.c.Size, rssdb.c.ComicName, rssdb.c.Issue_Number
                ),
            )
        }
        batman = stored["Absolute Batman 012 (2025) (Digital) (Zone-Empire)"]
        # The &i= and &r= credentials are stripped from the stored link.
        assert batman["Link"] == "https://nzb.example/getnzb/abc123.nzb"
        assert batman["Site"] == "nzb.example"
        assert str(batman["Size"]) == "52428800"
        assert batman["ComicName"] == "Absolute Batman"
        assert batman["Issue_Number"] == "012"
        saga = stored["Saga 070 (2025) (Digital)"]
        assert saga["ComicName"] == "Saga"
        assert saga["Issue_Number"] == "070"

        assert feed_env.searches == [{"rsschecker": "yes"}]
        assert [job.get("status") for job in feed_env.jobs] == ["Running", "Waiting"]
        assert comicarr.RSS_STATUS == "Waiting"

    def test_an_unforced_pass_inside_the_interval_does_nothing(self, feed_env, monkeypatch):
        monkeypatch.setattr(comicarr, "SCHED_RSS_LAST", str(helpers.utctimestamp()))

        assert rss.run_feed_check() is None

        assert feed_env.requests == []
        assert feed_env.searches == []
        assert feed_env.jobs == []


class TestMangaFeeds:
    """``check_mangadex_new_chapters`` and ``check_manga_releases``: MangaDex chapter feed."""

    @pytest.fixture
    def manga_db(self, rss_db, monkeypatch):
        monkeypatch.setattr(
            comicarr, "CONFIG", SimpleNamespace(FAILED_DOWNLOAD_HANDLING=False, FAILED_AUTO=False), raising=False
        )
        with rss_db.begin() as conn:
            conn.execute(
                comics.insert().values(
                    ComicID="md-csm",
                    ComicName="Chainsaw Man",
                    ComicYear="2018",
                    ContentType="manga",
                    Status="Active",
                )
            )
            conn.execute(
                issues.insert().values(
                    IssueID="md-csm-ch1",
                    ComicID="md-csm",
                    ComicName="Chainsaw Man",
                    Issue_Number="1",
                    ChapterNumber="1",
                    Status="Downloaded",
                )
            )
        return rss_db

    def test_new_chapters_from_mangadex_become_wanted_issues(self, manga_db, monkeypatch):
        polled = []
        monkeypatch.setattr(
            mangadex, "get_all_chapters", lambda manga_id, *a, **k: polled.append(manga_id) or MANGADEX_CHAPTERS
        )

        rss.check_mangadex_new_chapters()

        assert polled == ["csm"]
        rows = _rows(manga_db, select(issues).where(issues.c.ComicID == "md-csm").order_by(issues.c.IssueID))
        assert [row["IssueID"] for row in rows] == ["md-csm-ch1", "md-csm-ch2"]
        added = rows[1]
        assert added["Status"] == "Wanted"
        assert added["IssueName"] == "Chapter 2"
        assert added["Issue_Number"] == "2"
        assert added["ChapterNumber"] == "2"
        assert added["IssueDate"] == "2026-10-20"
        assert added["ReleaseDate"] == "2026-10-20"
        assert added["VolumeNumber"] is None
        # The tracked chapter is left as it was.
        assert rows[0]["Status"] == "Downloaded"

    def test_wanted_chapters_are_searched_when_rssdb_has_the_series(self, manga_db, monkeypatch):
        with manga_db.begin() as conn:
            conn.execute(
                issues.insert().values(
                    IssueID="md-csm-ch2",
                    ComicID="md-csm",
                    ComicName="Chainsaw Man",
                    Issue_Number="2",
                    ChapterNumber="2",
                    IssueDate="2026-10-20",
                    ReleaseDate="2026-10-20",
                    Status="Wanted",
                )
            )
            conn.execute(
                rssdb.insert().values(
                    Title="Chainsaw Man c002 (2026)",
                    Link="https://nzb.example/getnzb/csm2.nzb",
                    Pubdate="now",
                    Site="nzb.example",
                    Size="1",
                )
            )
        calls = []
        monkeypatch.setattr(comicarr.search, "search_init", lambda *a, **kw: calls.append((a, kw)))

        rss.check_manga_releases()

        assert len(calls) == 1
        args, kwargs = calls[0]
        assert args == ("Chainsaw Man", "2", "2018", "2018", None, "2026-10-20", "2026-10-20", "md-csm-ch2")
        assert kwargs["ComicID"] == "md-csm"
        assert kwargs["booktype"] == "manga"
        assert kwargs["content_type"] == "manga"
        assert kwargs["chapter_number"] == "2"
        assert kwargs["volume_number"] is None
        assert kwargs["rsschecker"] == "yes"
        assert kwargs["smode"] == "want"

    def test_a_series_rssdb_does_not_carry_is_not_searched(self, manga_db, monkeypatch):
        with manga_db.begin() as conn:
            conn.execute(
                issues.insert().values(
                    IssueID="md-csm-ch2", ComicID="md-csm", Issue_Number="2", ChapterNumber="2", Status="Wanted"
                )
            )
        calls = []
        monkeypatch.setattr(comicarr.search, "search_init", lambda *a, **kw: calls.append((a, kw)))

        rss.check_manga_releases()

        assert calls == []


class TestAppCallersUseTheSeam:
    def test_force_rss_starts_a_forced_feed_check(self, monkeypatch):
        from comicarr.app.search import service

        started = []
        monkeypatch.setattr(service, "start_background_thread", lambda target, **kw: started.append((target, kw)))
        ctx = SimpleNamespace(background_workers=object())

        assert service.force_rss(ctx) == {"success": True, "message": "RSS check initiated"}
        assert started == [
            (rss.run_feed_check, {"args": (True,), "name": "ManualRSS", "registry": ctx.background_workers})
        ]

    def test_manga_sync_polls_mangadex_before_searching(self, monkeypatch):
        from comicarr.app.manga import sync

        order = []
        monkeypatch.setattr(sync, "heal_empty_ledgers", lambda: 3)
        monkeypatch.setattr(rss, "check_mangadex_new_chapters", lambda: order.append("poll"))
        monkeypatch.setattr(rss, "check_manga_releases", lambda: order.append("search"))
        monkeypatch.setattr(comicarr, "SCHED_MANGA_SYNC_LAST", None, raising=False)

        assert sync.run_manga_sync() == {"healed": 3}
        assert order == ["poll", "search"]
