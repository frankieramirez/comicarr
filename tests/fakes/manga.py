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

"""In-process MangaDex and MyAnimeList that answer with recorded responses.

Every body comes from a file in ``tests/fixtures/mangadex/`` or
``tests/fixtures/myanimelist/``, captured from the real APIs by
``tests/fakes/record_manga.py``. The fakes keep only what a scenario changes
(which series exist and which chapters MangaDex lists for them) and write it
into the recorded envelopes, so the keys and types Comicarr reads are the
ones the real services send.

Install with ``FakeMangaDex().install(monkeypatch)`` and
``FakeMyAnimeList(client_id).install(monkeypatch)``. Each replaces
``requests.Session.request`` and passes any request for another host to
whatever was installed before it, so install them after a download-client
fake (``tests/fakes/sabnzbd.py``). A request no fake serves fails, so no test
reaches the network.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

import requests

from tests.fakes.sabnzbd import NetworkDisabled

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
# The recorded series: Shino-chan wa Jibun no Namae ga Ienai, eleven English
# chapters in one volume, linked to MAL 49017.
MANGADEX_ID = "be7fd0c5-209a-440c-b20d-8b611be1310c"
MAL_ID = "49017"
SERIES = "Shino-chan wa Jibun no Namae ga Ienai"
MISSING_MANGADEX_ID = "00000000-0000-4000-8000-000000000000"

_GENUINE_REQUEST = requests.Session.request


def recording(provider: str, name: str):
    """One recorded exchange (or a list of them): ``request``, ``status_code``, ``body``."""
    return json.loads((FIXTURES / provider / ("%s.json" % name)).read_text(encoding="utf-8"))


def _response(url, body, status=200):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    response.encoding = "utf-8"
    response.url = url
    return response


def _as_list(value):
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


class _Fake:
    host = ""

    def install(self, monkeypatch):
        previous = requests.Session.request
        fake = self

        def request(session, method, url, params=None, **kwargs):
            if urlsplit(str(url)).hostname == fake.host:
                fake.calls.append({"method": method.upper(), "path": urlsplit(str(url)).path, "params": params or {}})
                return fake.handle(method.upper(), str(url), params or {}, kwargs.get("headers") or {})
            if previous is _GENUINE_REQUEST and urlsplit(str(url)).hostname not in ("127.0.0.1", "localhost"):
                raise NetworkDisabled("tests may not reach %s" % url)
            return previous(session, method, url, params=params, **kwargs)

        monkeypatch.setattr(requests.Session, "request", request)
        return self


class FakeMangaDex(_Fake):
    host = "api.mangadex.org"

    def __init__(self):
        self.calls: list[dict] = []
        self.reachable = True
        details = recording("mangadex", "manga_details")["body"]
        chapters = recording("mangadex", "chapters_en")["body"]
        self.manga: dict[str, dict] = {MANGADEX_ID: details["data"]}
        self.chapters: dict[str, list[dict]] = {MANGADEX_ID: chapters["data"]}
        self.aggregates: dict[str, dict] = {MANGADEX_ID: recording("mangadex", "aggregate")["body"]}
        self._searches: dict[str, dict] = {}
        for name in ("search_by_title", "search_for_mal_add"):
            path = FIXTURES / "mangadex" / ("%s.json" % name)
            if path.exists():
                for exchange in _as_list(recording("mangadex", name)):
                    self._searches[exchange["request"]["params"]["title"].casefold()] = exchange["body"]

    # -- test controls ------------------------------------------------------

    def chapter_numbers(self, manga_id=MANGADEX_ID) -> list[str]:
        return [c["attributes"]["chapter"] for c in self.chapters.get(manga_id, [])]

    def drop_chapters_after(self, number: int, manga_id=MANGADEX_ID) -> None:
        """MangaDex lists only chapters up to ``number`` (a series earlier in its run)."""
        self.chapters[manga_id] = [c for c in self.chapters[manga_id] if float(c["attributes"]["chapter"]) <= number]

    # -- the API ------------------------------------------------------------

    def handle(self, method, url, params, headers):
        if not self.reachable:
            raise requests.ConnectionError("Failed to establish a new connection: [Errno 111] Connection refused")
        path = urlsplit(url).path.rstrip("/")
        parts = path.split("/")[1:]
        if parts == ["manga"]:
            return self._search(url, params)
        if parts == ["chapter"]:
            return self._chapters(url, params)
        if len(parts) == 2 and parts[0] == "manga":
            return self._details(url, parts[1])
        if len(parts) == 3 and parts[0] == "manga" and parts[2] == "aggregate":
            body = self.aggregates.get(parts[1])
            if body is None:
                return self._not_found(url, parts[1])
            return _response(url, copy.deepcopy(body))
        raise AssertionError("FakeMangaDex has no recording for %s %s" % (method, path))

    def _not_found(self, url, manga_id):
        exchange = recording("mangadex", "manga_not_found")
        body = copy.deepcopy(exchange["body"])
        body["errors"][0]["detail"] = "Manga `%s` not found." % manga_id
        return _response(url, body, status=exchange["status_code"])

    def _details(self, url, manga_id):
        data = self.manga.get(manga_id)
        if data is None:
            return self._not_found(url, manga_id)
        body = copy.deepcopy(recording("mangadex", "manga_details")["body"])
        body["data"] = copy.deepcopy(data)
        return _response(url, body)

    def _chapters(self, url, params):
        languages = set(_as_list(params.get("translatedLanguage[]")))
        chapters = [
            c
            for c in self.chapters.get(params.get("manga"), [])
            if not languages or c["attributes"]["translatedLanguage"] in languages
        ]
        offset = int(params.get("offset") or 0)
        limit = int(params.get("limit") or 100)
        body = copy.deepcopy(recording("mangadex", "chapters_en")["body"])
        body.update(
            data=copy.deepcopy(chapters[offset : offset + limit]), offset=offset, limit=limit, total=len(chapters)
        )
        return _response(url, body)

    def _search(self, url, params):
        body = self._searches.get(str(params.get("title") or "").casefold())
        if body is None:
            body = copy.deepcopy(recording("mangadex", "search_by_title")["body"])
            body.update(data=[], total=0)
        return _response(url, copy.deepcopy(body))


class FakeMyAnimeList(_Fake):
    host = "api.myanimelist.net"

    def __init__(self, client_id: str = "fake-mal-client"):
        self.client_id = client_id
        self.calls: list[dict] = []
        self.manga: dict[str, dict] = {MAL_ID: recording("myanimelist", "manga_details")["body"]}

    def handle(self, method, url, params, headers):
        if headers.get("X-MAL-CLIENT-ID") != self.client_id:
            exchange = recording("myanimelist", "forbidden")
            return _response(url, copy.deepcopy(exchange["body"]), status=exchange["status_code"])
        parts = urlsplit(url).path.rstrip("/").split("/")[1:]
        if len(parts) == 3 and parts[:2] == ["v2", "manga"]:
            body = self.manga.get(parts[2])
            if body is None:
                exchange = recording("myanimelist", "manga_not_found")
                return _response(url, copy.deepcopy(exchange["body"]), status=exchange["status_code"])
            return _response(url, copy.deepcopy(body))
        raise AssertionError("FakeMyAnimeList has no recording for %s %s" % (method, urlsplit(url).path))
