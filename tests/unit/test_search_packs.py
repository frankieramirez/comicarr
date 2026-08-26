#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import pytest

from comicarr.app.search.packs import parse_pack_title, parse_series_pack_title


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


class TestBraceMetadata:
    def test_brace_delimited_metadata_is_stripped(self):
        result = parse_pack_title("Solo Leveling v01-14 {2021-2025} {Digital}")
        assert result["kind"] == "volume"
        assert result["issues"] == "1-14"
        assert result["series"] == "Solo Leveling"
        assert result["year"] == "2021"


class TestSeriesPacks:
    def test_numberless_year_span_pack(self):
        result = parse_series_pack_title("Solo Leveling (2021-2026) (Digital) (1r0n)")
        assert result == {
            "series": "Solo Leveling",
            "issues": "all",
            "kind": "series",
            "year": "2021",
            "year_end": "2026",
            "booktype": "issue",
        }

    def test_brace_delimited_year_span_pack(self):
        result = parse_series_pack_title("Solo Leveling {2021-2023} {Digital} {Tapas} {4str0}")
        assert result["kind"] == "series"
        assert result["series"] == "Solo Leveling"
        assert result["year"] == "2021"

    def test_single_year_is_not_a_series_pack(self):
        # "(2021)" equally describes a lone volume or one-shot.
        assert parse_series_pack_title("Solo Leveling (2021) (Digital)") is None

    def test_digits_outside_metadata_groups_are_refused(self):
        assert parse_series_pack_title("Solo Leveling v05 (2022-2023)") is None
        assert parse_series_pack_title("Solo Leveling 001 (2021-2026)") is None

    def test_numbered_series_name_is_refused(self):
        # Conservative: "2099" is indistinguishable from an issue marker
        # from the title alone.
        assert parse_series_pack_title("Spider-Man 2099 (2019-2021)") is None

    def test_unbracketed_year_span_is_refused(self):
        assert parse_series_pack_title("Batman 1999-2005") is None

    def test_degenerate_year_spans_are_refused(self):
        # A reversed or single-repeated year is noise, not a span.
        assert parse_series_pack_title("Solo Leveling (2026-2021) (Digital)") is None
        assert parse_series_pack_title("Solo Leveling (2021-2021) (Digital)") is None

    def test_range_hidden_inside_bracket_group_is_refused(self):
        # "[v01-05]" is stripped with the metadata groups, so the outside-digit
        # check alone would escalate a 5-volume partial pack to "all".
        assert parse_series_pack_title("Example Series [v01-05] (2021-2022)") is None
        assert parse_series_pack_title("Example Series (v01-05) (2021-2022)") is None
        assert parse_series_pack_title("Example Series (2021-2026) [01-05]") is None

    def test_numbered_packs_are_not_series_packs(self):
        # parse_pack_title owns numbered ranges; this detector must not
        # double-claim them.
        assert parse_series_pack_title("Solo Leveling v01-14 (2021-2025)") is None

    def test_none_and_empty(self):
        assert parse_series_pack_title(None) is None
        assert parse_series_pack_title("") is None


class TestYearExtraction:
    def test_year_absent(self):
        result = parse_pack_title("Berserk Volumes 1-41 (Digital)")
        assert result["year"] is None

    def test_single_year_after_range(self):
        result = parse_pack_title("Batman #1-10 (2020)")
        assert result["year"] == "2020"
