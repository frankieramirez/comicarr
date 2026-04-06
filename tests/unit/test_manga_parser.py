"""
Unit tests for comicarr/manga_parser.py manga filename parser.

Tests cover all common naming conventions, user-specific filenames,
and edge cases like decimal chapters, chapter ranges, and invalid inputs.
"""



class TestUserFilenames:
    """Tests for the user's actual manga filenames from their NAS."""

    def test_bleach_volume_based(self):
        """Bleach v1.cbz through Bleach v17.cbz — volume only."""
        from comicarr.manga_parser import parse_manga_filename

        for vol in range(1, 18):
            result = parse_manga_filename("Bleach v%d.cbz" % vol)
            assert result is not None, "Failed to parse Bleach v%d.cbz" % vol
            assert result["series_name"] == "Bleach"
            assert result["volume_number"] == vol
            assert result["chapter_number"] is None

    def test_chainsaw_man_chapter_based(self):
        """Chainsaw Man 165.cbz through Chainsaw Man 181.cbz — bare number chapter."""
        from comicarr.manga_parser import parse_manga_filename

        for ch in range(165, 182):
            result = parse_manga_filename("Chainsaw Man %d.cbz" % ch)
            assert result is not None, "Failed to parse Chainsaw Man %d.cbz" % ch
            assert result["series_name"] == "Chainsaw Man"
            assert result["chapter_number"] == float(ch)
            assert result["volume_number"] is None


class TestScanlatorGroupStyle:
    """Pattern: [Group] Title - c001 (v01) [quality].cbz"""

    def test_full_group_pattern(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("[Viz] One Piece - c1044 (v103) [HQ].cbz")
        assert result is not None
        assert result["series_name"] == "One Piece"
        assert result["chapter_number"] == 1044.0
        assert result["volume_number"] == 103
        assert result["group"] == "Viz"
        assert result["quality"] == "HQ"

    def test_group_without_volume(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("[Scanlation] Naruto - c700 [Digital].cbz")
        assert result is not None
        assert result["series_name"] == "Naruto"
        assert result["chapter_number"] == 700.0
        assert result["volume_number"] is None
        assert result["group"] == "Scanlation"
        assert result["quality"] == "Digital"

    def test_group_without_quality(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("[Team] Dragon Ball - c100 (v10).cbr")
        assert result is not None
        assert result["series_name"] == "Dragon Ball"
        assert result["chapter_number"] == 100.0
        assert result["volume_number"] == 10
        assert result["group"] == "Team"
        assert result["quality"] is None

    def test_group_minimal(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("[SL] Demon Slayer - c205.cbz")
        assert result is not None
        assert result["series_name"] == "Demon Slayer"
        assert result["chapter_number"] == 205.0
        assert result["group"] == "SL"


class TestVolumeChapterStyle:
    """Pattern: Title v01 c001.cbz"""

    def test_volume_and_chapter(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Berserk v01 c001.cbz")
        assert result is not None
        assert result["series_name"] == "Berserk"
        assert result["chapter_number"] == 1.0
        assert result["volume_number"] == 1
        assert result["group"] is None
        assert result["quality"] is None

    def test_high_numbers(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("One Piece v103 c1044.cbz")
        assert result is not None
        assert result["series_name"] == "One Piece"
        assert result["chapter_number"] == 1044.0
        assert result["volume_number"] == 103


class TestExplicitChapterLabel:
    """Pattern: Title - Chapter 001.cbz"""

    def test_chapter_label(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Attack on Titan - Chapter 139.cbz")
        assert result is not None
        assert result["series_name"] == "Attack on Titan"
        assert result["chapter_number"] == 139.0
        assert result["volume_number"] is None

    def test_chapter_label_lowercase(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("My Hero Academia - chapter 001.cbz")
        assert result is not None
        assert result["series_name"] == "My Hero Academia"
        assert result["chapter_number"] == 1.0


class TestAbbreviatedVolChapter:
    """Pattern: Title Vol.01 Ch.001.cbz"""

    def test_abbreviated_with_dots(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Jujutsu Kaisen Vol.15 Ch.130.cbz")
        assert result is not None
        assert result["series_name"] == "Jujutsu Kaisen"
        assert result["chapter_number"] == 130.0
        assert result["volume_number"] == 15

    def test_abbreviated_without_dots(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Spy x Family Vol 10 Ch 62.cbz")
        assert result is not None
        assert result["series_name"] == "Spy x Family"
        assert result["chapter_number"] == 62.0
        assert result["volume_number"] == 10


class TestBareNumber:
    """Pattern: Title 001.cbz — bare number = chapter"""

    def test_bare_number(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Vagabond 327.cbz")
        assert result is not None
        assert result["series_name"] == "Vagabond"
        assert result["chapter_number"] == 327.0
        assert result["volume_number"] is None

    def test_bare_number_zero_padded(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Slam Dunk 001.cbz")
        assert result is not None
        assert result["series_name"] == "Slam Dunk"
        assert result["chapter_number"] == 1.0


class TestVolumeOnly:
    """Pattern: Title v01.cbz — volume only"""

    def test_volume_only(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Death Note v12.cbz")
        assert result is not None
        assert result["series_name"] == "Death Note"
        assert result["chapter_number"] is None
        assert result["volume_number"] == 12

    def test_volume_only_uppercase_v(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Fullmetal Alchemist V27.cbz")
        assert result is not None
        assert result["series_name"] == "Fullmetal Alchemist"
        assert result["volume_number"] == 27


class TestDecimalChapters:
    """Edge case: decimal chapter numbers like 686.5"""

    def test_decimal_chapter_bare(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Bleach 686.5.cbz")
        assert result is not None
        assert result["series_name"] == "Bleach"
        assert result["chapter_number"] == 686.5

    def test_decimal_chapter_with_c_prefix(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Bleach c686.5.cbz")
        assert result is not None
        assert result["series_name"] == "Bleach"
        assert result["chapter_number"] == 686.5

    def test_decimal_chapter_in_group_pattern(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("[Viz] Bleach - c686.5 (v74) [HQ].cbz")
        assert result is not None
        assert result["chapter_number"] == 686.5


class TestChapterRanges:
    """Edge case: chapter ranges like c001-003 take the first chapter."""

    def test_range_with_group(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("[Group] Title - c001-c003 [HQ].cbz")
        assert result is not None
        assert result["chapter_number"] == 1.0

    def test_range_without_c_prefix_on_end(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("[Group] Title - c001-003 [HQ].cbz")
        assert result is not None
        assert result["chapter_number"] == 1.0


class TestValidExtensions:
    """Only .cbr, .cbz, .cb7, .pdf should be accepted."""

    def test_cbr_accepted(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Bleach v1.cbr")
        assert result is not None

    def test_cbz_accepted(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Bleach v1.cbz")
        assert result is not None

    def test_cb7_accepted(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Bleach v1.cb7")
        assert result is not None

    def test_pdf_accepted(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Bleach v1.pdf")
        assert result is not None

    def test_jpg_rejected(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("cover.jpg")
        assert result is None

    def test_txt_rejected(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("readme.txt")
        assert result is None

    def test_no_extension_rejected(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Bleach v1")
        assert result is None

    def test_case_insensitive_extension(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Bleach v1.CBZ")
        assert result is not None


class TestUnparseableInput:
    """Filenames with no parseable numbers should return None."""

    def test_no_numbers(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Just a Title.cbz")
        assert result is None

    def test_empty_string(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("")
        assert result is None

    def test_only_extension(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename(".cbz")
        assert result is None


class TestDirectoryStripping:
    """Parser should handle full paths by stripping directory components."""

    def test_full_path(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("/manga/Bleach/Bleach v1.cbz")
        assert result is not None
        assert result["series_name"] == "Bleach"
        assert result["volume_number"] == 1

    def test_relative_path(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("manga/Chainsaw Man/Chainsaw Man 165.cbz")
        assert result is not None
        assert result["series_name"] == "Chainsaw Man"
        assert result["chapter_number"] == 165.0


class TestResultStructure:
    """Verify the result dict always has the expected keys."""

    def test_all_keys_present(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("[Viz] One Piece - c1044 (v103) [HQ].cbz")
        assert result is not None
        expected_keys = {"series_name", "chapter_number", "volume_number", "group", "quality"}
        assert set(result.keys()) == expected_keys

    def test_minimal_result_keys(self):
        from comicarr.manga_parser import parse_manga_filename

        result = parse_manga_filename("Bleach v1.cbz")
        assert result is not None
        expected_keys = {"series_name", "chapter_number", "volume_number", "group", "quality"}
        assert set(result.keys()) == expected_keys

    def test_chapter_number_is_float_or_none(self):
        from comicarr.manga_parser import parse_manga_filename

        # When present, chapter_number should be a float
        result = parse_manga_filename("Bleach 100.cbz")
        assert isinstance(result["chapter_number"], float)

        # When absent, chapter_number should be None
        result = parse_manga_filename("Bleach v1.cbz")
        assert result["chapter_number"] is None

    def test_volume_number_is_int_or_none(self):
        from comicarr.manga_parser import parse_manga_filename

        # When present, volume_number should be an int
        result = parse_manga_filename("Bleach v1.cbz")
        assert isinstance(result["volume_number"], int)

        # When absent, volume_number should be None
        result = parse_manga_filename("Bleach 100.cbz")
        assert result["volume_number"] is None
