#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Which chapters each manga volume holds, and what an owned volume covers."""

from decimal import Decimal

import pytest

import comicarr
from comicarr.app.manga import coverage, volumes
from comicarr.app.manga.acquisition import search_plan_for_series
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import metadata


def _chapter(number, volume=None):
    return {"id": "md-x-ch%s" % number, "ChapterNumber": str(number), "VolumeNumber": volume}


def _long_series():
    """MangaDex lists volumes 1-2 and 6, and chapters 3-5's volumes are unknown (like One Piece 8-60)."""
    rows = [_chapter(n, "1") for n in range(1, 6)]
    rows += [_chapter(n, "2") for n in range(6, 11)]
    rows += [_chapter(n) for n in range(11, 41)]
    rows += [_chapter(n, "6") for n in range(41, 46)]
    rows += [_chapter(n) for n in range(46, 51)]
    return rows


def test_the_roster_runs_from_one_to_the_highest_known_volume():
    assert coverage.volume_roster(_long_series(), []) == ["1", "2", "3", "4", "5", "6"]
    assert coverage.volume_roster([], [{"VolumeNumber": "3"}]) == ["1", "2", "3"]
    assert coverage.volume_roster([], [{"VolumeNumber": "9999"}]) == []


def test_unlisted_volumes_share_the_chapters_between_their_neighbours():
    ranges = coverage.volume_ranges(_long_series(), [])

    assert (ranges["2"]["first"], ranges["2"]["last"], ranges["2"]["source"]) == (6, 10, "mangadex")
    assert [(ranges[v]["first"], ranges[v]["last"]) for v in ("3", "4", "5")] == [(11, 20), (21, 30), (31, 40)]
    assert {ranges[v]["source"] for v in ("3", "4", "5")} == {"estimated"}
    assert len(ranges["4"]["chapters"]) == 10


def test_chapters_after_the_last_listed_volume_belong_to_none():
    ranges = coverage.volume_ranges(_long_series(), [])
    held = {identity for entry in ranges.values() for identity in entry["chapters"]}
    assert "md-x-ch46" not in held


def test_too_few_chapters_for_the_gap_estimates_nothing():
    rows = [_chapter(1, "1"), _chapter(2), _chapter(3, "5")]
    ranges = coverage.volume_ranges(rows, [])
    assert ranges["3"]["source"] is None
    assert ranges["3"]["first"] is None


def test_an_operator_range_wins_and_re_anchors_the_estimates():
    rows_by_operator = [{"VolumeNumber": "3", "Status": "", "FirstChapter": "11", "LastChapter": "16"}]
    ranges = coverage.volume_ranges(_long_series(), rows_by_operator)

    assert (ranges["3"]["first"], ranges["3"]["last"], ranges["3"]["source"]) == (11, 16, "user")
    # 17-40 now split across volumes 4 and 5.
    assert (ranges["4"]["first"], ranges["4"]["last"]) == (17, 28)
    assert (ranges["5"]["first"], ranges["5"]["last"]) == (29, 40)


def test_an_operator_range_can_claim_a_chapter_mangadex_put_elsewhere():
    rows = [{"VolumeNumber": "1", "Status": "", "FirstChapter": "1", "LastChapter": "6"}]
    ranges = coverage.volume_ranges(_long_series(), rows)
    assert "md-x-ch6" in ranges["1"]["chapters"]
    assert "md-x-ch6" not in ranges["2"]["chapters"]


def test_only_a_placed_volume_covers_and_estimates_say_so():
    rows = [
        {"VolumeNumber": "1", "Status": "Downloaded"},
        {"VolumeNumber": "4", "Status": "Downloaded"},
        {"VolumeNumber": "5", "Status": "Snatched"},
    ]
    covered = coverage.covered_chapters(_long_series(), rows)

    assert covered["md-x-ch1"] == ("1", False)
    assert covered["md-x-ch25"] == ("4", True)
    assert "md-x-ch35" not in covered


def test_volume_states_follow_files_grabs_and_decisions():
    rows = [
        {"VolumeNumber": "1", "Status": "Downloaded", "Location": "X v01.cbz"},
        {"VolumeNumber": "2", "Status": "Snatched"},
        {"VolumeNumber": "3", "Status": "Skipped"},
        {"VolumeNumber": "4", "Status": "Wanted"},
    ]
    entries = {e["number"]: e for e in coverage.volume_entries(_long_series(), rows, monitor_mode="chapters")}

    assert entries["1"]["displayState"] == "Have"
    assert entries["1"]["location"] == "X v01.cbz"
    assert entries["2"]["displayState"] == "Snatched"
    assert entries["3"]["displayState"] == "Not wanted"
    assert entries["4"]["displayState"] == "Wanted"
    # Chapters-only monitoring leaves undecided volumes alone.
    assert entries["5"]["displayState"] == "Not wanted"
    assert entries["5"]["rangeSource"] == "estimated"
    assert [e["number"] for e in coverage.volume_entries(_long_series(), rows)][:2] == ["6", "5"]


def test_search_skips_chapters_inside_an_estimated_owned_volume():
    rows = [{"VolumeNumber": str(v), "Status": "Downloaded"} for v in range(1, 6)]
    targets = search_plan_for_series({"MonitorMode": "blended"}, _long_series(), rows)

    assert {"kind": "volume", "number": "6"} in targets
    assert not [t for t in targets if t["kind"] == "volume" and t["number"] in {"1", "2", "3", "4", "5"}]
    chapter_numbers = {t["number"] for t in targets if t["kind"] == "chapter"}
    assert "25" not in chapter_numbers
    assert {"46", "50"} <= chapter_numbers


def test_search_leaves_a_volume_marked_not_wanted_alone():
    rows = [{"VolumeNumber": "3", "Status": "Skipped"}]
    targets = search_plan_for_series({"MonitorMode": "volumes"}, _long_series(), rows)
    assert {"kind": "volume", "number": "3"} not in targets
    assert {"kind": "volume", "number": "4"} in targets


# --- operator edits (database) -------------------------------------------


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if getattr(comicarr, "LOG_LEVEL", None) is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    metadata.create_all(get_engine())
    yield
    shutdown_engine()


def test_a_range_on_an_unowned_volume_makes_no_want_decision(isolated_db):
    row = volumes.edit_volume("md-x", "08", first_chapter="63", last_chapter=72)
    assert (row["VolumeNumber"], row["Status"], row["FirstChapter"], row["LastChapter"]) == ("8", "", "63", "72")

    volumes.edit_volume("md-x", "8", clear_range=True)
    assert volumes.volume_rows("md-x")[0]["FirstChapter"] is None


def test_a_decision_never_unowns_a_volume(isolated_db):
    volumes.record_volume("md-x", "2", volumes.DOWNLOADED, location="X v02.cbz")
    row = volumes.edit_volume("md-x", "2", status="Skipped", first_chapter="6", last_chapter="10")
    assert row["Status"] == "Downloaded"
    assert row["FirstChapter"] == "6"


def test_a_later_grab_replaces_a_want_decision(isolated_db):
    volumes.edit_volume("md-x", "3", status="Wanted")
    volumes.record_volume("md-x", "3", volumes.SNATCHED)
    assert volumes.volume_states("md-x") == {"3": "Snatched"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "Downloaded"},
        {"first_chapter": "5"},
        {"first_chapter": "9", "last_chapter": "2"},
        {"first_chapter": "x", "last_chapter": "2"},
        {},
    ],
)
def test_bad_edits_are_refused(isolated_db, kwargs):
    with pytest.raises(volumes.VolumeEditError):
        volumes.edit_volume("md-x", "1", **kwargs)
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
    assert by_id["md-x-ch3"]["coveredByVolume"] == "1"
    assert by_id["md-x-ch14"]["holdingVolume"] == "3"
    assert by_id["md-x-ch14"]["holdingEstimated"] is True
    assert by_id["md-x-ch14"]["coveredByVolume"] is None
    assert progress["volumesOwned"] == 2
    assert progress["volumesTotal"] == 6
    assert progress["chaptersCovered"] == 10
    assert progress["chaptersOwned"] == 2
    assert progress["chaptersReadable"] == 12
    assert progress["chaptersGap"] == 3  # 11-13 sit below the highest chapter you have
    assert [s["kind"] for s in progress["segments"]][:4] == ["volume", "gap", "chapter", "wanted"]
    assert vols[0]["number"] == "6"


def test_decimal_ranges_survive_fractional_chapters():
    rows = [_chapter("1", "1"), _chapter("1.5", "1"), _chapter("2", "2")]
    ranges = coverage.volume_ranges(rows, [])
    assert ranges["1"]["last"] == Decimal("1.5")
