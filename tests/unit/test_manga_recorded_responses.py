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

"""Comicarr's MangaDex and MyAnimeList clients read what the real services sent.

Each test drives ``comicarr/mangadex.py`` or ``comicarr/myanimelist.py``
against ``tests/fakes/manga.py``, whose answers are responses recorded from
the live APIs (``tests/fixtures/mangadex/``, ``tests/fixtures/myanimelist/``).
"""

from types import SimpleNamespace

import pytest

import comicarr
from comicarr import mangadex, myanimelist
from tests.fakes import manga as fake
from tests.fakes.sabnzbd import NetworkDisabled


@pytest.fixture
def apis(monkeypatch):
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            CV_USER_AGENT="Comicarr/test",
            MANGADEX_ENABLED=True,
            MANGADEX_CONTENT_RATING="safe,suggestive",
            MANGADEX_LANGUAGES="en",
            MAL_ENABLED=True,
            MAL_CLIENT_ID="fake-mal-client",
        ),
        raising=False,
    )
    monkeypatch.setattr(mangadex, "_rate_limit", lambda: None)
    monkeypatch.setattr(myanimelist, "_rate_limit", lambda: None)
    mangadex.clear_cache()
    md = fake.FakeMangaDex().install(monkeypatch)
    mal = fake.FakeMyAnimeList("fake-mal-client").install(monkeypatch)
    yield SimpleNamespace(mangadex=md, mal=mal)
    mangadex.clear_cache()


def test_recorded_requests_match_what_comicarr_sends(apis):
    """The fixtures were captured from these exact calls, so the request shapes still agree."""
    mangadex.get_manga_details(fake.MANGADEX_ID)
    mangadex.get_manga_chapters(fake.MANGADEX_ID, languages=["en"])
    for name, call in zip(("manga_details", "chapters_en"), apis.mangadex.calls):
        recorded = fake.recording("mangadex", name)["request"]
        assert call["path"] == recorded["path"]
        assert set(call["params"]) == set(recorded["params"])


def test_mangadex_details_read_the_mal_link_and_chapter_counts(apis):
    details = mangadex.get_manga_details("md-" + fake.MANGADEX_ID)

    assert details["name"] == "Shino-chan Can't Say Her Name"
    assert details["mal_id"] == fake.MAL_ID
    assert details["last_chapter"] == "11"
    assert details["cover_url"].startswith("https://uploads.mangadex.org/covers/%s/" % fake.MANGADEX_ID)


def test_all_chapters_come_back_once_each_in_order(apis):
    chapters = mangadex.get_all_chapters(fake.MANGADEX_ID)

    assert [c["chapter"] for c in chapters] == [str(n) for n in range(1, 12)]
    assert {c["volume"] for c in chapters} == {"1"}
    assert not any(c.get("unavailable") for c in chapters)


def test_aggregate_counts_every_chapter(apis):
    assert mangadex.get_total_chapter_count(fake.MANGADEX_ID) == 11


def test_missing_mangadex_series_is_none_not_an_exception(apis):
    assert mangadex.get_manga_details(fake.MISSING_MANGADEX_ID) is None


def test_mal_id_resolves_to_the_mangadex_series_by_its_link(apis):
    found = mangadex.find_by_mal_id(
        fake.MAL_ID, title_hint="Shino-chan wa Jibun no Namae ga Ienai", allow_title_match=False
    )

    assert found == fake.MANGADEX_ID


def test_unknown_title_finds_no_mangadex_series(apis):
    assert mangadex.find_by_mal_id(fake.MAL_ID, title_hint="No Such Manga", allow_title_match=True) is None


def test_mal_details_map_to_the_mangadex_shape(apis):
    details = myanimelist.get_manga_details("mal-" + fake.MAL_ID)

    assert details["id"] == "mal-" + fake.MAL_ID
    assert details["mal_id"] == fake.MAL_ID
    assert details["name"] == "Shino-chan wa Jibun no Namae ga Ienai"
    assert "Shino Can't Say Her Name" in details["alt_titles"]
    assert details["status"] == "completed"
    assert details["last_chapter"] == "11"
    assert details["year"] == "2011"


def test_missing_mal_series_is_none(apis):
    assert myanimelist.get_manga_details("mal-999999999") is None


def test_rejected_mal_client_id_is_none(apis):
    apis.mal.client_id = "the-real-one"

    assert myanimelist.get_manga_details("mal-" + fake.MAL_ID) is None


def test_fakes_refuse_any_other_host(apis):
    import requests

    with pytest.raises(NetworkDisabled):
        requests.get("https://api.comicvine.gamespot.com/api/issues/")
