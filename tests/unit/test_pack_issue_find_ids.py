#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import pytest

import comicarr
from comicarr.app.downloads import service as downloads_service
from comicarr.helpers import issuedigits


def _row(issueid, number, status="Wanted", chapter=None, volume=None, released=None):
    return {
        "IssueID": issueid,
        "Issue_Number": str(number),
        "Int_IssueNumber": issuedigits(str(number)),
        "Status": status,
        "ChapterNumber": chapter,
        "VolumeNumber": volume,
        "ReleaseDate": released,
        "IssueDate": None,
        "DigitalDate": None,
    }


@pytest.fixture(autouse=True)
def _pack_state(monkeypatch):
    monkeypatch.setattr(comicarr, "PACK_ISSUEIDS_DONT_QUEUE", {}, raising=False)


def _install_rows(monkeypatch, rows):
    monkeypatch.setattr(downloads_service.db, "select_all", lambda _query: rows)


def test_default_kind_matches_issue_numbers_and_registers_pack_ids(monkeypatch):
    rows = [_row("id-1", 1), _row("id-2", 2), _row("id-3", 3, status="Downloaded")]
    _install_rows(monkeypatch, rows)

    result = downloads_service.issue_find_ids("Example", "comic-1", "1-3", "2", "pack-1")

    assert result["valid"] is True
    assert [x["issueid"] for x in result["issues"]] == ["id-1", "id-2"]
    assert comicarr.PACK_ISSUEIDS_DONT_QUEUE == {"id-1": "pack-1", "id-2": "pack-1"}


def test_volume_kind_skips_chapter_rows_of_unknown_volume(monkeypatch):
    rows = [
        _row("chap-7", 7, chapter="7"),
        _row("vol-7", 7, volume="7"),
        _row("vol-8", 8, volume="8"),
    ]
    _install_rows(monkeypatch, rows)

    result = downloads_service.issue_find_ids("Example", "comic-1", "1-14", "7", "pack-2", kind="volume")

    assert result["valid"] is True
    assert [x["issueid"] for x in result["issues"]] == ["vol-7", "vol-8"]
    assert "chap-7" not in comicarr.PACK_ISSUEIDS_DONT_QUEUE


def test_volume_pack_covers_every_chapter_row_in_its_volumes(monkeypatch):
    # The reported Solo Leveling case: a chapter-tracked manga where a
    # v01-14 pack must satisfy every chapter belonging to those volumes.
    rows = [
        _row("c-1", 1, chapter="1", volume="1"),
        _row("c-2", 2, chapter="2", volume="1"),
        _row("c-3", 3, chapter="3", volume="2"),
        _row("c-99", 99, chapter="99", volume="20"),
    ]
    _install_rows(monkeypatch, rows)

    result = downloads_service.issue_find_ids("Example", "comic-1", "1-14", "2", "pack-5", kind="volume")

    assert result["valid"] is True
    assert [x["issueid"] for x in result["issues"]] == ["c-1", "c-2", "c-3"]
    assert "c-99" not in comicarr.PACK_ISSUEIDS_DONT_QUEUE


def test_chapter_kind_does_not_claim_volume_rows(monkeypatch):
    rows = [_row("vol-2", 2, volume="2"), _row("c-2", 2, chapter="2", volume="1")]
    _install_rows(monkeypatch, rows)

    result = downloads_service.issue_find_ids("Example", "comic-1", "1-10", "2", "pack-6", kind="chapter")

    assert result["valid"] is True
    assert [x["issueid"] for x in result["issues"]] == ["c-2"]


def test_volume_kind_falls_back_to_issue_numbers_for_plain_rows(monkeypatch):
    # A TPB/GN-tracked series has no VolumeNumber column values; its
    # Issue_Number values are the volume numbers.
    rows = [_row("tpb-1", 1), _row("tpb-2", 2)]
    _install_rows(monkeypatch, rows)

    result = downloads_service.issue_find_ids("Example", "comic-1", "1-2", "1", "pack-3", kind="volume")

    assert result["valid"] is True
    assert [x["issueid"] for x in result["issues"]] == ["tpb-1", "tpb-2"]


def test_series_kind_claims_every_undownloaded_row(monkeypatch):
    # A numberless complete-series pack ("Solo Leveling (2021-2026)") has no
    # range to expand - it covers volume rows and chapter rows alike, minus
    # anything already Downloaded.
    rows = [
        _row("vol-1", 1, volume="1"),
        _row("c-2", 2, chapter="2", volume="1"),
        _row("c-3", 3, chapter="3"),
        _row("done", 4, status="Downloaded"),
    ]
    _install_rows(monkeypatch, rows)

    result = downloads_service.issue_find_ids("Example", "comic-1", "all", "2", "pack-7", kind="series")

    assert result["valid"] is True
    assert [x["issueid"] for x in result["issues"]] == ["vol-1", "c-2", "c-3"]
    assert "done" not in comicarr.PACK_ISSUEIDS_DONT_QUEUE
    assert comicarr.PACK_ISSUEIDS_DONT_QUEUE == {"vol-1": "pack-7", "c-2": "pack-7", "c-3": "pack-7"}


def test_series_kind_excludes_rows_released_after_the_pack_span(monkeypatch):
    # A "Series {2021-2023}" pack cut in 2023 cannot contain chapters
    # published later; claiming them would mark unattainable issues Snatched.
    rows = [
        _row("c-1", 1, released="2021-05-01"),
        _row("c-2", 2, released="2023-11-01"),
        _row("c-3", 3, released="2024-02-01"),
        _row("c-4", 4, released="0000-00-00"),
    ]
    _install_rows(monkeypatch, rows)

    result = downloads_service.issue_find_ids("Example", "comic-1", "all", "2", "pack-9", kind="series", span_end="2023")

    assert result["valid"] is True
    assert [x["issueid"] for x in result["issues"]] == ["c-1", "c-2", "c-4"]
    assert "c-3" not in comicarr.PACK_ISSUEIDS_DONT_QUEUE


def test_series_kind_invalid_when_searched_issue_is_past_the_span(monkeypatch):
    rows = [_row("c-1", 1, released="2021-05-01"), _row("c-9", 9, released="2026-01-01")]
    _install_rows(monkeypatch, rows)

    result = downloads_service.issue_find_ids("Example", "comic-1", "all", "9", "pack-10", kind="series", span_end="2023")

    assert result["valid"] is False
    assert comicarr.PACK_ISSUEIDS_DONT_QUEUE == {}


def test_series_kind_invalid_when_searched_issue_already_downloaded(monkeypatch):
    rows = [_row("done-2", 2, status="Downloaded"), _row("id-3", 3)]
    _install_rows(monkeypatch, rows)

    result = downloads_service.issue_find_ids("Example", "comic-1", "all", "2", "pack-8", kind="series")

    assert result["valid"] is False
    assert comicarr.PACK_ISSUEIDS_DONT_QUEUE == {}


def test_volume_kind_invalid_when_searched_number_outside_pack(monkeypatch):
    rows = [_row("vol-1", 1, volume="1")]
    _install_rows(monkeypatch, rows)

    result = downloads_service.issue_find_ids("Example", "comic-1", "1-2", "9", "pack-4", kind="volume")

    assert result["valid"] is False
    assert comicarr.PACK_ISSUEIDS_DONT_QUEUE == {}
