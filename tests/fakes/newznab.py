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

"""A newznab indexer that serves one NZB download.

RSS scenarios read search results from Comicarr's own ``rssdb`` table, so the
indexer only has to answer the NZB download ``search.py`` makes after a match.
It answers the way the newznab API documents a ``t=get`` download: the NZB as
the body and its name in ``X-DNZB-Name``, which ``search.py`` requires. Install
it after the other fakes; other hosts pass through to them.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import requests

from tests.fakes.manga import _GENUINE_REQUEST
from tests.fakes.nntp import nzb_document
from tests.fakes.sabnzbd import NetworkDisabled


class FakeNewznab:
    host = "indexer.test"

    def __init__(self, name="Indexer", apikey="fake-indexer-key", category="7030"):
        self.name = name
        self.apikey = apikey
        self.category = category
        self.releases: dict[str, tuple[str, str]] = {}
        self.calls: list[dict] = []

    @property
    def url(self) -> str:
        return "https://%s" % self.host

    def config_entry(self) -> list:
        """The ``EXTRA_NEWZNABS`` row: name, host, verify, apikey, uid, enabled."""
        return [self.name, self.url, "1", self.apikey, self.category, "1"]

    def publish(self, release_id: str, title: str, filename: str) -> str:
        """Offer one release; return the download link an RSS row carries."""
        self.releases[release_id] = (title, filename)
        return "%s/api?t=get&id=%s" % (self.url, release_id)

    def install(self, monkeypatch) -> FakeNewznab:
        previous = requests.Session.request
        fake = self

        def request(session, method, url, params=None, **kwargs):
            if urlsplit(str(url)).hostname == fake.host:
                return fake.handle(str(url), params or {})
            if previous is _GENUINE_REQUEST:
                raise NetworkDisabled("tests may not reach %s" % url)
            return previous(session, method, url, params=params, **kwargs)

        monkeypatch.setattr(requests.Session, "request", request)
        return self

    def handle(self, url, params):
        query = dict(part.split("=", 1) for part in urlsplit(url).query.split("&") if "=" in part)
        query.update({k: v for k, v in params.items() if v is not None})
        self.calls.append(query)
        response = requests.Response()
        response.url = url
        release = self.releases.get(query.get("id"))
        if query.get("t") != "get" or release is None:
            response.status_code = 404
            response._content = b"<error code='300' description='No such item'/>"
            return response
        title, filename = release
        response.status_code = 200
        response._content = nzb_document([(filename, "%s@indexer.invalid" % query["id"], 4096)])
        response.headers["Content-Type"] = "application/x-nzb"
        response.headers["X-DNZB-Name"] = title
        # search.py streams the download with iter_content().
        response._content_consumed = True
        return response
