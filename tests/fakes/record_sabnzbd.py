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

"""Record the SABnzbd API responses the scenario tests replay.

Run against a disposable SABnzbd (it deletes the instance's history):

    docker run -d --name sab -p 18080:8080 linuxserver/sabnzbd:<tag>
    python -m tests.fakes.record_sabnzbd --url http://127.0.0.1:18080 \\
        --apikey <key from sabnzbd.ini> --nntp-host 172.17.0.1

The recorder starts ``tests.fakes.nntp`` on this machine and points SABnzbd at
it, so one job completes and one fails on missing articles without touching
Usenet. Responses are scrubbed and written to
``tests/fixtures/sabnzbd/<version>/``. ``capture()`` is shared with the
nightly contract job, which compares fresh responses against these files.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import time
import zipfile
from pathlib import Path

import requests

from tests.fakes.nntp import RecordingNNTPServer, nzb_document

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sabnzbd"
CATEGORY = "comics"
GOOD = "Absolute.Batman.001.2024"
BAD = "Absolute.Batman.002.2024"
SLOW = "Absolute.Batman.003.2024"
UNKNOWN_NZO = "SABnzbd_nzo_unknown"
# Values that identify the recording machine. Everything else is kept as sent.
_SCRUB_KEYS = {
    "apikey",
    "api_key",
    "nzb_key",
    "username",
    "password",
    "host",
    "localipv4",
    "publicipv4",
    "ipv6",
    "dnslookup",
    "cpumodel",
    "pystone",
    "loadavg",
    "folders",
}


def sample_comic() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("001.jpg", b"\xff\xd8recorded page" * 400)
    return buffer.getvalue()


class _Client:
    def __init__(self, url: str, apikey: str):
        self.url = url.rstrip("/") + "/api"
        self.apikey = apikey
        self.session = requests.Session()
        self.session.trust_env = False

    def call(self, params: dict, *, apikey: str | None = None, files=None) -> dict:
        sent = {"output": "json", **params}
        query = {**sent, "apikey": self.apikey if apikey is None else apikey}
        if files:
            response = self.session.post(self.url, params=query, files=files, timeout=30)
        else:
            response = self.session.get(self.url, params=query, timeout=30)
        try:
            body = response.json()
        except ValueError:
            body = response.text
        return {"request": sent, "status_code": response.status_code, "body": body}


def _add(client: _Client, name: str, document: bytes) -> dict:
    return client.call(
        {"mode": "addfile", "cat": CATEGORY, "nzbname": name},
        files={"name": (name + ".nzb", document, "application/x-nzb")},
    )


def _history(client: _Client, **params) -> dict:
    return client.call({"mode": "history", **params})


def _wait_for(client: _Client, nzo_id: str, statuses: tuple[str, ...], timeout: float = 90.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        recorded = _history(client, nzo_ids=nzo_id)
        slots = recorded["body"]["history"]["slots"]
        if slots and slots[0]["status"] in statuses:
            return recorded
        time.sleep(1)
    raise TimeoutError("%s never reached %s" % (nzo_id, statuses))


def capture(url: str, apikey: str, nntp_host: str, nntp_port: int = 1119) -> dict[str, dict]:
    """Drive a fresh SABnzbd through every recorded call; return name -> recording."""
    nntp = RecordingNNTPServer(nntp_port)
    client = _Client(url, apikey)
    out: dict[str, dict] = {}
    try:
        client.call({"mode": "history", "name": "delete", "value": "all", "del_files": 1})
        client.call(
            {
                "mode": "set_config",
                "section": "servers",
                "keyword": "recording",
                "name": "recording",
                "host": nntp_host,
                "port": nntp_port,
                "connections": 2,
                "ssl": 0,
                "enable": 1,
                "username": "recorder",
                "password": "recorder",
            }
        )
        client.call(
            {"mode": "set_config", "section": "categories", "keyword": CATEGORY, "name": CATEGORY, "dir": CATEGORY}
        )

        out["version"] = client.call({"mode": "version"})
        out["wrong_apikey"] = client.call({"mode": "queue"}, apikey="0" * 32)
        out["status"] = client.call({"mode": "status"})
        out["get_config_categories"] = client.call({"mode": "get_config", "section": "categories", "keyword": CATEGORY})

        comic = sample_comic()
        good_size = nntp.add("good@recording.invalid", comic, GOOD.replace(".", " ") + ".cbz")
        slow_size = nntp.add("slow@recording.invalid", comic, SLOW.replace(".", " ") + ".cbz")

        client.call({"mode": "pause"})
        out["addfile_accepted"] = _add(
            client, GOOD, nzb_document([(GOOD + ".cbz", "good@recording.invalid", good_size)])
        )
        good_id = out["addfile_accepted"]["body"]["nzo_ids"][0]
        out["queue_paused"] = client.call({"mode": "queue", "start": 0, "limit": 5})
        out["queue_paused_job"] = client.call({"mode": "queue", "nzo_ids": good_id})
        client.call({"mode": "resume"})
        out["history_completed"] = _wait_for(client, good_id, ("Completed",))
        out["history_completed_search"] = _history(client, search=GOOD, limit=200)
        out["history_completed_category"] = _history(client, nzo_ids=good_id, category=CATEGORY)
        out["queue_job_gone"] = client.call({"mode": "queue", "nzo_ids": good_id})

        bad = _add(client, BAD, nzb_document([(BAD + ".cbz", "missing@recording.invalid", 60000)]))
        out["history_failed"] = _wait_for(client, bad["body"]["nzo_ids"][0], ("Failed",))

        nntp.delay = 4.0
        slow = _add(client, SLOW, nzb_document([(SLOW + ".cbz", "slow@recording.invalid", slow_size)]))
        slow_id = slow["body"]["nzo_ids"][0]
        time.sleep(1.5)
        out["queue_downloading_job"] = client.call({"mode": "queue", "nzo_ids": slow_id})
        _wait_for(client, slow_id, ("Completed",))
        nntp.delay = 0.0

        out["history_unknown"] = _history(client, nzo_ids=UNKNOWN_NZO)
        out["addfile_rejected"] = _add(client, "Not.An.Nzb", b"this is not an nzb")
        out["history_delete"] = client.call({"mode": "history", "name": "delete", "value": good_id, "del_files": 0})
    finally:
        nntp.shutdown()
        nntp.server_close()
    return scrub(out)


def scrub(value):
    if isinstance(value, dict):
        return {
            k: ("<scrubbed>" if k in _SCRUB_KEYS and v not in (None, "", [], {}) else scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        return re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "192.0.2.1", value)
    return value


def write(recordings: dict[str, dict], root: Path = FIXTURES) -> Path:
    version = recordings["version"]["body"]["version"]
    target = root / version
    target.mkdir(parents=True, exist_ok=True)
    for name, recording in sorted(recordings.items()):
        (target / ("%s.json" % name)).write_text(
            json.dumps(recording, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--apikey", required=True)
    parser.add_argument("--nntp-host", required=True, help="address SABnzbd uses to reach this machine")
    parser.add_argument("--nntp-port", type=int, default=1119)
    args = parser.parse_args()
    print(write(capture(args.url, args.apikey, args.nntp_host, args.nntp_port)))


if __name__ == "__main__":
    main()
