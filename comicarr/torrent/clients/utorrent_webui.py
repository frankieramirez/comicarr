#  Copyright (C) 2025–2026 Comicarr contributors
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

"""A minimal uTorrent WebUI client, written from the public WebUI API.

The WebUI lives under ``/gui/``. A client first reads a CSRF token from
``/gui/token.html`` (inside ``<div id="token">``), keeps the ``GUID`` cookie
that page sets, and sends ``token=`` with every later request. Requests use
HTTP basic auth and answer with JSON.
"""

import re
from urllib.parse import urljoin

import requests

TIMEOUT_SECONDS = 30
_TOKEN_PATTERN = re.compile(r"<div[^>]*id=['\"]token['\"][^>]*>([^<]+)</div>")


class UTorrentClient:
    def __init__(self, base_url, username, password):
        if not username or not password:
            raise ValueError("uTorrent WebUI needs a username and password")
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.session = requests.Session()
        self.session.auth = (username, password)
        response = self.session.get(urljoin(self.base_url, "token.html"), timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        match = _TOKEN_PATTERN.search(response.text)
        if not match:
            raise ValueError("uTorrent WebUI token page had no token")
        self.token = match.group(1).strip()

    def _request(self, **params):
        response = self.session.get(self.base_url, params={"token": self.token, **params}, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.status_code, response.json()

    def _action(self, action, torrent_hash):
        return self._request(action=action, hash=torrent_hash)

    def list(self):
        return self._request(list=1)

    def getfiles(self, torrent_hash):
        return self._action("getfiles", torrent_hash)

    def start(self, torrent_hash):
        return self._action("start", torrent_hash)

    def stop(self, torrent_hash):
        return self._action("stop", torrent_hash)

    def removedata(self, torrent_hash):
        return self._action("removedata", torrent_hash)
