#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""RSS must not go quiet when a feed URL answers with something that isn't a feed.

Prowlarr per-indexer hosts are saved as ``http://prowlarr:9696/<id>/api``. The
RSS pass asked for ``<host>/rss``; Prowlarr serves its web page with a 200 for
unknown paths, feedparser found no entries, and the API fallback never ran, so
every Prowlarr indexer reported "0 entries indexed" on every pass.

Separately, one GetComics post without the expected details paragraph aborted
the DDL feed with ``'NoneType' object has no attribute 'findNext'``.
"""

from types import SimpleNamespace

import pytest
import requests

import comicarr
from comicarr import rsscheck

NEWZNAB_API_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>prowlarr</title>
  <item>
    <title>Absolute Batman 025 (2026) (Digital) (Zone-Empire)</title>
    <link>http://prowlarr:9696/1/download?apikey=k&amp;link=abc</link>
    <pubDate>Wed, 04 Nov 2026 10:00:00 +0000</pubDate>
    <enclosure url="http://prowlarr:9696/1/download?link=abc" length="52428800" type="application/x-nzb"/>
  </item>
</channel></rss>
"""

PROWLARR_WEB_PAGE = b'<!doctype html><html lang="en"><head><title>Prowlarr</title></head><body></body></html>'

PROWLARR_HOST = ("Example (Prowlarr)", "http://prowlarr:9696/1/api", "0", "apikey123", "#7000", "1")


@pytest.fixture
def captured(monkeypatch):
    stored = []
    monkeypatch.setattr(rsscheck, "rssdbupdate", lambda data, count, kind: stored.append((kind, data)))
    return stored


def _fake_requests(monkeypatch, respond):
    calls = []

    def fake_get(url, params=None, verify=None, headers=None, timeout=None):
        calls.append(url)
        content, ctype = respond(url)
        return SimpleNamespace(status_code=200, content=content, headers={"Content-Type": ctype})

    monkeypatch.setattr(rsscheck, "requests", SimpleNamespace(get=fake_get, exceptions=requests.exceptions))
    return calls


def test_a_web_page_on_the_rss_url_falls_back_to_the_api(monkeypatch, captured):
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(NEWZNAB=True, EXPERIMENTAL=False, EXTRA_NEWZNABS=[PROWLARR_HOST]),
        raising=False,
    )
    monkeypatch.setattr(rsscheck, "provider_enabled", lambda host: True)

    def respond(url):
        if url.endswith("/rss"):
            return PROWLARR_WEB_PAGE, "text/html"
        return NEWZNAB_API_FEED, "application/rss+xml"

    calls = _fake_requests(monkeypatch, respond)

    rsscheck.nzbs()

    assert calls == ["http://prowlarr:9696/1/rss", "http://prowlarr:9696/1/api"]
    assert len(captured) == 1
    kind, data = captured[0]
    assert kind == "usenet"
    assert [row["Title"] for row in data] == ["Absolute Batman 025 (2026) (Digital) (Zone-Empire)"]


@pytest.mark.parametrize(
    ("host", "api", "rss"),
    [
        ("http://prowlarr:9696/1/api", "http://prowlarr:9696/1/api", "http://prowlarr:9696/1/rss"),
        ("http://prowlarr:9696/1/api/", "http://prowlarr:9696/1/api", "http://prowlarr:9696/1/rss"),
        ("https://nzb.example", "https://nzb.example/api", "https://nzb.example/rss"),
        ("https://nzb.example/", "https://nzb.example/api", "https://nzb.example/rss"),
    ],
)
def test_newznab_urls_follow_the_saved_host_shape(host, api, rss):
    assert rsscheck._newznab_api_url(host) == api
    assert rsscheck._newznab_rss_url(host) == rss


GETCOMICS_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>GetComics</title>
  <item>
    <title>Weekly Pack 2026.11.04</title>
    <link>https://getcomics.info/?p=1</link>
    <guid>https://getcomics.info/?p=1</guid>
    <pubDate>Wed, 04 Nov 2026 10:00:00 +0000</pubDate>
    <description><![CDATA[<p>New layout without the details paragraph.</p>]]></description>
  </item>
  <item>
    <title>Absolute Batman #25 (2026)</title>
    <link>https://getcomics.info/?p=2</link>
    <guid>https://getcomics.info/?p=2</guid>
    <pubDate>Wed, 04 Nov 2026 11:00:00 +0000</pubDate>
    <description><![CDATA[<p style="text-align: center;"><strong>Year : </strong>2026 | <strong>Size : </strong>48 MB</p>]]></description>
  </item>
</channel></rss>
"""


def test_a_getcomics_post_without_details_is_skipped_not_fatal(monkeypatch, captured):
    _fake_requests(monkeypatch, lambda url: (GETCOMICS_FEED, "application/rss+xml"))

    rsscheck.ddl()

    assert len(captured) == 1
    kind, data = captured[0]
    assert kind == "ddl"
    assert [row["Title"] for row in data] == ["Absolute Batman #25 (2026)"]
