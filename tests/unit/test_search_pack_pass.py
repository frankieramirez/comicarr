#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import pytest

from comicarr import search
from comicarr.app.search.packs import pack_shaped


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, True), ("1", True), (True, True), (0, False), ("0", False), (None, False), (False, False)],
)
def test_allow_packs_enabled_truth_table(value, expected):
    assert search._allow_packs_enabled(value) is expected


def test_bare_pack_pass_is_torznab_only():
    assert search._bare_pack_pass_allowed({"type": "torznab", "id": 1}) is True
    assert search._bare_pack_pass_allowed({"type": "newznab", "id": 1}) is False
    assert search._bare_pack_pass_allowed({"type": "experimental"}) is False
    # string provider_stat ("experimental" fast path) must not crash
    assert search._bare_pack_pass_allowed("experimental") is False


def _scarios(**overrides):
    values = {
        "ComicName": "Example Series",
        "tmp_IssueNumber": "2",
        "ComicYear": "2024",
        "SeriesYear": "2024",
        "Publisher": None,
        "IssueDate": "2024-01-01",
        "StoreDate": "2024-01-01",
        "current_prov": {"torznab": {"type": "torznab", "id": 1}},
        "send_prov_count": 1,
        "IssDateFix": "no",
        "IssueID": "issue-1",
        "UseFuzzy": "0",
        "newznab_host": None,
        "ComicVersion": None,
        "SARC": None,
        "IssueArcID": None,
        "RSS": "no",
        "ComicID": "comic-1",
        "issuetitle": None,
        "unaltered_ComicName": "Example Series",
        "oneoff": False,
        "cmloopit": 0,
        "manual": True,
        "torznab_host": ("nyaa", "https://nyaa.test", "0", "key", "8020"),
        "digitaldate": "0000-00-00",
        "booktype": "manga",
        "chktpb": 0,
        "ignore_booktype": False,
        "smode": None,
        "allow_packs": True,
        "findit": {"status": False},
    }
    values.update(overrides)
    return values


def test_search_the_matrix_forwards_allow_packs(monkeypatch):
    # The regression this guards: scarios carried no allow_packs, NZB_SEARCH's
    # None default normalized to False, and pack detection was dead on the
    # whole search_init driver path (#744 review finding #1).
    captured = {}

    def fake_nzb_search(*args, **kwargs):
        captured["kwargs"] = kwargs
        return {"status": False}

    monkeypatch.setattr(search, "NZB_SEARCH", fake_nzb_search)

    search.search_the_matrix(_scarios())

    assert captured["kwargs"]["allow_packs"] is True


def test_search_the_matrix_tolerates_legacy_scarios_without_allow_packs(monkeypatch):
    captured = {}

    def fake_nzb_search(*args, **kwargs):
        captured["kwargs"] = kwargs
        return {"status": False}

    monkeypatch.setattr(search, "NZB_SEARCH", fake_nzb_search)

    scarios = _scarios()
    del scarios["allow_packs"]
    search.search_the_matrix(scarios)

    assert captured["kwargs"]["allow_packs"] is None


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Solo Leveling v01-14 (2021-2025) (Digital)", True),
        ("Solo Leveling (2021-2026) (Digital) (1r0n)", True),
        ("Solo Leveling 105 (2024) (Digital)", False),
        ("Some Other Release v05 (2022)", False),
        (None, False),
    ],
)
def test_pack_shaped_gate(title, expected):
    assert pack_shaped(title) is expected
