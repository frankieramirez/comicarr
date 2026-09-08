#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""verification() must hand searcher() the candidate it is currently trying.

searcher() reads ComicName, nzbid, size, nzbtitle and friends off comicinfo[0].
When verification() passed the whole verified_matches list, every candidate was
described by candidate 0 -- so the failed-release check ran against candidate 0's
nzbid for all of them, and a single previously-failed release rejected every
alternative the provider offered.
"""

import comicarr.search as search


def _candidate(nzbid, title, downloadit=True, comyear="2011"):
    return {
        "downloadit": downloadit,
        "chkit": None,
        "ComicTitle": title,
        "nzbid": nzbid,
        "nzbtitle": title,
        "comyear": comyear,
        "nzbprov": "NZBGeek",
        "tmpprov": "NZBGeek (newznab)",
        "IssueID": "1001",
        "ComicID": "17993",
        "newznab": None,
        "torznab": None,
        "provider_stat": {},
        "pack": False,
        "entry": {"id": nzbid, "link": "https://example.invalid/%s" % nzbid},
    }


def _is_info():
    return {
        "nzbprov": "NZBGeek",
        "RSS": "no",
        "foundc": {"status": False, "info": None},
    }


def test_each_candidate_is_described_by_itself(monkeypatch):
    """The nzbid searcher() sees must advance with the candidate."""
    seen = []

    def fake_searcher(nzbprov, nzbname, comicinfo, link, *a, **kw):
        seen.append(comicinfo[0]["nzbid"])
        return "downloadchk-fail"  # force the loop on to the next candidate

    monkeypatch.setattr(search, "searcher", fake_searcher)
    monkeypatch.setattr(search, "nzbname_create", lambda *a, **kw: "nzbname")

    matches = [_candidate("empire-id", "Invincible 085 (digital-Empire)"),
               _candidate("minutemen-id", "Invincible 085 (Minutemen-InnerDemons)")]

    search.verification(matches, _is_info())

    assert seen == ["empire-id", "minutemen-id"], (
        "second candidate was described by candidate 0: %r" % (seen,)
    )


def test_fallback_candidate_can_still_be_taken(monkeypatch):
    """A failed first candidate must not stop the second from being sent."""

    def fake_searcher(nzbprov, nzbname, comicinfo, link, *a, **kw):
        if comicinfo[0]["nzbid"] == "empire-id":
            return "downloadchk-fail"
        return {
            "nzbid": comicinfo[0]["nzbid"],
            "nzbname": "nzbname",
            "sent_to": "NZBGet",
            "alt_nzbname": None,
            "SARC": None,
        }

    monkeypatch.setattr(search, "searcher", fake_searcher)
    monkeypatch.setattr(search, "nzbname_create", lambda *a, **kw: "nzbname")
    monkeypatch.setattr(search.updater, "nzblog", lambda *a, **kw: None)
    monkeypatch.setattr(search.updater, "foundsearch", lambda *a, **kw: None)
    monkeypatch.setattr(search, "notify_snatch", lambda *a, **kw: None)

    matches = [_candidate("empire-id", "Invincible 085 (digital-Empire)"),
               _candidate("minutemen-id", "Invincible 085 (Minutemen-InnerDemons)")]

    info = _is_info()
    info.update({"ComicName": "Invincible", "ComicYear": "2003", "IssueID": "1001",
                 "ComicID": "17993", "SARC": None, "IssueArcID": None,
                 "smode": "want", "oneoff": False, "IssueNumber": "85"})

    out = search.verification(matches, info)

    assert out["foundc"]["status"] is True
    assert out["foundc"]["info"]["nzbid"] == "minutemen-id"


def test_skipped_candidate_does_not_misname_the_snatch(monkeypatch):
    """A leading downloadit=False entry must not shift what gets logged.

    release evaluation emits alt_match entries with downloadit=False into the same
    list. They are skipped without ever reaching searcher(), so the index used
    by the post-loop block has to advance past them anyway -- otherwise the
    accepted release is recorded under the skipped entry's nzbid and year, and
    post-processing later cannot match the download back to the issue.
    """
    logged = {}
    snatched = {}

    def fake_searcher(nzbprov, nzbname, comicinfo, link, *a, **kw):
        return {
            "nzbid": comicinfo[0]["nzbid"],
            "nzbname": "nzbname",
            "sent_to": "NZBGet",
            "alt_nzbname": None,
            "SARC": None,
        }

    monkeypatch.setattr(search, "searcher", fake_searcher)
    monkeypatch.setattr(search, "nzbname_create", lambda *a, **kw: "nzbname")
    monkeypatch.setattr(search.updater, "nzblog", lambda *a, **kw: logged.update(kw))
    monkeypatch.setattr(search.updater, "foundsearch", lambda *a, **kw: None)
    monkeypatch.setattr(
        search, "notify_snatch", lambda sent_to, name, year, *a: snatched.update(year=year)
    )

    matches = [
        _candidate("alt-id", "Invincible 085 (alt match)", downloadit=False, comyear="1999"),
        _candidate("minutemen-id", "Invincible 085 (Minutemen-InnerDemons)"),
    ]

    info = _is_info()
    info.update({"ComicName": "Invincible", "ComicYear": "2003", "IssueID": "1001",
                 "ComicID": "17993", "SARC": None, "IssueArcID": None,
                 "smode": "want", "oneoff": False, "IssueNumber": "85"})

    out = search.verification(matches, info)

    assert out["foundc"]["status"] is True
    assert logged["id"] == "minutemen-id", (
        "nzblog was given the skipped candidate's nzbid: %r" % (logged.get("id"),)
    )
    assert snatched["year"] == "2011"
