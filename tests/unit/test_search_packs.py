#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import pytest

from comicarr.app.search.packs import parse_pack_title


class TestVolumeRangePacks:
    def test_manga_volume_pack_with_year_range(self):
        result = parse_pack_title("Solo Leveling v01-14 (2021-2025) (Digital) (1r0n)")
        assert result == {
            "series": "Solo Leveling",
            "issues": "1-14",
            "kind": "volume",
            "year": "2021",
            "booktype": "TPB",
        }

    def test_vol_dot_spelling(self):
        result = parse_pack_title("Monster Vol. 1-9 (2014-2016)")
        assert result["kind"] == "volume"
        assert result["issues"] == "1-9"
        assert result["series"] == "Monster"

    def test_volumes_word_spelling(self):
        result = parse_pack_title("Berserk Volumes 1-41 (Digital)")
        assert result["kind"] == "volume"
        assert result["issues"] == "1-41"

    def test_v_to_v_range(self):
        result = parse_pack_title("Vagabond v1-v37")
        assert result["kind"] == "volume"
        assert result["issues"] == "1-37"

    def test_single_volume_is_not_a_pack(self):
        assert parse_pack_title("Solo Leveling v05 (2022) (Digital)") is None


class TestIssueRangePacks:
    def test_hash_issue_range(self):
        result = parse_pack_title("Batman #1-10 (2020)")
        assert result == {
            "series": "Batman",
            "issues": "1-10",
            "kind": "issue",
            "year": "2020",
            "booktype": "issue",
        }

    def test_zero_padded_issue_range(self):
        result = parse_pack_title("Invincible 001-144 (2003-2018) (digital)")
        assert result["kind"] == "issue"
        assert result["issues"] == "1-144"
        assert result["series"] == "Invincible"

    def test_series_with_number_in_name(self):
        result = parse_pack_title("Spider-Man 2099 #1-10 (2019)")
        assert result["series"] == "Spider-Man 2099"
        assert result["issues"] == "1-10"

    def test_single_issue_is_not_a_pack(self):
        assert parse_pack_title("Batman #5 (2020)") is None
        assert parse_pack_title("Example Series 001 (2024)") is None

    def test_ambiguous_short_bare_range_is_not_a_pack(self):
        # "05-06" is more likely a date fragment than a two-issue pack;
        # an unmarked range needs at least three issues to be believed.
        assert parse_pack_title("Example Series 05-06") is None

    def test_marked_short_range_is_still_a_pack(self):
        assert parse_pack_title("Example Series #5-6")["issues"] == "5-6"

    def test_unmarked_long_range_is_a_pack(self):
        assert parse_pack_title("Example Series 5-40")["issues"] == "5-40"


class TestChapterRangePacks:
    def test_chapter_range(self):
        result = parse_pack_title("One Piece c001-100 (Digital)")
        assert result["kind"] == "chapter"
        assert result["issues"] == "1-100"
        assert result["booktype"] == "issue"

    def test_chapters_word_spelling(self):
        result = parse_pack_title("Naruto Chapters 1-700")
        assert result["kind"] == "chapter"
        assert result["issues"] == "1-700"

    def test_chapter_zero_start(self):
        result = parse_pack_title("Solo Leveling c000-179 (2018-2023)")
        assert result["kind"] == "chapter"
        assert result["issues"] == "0-179"

    @pytest.mark.parametrize(
        "title",
        [
            "One Piece c001.5-003.5",
            "One Piece c1.5-10",
            "One Piece c1-10.5",
        ],
    )
    def test_fractional_endpoints_are_not_truncated_into_a_wrong_range(self, title):
        # Truncating "c001.5-003.5" to 1-3 would claim chapter 1, which the
        # pack does not contain. Range expansion is integer-only, so refuse
        # the release rather than cover the wrong chapters.
        assert parse_pack_title(title) is None


class TestNonPacks:
    @pytest.mark.parametrize(
        "title",
        [
            "Batman (2016-2020)",  # year range in parens only
            "Batman 1999-2005",  # bare year-to-year range
            "Batman - Detective Comics 027 (1939)",
            "2000AD prog 2000 (2016)",
            "Batman v2 #7 (2012)",  # volume marker + single issue
            "52 (2006)",
            "",
        ],
    )
    def test_not_detected_as_pack(self, title):
        assert parse_pack_title(title) is None

    def test_none_title(self):
        assert parse_pack_title(None) is None

    def test_reversed_range_rejected(self):
        assert parse_pack_title("Example 10-1 (2020)") is None

    def test_range_without_series_name_rejected(self):
        assert parse_pack_title("1-10") is None

    def test_huge_range_rejected(self):
        assert parse_pack_title("Example 1-5000") is None


class TestYearExtraction:
    def test_year_absent(self):
        result = parse_pack_title("Berserk Volumes 1-41 (Digital)")
        assert result["year"] is None

    def test_single_year_after_range(self):
        result = parse_pack_title("Batman #1-10 (2020)")
        assert result["year"] == "2020"
