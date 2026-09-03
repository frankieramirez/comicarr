#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Executable contract for manga chapter and volume ledgers."""

from comicarr.app.acquisition.models import AcquisitionIntent, Fulfillment
from comicarr.app.acquisition.policy import EligibilityInput, evaluate_eligibility
from comicarr.app.manga.ledger import (
    apply_volume_coverage,
    blended_progress,
    chapter_id,
    covers_to_volume_rows,
    is_volume_target,
    last_released_volume,
    merge_refresh_row,
    normalize_volume_number,
    volume_id,
    volume_numbers_match,
)


def test_ids_match_importer_chapter_scheme_and_keep_volumes_off_issues():
    assert chapter_id("md-onepiece", "1100") == "md-onepiece-ch1100"
    assert volume_id("md-onepiece", "1.0") == "md-onepiece-v1"
    assert volume_id("md-onepiece", "none") is None


def test_last_released_volume_is_cover_feed_max_not_aggregate_holes():
    covers = [
        {"attributes": {"volume": "1", "createdAt": "2022-06-13T00:00:00"}},
        {"attributes": {"volume": "115", "createdAt": "2022-06-13T00:00:00"}},
        {"attributes": {"volume": "7", "createdAt": "2022-06-13T00:00:00"}},
    ]
    assert last_released_volume(covers) == "115"
    rows = covers_to_volume_rows("md-onepiece", covers)
    assert [row["VolumeID"] for row in rows] == [
        "md-onepiece-v1",
        "md-onepiece-v115",
        "md-onepiece-v7",
    ]
    assert rows[0]["KnownAt"] == "2022-06-13T00:00:00"


def test_owning_a_volume_covers_only_mapped_chapters():
    chapters = [
        {"id": "md-x-ch1", "fulfillment": "missing", "acquisitionIntent": "policy"},
        {"id": "md-x-ch2", "fulfillment": "missing", "acquisitionIntent": "policy"},
        {"id": "md-x-ch3", "fulfillment": "missing", "acquisitionIntent": "skipped"},
        {"id": "md-x-ch4", "fulfillment": "downloaded", "acquisitionIntent": "policy"},
    ]
    projected = apply_volume_coverage(
        chapters,
        owned_volumes=["1"],
        containment={"1": ["md-x-ch1", "md-x-ch3"], "2": ["md-x-ch2"]},
    )
    by_id = {row["id"]: row for row in projected}
    assert by_id["md-x-ch1"]["fulfillment"] == Fulfillment.COVERED.value
    assert by_id["md-x-ch1"]["covered"] is True
    assert by_id["md-x-ch1"]["owned"] is False
    assert by_id["md-x-ch1"]["missing"] is False
    assert by_id["md-x-ch2"]["fulfillment"] == "missing"
    assert by_id["md-x-ch3"]["fulfillment"] == "missing"
    assert by_id["md-x-ch4"]["fulfillment"] == "downloaded"


def test_unknown_containment_does_not_cover_chapters():
    chapters = [{"id": "md-x-ch8", "fulfillment": "missing", "acquisitionIntent": "policy"}]
    projected = apply_volume_coverage(chapters, owned_volumes=["8"], containment={})
    assert projected[0]["fulfillment"] == "missing"
    assert projected[0].get("covered") is not True


def test_blended_frontier_counts_volumes_then_chapters_beyond():
    volumes = [{"VolumeNumber": n} for n in ("1", "2", "3")]
    chapters = [
        {"id": "md-x-ch1", "VolumeNumber": "1", "owned": False},
        {"id": "md-x-ch100", "VolumeNumber": None, "owned": False, "fulfillment": "missing"},
        {"id": "md-x-ch101", "VolumeNumber": "4", "owned": True, "fulfillment": "downloaded"},
    ]
    progress = blended_progress(volumes, chapters, owned_volumes=["1"], containment={"1": ["md-x-ch1"]})
    assert progress["lastReleasedVolume"] == "3"
    assert progress["volumeTotal"] == 3
    assert progress["volumeHave"] == 1
    assert progress["volumeMissing"] == 2
    assert progress["chapterBeyondTotal"] == 2
    assert progress["chapterBeyondHave"] == 1
    assert progress["missing"] == 3
    assert progress["have"] == 2
    assert progress["total"] == 5


def test_refresh_preserves_operator_status():
    incoming = {"IssueID": "md-x-ch1", "ChapterNumber": "1", "Status": "Skipped"}
    existing = {"IssueID": "md-x-ch1", "Status": "Downloaded", "AcquisitionIntent": "skipped", "Location": "v1.cbz"}
    merged = merge_refresh_row(existing, incoming)
    assert merged["Status"] == "Downloaded"
    assert merged["AcquisitionIntent"] == "skipped"
    assert merged["Location"] == "v1.cbz"
    assert merged["ChapterNumber"] == "1"


def test_covered_fulfillment_is_not_have_and_is_not_searchable():
    assert Fulfillment.COVERED.is_owned is False
    assert Fulfillment.COVERED.is_covered is True
    decision = evaluate_eligibility(
        EligibilityInput(
            series_active=True,
            intent=AcquisitionIntent.POLICY,
            fulfillment=Fulfillment.COVERED,
        ),
    )
    assert decision.eligible is False
    assert decision.reason == "covered"


def test_is_volume_target_requires_a_volume_and_no_chapter():
    """The single owner of the volume-vs-chapter rule, used by search and packs."""
    assert is_volume_target(None, "1") is True
    assert is_volume_target("", "1") is True
    # A chapter that happens to know its volume is still a chapter -- this is
    # what stops a volume pack claiming "chapter 7" as "volume 7".
    assert is_volume_target("7", "1") is False
    assert is_volume_target("7", None) is False
    assert is_volume_target(None, None) is False


def test_volume_numbers_match_across_the_spellings_in_use():
    """A release writes "v01", the ledger stores "1", a pack yields int 1."""
    assert volume_numbers_match("v01", "1") is True
    assert volume_numbers_match("Vol. 3", 3) is True
    assert volume_numbers_match("01", 1) is True
    assert volume_numbers_match("v02", "1") is False


def test_volume_numbers_match_never_matches_on_missing_or_unparsable_data():
    """Returning False on junk keeps a parse failure from claiming a volume."""
    assert volume_numbers_match(None, "1") is False
    assert volume_numbers_match("v01", None) is False
    assert volume_numbers_match("", "") is False
    assert volume_numbers_match("none", "1") is False
    # "v" is only stripped when it introduces a number, so this stays unequal.
    assert volume_numbers_match("vTPB", "1") is False


def test_volume_numbers_match_keeps_fractional_volumes_distinct():
    """A fractional volume is its own volume, not a truncation of the integer.

    normalize_volume_number() already models fractional volumes, so 1.5 must
    not collapse into 1 the way an int(float(...)) comparison would.
    """
    assert volume_numbers_match("1.5", "1") is False
    assert volume_numbers_match("1.5", "1.5") is True


def test_normalize_volume_number_treats_none_sentinel_as_absent():
    assert normalize_volume_number("1.0") == "1"
    assert normalize_volume_number("none") is None
    assert normalize_volume_number("") is None


class TestVolumeNumbersMatchIsExact:
    """The matcher's own contract: no usable volume on either side means False.

    normalize_volume_number is a DISPLAY normaliser -- it preserves arbitrary
    text and formats floats to six significant digits -- so comparing through
    it made two non-volumes equal each other and lost precision.
    """

    def test_two_identical_non_volumes_do_not_match(self):
        """"TPB" is not a volume, so a TPB does not satisfy another TPB."""
        assert volume_numbers_match("TPB", "TPB") is False

    def test_precision_is_not_rounded_away(self):
        assert volume_numbers_match("1.0000001", "1") is False

    def test_padding_and_markers_still_match(self):
        assert volume_numbers_match("v01", "1") is True
        assert volume_numbers_match("01", "1") is True
        assert volume_numbers_match("v01.5", "1.5") is True

    def test_a_different_volume_still_does_not_match(self):
        assert volume_numbers_match("v01", "1.5") is False
