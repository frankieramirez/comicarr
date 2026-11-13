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

"""Record the NZBGet API responses the scenario tests replay.

Run against a disposable NZBGet (it rewrites the instance's news server and
clears its queue and history):

    docker run -d --name nzbget -p 16789:6789 linuxserver/nzbget:<tag>
    python -m tests.fakes.record_nzbget --url http://127.0.0.1:16789 \\
        --username nzbget --password tegbzn6789 --nntp-host 172.17.0.1

The recorder starts ``tests.fakes.nntp`` on this machine and points NZBGet at
it, then finishes one job and fails one each on health (missing articles),
unpack (a broken archive), par (damage the recovery set cannot repair) and
scan (a file that is not an NZB).
Needs the ``par2`` command. Responses are scrubbed and written to
``tests/fixtures/nzbget/<version>/``. ``capture()`` is shared with the nightly
contract job.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import tempfile
import time
import xmlrpc.client
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

from tests.fakes.nntp import RecordingNNTPServer, nzb_document
from tests.fakes.record_sabnzbd import sample_comic

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nzbget"
CATEGORY = "comics"
JOBS = {
    "success": "Absolute.Batman.001.2024",
    "health": "Absolute.Batman.002.2024",
    "unpack": "Absolute.Batman.003.2024",
    "par": "Absolute.Batman.004.2024",
    "slow": "Absolute.Batman.005.2024",
}
# Option names whose values identify the recording machine or its accounts.
_SECRET_OPTION_PARTS = ("password", "username", "host", "secret", "key", "token", "user")


def _with_auth(url: str, username: str, password: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(netloc="%s:%s@%s" % (username, password, parts.netloc)))


def _xmlrpc(url: str):
    return xmlrpc.client.ServerProxy(url.rstrip("/") + "/xmlrpc", allow_none=True)


def _call(server, method: str, *params, record_params=None) -> dict:
    sent = list(params) if record_params is None else record_params
    try:
        result = getattr(server, method)(*params)
    except xmlrpc.client.ProtocolError as e:
        return {"method": method, "params": sent, "protocol_error": {"errcode": e.errcode, "errmsg": e.errmsg}}
    except xmlrpc.client.Fault as e:
        return {"method": method, "params": sent, "fault": {"faultCode": e.faultCode, "faultString": e.faultString}}
    return {"method": method, "params": sent, "result": result}


def _append(server, name: str, files) -> dict:
    document = base64.b64encode(nzb_document(files)).decode()
    params = (name + ".nzb", document, CATEGORY, 0, False, False, "", 0, "SCORE")
    return _call(server, "append", *params, record_params=[name + ".nzb", "<nzb base64>", *params[2:]])


def _job(entries, nzbid):
    return next((entry for entry in entries if entry["NZBID"] == nzbid), None)


def _wait(server, nzbid: int, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        entry = _job(server.history(True), nzbid)
        if entry and entry["Status"] and not entry["Status"].startswith("PP_"):
            return entry
        time.sleep(1)
    raise TimeoutError("NZBID %s never reached history" % nzbid)


def _par_damaged_set(nntp) -> list[tuple[str, str, int]]:
    name = "Absolute Batman 004 (2024).cbz"
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / name
        data.write_bytes(sample_comic() + os.urandom(16384))
        subprocess.run(
            ["par2", "create", "-q", "-r1", "-n1", str(Path(tmp) / "set.par2"), str(data)],
            check=True,
            capture_output=True,
        )
        damaged = bytearray(data.read_bytes())
        damaged[100:9000] = os.urandom(8900)
        files = [(name, "par-data@recording.invalid", nntp.add("par-data@recording.invalid", bytes(damaged), name))]
        for par in sorted(Path(tmp).glob("*.par2")):
            message_id = "%s@recording.invalid" % par.name
            files.append((par.name, message_id, nntp.add(message_id, par.read_bytes(), par.name)))
    return files


def capture(url: str, username: str, password: str, nntp_host: str, nntp_port: int = 1119) -> dict[str, dict]:
    nntp = RecordingNNTPServer(nntp_port)
    server = _xmlrpc(_with_auth(url, username, password))
    out: dict[str, dict] = {}
    try:
        for entry in server.listgroups():
            server.editqueue("GroupFinalDelete", "", [entry["NZBID"]])
        for entry in server.history(True):
            server.editqueue("HistoryFinalDelete", "", [entry["NZBID"]])
        options = {o["Name"]: o["Value"] for o in server.loadconfig()}
        options.update(
            {
                "Server1.Name": "recording",
                "Server1.Active": "yes",
                "Server1.Host": nntp_host,
                "Server1.Port": str(nntp_port),
                "Server1.Encryption": "no",
                "Server1.Connections": "2",
                "Server1.Level": "0",
                "Server1.Username": "recorder",
                "Server1.Password": "recorder",
                "Category1.Name": CATEGORY,
                "DestDir": "${MainDir}/completed",
                "InterDir": "${MainDir}/intermediate",
            }
        )
        server.saveconfig([{"Name": k, "Value": v} for k, v in options.items()])
        server.reload()
        time.sleep(5)
        server = _xmlrpc(_with_auth(url, username, password))

        session = requests.Session()
        session.trust_env = False
        good = session.get(url.rstrip("/") + "/jsonrpc/version", auth=(username, password), timeout=30)
        bad = session.get(url.rstrip("/") + "/jsonrpc/version", auth=(username, "wrong-password"), timeout=30)
        out["http_version"] = {"status_code": good.status_code, "body": good.json()}
        out["http_version_unauthorized"] = {"status_code": bad.status_code, "body": bad.text}
        out["wrong_password"] = _call(_xmlrpc(_with_auth(url, username, "wrong-password")), "version")
        out["version"] = _call(server, "version")
        out["config"] = _call(server, "config")

        comic = sample_comic()
        server.pausedownload()
        success_file = JOBS["success"].replace(".", " ") + ".cbz"
        size = nntp.add("success@recording.invalid", comic, success_file)
        out["append_accepted"] = _append(server, JOBS["success"], [(success_file, "success@recording.invalid", size)])
        success_id = out["append_accepted"]["result"]
        out["listgroups_queued"] = _call(server, "listgroups")
        out["status_paused"] = _call(server, "status")
        server.resumedownload()
        _wait(server, success_id)

        health = _append(server, JOBS["health"], [(JOBS["health"] + ".cbz", "missing@recording.invalid", 60000)])
        _wait(server, health["result"])
        broken = b"Rar!\x1a\x07\x00" + os.urandom(5000)
        size = nntp.add("unpack@recording.invalid", broken, JOBS["unpack"] + ".rar")
        unpack = _append(server, JOBS["unpack"], [(JOBS["unpack"] + ".rar", "unpack@recording.invalid", size)])
        _wait(server, unpack["result"])
        par = _append(server, JOBS["par"], _par_damaged_set(nntp))
        _wait(server, par["result"])

        nntp.delay = 4.0
        slow_file = JOBS["slow"].replace(".", " ") + ".cbz"
        size = nntp.add("slow@recording.invalid", comic, slow_file)
        slow = _append(server, JOBS["slow"], [(slow_file, "slow@recording.invalid", size)])
        time.sleep(2)
        out["listgroups_downloading"] = _call(server, "listgroups")
        _wait(server, slow["result"])
        nntp.delay = 0.0

        # NZBGet gives even a file it cannot parse a positive NZBID; the job
        # goes straight to history as FAILURE/SCAN.
        out["append_rejected"] = _call(
            server,
            "append",
            "Not.An.Nzb.nzb",
            base64.b64encode(b"not an nzb").decode(),
            CATEGORY,
            0,
            False,
            False,
            "",
            0,
            "SCORE",
            record_params=["Not.An.Nzb.nzb", "<not an nzb, base64>", CATEGORY, 0, False, False, "", 0, "SCORE"],
        )
        _wait(server, out["append_rejected"]["result"])
        out["history"] = _call(server, "history", True)
        out["editqueue_history_delete"] = _call(server, "editqueue", "HistoryDelete", "", [success_id])
    finally:
        nntp.shutdown()
        nntp.server_close()
    return scrub(out)


def _secret_option(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered.rsplit(".", 1)[-1] for part in _SECRET_OPTION_PARTS)


def scrub(value):
    if isinstance(value, dict):
        if set(value) == {"Name", "Value"} and _secret_option(str(value["Name"])) and value["Value"]:
            return {"Name": value["Name"], "Value": "<scrubbed>"}
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def write(recordings: dict[str, dict], root: Path = FIXTURES) -> Path:
    version = recordings["version"]["result"]
    target = root / version
    target.mkdir(parents=True, exist_ok=True)
    for name, recording in sorted(recordings.items()):
        (target / ("%s.json" % name)).write_text(
            json.dumps(recording, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--nntp-host", required=True, help="address NZBGet uses to reach this machine")
    parser.add_argument("--nntp-port", type=int, default=1119)
    args = parser.parse_args()
    print(write(capture(args.url, args.username, args.password, args.nntp_host, args.nntp_port)))


if __name__ == "__main__":
    main()
