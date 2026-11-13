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

"""Shared steps for ``tests/integration/test_acquisition_pipeline.py`` scenarios.

A scenario runs from an accepted search result to the final library state:
the real handoff, download-client monitor, completed-download handling and
post-processing run against a fake download client. These helpers hold the
parts every scenario repeats, written the way ``comicarr/search.py`` and
``comicarr/app/downloads/service.py`` do them, so a scenario reads as the
steps it cares about.
"""

from __future__ import annotations

import io
import os
import time
import zipfile
from types import SimpleNamespace

import comicarr
from comicarr import sabnzbd, updater
from comicarr.app.core.context import AppContext
from comicarr.app.downloads import handoff, journal, postprocessing, service
from comicarr.app.series import service as series_service
from comicarr.config import _CONFIG_DEFINITIONS, Config
from tests.fakes.nntp import nzb_document

COMIC_ID = "160294"
# Below 900000: larger IssueIDs currently key as one-offs (#1261).
ISSUE_ID = "523814"
SERIES = "Absolute Batman"
RELEASE = "Absolute.Batman.001.2024"
FILENAME = "Absolute Batman 001 (2024).cbz"
INDEXER = "fakeindexer"
INDEXER_ID = "nzb-1"


def default_config(**overrides) -> SimpleNamespace:
    """Every registered setting at its shipped default, plus ``overrides``."""
    probe = object.__new__(Config)
    values = {}
    for name in _CONFIG_DEFINITIONS:
        key, _type, _section, _ini_key, default = Config._define(probe, name)
        values[key] = default
    values.update(overrides)
    return SimpleNamespace(**values)


def comic_archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("001.jpg", b"\xff\xd8page" * 200)
    return buffer.getvalue()


def write_download(path):
    """Put a finished archive at ``path``, last written a minute ago.

    Post-processing waits for a file written in the last ten seconds to
    settle, and a client that reports a job complete finished writing it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(comic_archive())
    settled = time.time() - 60
    os.utime(path, (settled, settled))
    return path


def comic_series_row(series_root) -> dict:
    """A ComicVine series row as a completed refresh leaves it."""
    return {
        "ComicID": COMIC_ID,
        "ComicName": SERIES,
        "ComicSortName": SERIES,
        "ComicName_Filesafe": SERIES,
        "DynamicComicName": "absolutebatman",
        "ComicYear": "2024",
        "ComicPublisher": "DC Comics",
        "ComicPublished": "October 2024 - Present",
        "ComicVersion": "v1",
        "Type": "Print",
        "Status": "Active",
        "LatestIssue": "1",
        "intLatestIssue": 1,
        "LatestDate": "2024-12-01",
        "LastUpdated": "2026-11-01 00:00:00",
        "ForceContinuing": 0,
        "Have": 0,
        "Total": 1,
        "ComicLocation": str(series_root),
    }


def comic_issue_row() -> dict:
    return {
        "IssueID": ISSUE_ID,
        "ComicID": COMIC_ID,
        "ComicName": SERIES,
        "Issue_Number": "1",
        "Int_IssueNumber": 1000,
        "Status": "Wanted",
        "ReleaseDate": "2024-10-09",
        "IssueDate": "2024-12-01",
    }


def cached_nzb(tmp_path, name=RELEASE):
    """The .nzb search.py caches before a handoff."""
    path = tmp_path / "cache" / ("%s.nzb" % name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(nzb_document([(FILENAME, "%s@indexer.invalid" % name, 4096)]))
    return path


def release_key(name=RELEASE):
    return journal.release_key(ISSUE_ID, INDEXER, nzbname=name, discriminant=INDEXER_ID)


def send_to_sab(nzb_path, name=RELEASE):
    """Hand a cached NZB to SABnzbd as ``search.py`` does; return (response, monitor item)."""
    config = comicarr.CONFIG
    params = {"apikey": config.SAB_APIKEY, "mode": "addfile", "nzbname": name, "output": "json", "priority": "-100"}
    if config.SAB_CATEGORY:
        params["cat"] = config.SAB_CATEGORY
    sender = sabnzbd.SABnzbd(params)
    key = release_key(name)
    response, _acceptance = handoff.perform_handoff(
        key,
        "sabnzbd",
        lambda: sender.sender(str(nzb_path)),
        payload={
            "issueid": ISSUE_ID,
            "comicid": COMIC_ID,
            "provider": INDEXER,
            "nzbname": name,
            "comicname": SERIES,
            "issuenumber": "1",
        },
        issueid=ISSUE_ID,
        provider=INDEXER,
        nzbname=name,
    )
    if response.get("status") is not True:
        return response, None
    # search.py records the grab once the client has accepted it.
    updater.nzblog(ISSUE_ID, name, SERIES, id=INDEXER_ID, prov=INDEXER)
    updater.foundsearch(
        COMIC_ID,
        ISSUE_ID,
        mode="want",
        provider=INDEXER,
        nzbname=name,
        journal_release_key=key,
        journal_managed=True,
    )
    item = dict(response)
    item.update(
        comicid=COMIC_ID,
        issueid=ISSUE_ID,
        apicall=True,
        download_info={"provider": INDEXER, "id": INDEXER_ID},
        journal_release_key=key,
        clientmode="sabnzbd",
    )
    return response, item


def monitor_sab(item):
    """One pass of the NZB monitor for ``item``; return SABnzbd's reported status."""
    nzstat = sabnzbd.SABnzbd(item).processor()
    service.cdh_monitor(comicarr.NZB_QUEUE, item, nzstat)
    return nzstat


def post_process_next():
    """Run the post-processing request completed-download handling queued."""
    return postprocessing.run(comicarr.PP_QUEUE.get_nowait())


def library_issue():
    detail = series_service.get_comic_detail(AppContext(config=SimpleNamespace(ANNUALS_ON=False)), COMIC_ID)
    return detail["issues"][0], detail["summary"]
