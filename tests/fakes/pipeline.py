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
from comicarr import nzbget, sabnzbd, updater
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


def release_key(name=RELEASE, issueid=None):
    return journal.release_key(issueid or ISSUE_ID, INDEXER, nzbname=name, discriminant=INDEXER_ID)


def _hand_off(route, send, name, *, issueid=None, comicid=None, series=None):
    """Run ``send`` through the handoff and record the grab as ``search.py`` does."""
    issueid, comicid, series = issueid or ISSUE_ID, comicid or COMIC_ID, series or SERIES
    key = release_key(name, issueid)
    response, _acceptance = handoff.perform_handoff(
        key,
        route,
        send,
        payload={
            "issueid": issueid,
            "comicid": comicid,
            "provider": INDEXER,
            "nzbname": name,
            "comicname": series,
            "issuenumber": "1",
        },
        issueid=issueid,
        provider=INDEXER,
        nzbname=name,
    )
    if response.get("status") is not True:
        return response, None
    item = dict(response)
    item.update(
        comicid=comicid,
        issueid=issueid,
        apicall=True,
        download_info={"provider": INDEXER, "id": INDEXER_ID},
        journal_release_key=key,
        clientmode=route,
        snatch_error=None,
    )
    # search.py queues the monitor item inside searcher(), then records the
    # grab. A failure while recording does not take the queued item back, so
    # it is kept on the item for the test to look at rather than raised.
    updater.nzblog(issueid, name, series, id=INDEXER_ID, prov=INDEXER)
    try:
        updater.foundsearch(
            comicid,
            issueid,
            mode="want",
            provider=INDEXER,
            nzbname=name,
            journal_release_key=key,
            journal_managed=True,
        )
    except Exception as e:
        item["snatch_error"] = e
    return response, item


def send_to_sab(nzb_path, name=RELEASE, **grab):
    """Hand a cached NZB to SABnzbd as ``search.py`` does; return (response, monitor item).

    ``grab`` may name the ``issueid``, ``comicid`` and ``series`` the search
    was for; they default to the comic fixture.
    """
    config = comicarr.CONFIG
    params = {"apikey": config.SAB_APIKEY, "mode": "addfile", "nzbname": name, "output": "json", "priority": "-100"}
    if config.SAB_CATEGORY:
        params["cat"] = config.SAB_CATEGORY
    sender = sabnzbd.SABnzbd(params)
    return _hand_off("sabnzbd", lambda: sender.sender(str(nzb_path)), name, **grab)


def send_to_nzbget(nzb_path, name=RELEASE):
    """Hand a cached NZB to NZBGet as ``search.py`` does; return (response, monitor item)."""
    sender = nzbget.NZBGet()
    return _hand_off("nzbget", lambda: sender.sender(str(nzb_path)), name)


def monitor_sab(item):
    """One pass of the NZB monitor for ``item``; return SABnzbd's reported status."""
    nzstat = sabnzbd.SABnzbd(item).processor()
    service.cdh_monitor(comicarr.NZB_QUEUE, item, nzstat)
    return nzstat


def monitor_nzbget(item):
    """One pass of the NZB monitor for ``item``; return NZBGet's reported status."""
    nzstat = nzbget.NZBGet().processor(item)
    service.cdh_monitor(comicarr.NZB_QUEUE, item, nzstat)
    return nzstat


def post_process_next():
    """Run the post-processing request completed-download handling queued."""
    return postprocessing.run(comicarr.PP_QUEUE.get_nowait())


def library_issue():
    detail = series_service.get_comic_detail(AppContext(config=SimpleNamespace(ANNUALS_ON=False)), COMIC_ID)
    return detail["issues"][0], detail["summary"]


# -- manga ------------------------------------------------------------------

MANGA_ID = "md-7c1e2a4b-0000-4000-8000-000000000001"
MANGA_SERIES = "Sakamoto Days"
# Two released volumes of four chapters each, then two chapters past the last
# volume, as MangaDex's chapter feed lays them out.
MANGA_VOLUMES = {"1": ("1", "2", "3", "4"), "2": ("5", "6", "7", "8")}
MANGA_BEYOND = ("9", "10")


def manga_series_row(series_root, **overrides) -> dict:
    row = {
        "ComicID": MANGA_ID,
        "ComicName": MANGA_SERIES,
        "ComicSortName": MANGA_SERIES,
        "ComicName_Filesafe": MANGA_SERIES,
        "DynamicComicName": "sakamotodays",
        "ComicYear": "2020",
        "ComicPublisher": "Shueisha",
        "ComicPublished": "2020 - Present",
        "Type": "Print",
        "ContentType": "manga",
        "Status": "Active",
        "LatestIssue": "10",
        "LastUpdated": "2026-11-01 00:00:00",
        "Have": 0,
        "Total": 10,
        "ComicLocation": str(series_root),
        "BareNumberMode": "auto",
        "MonitorMode": "blended",
    }
    row.update(overrides)
    return row


def manga_chapter_id(chapter) -> str:
    return "%s-ch%s" % (MANGA_ID, chapter)


def manga_chapter_rows() -> list[dict]:
    """Chapter rows as the MangaDex import writes them: one per chapter, no volume rows."""
    placed = [(chapter, volume) for volume, chapters in MANGA_VOLUMES.items() for chapter in chapters]
    placed += [(chapter, None) for chapter in MANGA_BEYOND]
    return [
        {
            "IssueID": manga_chapter_id(chapter),
            "ComicID": MANGA_ID,
            "ComicName": MANGA_SERIES,
            "Issue_Number": chapter,
            "IssueName": "Chapter %s" % chapter,
            "Int_IssueNumber": int(chapter) * 1000,
            "ChapterNumber": chapter,
            "VolumeNumber": volume,
            "Status": "Wanted",
            "ReleaseDate": "2021-01-%02d" % int(chapter),
            "IssueDate": "2021-01-%02d" % int(chapter),
        }
        for chapter, volume in placed
    ]


def manga_issues() -> dict[str, dict]:
    """This series' issue rows by IssueID, as the database holds them now."""
    from sqlalchemy import select

    from comicarr import db
    from comicarr.tables import issues

    rows = db.select_all(select(issues).where(issues.c.ComicID == MANGA_ID))
    return {row["IssueID"]: row for row in rows}


# -- manga added from recorded MangaDex / MyAnimeList answers ----------------
# These scenarios add their series through the real importer against
# tests/fakes/manga.py, so the ledger under test is the one Comicarr builds
# from what those services really sent.

RECORDED_SERIES = "Shino-chan Can't Say Her Name"


def recorded_release(number, source="Digital") -> tuple[str, str]:
    """The release name and archive filename an indexer offers for one chapter."""
    padded = "%03d" % int(number)
    return (
        "Shino-chan.Cant.Say.Her.Name.c%s.2018.%s" % (padded, source),
        "%s c%s (2018) (%s).cbz" % (RECORDED_SERIES, padded, source),
    )


def recorded_chapter_id(comic_id, number) -> str:
    return "%s-ch%s" % (comic_id, number)


def want_recorded_chapter(comic_id, number) -> str:
    from comicarr import db
    from comicarr.tables import issues

    issue_id = recorded_chapter_id(comic_id, number)
    with db.get_engine().begin() as conn:
        conn.execute(issues.update().where(issues.c.IssueID == issue_id).values(Status="Wanted"))
    return issue_id


def send_recorded_chapter(tmp_path, comic_id, number, source="Digital"):
    """Hand one chapter release to SABnzbd as ``search.py`` does; return (response, monitor item)."""
    name, _filename = recorded_release(number, source)
    return send_to_sab(
        cached_nzb(tmp_path, name),
        name,
        issueid=recorded_chapter_id(comic_id, number),
        comicid=comic_id,
        series=RECORDED_SERIES,
    )


def recorded_release_key(comic_id, number, source="Digital"):
    return release_key(recorded_release(number, source)[0], recorded_chapter_id(comic_id, number))


def series_row(comic_id) -> dict:
    from comicarr import db
    from comicarr.tables import comics

    return db.select_one(comics.select().where(comics.c.ComicID == comic_id))


def chapters_by_number(comic_id) -> dict:
    """Chapter number -> issue row, for one series."""
    from comicarr import db
    from comicarr.tables import issues

    return {row["Issue_Number"]: row for row in db.select_all(issues.select().where(issues.c.ComicID == comic_id))}
