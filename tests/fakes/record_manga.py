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

"""Record real MangaDex and MyAnimeList responses for ``tests/fakes/manga.py``.

Run it from the repository root on a machine that can reach both APIs::

    python -m tests.fakes.record_manga --mangadex
    MAL_CLIENT_ID=... python -m tests.fakes.record_manga --mal

Each exchange is captured while Comicarr's own client code makes the call
(``comicarr/mangadex.py``, ``comicarr/myanimelist.py``), so the recorded
request is exactly what Comicarr sends. Only the request's method, path and
query and the response's status and JSON body are written; headers are not,
so the MAL client ID never reaches a fixture. Files land in
``tests/fixtures/mangadex/`` and ``tests/fixtures/myanimelist/``.

The series is *Shino-chan wa Jibun no Namae ga Ienai* (Oshimi Shuzo): eleven
English chapters in one volume, completed, linked to MAL 49017. It is small
enough to keep every chapter in the fixtures.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1] / "fixtures"
MANGADEX_ID = "be7fd0c5-209a-440c-b20d-8b611be1310c"
MAL_ID = "49017"
# A well-formed UUID MangaDex has no manga for: the add-failure scenario.
MISSING_MANGADEX_ID = "00000000-0000-4000-8000-000000000000"
MISSING_MAL_ID = "999999999"


class _Capture:
    """Wrap ``requests.get``/``requests.request`` and keep each exchange."""

    def __init__(self):
        self.exchanges: list[dict] = []
        self._get = requests.get
        self._request = requests.request

    def __enter__(self):
        capture = self

        def get(url, params=None, **kwargs):
            response = capture._get(url, params=params, **kwargs)
            capture._keep("GET", response)
            return response

        def request(method, url, params=None, **kwargs):
            response = capture._request(method, url, params=params, **kwargs)
            capture._keep(method, response)
            return response

        requests.get = get
        requests.request = request
        return self

    def __exit__(self, *exc):
        requests.get = self._get
        requests.request = self._request

    def _keep(self, method, response):
        url = urlsplit(response.request.url)
        query = {k: (v if len(v) > 1 else v[0]) for k, v in parse_qs(url.query).items()}
        try:
            body = response.json()
        except ValueError:
            body = response.text
        self.exchanges.append(
            {
                "request": {"method": method.upper(), "host": url.hostname, "path": url.path, "params": query},
                "status_code": response.status_code,
                "body": body,
            }
        )

    def take(self) -> list[dict]:
        taken, self.exchanges = self.exchanges, []
        return taken


def _write(directory: Path, name: str, exchanges: list[dict]) -> None:
    if not exchanges:
        raise SystemExit("no request was made for %s" % name)
    directory.mkdir(parents=True, exist_ok=True)
    payload = exchanges[0] if len(exchanges) == 1 else exchanges
    (directory / ("%s.json" % name)).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print("wrote %s/%s.json" % (directory.name, name))


def _configure(mal_client_id=None):
    import comicarr

    comicarr.CONFIG = SimpleNamespace(
        CV_USER_AGENT="Comicarr/1.0",
        MANGADEX_ENABLED=True,
        MANGADEX_CONTENT_RATING="safe,suggestive",
        MANGADEX_LANGUAGES="en",
        MAL_CLIENT_ID=mal_client_id,
        MAL_ENABLED=True,
    )


def record_mangadex() -> None:
    from comicarr import mangadex

    out = ROOT / "mangadex"
    with _Capture() as capture:
        mangadex.get_manga_details(MANGADEX_ID)
        _write(out, "manga_details", capture.take())
        mangadex.get_manga_chapters(MANGADEX_ID, languages=["en"])
        _write(out, "chapters_en", capture.take())
        mangadex.get_total_chapter_count(MANGADEX_ID)
        _write(out, "aggregate", capture.take())
        mangadex.find_by_mal_id(MAL_ID, title_hint="Shino-chan wa Jibun no Namae ga Ienai", allow_title_match=False)
        _write(out, "search_by_title", capture.take())
        mangadex.clear_cache()
        mangadex.get_manga_details(MISSING_MANGADEX_ID)
        _write(out, "manga_not_found", capture.take())


def record_mal() -> None:
    from comicarr import mangadex, myanimelist

    out = ROOT / "myanimelist"
    with _Capture() as capture:
        details = myanimelist.get_manga_details(MAL_ID)
        _write(out, "manga_details", capture.take())
        myanimelist.get_manga_details(MISSING_MAL_ID)
        _write(out, "manga_not_found", capture.take())
        # The MangaDex lookups a MAL add makes: one search per title until a
        # result links back to this MAL id, as find_by_mal_id stops there.
        mangadex.find_by_mal_id(
            MAL_ID,
            title_hint=details["name"],
            alternate_titles=details.get("alt_titles", []),
            allow_title_match=False,
        )
        _write(ROOT / "mangadex", "search_for_mal_add", capture.take())


def record_mal_forbidden() -> None:
    """What MAL answers a request whose client ID it does not accept."""
    with _Capture() as capture:
        requests.get(
            "https://api.myanimelist.net/v2/manga/%s" % MAL_ID,
            params={"fields": "id,title"},
            headers={"X-MAL-CLIENT-ID": "not-a-client-id"},
            timeout=30,
        )
        _write(ROOT / "myanimelist", "forbidden", capture.take())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mangadex", action="store_true")
    parser.add_argument("--mal", action="store_true")
    parser.add_argument("--mal-forbidden", action="store_true", help="only the rejected-client-ID answer")
    args = parser.parse_args(argv)
    client_id = os.environ.get("MAL_CLIENT_ID")
    if args.mal and not client_id:
        print("--mal needs MAL_CLIENT_ID in the environment", file=sys.stderr)
        return 2
    _configure(client_id)
    if args.mangadex:
        record_mangadex()
    if args.mal:
        record_mal()
    if args.mal or args.mal_forbidden:
        record_mal_forbidden()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
