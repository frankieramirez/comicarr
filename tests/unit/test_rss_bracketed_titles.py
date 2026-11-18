#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""One unreadable feed title must not abort the whole RSS check (#1441).

Some Newznab feeds wrap a whole title in square brackets. The parser read the
brackets as a leading scanlation-group tag, stripped the title to nothing and
then indexed an empty token list, so `rssdbupdate` raised and nothing after
that entry was cached or searched.
"""

from unittest.mock import MagicMock

import pytest

BRACKETED = [
    ("[Zentak, Tome 1 - La Passe des Argonautes.cbz]", "Zentak Tome", "1"),
    (
        "[Captain America - Sentinel of Liberty, Tome 1 - Révolution.cbz]",
        "Captain America - Sentinel of Liberty Tome",
        "1",
    ),
]


@pytest.fixture
def config(monkeypatch):
    import comicarr

    if comicarr.LOG_LEVEL is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0)
    cfg = MagicMock()
    cfg.IGNORE_SEARCH_WORDS = []
    cfg.READ2FILENAME = False
    cfg.AI_FILENAME_FALLBACK = False
    monkeypatch.setattr(comicarr, "CONFIG", cfg)
    return cfg


def _parse(title):
    from comicarr.app.library.filechecker import FileChecker

    return FileChecker(file=title).listFiles()


@pytest.mark.parametrize(("title", "series", "issue"), BRACKETED)
def test_a_title_wrapped_in_brackets_parses_like_the_bare_title(config, title, series, issue):
    result = _parse(title)

    assert result["series_name"] == series
    assert result["issue_number"] == issue
    assert result == {**_parse(title[1:-1]), "comicfilename": title}


@pytest.mark.parametrize("title", ["[]", "[ ]", "[ ]  "])
def test_a_title_with_nothing_to_parse_fails_instead_of_raising(config, title):
    result = _parse(title)

    assert result["parse_status"] == "failure"
    assert result["series_name"] is None


def test_rssdbupdate_caches_every_entry_when_one_title_cannot_be_parsed(config, monkeypatch):
    from comicarr.app.library import filechecker
    from comicarr.app.search import rss_feeds as rsscheck

    real = filechecker.FileChecker

    class Exploding(real):
        def listFiles(self):
            if self.file == "boom":
                raise IndexError("list index out of range")
            return super().listFiles()

    stored = []
    monkeypatch.setattr(filechecker, "FileChecker", Exploding)
    monkeypatch.setattr(rsscheck.db, "upsert", lambda table, values, key: stored.append((key["Title"], values)))

    feed = [
        {"Title": title, "Link": "l", "Pubdate": "p", "Site": "s", "Size": "1"}
        for title in ("boom", BRACKETED[0][0], "Zentak 002 (2024).cbz")
    ]
    rsscheck.rssdbupdate(feed, len(feed), "usenet")

    assert [title for title, _ in stored] == [entry["Title"] for entry in feed]
    assert stored[0][1]["ComicName"] is None
    assert stored[1][1]["ComicName"] == "Zentak Tome"
    assert stored[2][1]["ComicName"] == "Zentak"
