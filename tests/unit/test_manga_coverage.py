#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Which chapters each manga volume holds, and what an owned volume covers."""

import pytest

from comicarr.app.core import runtime
from comicarr.app.core.db import get_engine, shutdown_engine
from comicarr.app.core.tables import metadata
from comicarr.app.manga import coverage, volumes
from comicarr.app.manga.acquisition import search_plan_for_series


def _chapter(number, volume=None):
    return {"id": "md-x-ch%s" % number, "ChapterNumber": str(number), "VolumeNumber": volume}


def _long_series():
    """MangaDex lists volumes 1-2 and 6; 3-5 have no chapter list (like One Piece 8-60)."""
    rows = [_chapter(n, "1") for n in range(1, 6)]
    rows += [_chapter(n, "2") for n in range(6, 11)]
    rows += [_chapter(n) for n in range(11, 41)]
    rows += [_chapter(n, "6") for n in range(41, 46)]
    rows += [_chapter(n) for n in range(46, 51)]
    return rows


def _spans(ranges, *volumes_):
    return [(ranges[v]["first"], ranges[v]["last"], ranges[v]["source"]) for v in volumes_]


def test_every_volume_up_to_the_highest_known_one_exists():
    assert list(coverage.volume_ranges(_long_series(), [])) == ["1", "2", "3", "4", "5", "6"]
    assert list(coverage.volume_ranges([], [{"VolumeNumber": "3"}])) == ["1", "2", "3"]
    # A year parsed as a volume number must not make 2,019 volumes.
    assert coverage.volume_ranges([], [{"VolumeNumber": "2019"}]) == {}


def test_unlisted_volumes_share_the_chapters_between_their_neighbours():
    ranges = coverage.volume_ranges(_long_series(), [])

    assert _spans(ranges, "2", "6") == [(6, 10, "mangadex"), (41, 45, "mangadex")]
    assert _spans(ranges, "3", "4", "5") == [(11, 20, "estimated"), (21, 30, "estimated"), (31, 40, "estimated")]
    assert len(ranges["4"]["chapters"]) == 10


def test_chapters_after_the_last_known_volume_belong_to_none():
    ranges = coverage.volume_ranges(_long_series(), [])
    assert coverage.volume_holding(_chapter(45), ranges) == "6"
    assert coverage.volume_holding(_chapter(46), ranges) is None


def test_too_few_chapters_for_the_gap_estimates_nothing():
    ranges = coverage.volume_ranges([_chapter(1, "1"), _chapter(2), _chapter(3, "5")], [])
    assert _spans(ranges, "3") == [(None, None, None)]
    assert coverage.volume_holding(_chapter(2), ranges) is None


def test_an_operator_end_moves_both_neighbours_and_leaves_no_hole():
    ranges = coverage.volume_ranges(_long_series(), [{"VolumeNumber": "3", "Status": "", "LastChapter": "16"}])

    assert _spans(ranges, "3", "4", "5") == [(11, 16, "user"), (17, 28, "estimated"), (29, 40, "estimated")]
    held = sorted(int(identity.split("ch")[1]) for entry in ranges.values() for identity in entry["chapters"])
    assert held == list(range(1, 46))


def test_an_operator_end_overrides_mangadex_and_a_contradicting_one_is_ignored():
    ranges = coverage.volume_ranges(_long_series(), [{"VolumeNumber": "1", "LastChapter": "6"}])
    assert "md-x-ch6" in ranges["1"]["chapters"]
    assert _spans(ranges, "2") == [(7, 10, "mangadex")]

    # Volume 2 cannot end before volume 1 does.
    backwards = [{"VolumeNumber": "1", "LastChapter": "8"}, {"VolumeNumber": "2", "LastChapter": "3"}]
    ranges = coverage.volume_ranges(_long_series(), backwards)
    assert _spans(ranges, "1", "2") == [(1, 8, "user"), (9, 10, "mangadex")]


def test_a_fractional_chapter_between_two_volumes_goes_to_the_later_one():
    rows = [_chapter("1", "1"), _chapter("2", "1"), _chapter("2.5"), _chapter("3", "2")]
    ranges = coverage.volume_ranges(rows, [])
    assert coverage.volume_holding(_chapter("2.5"), ranges) == "2"


def test_search_follows_the_same_ranges_as_the_page():
    owned = [{"VolumeNumber": str(v), "Status": "Downloaded"} for v in range(1, 5)]
    targets = search_plan_for_series({"MonitorMode": "blended"}, _long_series(), owned)

    assert [t["number"] for t in targets if t["kind"] == "volume"] == ["5", "6"]
    # 31-40 sit in unowned volume 5, so the volume is searched, not ten chapters.
    assert {t["number"] for t in targets if t["kind"] == "chapter"} == {"46", "47", "48", "49", "50"}

    chapters = search_plan_for_series({"MonitorMode": "chapters"}, _long_series(), owned)
    assert "25" not in {t["number"] for t in chapters}  # inside owned, estimated volume 4
    assert "35" in {t["number"] for t in chapters}


# --- database ---------------------------------------------------------


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "data_dir", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if runtime.current().log_level is None:
        monkeypatch.setattr(runtime.current(), "log_level", 0, raising=False)
    metadata.create_all(get_engine())
    yield
    shutdown_engine()


def test_an_end_on_an_unowned_volume_does_not_own_it(isolated_db):
    assert volumes.set_volume_end("md-x", "08", "72") == "72"
    assert volumes.volume_rows("md-x")[0]["LastChapter"] == "72"
    assert volumes.covering_volumes(volumes.volume_states("md-x")) == set()

    # The grab and the file landing later keep the end.
    volumes.record_volume("md-x", "8", volumes.DOWNLOADED, location="X v08.cbz")
    row = volumes.volume_rows("md-x")[0]
    assert (row["Status"], row["LastChapter"]) == ("Downloaded", "72")

    assert volumes.set_volume_end("md-x", "8", None) is None
    row = volumes.volume_rows("md-x")[0]
    assert (row["Status"], row["LastChapter"]) == ("Downloaded", None)


@pytest.mark.parametrize("value", ["x", "0", "-3"])
def test_a_bad_end_is_refused(isolated_db, value):
    with pytest.raises(ValueError):
        volumes.set_volume_end("md-x", "1", value)
    assert volumes.volume_rows("md-x") == []


def test_series_view_marks_coverage_and_counts_the_run(isolated_db):
    for v in ("1", "2"):
        volumes.record_volume("md-x", v, volumes.DOWNLOADED, location="X v0%s.cbz" % v)
    issues = []
    for row in _long_series():
        number = int(row["ChapterNumber"])
        owned = number in (14, 15)
        issues.append(
            {
                "id": row["id"],
                "chapterNumber": row["ChapterNumber"],
                "volumeNumber": row["VolumeNumber"],
                "fulfillment": "downloaded" if owned else "missing",
                "owned": owned,
                "covered": False,
                "monitored": number < 30,
                "acquisitionIntent": "policy",
            }
        )

    rows, vols, progress = volumes.series_view("md-x", issues)
    by_id = {row["id"]: row for row in rows}

    assert by_id["md-x-ch3"]["covered"] is True
    assert by_id["md-x-ch3"]["holdingVolume"] == "1"
    assert by_id["md-x-ch14"]["covered"] is False
    assert (by_id["md-x-ch14"]["holdingVolume"], by_id["md-x-ch14"]["holdingEstimated"]) == ("3", True)
    assert by_id["md-x-ch48"]["holdingVolume"] is None
    assert [v["number"] for v in vols] == ["6", "5", "4", "3", "2", "1"]
    assert vols[-1] == {
        "number": "1",
        "firstChapter": "1",
        "lastChapter": "5",
        "rangeSource": "mangadex",
        "owned": True,
        "inFlight": False,
        "location": "X v01.cbz",
    }
    assert {k: v for k, v in progress.items() if k != "segments"} == {
        "volumesTotal": 6,
        "volumesOwned": 2,
        "volumesEstimated": 3,
        "chaptersOwned": 2,
        "chaptersGap": 3,  # 11-13 sit below the highest chapter you have
    }
    assert [(s["kind"], s["from"], s["to"]) for s in progress["segments"]] == [
        ("volume", "1", "10"),
        ("gap", "11", "13"),
        ("chapter", "14", "15"),
        ("wanted", "16", "29"),
        ("notWanted", "30", "50"),
    ]
