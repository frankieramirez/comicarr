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

"""First-run smoke test for a built Comicarr Docker image (#1352).

Boots the image the way the README tells operators to: an empty ``/config``
volume, ``PUID``/``PGID`` env, port 8090. Then it does what a new user does
through the HTTP API alone:

1. waits for ``/api/health`` and confirms setup is pending;
2. reads the setup token from the container log, creates the user;
3. signs in straight away (setup needs no restart) and makes an
   authenticated API call;
4. checks every file under ``/config`` belongs to ``PUID``/``PGID``;
5. stops the container (it must exit cleanly, not by the stop timeout's kill),
   starts it on the same volume, and checks setup is not asked for again and
   the same user still signs in.

Standard library only, so it runs on a bare CI runner::

    python3 scripts/docker_first_run_smoke.py --image comicarr:smoke

Exits non-zero with the container log on any failure.
"""

import argparse
import http.cookiejar
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PUID = "1234"
PGID = "1234"
USERNAME = "smoke"
PASSWORD = "smoke-test-password"
STOP_TIMEOUT = 30  # docker-compose.yml stop_grace_period
TOKEN_RE = re.compile(r"\[SETUP\] Setup token: (\S+)")


class SmokeFailure(Exception):
    pass


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SmokeFailure("docker %s failed: %s" % (" ".join(args), result.stderr.strip()))
    return result


class Client:
    """A browser-shaped HTTP client: one cookie jar, the frontend's CSRF header."""

    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),  # localhost, never through a proxy
            urllib.request.HTTPCookieProcessor(self.jar),
        )

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("X-Requested-With", "ComicarrFrontend")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(request, timeout=10) as response:
                return response.status, _json(response.read())
        except urllib.error.HTTPError as e:
            return e.code, _json(e.read())

    def wait_for(self, path, predicate, what, timeout=180):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                status, body = self.call("GET", path)
                last = (status, body)
                if predicate(status, body):
                    return body
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
                last = repr(e)
            time.sleep(1)
        raise SmokeFailure("timed out after %ss waiting for %s; last answer: %r" % (timeout, what, last))


def _json(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode(errors="replace")[:300]


def expect(condition, message):
    if not condition:
        raise SmokeFailure(message)
    print("  ok  %s" % message, flush=True)


def wait_healthy(client):
    client.wait_for("/api/health", lambda s, b: s == 200, "/api/health")


def sign_in_and_call_api(client):
    status, body = client.call("POST", "/api/auth/login", {"username": USERNAME, "password": PASSWORD})
    expect(status == 200 and body.get("success") is True, "sign-in succeeds (%s %r)" % (status, body))
    status, body = client.call("GET", "/api/auth/check-session")
    expect(status == 200 and body.get("authenticated") is True, "the session cookie authenticates")
    status, body = client.call("GET", "/api/series")
    expect(status == 200 and isinstance(body, list), "an authenticated API call succeeds (GET /api/series %s)" % status)


def check_ownership(container):
    listing = docker("exec", container, "find", "/config", "-printf", "%U:%G %p\\n").stdout.splitlines()
    expect(any(line.endswith("/config/comicarr/config.ini") for line in listing), "config.ini was written to /config")
    expect(any(line.endswith("/config/comicarr/comicarr.db") for line in listing), "comicarr.db was written to /config")
    wrong = [line for line in listing if not line.startswith("%s:%s " % (PUID, PGID))]
    expect(
        not wrong,
        "every path under /config is owned by %s:%s%s" % (PUID, PGID, "".join("\n      " + w for w in wrong[:20])),
    )


def setup_tokens(container):
    return TOKEN_RE.findall(docker("logs", container).stdout + docker("logs", container).stderr)


def run(image, port):
    container = "comicarr-first-run-smoke"
    config_dir = tempfile.mkdtemp(prefix="comicarr-config-")
    docker("rm", "-f", container, check=False)
    client = Client("http://127.0.0.1:%d" % port)
    try:
        print("Starting %s with an empty /config (PUID=%s PGID=%s)" % (image, PUID, PGID), flush=True)
        docker(
            "run", "-d", "--name", container,
            "-p", "127.0.0.1:%d:8090" % port,
            "-e", "PUID=" + PUID, "-e", "PGID=" + PGID, "-e", "TZ=Etc/UTC",
            "-v", "%s:/config" % config_dir,
            image,
        )  # fmt: skip

        print("First boot", flush=True)
        wait_healthy(client)
        expect(True, "/api/health answers on port 8090")
        status, body = client.call("GET", "/api/auth/check-setup")
        expect(status == 200 and body.get("needs_setup") is True, "a fresh /config asks for setup")
        status, _ = client.call("GET", "/api/series")
        expect(status == 503, "the setup gate holds the API until setup is done (%s)" % status)

        tokens = setup_tokens(container)
        expect(len(tokens) == 1, "the container log shows one setup token")
        status, body = client.call(
            "POST", "/api/auth/setup", {"username": USERNAME, "password": PASSWORD, "setup_token": tokens[0]}
        )
        expect(status == 200 and body.get("success") is True, "setup creates the user (%s %r)" % (status, body))

        # The setup page waits for this answer, so it must come without a restart.
        expect(body.get("needs_restart") is False, "setup needs no restart")
        status, body = client.call("GET", "/api/auth/check-setup")
        expect(status == 200 and body.get("needs_setup") is False, "setup is saved")
        sign_in_and_call_api(client)
        check_ownership(container)

        print("Container stop and start on the same volume", flush=True)
        started = time.monotonic()
        docker("stop", "-t", str(STOP_TIMEOUT), container)
        elapsed = time.monotonic() - started
        exit_code = docker("inspect", "-f", "{{.State.ExitCode}}", container).stdout.strip()
        expect(
            exit_code == "0" and elapsed < STOP_TIMEOUT - 5,
            "docker stop exits cleanly, not by the %ss kill (exit %s after %.1fs)" % (STOP_TIMEOUT, exit_code, elapsed),
        )
        docker("start", container)
        wait_healthy(client)
        status, body = client.call("GET", "/api/auth/check-setup")
        expect(status == 200 and body.get("needs_setup") is False, "setup is not asked for again")
        expect(len(setup_tokens(container)) == 1, "no new setup token after the restart")
        running = docker("inspect", "-f", "{{.State.Running}}", container).stdout.strip()
        expect(running == "true", "the container is still running")
        client = Client(client.base)  # a new browser: no cookie from before the restart
        sign_in_and_call_api(client)
        check_ownership(container)
        print("Docker first-run smoke test passed.", flush=True)
        return 0
    except SmokeFailure as e:
        print("\nFAILED: %s\n" % e, file=sys.stderr, flush=True)
        logs = docker("logs", container, check=False)
        print("----- container log -----\n%s%s" % (logs.stdout, logs.stderr), file=sys.stderr)
        return 1
    finally:
        docker("rm", "-f", container, check=False)
        # Files belong to PUID now; remove them from inside a container.
        docker(
            "run",
            "--rm",
            "--entrypoint",
            "rm",
            "-v",
            "%s:/config" % config_dir,
            image,
            "-rf",
            "/config/comicarr",
            check=False,
        )
        shutil.rmtree(config_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", required=True, help="image to test, e.g. comicarr:smoke")
    parser.add_argument("--port", type=int, default=8090, help="host port to publish 8090 on")
    args = parser.parse_args()
    return run(args.image, args.port)


if __name__ == "__main__":
    sys.exit(main())
