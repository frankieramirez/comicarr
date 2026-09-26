#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""GetComics WP REST API search (issue #904)."""

from types import SimpleNamespace

import pytest

import comicarr
from comicarr import getcomics, search


def _post(post_id, title, link, date="2026-09-23T10:00:00", size="47 MB", year="2026"):
    return {
        "id": post_id,
        "date": date,
        "link": link,
        "title": {"rendered": title},
        "excerpt": {
            "rendered": (
                '<p style="text-align: center;"><strong>Year : </strong>%s | '
                "<strong>Size :</strong> %s</p>" % (year, size)
            )
        },
    }


class _Response:
    def __init__(self, posts, total_pages=1, status=200):
        self.status_code = status
        self.headers = {"X-WP-TotalPages": str(total_pages)}
        self._posts = posts
        self.text = ""

    def json(self):
        return self._posts


class _Session:
    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def get(self, url, params=None, **kwargs):
        self.requests.append({"url": url, "params": dict(params)})
        return self.pages[params["page"]]


def _source(session):
    gc = getcomics.GC.__new__(getcomics.GC)
    gc.url = "https://getcomics.org"
    gc.headers = {"User-Agent": "test"}
    gc.session = session
    gc.query = {"comicname": "Absolute Batman", "issue": "24", "year": "2026"}
    gc.provider_stat = {"lastrun": 0, "hits": 0}
    gc.pack_receipts = [
        "+ TPBs",
        "+TPBs",
        "+ TPB",
        "+TPB",
        "TPB",
        "+ Deluxe Books",
        "+ Annuals",
        "+Annuals",
        " & ",
    ]
    return gc


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(DDL_QUERY_DELAY=0))
    monkeypatch.setattr(search, "last_run_check", lambda *args, **kwargs: None)


def test_wp_posts_yield_parsed_results():
    session = _Session(
        {
            1: _Response(
                [
                    _post(12345, "Absolute Batman #24 (2026)", "https://getcomics.org/absolute-batman-24-2026/"),
                    _post(12340, "Absolute Batman #23 (2026)", "https://getcomics.org/absolute-batman-23-2026/"),
                ],
                total_pages=1,
            )
        }
    )

    results = list(_source(session).perform_search_queries("Absolute Batman"))

    request = session.requests[0]
    assert request["url"] == "https://getcomics.org/wp-json/wp/v2/posts"
    assert request["params"]["search"] == "Absolute Batman"
    assert request["params"]["orderby"] == "relevance"
    assert request["params"]["page"] == 1

    assert len(results) == 2
    first = next(r for r in results if r["id"] == "12345")
    assert first["title"] == "Absolute Batman #24 (2026)"
    assert first["link"] == "https://getcomics.org/absolute-batman-24-2026/"
    assert first["size"] == "47M"
    assert first["year"] == "2026"
    assert first["pack"] is False
    assert first["site"] == "DDL(GetComics)"


def test_pages_follow_x_wp_totalpages_and_dedupe():
    session = _Session(
        {
            1: _Response(
                [_post(1, "Absolute Batman #24 (2026)", "https://getcomics.org/absolute-batman-24-2026/")],
                total_pages=2,
            ),
            2: _Response(
                [
                    _post(1, "Absolute Batman #24 (2026)", "https://getcomics.org/absolute-batman-24-2026/"),
                    _post(2, "Absolute Batman #23 (2026)", "https://getcomics.org/absolute-batman-23-2026/"),
                ],
                total_pages=2,
            ),
        }
    )

    results = list(_source(session).perform_search_queries("Absolute Batman"))

    assert [r["params"]["page"] for r in session.requests] == [1, 2]
    assert [r["id"] for r in results] == ["1", "2"]


def test_non_200_stops_without_results():
    session = _Session({1: _Response([], status=503)})

    assert list(_source(session).perform_search_queries("Absolute Batman")) == []
    assert len(session.requests) == 1


def test_posts_without_year_size_block_are_skipped():
    post = _post(7, "Absolute Batman #24 (2026)", "https://getcomics.org/absolute-batman-24-2026/")
    post["excerpt"]["rendered"] = "<p>no metadata block</p>"
    session = _Session({1: _Response([post], total_pages=1)})

    assert list(_source(session).perform_search_queries("Absolute Batman")) == []
