#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Replay the request sequence real OPDS reader apps send (#1351).

#1148 shipped because every feed builder passed its unit test while Panels
could not sign in, open a folder, or reach page 2. These tests drive the whole
FastAPI app (middleware, setup gate, every registered router) the way a reader
does: send the app's own headers, answer the auth challenge the way the app
answers it, resolve each ``href`` against the feed it came from, and follow
next/previous links instead of building URLs by hand.

The library has one series with more than two pages of issues at the default
page size of 30, so pages 2 and 3 exist, plus history rows a long-running
install accumulates: a re-grabbed issue, a deleted series, a missing file and a
corrupt archive.
"""

import io
import zipfile
from dataclasses import dataclass
from types import SimpleNamespace
from urllib.parse import unquote, urljoin, urlsplit
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from starlette.routing import Match, Mount

import comicarr
from comicarr.app.core import db
from comicarr.app.core.tables import comics, issues, metadata, snatched
from comicarr.app.series import service as series_service

ATOM = "{http://www.w3.org/2005/Atom}"
ACQUISITION = "http://opds-spec.org/acquisition"
PSE_STREAM = "http://vaemendis.net/opds-pse/stream"
BASE = "http://testserver"
CREDENTIALS = ("reader", "s3cret & more")
PAGE_SIZE = 30  # Comicarr's default OPDS_PAGESIZE, and the #1148 reporter's.
LONG_SERIES_ISSUES = 65  # Pages of 30, 30 and 5.


@dataclass(frozen=True)
class ReaderApp:
    """The headers and auth behaviour one reader app sends.

    ``challenge_first`` apps send no credentials until a 401 carries a
    ``WWW-Authenticate: Basic`` challenge, then answer every later request in
    the same realm. The others send Basic credentials on every request.
    """

    name: str
    user_agent: str
    accept: str
    challenge_first: bool


# Panels' User-Agent is a field-reported iOS build; Panels prompts for
# credentials only after a Basic challenge (#1148). Chunky and KyBook 3 are
# CFNetwork apps, so they send the same "<App>/<build> CFNetwork Darwin" shape
# and URLSession's default Accept; both store the server's credentials when it
# is added and send them up front.
READER_APPS = [
    ReaderApp(
        name="Panels",
        user_agent="Panels/956 CFNetwork/3896.100.1.2.1 Darwin/27.0.0",
        accept="*/*",
        challenge_first=True,
    ),
    ReaderApp(
        name="Chunky",
        user_agent="Chunky/1.4.2 CFNetwork/1568.200.51 Darwin/24.1.0",
        accept="*/*",
        challenge_first=False,
    ),
    ReaderApp(
        name="KyBook 3",
        user_agent="KyBook/3.9.4 CFNetwork/1568.200.51 Darwin/24.1.0",
        accept="application/atom+xml, application/xml;q=0.9, */*;q=0.8",
        challenge_first=False,
    ),
]


class ReaderSession:
    """A reader app talking to the server: its headers, its auth, its link resolution."""

    def __init__(self, client, app, credentials=CREDENTIALS):
        self.client = client
        self.app = app
        self.credentials = credentials
        self.realm = None
        self.challenges = []

    def request(self, url):
        absolute = urljoin(BASE, url)
        headers = {"User-Agent": self.app.user_agent, "Accept": self.app.accept}
        auth = self.credentials if (self.realm or not self.app.challenge_first) else None
        response = self.client.get(absolute, headers=headers, auth=auth)
        if response.status_code == 401 and auth is None:
            challenge = response.headers.get("WWW-Authenticate", "")
            self.challenges.append(challenge)
            assert challenge.startswith("Basic "), "%s gets no Basic challenge at %s" % (self.app.name, url)
            self.realm = challenge
            response = self.client.get(absolute, headers=headers, auth=self.credentials)
        return response

    def feed(self, url):
        response = self.request(url)
        assert response.status_code == 200, (self.app.name, url, response.status_code, response.text[:300])
        assert response.headers["content-type"].startswith("application/atom+xml"), url
        raw = response.text
        assert "cmd=" not in raw, url
        assert "&amp;amp;" not in raw, url
        return Feed(urljoin(BASE, url), raw, ElementTree.fromstring(response.content))


class Feed:
    def __init__(self, url, raw, root):
        self.url = url
        self.raw = raw
        self.root = root

    def resolve(self, href):
        return urljoin(self.url, href)

    def links(self, rel):
        return [self.resolve(link.get("href")) for link in self.root.findall(ATOM + "link") if link.get("rel") == rel]

    def one_link(self, rel):
        found = self.links(rel)
        assert len(found) <= 1, (self.url, rel, found)
        return found[0] if found else None

    def entries(self):
        return self.root.findall(ATOM + "entry")

    def entry(self, title_prefix):
        for entry in self.entries():
            if entry.findtext(ATOM + "title").startswith(title_prefix):
                return entry
        raise AssertionError("%s has no entry titled %r" % (self.url, title_prefix))

    def entry_href(self, title_prefix, rel=None):
        entry = self.entry(title_prefix)
        for link in entry.findall(ATOM + "link"):
            if rel is None or link.get("rel") == rel:
                return self.resolve(link.get("href"))
        raise AssertionError("%r has no %s link" % (title_prefix, rel))

    def all_hrefs(self):
        hrefs = [self.resolve(link.get("href")) for link in self.root.iter(ATOM + "link")]
        return [href.replace("{pageNumber}", "0") for href in hrefs]

    def issue_ids(self):
        """The IssueIDs this feed offers for download, in order."""
        found = []
        for entry in self.entries():
            for link in entry.findall(ATOM + "link"):
                if link.get("rel") == ACQUISITION:
                    path = urlsplit(self.resolve(link.get("href"))).path
                    found.append(unquote(path.rsplit("/", 1)[1]))
        return found


def _png():
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
    )


def _cbz(path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("001.png", _png())
        zf.writestr("002.png", _png())
    path.write_bytes(buf.getvalue())


# (ComicID, name, year, publisher, issue count)
SERIES = [
    ("2914", "Star Wars", "1977", "Marvel", LONG_SERIES_ISSUES),
    ("18166", "The Sandman", "1989", "DC & Vertigo", 3),
    ("47530", "Saga", "2012", "Image", 2),
]
MISSING_FILE_ISSUE = "47530-2"  # Location is set, the file is gone.
CORRUPT_ISSUE = "18166-3"  # Location is set, the file is not an archive.
REGRABBED_ISSUE = "2914-5"  # Two history rows: Downloaded, then Post-Processed.


@pytest.fixture
def library(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    metadata.create_all(engine)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(series_service, "_havetotals_cache", None)

    root = tmp_path / "comics"
    config = SimpleNamespace(
        OPDS_ENABLE=True,
        OPDS_PAGESIZE=PAGE_SIZE,
        OPDS_METAINFO=False,
        OPDS_USERNAME=CREDENTIALS[0],
        OPDS_PASSWORD=CREDENTIALS[1],
        HTTP_USERNAME="admin",
        HTTP_PASSWORD="$2b$12$notarealhashnotarealhashnotarealhashnotarealhashnot",
        HTTP_ROOT="/",
        ANNUALS_ON=False,
        DESTINATION_DIR=str(root),
        COMIC_DIR=str(root),
        GRABBAG_DIR=None,
        STORYARC_LOCATION=None,
    )
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)

    downloadable = []
    added = 0
    with engine.begin() as conn:
        for comic_id, name, year, publisher, count in SERIES:
            series_dir = root / ("%s (%s)" % (name, year))
            series_dir.mkdir(parents=True)
            conn.execute(
                comics.insert(),
                {
                    "ComicID": comic_id,
                    "ComicName": name,
                    "ComicSortName": name,
                    "ComicYear": year,
                    "ComicPublisher": publisher,
                    "ComicLocation": str(series_dir),
                    "LatestIssue": str(count),
                    "intLatestIssue": count * 1000,
                    "LatestDate": "%s-01-01" % year,
                    "ComicPublished": year,
                    "DateAdded": "2026-11-01",
                    "LastUpdated": "2026-11-01",
                    "Have": count,
                    "Total": count,
                    "Status": "Active",
                },
            )
            for n in range(1, count + 1):
                issue_id = "%s-%d" % (comic_id, n)
                filename = "%s %03d (%s).cbz" % (name, n, year)
                if issue_id == CORRUPT_ISSUE:
                    (series_dir / filename).write_bytes(b"not a zip archive")
                elif issue_id != MISSING_FILE_ISSUE:
                    _cbz(series_dir / filename)
                if issue_id != MISSING_FILE_ISSUE:
                    downloadable.append(issue_id)
                conn.execute(
                    issues.insert(),
                    {
                        "IssueID": issue_id,
                        "ComicID": comic_id,
                        "ComicName": name,
                        "Issue_Number": str(n),
                        "Int_IssueNumber": n * 1000,
                        "IssueName": "Part %d" % n,
                        "IssueDate": "%s-01-01" % year,
                        "ReleaseDate": "%s-01-01" % year,
                        "DateAdded": "2026-11-01",
                        "ImageURL": "https://comicvine.example/thumb/%s.jpg" % issue_id,
                        "ImageURL_ALT": "https://comicvine.example/full/%s.jpg" % issue_id,
                        "Location": filename,
                        "Status": "Downloaded",
                    },
                )
                added += 1
                conn.execute(
                    snatched.insert(),
                    {
                        "IssueID": issue_id,
                        "ComicID": comic_id,
                        "ComicName": name,
                        "Issue_Number": str(n),
                        "DateAdded": "2026-10-%02d %02d:%02d:00" % (1 + added // 60, (added // 60) % 24, added % 60),
                        "Status": "Post-Processed",
                        "Provider": "nzbgeek",
                    },
                )
        # A re-grab leaves an older history row for the same issue.
        conn.execute(
            snatched.insert(),
            {
                "IssueID": REGRABBED_ISSUE,
                "ComicID": "2914",
                "ComicName": "Star Wars",
                "Issue_Number": "5",
                "DateAdded": "2026-09-30 12:00:00",
                "Status": "Downloaded",
                "Provider": "getcomics",
            },
        )
        # Deleting a series keeps its download history.
        conn.execute(
            snatched.insert(),
            {
                "IssueID": "deleted-1",
                "ComicID": "999999",
                "ComicName": "Deleted Series",
                "Issue_Number": "1",
                "DateAdded": "2026-11-14 09:00:00",
                "Status": "Post-Processed",
                "Provider": "nzbgeek",
            },
        )

    from comicarr.app.core.context import AppContext
    from comicarr.app.main import create_app

    app = create_app()
    # No lifespan: the runtime would open the real data dir and scheduler.
    app.state.ctx = AppContext(config=config)
    client = TestClient(app, base_url=BASE)  # not a context manager: that would run the lifespan
    yield SimpleNamespace(app=app, client=client, downloadable=downloadable)
    client.close()


def _series_issue_ids(comic_id, downloadable):
    return {issue_id for issue_id in downloadable if issue_id.startswith(comic_id + "-")}


def _route_for(app, url):
    """The registered route that serves ``url``, or None (SPA mounts don't count)."""
    scope = {"type": "http", "path": urlsplit(url).path, "method": "GET", "root_path": ""}
    for route in app.router.routes:
        if isinstance(route, Mount):
            continue
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return route
    return None


def _walk_pages(reader, first_url):
    """Follow next links from ``first_url``; return the feeds in order."""
    pages = [reader.feed(first_url)]
    while (next_url := pages[-1].one_link("next")) is not None:
        assert len(pages) < 20, "next links loop at %s" % next_url
        pages.append(reader.feed(next_url))
    return pages


def _walk_back(reader, last_page):
    pages = [last_page]
    while (prev_url := pages[-1].one_link("previous")) is not None:
        assert len(pages) < 20, "previous links loop at %s" % prev_url
        pages.append(reader.feed(prev_url))
    return pages


@pytest.fixture(params=READER_APPS, ids=lambda app: app.name)
def reader(request, library):
    return ReaderSession(library.client, request.param)


def test_unauthenticated_request_gets_basic_challenge(library):
    for app in READER_APPS:
        headers = {"User-Agent": app.user_agent, "Accept": app.accept}
        for url in ("/opds/", "/opds/comics/2914?index=30", "/opds/issues/2914-1"):
            for auth in (None, ("reader", "wrong"), ("nobody", CREDENTIALS[1])):
                response = library.client.get(url, headers=headers, auth=auth)
                assert response.status_code == 401, (app.name, url, auth)
                assert response.headers["WWW-Authenticate"].startswith("Basic realm="), (app.name, url)


def test_reader_walks_root_to_publisher_series_issue_and_download(reader, library):
    root = reader.feed("/opds/")
    if reader.app.challenge_first:
        assert len(reader.challenges) == 1

    publishers = reader.feed(root.entry_href("Publishers"))
    assert sorted(entry.findtext(ATOM + "title") for entry in publishers.entries()) == [
        "DC & Vertigo (1)",
        "Image (1)",
        "Marvel (1)",
    ]

    marvel = reader.feed(publishers.entry_href("Marvel"))
    series = reader.feed(marvel.entry_href("Star Wars"))
    assert len(series.entries()) == PAGE_SIZE

    entry = series.entries()[0]
    acquisition = [
        series.resolve(link.get("href")) for link in entry.findall(ATOM + "link") if link.get("rel") == ACQUISITION
    ]
    (download_url,) = acquisition
    download = reader.request(download_url)
    assert download.status_code == 200
    assert download.content[:2] == b"PK"
    assert "attachment" in download.headers.get("content-disposition", "")

    (stream_url,) = [
        series.resolve(link.get("href")) for link in entry.findall(ATOM + "link") if link.get("rel") == PSE_STREAM
    ]
    page = reader.request(stream_url.replace("{pageNumber}", "1"))
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("image/")

    # A challenge-first reader answers once and keeps its credentials for the realm.
    assert len(reader.challenges) == (1 if reader.app.challenge_first else 0)


def test_series_pages_reach_every_issue_exactly_once(reader, library):
    pages = _walk_pages(reader, "/opds/comics/2914")
    assert [len(page.entries()) for page in pages] == [30, 30, 5]
    seen = [issue_id for page in pages for issue_id in page.issue_ids()]
    assert len(seen) == len(set(seen))
    assert set(seen) == _series_issue_ids("2914", library.downloadable)

    back = _walk_back(reader, pages[-1])
    assert [page.url for page in back] == [page.url for page in reversed(pages)]


def test_recent_additions_page_through_every_download_exactly_once(reader, library):
    root = reader.feed("/opds/")
    pages = _walk_pages(reader, root.entry_href("Recent Additions"))
    seen = [issue_id for page in pages for issue_id in page.issue_ids()]
    duplicates = sorted({issue_id for issue_id in seen if seen.count(issue_id) > 1})
    assert duplicates == []
    assert set(seen) == set(library.downloadable)
    assert all(len(page.entries()) <= PAGE_SIZE for page in pages)
    assert len(pages) == -(-len(library.downloadable) // PAGE_SIZE)

    back = _walk_back(reader, pages[-1])
    assert [page.url for page in back] == [page.url for page in reversed(pages)]


def test_corrupt_archive_does_not_break_its_series_feed(reader, library):
    feed = reader.feed("/opds/comics/18166")
    assert set(feed.issue_ids()) == _series_issue_ids("18166", library.downloadable)
    entry = feed.entries()[0]
    assert entry.findtext(ATOM + "title").startswith("The Sandman (1989) #3")
    stream = [link for link in entry.findall(ATOM + "link") if link.get("rel") == PSE_STREAM][0]
    assert stream.get("{http://vaemendis.net/opds-pse/ns}count") == "0"


def test_every_href_in_every_feed_resolves_to_a_registered_route(reader, library):
    """Crawl the whole catalog from the root the way a reader would."""
    queue = [urljoin(BASE, "/opds/")]
    visited = set()
    feeds = 0
    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        parts = urlsplit(url)
        if parts.netloc != urlsplit(BASE).netloc:
            # Cover art points at the metadata provider, never back at Comicarr.
            assert parts.scheme == "https", url
            continue
        assert _route_for(library.app, url) is not None, "no registered route serves %s" % url
        response = reader.request(url)
        if parts.path == "/opds/stream/" + CORRUPT_ISSUE:
            # Its entry advertises pse:count="0"; asking anyway is a clean error, not a 500.
            assert response.status_code == 400, url
            continue
        assert response.status_code == 200, (reader.app.name, url, response.status_code, response.text[:300])
        if response.headers["content-type"].startswith("application/atom+xml"):
            feeds += 1
            feed = reader.feed(url)
            queue.extend(href for href in feed.all_hrefs() if href not in visited)
    # Root, publishers, three publishers, titles, three series pages + two more
    # for Star Wars, recent pages: the crawl really walked the catalog.
    assert feeds >= 14
    downloaded = {unquote(urlsplit(url).path.rsplit("/", 1)[1]) for url in visited if "/opds/issues/" in url}
    assert downloaded == set(library.downloadable)
