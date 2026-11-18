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

"""ComicVine client behavior, pinned with recorded responses (#1415).

The HTTP session is faked; each test checks the URL Comicarr asks for and what
it makes of ComicVine's answer.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from xml.dom.minidom import parseString

import pytest

from comicarr.app.core import runtime
from comicarr.app.metadata import cv

VOLUME_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<response><error>OK</error><number_of_total_results>1</number_of_total_results>
<results>
  <aliases>Saga Vol 1
Saga (2012)
</aliases>
  <count_of_issues>2</count_of_issues>
  <deck>Star-crossed lovers on the run.</deck>
  <description>&lt;p&gt;An ongoing series.&lt;/p&gt;</description>
  <first_issue><id>4000-1</id><name>Chapter One</name><issue_number>1</issue_number></first_issue>
  <image><icon_url>https://img.example/icon.jpg</icon_url><small_url>https://img.example/small.jpg</small_url><super_url>https://img.example/super.jpg</super_url><thumb_url>https://img.example/thumb.jpg</thumb_url></image>
  <issues>
    <issue><id>4000-1</id><name>Chapter One</name><issue_number>1</issue_number><site_detail_url>https://cv.example/issue/1</site_detail_url></issue>
    <issue><id>4000-2</id><name>Chapter Two</name><issue_number>2</issue_number><site_detail_url>https://cv.example/issue/2</site_detail_url></issue>
  </issues>
  <name>Saga</name>
  <publisher><id>4010-1</id><name>Image</name></publisher>
  <site_detail_url>https://cv.example/volume/43</site_detail_url>
  <start_year>2012</start_year>
</results></response>
"""


def _issues_page(total, issues):
    body = "".join(
        "<issue><cover_date>%s</cover_date><store_date>%s</store_date><id>%s</id>"
        "<image><small_url>https://img.example/%s-s.jpg</small_url><medium_url>https://img.example/%s-m.jpg</medium_url></image>"
        "<issue_number>%s</issue_number><name>%s</name></issue>" % (cover, store, iid, iid, iid, number, name)
        for iid, number, name, cover, store in issues
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?><response><error>OK</error>'
        "<number_of_total_results>%d</number_of_total_results><results>%s</results></response>" % (total, body)
    ).encode()


class _Session:
    def __init__(self, *bodies):
        self.bodies = list(bodies)
        self.urls = []

    def get(self, url, verify=None, timeout=None):
        self.urls.append(url)
        body = self.bodies.pop(0)
        return SimpleNamespace(
            status_code=200,
            content=body,
            text=body.decode(),
            json=lambda: json.loads(body),
        )


@pytest.fixture
def comicvine(monkeypatch):
    config = SimpleNamespace(
        COMICVINE_API="key123",
        CV_ONLY=True,
        CV_CACHE_ENABLED=False,
        CV_VERIFY=True,
        CV_CACHE_TTL_SEARCH=3600,
        CV_CACHE_TTL_METADATA=86400,
        CV_CACHE_TTL_ARC=86400,
        PROBLEM_DATES=[],
        PROBLEM_DATES_SECONDS=0,
    )
    monkeypatch.setattr(runtime.current(), "config", config)
    monkeypatch.setattr(runtime.current(), "cv_url", "https://cv.example/api/")
    monkeypatch.setattr(runtime.current(), "cv_rate_limiter", MagicMock())
    monkeypatch.setattr(runtime.current(), "cv_timeout", 30)
    monkeypatch.setattr(runtime.current(), "cv_cache", None)
    monkeypatch.setattr(runtime.current(), "backend_status_cv", "unknown")

    def install(*bodies):
        session = _Session(*bodies)
        monkeypatch.setattr(runtime.current(), "cv_session", session)
        return session

    return install


def test_without_an_api_key_nothing_is_requested(comicvine, monkeypatch):
    session = comicvine()
    monkeypatch.setattr(runtime.current().config, "COMICVINE_API", None)

    assert cv.pulldetails("43", "comic") is None
    assert session.urls == []


def test_a_volume_is_fetched_by_its_4050_id(comicvine):
    session = comicvine(VOLUME_XML)

    dom = cv.pulldetails("43", "comic")

    assert session.urls == [
        "https://cv.example/api/volume/4050-43/?api_key=key123&format=xml&field_list=name,count_of_issues,"
        "issues,start_year,site_detail_url,image,publisher,description,first_issue,deck,aliases"
    ]
    assert dom.getElementsByTagName("start_year")[0].firstChild.wholeText == "2012"
    assert runtime.current().backend_status_cv == "up"


def test_a_single_issue_is_fetched_as_json(comicvine):
    session = comicvine(json.dumps({"results": {"id": 4242, "issue_number": "1"}}).encode())

    payload = cv.pulldetails(None, "single_issue", issueid="4242")

    assert session.urls == ["https://cv.example/api/issue/4000-4242?api_key=key123&format=json"]
    assert payload["results"]["id"] == 4242


def test_an_unreachable_comicvine_marks_the_backend_down(comicvine, monkeypatch):
    def boom(*_a, **_k):
        raise ConnectionError("refused")

    monkeypatch.setattr(runtime.current(), "cv_session", SimpleNamespace(get=boom))

    assert cv.pulldetails("43", "comic") is None
    assert runtime.current().backend_status_cv == "down"


def test_get_comic_reads_the_series_from_a_volume(comicvine):
    comicvine(VOLUME_XML)

    comic = cv.getComic("43", "comic")

    assert comic["ComicName"] == "Saga"
    assert comic["ComicPublisher"] == "Image"
    assert comic["ComicYear"] == "2012"
    assert comic["ComicIssues"] == "2"
    assert comic["FirstIssueID"] == "4000-1"
    assert comic["ComicURL"] == "https://cv.example/volume/43"
    assert comic["Aliases"] == "Saga Vol 1##Saga (2012)"
    assert comic["ComicImage"] == "https://img.example/super.jpg"
    assert comic["ComicImageALT"] == "https://img.example/small.jpg"
    assert comic["ComicThumbURL"] == "https://img.example/thumb.jpg"
    assert comic["Issue_List"] == "None"


def test_get_comic_pages_through_a_volumes_issue_list(comicvine):
    first = [("%d" % n, str(n), "Chapter %d" % n, "2012-%02d-01" % (n % 12 + 1), "2012-01-01") for n in range(1, 101)]
    session = comicvine(
        _issues_page(102, first),
        _issues_page(
            102,
            [
                ("101", "101", "Chapter 101", "2011-12-01", "0000-00-00"),
                ("102", "Issue #102", "", "0000-00-00", "2020-01-01"),
            ],
        ),
    )

    result = cv.getComic("43", "issue")

    assert [url.rsplit("&offset=", 1)[1] for url in session.urls] == ["0", "100"]
    assert "filter=volume:43" in session.urls[0]
    issues = result["issuechoice"]
    assert len(issues) == 102
    assert issues[0] == {
        "Comic_ID": "43",
        "Issue_ID": "1",
        "Issue_Number": "1",
        "Issue_Date": "2012-02-01",
        "Store_Date": "2012-01-01",
        "Digital_Date": "0000-00-00",
        "Issue_Name": "Chapter 1",
        "Image": "https://img.example/1-s.jpg",
        "ImageALT": "https://img.example/1-m.jpg",
    }
    assert issues[-1]["Issue_Number"] == "102", "an 'Issue #' prefix is dropped"
    assert result["firstdate"] == "2011-12-01", "a 0000-00-00 cover date never counts as the first"


def test_an_issue_description_with_a_digital_date_sets_it(comicvine):
    page = _issues_page(1, [("7", "7", "Seven", "2015-05-01", "2015-04-01")]).replace(
        b"<issue_number>",
        b"<description>Released digitally Mar 4, 2015 before the print edition.</description><issue_number>",
    )
    comicvine(page)

    result = cv.getComic("43", "issue")

    assert result["issuechoice"][0]["Digital_Date"] == "2015-03-04"


def test_get_comic_reports_a_failed_issue_fetch(comicvine, monkeypatch):
    comicvine()
    monkeypatch.setattr(runtime.current().config, "COMICVINE_API", None)

    assert cv.getComic("43", "issue") is False


def test_a_volume_issue_list_is_read_when_cv_only_is_off(comicvine, monkeypatch):
    monkeypatch.setattr(runtime.current().config, "CV_ONLY", False)
    dom = parseString(VOLUME_XML)

    issues, firstdate = cv.GetIssuesInfo("43", dom)

    # Inherited behavior: ids are read by position from the end of the issue count.
    assert [issue["Issue_ID"] for issue in issues] == ["4000-1", "4000-1"]
    assert firstdate == "2099-00-00"
