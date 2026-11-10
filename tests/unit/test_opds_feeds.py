#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""OPDS feeds a reader app can walk: auth challenge, route links, paging (#1148)."""

import io
import zipfile
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import comicarr
from comicarr import db
from comicarr.app.series import service as series_service
from comicarr.tables import comics, issues, metadata

ATOM = "{http://www.w3.org/2005/Atom}"
AUTH = ("reader", "secret")
PAGE_SIZE = 2


def _png():
    # Smallest valid PNG: one transparent pixel.
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


@pytest.fixture
def opds(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    metadata.create_all(engine)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(series_service, "_havetotals_cache", None)

    library = tmp_path / "comics"
    series_dir = library / "Star Wars (1977)"
    series_dir.mkdir(parents=True)
    grabbag = tmp_path / "grabbag"
    grabbag.mkdir()
    _cbz(grabbag / "One Shot.cbz")

    config = SimpleNamespace(
        OPDS_ENABLE=True,
        OPDS_PAGESIZE=PAGE_SIZE,
        OPDS_METAINFO=False,
        OPDS_USERNAME=AUTH[0],
        OPDS_PASSWORD=AUTH[1],
        HTTP_USERNAME=None,
        HTTP_PASSWORD=None,
        HTTP_ROOT="/",
        ANNUALS_ON=False,
        DESTINATION_DIR=str(library),
        COMIC_DIR=str(library),
        GRABBAG_DIR=str(grabbag),
        STORYARC_LOCATION=None,
    )
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)

    with engine.begin() as conn:
        for comic_id, name, publisher in (("2914", "Star Wars", "DC & Vertigo"), ("5000", "Other", "Image")):
            conn.execute(
                comics.insert(),
                {
                    "ComicID": comic_id,
                    "ComicName": name,
                    "ComicSortName": name,
                    "ComicYear": "1977",
                    "ComicPublisher": publisher,
                    "ComicLocation": str(series_dir),
                    "LatestIssue": "3",
                    "intLatestIssue": 3000,
                    "LatestDate": "1977-09-01",
                    "ComicPublished": "1977 - 1986",
                    "LastUpdated": "2026-11-01",
                    "Have": 3,
                    "Total": 3,
                    "Status": "Active",
                },
            )
        for n in (1, 2, 3):
            filename = "Star Wars 00%d.cbz" % n
            _cbz(series_dir / filename)
            conn.execute(
                issues.insert(),
                {
                    "IssueID": "i%d" % n,
                    "ComicID": "2914",
                    "ComicName": "Star Wars",
                    "Issue_Number": str(n),
                    "Int_IssueNumber": n * 1000,
                    "IssueName": "Part %d" % n,
                    "IssueDate": "1977-0%d-01" % n,
                    "ReleaseDate": "1977-0%d-01" % n,
                    "Location": filename,
                    "Status": "Downloaded",
                },
            )

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from comicarr.app.core.context import AppContext, get_context
    from comicarr.app.opds.router import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_context] = lambda: AppContext(config=config)
    with TestClient(app) as client:
        yield client


def _feed(client, href):
    response = client.get(href, auth=AUTH)
    assert response.status_code == 200, (href, response.status_code, response.text[:300])
    return response.text, ElementTree.fromstring(response.content)


def _links(element, rel=None):
    return [link.get("href") for link in element.findall(ATOM + "link") if rel is None or link.get("rel") == rel]


def _entry_href(feed, title_prefix):
    for entry in feed.findall(ATOM + "entry"):
        if entry.findtext(ATOM + "title").startswith(title_prefix):
            return _links(entry)[0]
    raise AssertionError("no entry titled %r" % title_prefix)


def test_unauthenticated_request_gets_basic_challenge(opds):
    for auth in (None, ("reader", "wrong")):
        response = opds.get("/opds/", auth=auth)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"].startswith("Basic ")


def test_reader_walks_root_to_issue_file_through_registered_routes(opds):
    raw, root = _feed(opds, "/opds/")
    assert "cmd=" not in raw
    assert "&amp;amp;" not in raw

    raw, publishers = _feed(opds, _entry_href(root, "Publishers"))
    publisher_href = _entry_href(publishers, "DC & Vertigo")
    assert publisher_href == "/opds/publishers/DC%20%26%20Vertigo"

    _, publisher = _feed(opds, publisher_href)
    assert publisher.findtext(ATOM + "id") == "publisher:DC & Vertigo"
    comic_href = _entry_href(publisher, "Star Wars")

    raw, comic = _feed(opds, comic_href)
    assert "cmd=" not in raw and "&amp;amp;" not in raw
    issue_entry = comic.findall(ATOM + "entry")[0]
    acquisition = [
        link.get("href")
        for link in issue_entry.findall(ATOM + "link")
        if link.get("rel") == "http://opds-spec.org/acquisition"
    ][0]
    download = opds.get(acquisition, auth=AUTH)
    assert download.status_code == 200
    assert download.content[:2] == b"PK"

    stream = [
        link.get("href")
        for link in issue_entry.findall(ATOM + "link")
        if link.get("rel") == "http://vaemendis.net/opds-pse/stream"
    ][0]
    assert parse_qs(urlsplit(stream).query)["page"] == ["{pageNumber}"]
    page = opds.get(stream.replace("{pageNumber}", "0"), auth=AUTH)
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("image/")


@pytest.mark.parametrize("entry_title", ["All Titles", "Recent Additions", "One-Offs"])
def test_root_navigation_entries_resolve(opds, entry_title):
    _, root = _feed(opds, "/opds/")
    _, feed = _feed(opds, _entry_href(root, entry_title))
    assert feed.findtext(ATOM + "title").startswith("Comicarr OPDS - ")


def test_comic_feed_pages_with_next_and_previous_links(opds):
    _, first = _feed(opds, "/opds/comics/2914")
    assert len(first.findall(ATOM + "entry")) == PAGE_SIZE
    (next_href,) = _links(first, "next")
    assert next_href == "/opds/comics/2914?index=%d" % PAGE_SIZE

    _, second = _feed(opds, next_href)
    assert len(second.findall(ATOM + "entry")) == 1
    assert _links(second, "next") == []
    assert _links(second, "previous") == ["/opds/comics/2914?index=0"]


def test_all_titles_paging_links_resolve(opds, monkeypatch):
    monkeypatch.setattr(comicarr.CONFIG, "OPDS_PAGESIZE", 1)
    _, first = _feed(opds, "/opds/titles")
    (next_href,) = _links(first, "next")
    _, second = _feed(opds, next_href)
    assert _links(second, "previous") == ["/opds/titles?index=0"]


def test_one_off_entry_downloads_from_grabbag(opds):
    _, root = _feed(opds, "/opds/")
    _, oneoffs = _feed(opds, _entry_href(root, "One-Offs"))
    href = [link.get("href") for link in oneoffs.find(ATOM + "entry").findall(ATOM + "link")][0]
    assert href == "/opds/oneoffs/One%20Shot.cbz"
    assert opds.get(href, auth=AUTH).content[:2] == b"PK"
    assert opds.get("/opds/oneoffs/..%2Fcomics", auth=AUTH).status_code in (400, 404)


def test_links_keep_http_root_prefix(opds, monkeypatch):
    monkeypatch.setattr(comicarr.CONFIG, "HTTP_ROOT", "/comicarr/")
    raw, _ = _feed(opds, "/opds/")
    assert 'href="/comicarr/opds/publishers"' in raw
