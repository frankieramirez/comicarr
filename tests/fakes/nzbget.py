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

"""An in-process NZBGet that answers with recorded responses.

Every queue entry, history entry and config listing is built from a file in
``tests/fixtures/nzbget/<version>/``, captured from a real NZBGet by
``tests/fakes/record_nzbget.py``. The fake keeps only what a scenario changes
(which jobs exist, whether each is queued, downloading or finished, and how it
finished) and writes that into the recorded entries, so the fields and types
Comicarr reads are the ones a real NZBGet sends.

Install it with ``FakeNzbget(...).install(monkeypatch)``. It answers XML-RPC
through ``xmlrpc.client.Transport.request``, re-marshalling every result so
values cross the same encoding a real server's do, and answers the connection
probe's ``/jsonrpc/version`` through ``requests.Session.request``. A request to
any other host fails, so no test reaches the network.
"""

from __future__ import annotations

import base64
import copy
import json
import xmlrpc.client
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import requests

from tests.fakes.sabnzbd import NetworkDisabled

VERSION = "26.3"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nzbget" / VERSION
REMOTE_MAIN = "/config"

# How NZBGet 26.3 reports each way a job ends. Every pair was recorded.
OUTCOMES = {
    "success": "SUCCESS/HEALTH",
    "health": "FAILURE/HEALTH",
    "unpack": "FAILURE/UNPACK",
    "par": "FAILURE/PAR",
    "scan": "FAILURE/SCAN",
}


def recording(name: str) -> dict:
    """Return one recorded exchange: ``method``, ``params`` and ``result`` (or the error)."""
    return json.loads((FIXTURES / ("%s.json" % name)).read_text(encoding="utf-8"))


def _history_template(status: str) -> dict:
    for entry in recording("history")["result"]:
        if entry["Status"] == status:
            return copy.deepcopy(entry)
    raise AssertionError("no recorded history entry has Status %s" % status)


class FakeNzbget:
    def __init__(
        self,
        *,
        host: str = "http://nzbget.test",
        port: str = "6789",
        username: str = "nzbget",
        password: str = "fake-nzbget-pass",
        category: str = "comics",
        main_dir: str = REMOTE_MAIN,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.category = category
        self.main_dir = main_dir
        self.reachable = True
        self.jobs: dict[int, dict] = {}
        self.calls: list[dict] = []
        self._next_id = 1

    @property
    def netloc(self) -> str:
        return "%s:%s" % (urlsplit(self.host).hostname, self.port)

    # -- test controls ------------------------------------------------------

    def install(self, monkeypatch) -> FakeNzbget:
        real_request = requests.Session.request
        fake = self

        def transport_request(transport, host, handler, request_body, verbose=False):
            auth, _, hostport = host.rpartition("@")
            if hostport != fake.netloc:
                raise NetworkDisabled("tests may not reach %s%s" % (hostport, handler))
            return fake.handle_xmlrpc(auth, handler, request_body)

        def session_request(session, method, url, **kwargs):
            parts = urlsplit(str(url))
            if parts.netloc.rpartition("@")[2] == fake.netloc:
                return fake.handle_http(method, parts.path, kwargs.get("auth"))
            if parts.hostname in ("127.0.0.1", "localhost"):
                return real_request(session, method, url, **kwargs)
            raise NetworkDisabled("tests may not reach %s" % url)

        monkeypatch.setattr(xmlrpc.client.Transport, "request", transport_request)
        monkeypatch.setattr(requests.Session, "request", session_request)
        return self

    def start(self, nzbid: int, *, then: str = "success", polls: int = 1) -> None:
        """The job is downloading; after ``polls`` more queue reads it ends as ``then``."""
        self.jobs[nzbid].update(state="DOWNLOADING", then=then, polls=polls)

    def complete(self, nzbid: int) -> None:
        self._finish(nzbid, "success")

    def fail(self, nzbid: int, how: str) -> None:
        """End the job the way NZBGet does on a ``health``, ``unpack`` or ``par`` failure."""
        self._finish(nzbid, how)

    def forget(self, nzbid: int) -> None:
        """The job leaves both the queue and the history, as if a user deleted it."""
        self.jobs.pop(nzbid, None)

    def remote_dest(self, nzbid: int) -> str:
        """Where NZBGet itself puts a finished job: ``DestDir/<category>/<name>``."""
        job = self.jobs[nzbid]
        return "%s/completed/%s/%s" % (self.main_dir, job["category"], job["name"])

    def _finish(self, nzbid: int, how: str) -> None:
        job = self.jobs[nzbid]
        job["state"] = OUTCOMES[how]

    # -- the API ------------------------------------------------------------

    def handle_xmlrpc(self, auth: str, handler: str, request_body: bytes):
        if not self.reachable:
            raise ConnectionRefusedError(111, "Connection refused")
        params, method = xmlrpc.client.loads(request_body)
        self.calls.append({"method": method, "params": list(params)})
        # NZBGet takes credentials in the URL's user info or, as nzbget.py
        # sends them, as the path segment before /xmlrpc.
        path_auth = handler.rsplit("/xmlrpc", 1)[0].strip("/")
        if (auth or path_auth) != "%s:%s" % (self.username, self.password):
            error = recording("wrong_password")["protocol_error"]
            raise xmlrpc.client.ProtocolError(self.netloc + handler, error["errcode"], error["errmsg"], {})
        answer = getattr(self, "_rpc_%s" % method, None)
        if answer is None:
            raise AssertionError("FakeNzbget has no recording for %s" % method)
        result = answer(*params)
        # Marshal and unmarshal so the caller sees what the wire would carry.
        return xmlrpc.client.loads(xmlrpc.client.dumps((result,), methodresponse=True))[0]

    def handle_http(self, method: str, path: str, auth):
        if not self.reachable:
            raise requests.ConnectionError("Failed to establish a new connection: [Errno 111] Connection refused")
        self.calls.append({"method": "HTTP %s" % method.upper(), "path": path})
        if path.rstrip("/").endswith("/jsonrpc/version") and tuple(auth or ()) == (self.username, self.password):
            recorded = recording("http_version")
        elif path.rstrip("/").endswith("/jsonrpc/version"):
            recorded = recording("http_version_unauthorized")
        else:
            raise AssertionError("FakeNzbget has no recording for %s" % path)
        response = requests.Response()
        response.status_code = recorded["status_code"]
        body = recorded["body"]
        response._content = (body if isinstance(body, str) else json.dumps(body)).encode()
        response.encoding = "utf-8"
        response.url = self.host + path
        return response

    def _rpc_version(self):
        return recording("version")["result"]

    def _rpc_config(self):
        options = recording("config")["result"]
        for option in options:
            if option["Name"] == "MainDir":
                option["Value"] = self.main_dir
            elif option["Value"].startswith(REMOTE_MAIN + "/"):
                option["Value"] = self.main_dir + option["Value"][len(REMOTE_MAIN) :]
            elif option["Name"] == "Category1.Name":
                option["Value"] = self.category
        return options

    def _rpc_append(self, filename, content, category, priority, addtop, addpaused, dupekey, dupescore, dupemode):
        nzbid = self._next_id
        self._next_id += 1
        name = PurePosixPath(filename).name
        name = name[:-4] if name.lower().endswith(".nzb") else name
        job = {"name": name, "filename": filename, "category": category, "priority": priority, "state": "QUEUED"}
        # NZBGet accepts any upload with a positive NZBID; one it cannot parse
        # goes straight to history as FAILURE/SCAN (recorded).
        if b"<nzb" not in base64.b64decode(content):
            job["state"] = OUTCOMES["scan"]
        self.jobs[nzbid] = job
        return nzbid

    def _rpc_listgroups(self, *_number_of_log_entries):
        template = recording("listgroups_downloading")["result"][0]
        groups = []
        for nzbid, job in list(self.jobs.items()):
            if job["state"] not in ("QUEUED", "DOWNLOADING"):
                continue
            if job["state"] == "DOWNLOADING":
                if job["polls"] <= 0:
                    self._finish(nzbid, job["then"])
                    continue
                job["polls"] -= 1
            entry = copy.deepcopy(template)
            entry.update(
                NZBID=nzbid,
                FirstID=nzbid,
                LastID=nzbid,
                NZBName=job["name"],
                NZBNicename=job["name"],
                NZBFilename=job["filename"],
                Category=job["category"],
                Status=job["state"],
                DestDir="%s/intermediate/%s.#%s" % (self.main_dir, job["name"], nzbid),
            )
            groups.append(entry)
        return groups

    def _rpc_history(self, hidden=False):
        entries = []
        for nzbid, job in self.jobs.items():
            if job["state"] in ("QUEUED", "DOWNLOADING"):
                continue
            entry = _history_template(job["state"])
            entry.update(NZBID=nzbid, ID=nzbid, Name=job["name"], NZBName=job["name"], Category=job["category"])
            entry["NZBFilename"] = job["filename"]
            if job["state"] == OUTCOMES["success"]:
                entry["DestDir"] = self.remote_dest(nzbid)
            else:
                entry["DestDir"] = "%s/intermediate/%s.#%s" % (self.main_dir, job["name"], nzbid)
            if entry.get("FinalDir"):
                entry["FinalDir"] = self.remote_dest(nzbid)
            entries.append(entry)
        return sorted(entries, key=lambda entry: -entry["NZBID"])

    def _rpc_editqueue(self, command, param, ids):
        ids = ids if isinstance(ids, list) else [ids]
        if command in ("HistoryDelete", "HistoryFinalDelete", "GroupFinalDelete"):
            for nzbid in ids:
                self.jobs.pop(nzbid, None)
            return recording("editqueue_history_delete")["result"]
        raise AssertionError("FakeNzbget has no recording for editqueue %s" % command)

    def _rpc_status(self):
        return recording("status_paused")["result"]
