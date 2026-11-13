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

"""An in-process SABnzbd that answers with recorded responses.

Every response body is built from a file in ``tests/fixtures/sabnzbd/<version>/``,
captured from a real SABnzbd by ``tests/fakes/record_sabnzbd.py``. The fake keeps
only the state that a scenario changes (which jobs exist, whether each is
queued, downloading, completed or failed, and where SABnzbd says it put the
files) and writes that state into the recorded envelopes, so the keys and
types Comicarr reads are the ones a real SABnzbd sends.

Install it with ``FakeSabnzbd(...).install(monkeypatch)``. It replaces
``requests.Session.request``, which ``requests.get`` and ``requests.post`` also
go through; a request to any other host fails, so no test reaches the network.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import requests

VERSION = "5.1.3"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sabnzbd" / VERSION
REMOTE_COMPLETE = "/config/Downloads/complete"


def recording(name: str) -> dict:
    """Return one recorded exchange: ``request``, ``status_code`` and ``body``."""
    return json.loads((FIXTURES / ("%s.json" % name)).read_text(encoding="utf-8"))


def _body(name: str):
    return copy.deepcopy(recording(name)["body"])


class NetworkDisabled(RuntimeError):
    """A test tried to reach a host that no fake serves."""


class FakeSabnzbd:
    def __init__(
        self,
        *,
        host: str = "http://sab.test:8080",
        apikey: str = "fake-sab-key",
        category: str = "comics",
        complete_dir: str = REMOTE_COMPLETE,
    ):
        self.host = host
        self.apikey = apikey
        self.category = category
        self.complete_dir = complete_dir
        self.reachable = True
        self.paused = False
        self.jobs: dict[str, dict] = {}
        self.calls: list[dict] = []

    # -- test controls ------------------------------------------------------

    def install(self, monkeypatch) -> FakeSabnzbd:
        real = requests.Session.request
        fake = self

        def request(session, method, url, params=None, data=None, files=None, **kwargs):
            if str(url).startswith(fake.host):
                return fake.handle(method, str(url), params=params, data=data, files=files)
            if urlsplit(str(url)).hostname in ("127.0.0.1", "localhost"):
                return real(session, method, url, params=params, data=data, files=files, **kwargs)
            raise NetworkDisabled("tests may not reach %s" % url)

        monkeypatch.setattr(requests.Session, "request", request)
        return self

    def start(self, nzo_id: str) -> None:
        self.jobs[nzo_id]["state"] = "Downloading"

    def complete(self, nzo_id: str, storage: str) -> None:
        """Finish a job; ``storage`` is the path SABnzbd reports for its file."""
        self.jobs[nzo_id].update(state="Completed", storage=storage)

    def fail(self, nzo_id: str) -> None:
        job = self.jobs[nzo_id]
        job.update(state="Failed", storage="%s/incomplete/%s" % (self.complete_dir.rsplit("/", 1)[0], job["name"]))

    def forget(self, nzo_id: str) -> None:
        """The job leaves both the queue and the history, as if a user deleted it."""
        self.jobs.pop(nzo_id, None)

    def remote_storage(self, nzo_id: str, filename: str) -> str:
        """Where SABnzbd itself would put ``filename`` for this job."""
        job = self.jobs[nzo_id]
        return "%s/%s/%s/%s" % (self.complete_dir, job["category"], job["name"], filename)

    # -- the API ------------------------------------------------------------

    def handle(self, method, url, *, params=None, data=None, files=None):
        if not self.reachable:
            raise requests.ConnectionError("Failed to establish a new connection: [Errno 111] Connection refused")
        query = {**(params or {}), **(data or {})}
        query = {k: v for k, v in query.items() if v is not None}
        self.calls.append({"method": method.upper(), **{k: v for k, v in query.items() if k != "apikey"}})
        mode = query.get("mode")
        if mode != "version" and query.get("apikey") != self.apikey:
            return self._response(recording("wrong_apikey")["body"], status=403)
        handler = getattr(self, "_mode_%s" % mode, None)
        if handler is None:
            raise AssertionError("FakeSabnzbd has no recording for mode=%s" % mode)
        return self._response(handler(query, files or {}))

    def _response(self, body, status=200):
        response = requests.Response()
        response.status_code = status
        if isinstance(body, str):
            response._content = body.encode()
            response.headers["Content-Type"] = "text/plain"
        else:
            response._content = json.dumps(body).encode()
            response.headers["Content-Type"] = "application/json"
        response.encoding = "utf-8"
        response.url = self.host + "/api"
        return response

    def _mode_version(self, query, files):
        return _body("version")

    def _mode_status(self, query, files):
        body = _body("status")
        body["status"]["completedir"] = self.complete_dir
        return body

    def _mode_get_config(self, query, files):
        body = _body("get_config_categories")
        body["config"]["categories"][0].update(name=self.category, dir=self.category)
        return body

    def _mode_addfile(self, query, files):
        upload = files.get("name")
        content = upload[1] if upload else b""
        if b"<nzb" not in content:
            return _body("addfile_rejected")
        nzo_id = str(uuid.uuid4())
        name = query.get("nzbname") or Path(upload[0]).stem
        self.jobs[nzo_id] = {"name": name, "category": query.get("cat") or "*", "state": "Queued", "storage": ""}
        body = _body("addfile_accepted")
        body["nzo_ids"] = [nzo_id]
        return body

    def _selected(self, query, states):
        wanted = query.get("nzo_ids")
        search = (query.get("search") or "").lower()
        category = query.get("category")
        for nzo_id, job in self.jobs.items():
            if job["state"] not in states:
                continue
            if wanted and nzo_id not in str(wanted).split(","):
                continue
            if search and search not in job["name"].lower():
                continue
            if category and job["category"] != category:
                continue
            yield nzo_id, job

    def _mode_queue(self, query, files):
        body = _body("queue_paused")
        template = body["queue"]["slots"][0]
        slots = []
        for index, (nzo_id, job) in enumerate(self._selected(query, ("Queued", "Downloading"))):
            slot = copy.deepcopy(template)
            slot.update(nzo_id=nzo_id, filename=job["name"], cat=job["category"], index=index, status=job["state"])
            slots.append(slot)
        queue = body["queue"]
        queue.update(slots=slots, noofslots=len(slots), noofslots_total=len(slots), paused=self.paused)
        queue["status"] = "Paused" if self.paused else ("Downloading" if slots else "Idle")
        if not slots:
            queue.update(mbleft="0.00", sizeleft="0 B")
        return body

    def _mode_history(self, query, files):
        if query.get("name") == "delete":
            for nzo_id in str(query.get("value", "")).split(","):
                self.jobs.pop(nzo_id, None)
            return _body("history_delete")
        body = _body("history_completed")
        templates = {"Completed": body["history"]["slots"][0], "Failed": _body("history_failed")["history"]["slots"][0]}
        slots = []
        for nzo_id, job in self._selected(query, ("Completed", "Failed")):
            slot = copy.deepcopy(templates[job["state"]])
            slot.update(
                nzo_id=nzo_id,
                name=job["name"],
                nzb_name=job["name"] + ".nzb",
                category=job["category"],
                storage=job["storage"],
                path=job["storage"],
            )
            slots.append(slot)
        body["history"].update(slots=slots, noofslots=len(slots))
        return body
