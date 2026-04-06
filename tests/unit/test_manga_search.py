"""
Unit tests for manga search query construction in comicarr/search.py.

Tests cover _build_manga_search_terms() which generates NZB/torrent-provider
query variations for manga chapters and volumes.
"""

from unittest.mock import patch

import pytest


# Patch the logger so _build_manga_search_terms can be imported without
# initializing the full comicarr application.
@pytest.fixture(autouse=True)
def _mock_logger():
    with patch("comicarr.search.logger") as mock_log:
        mock_log.fdebug = lambda *a, **kw: None
        yield mock_log


def _build():
    from comicarr.search import _build_manga_search_terms

    return _build_manga_search_terms


class TestBuildMangaSearchTermsChapterOnly:
    """When only a chapter number is provided (no volume)."""

    def test_integer_chapter(self):
        build = _build()
        terms = build("One Piece", "1044", None)
        assert '"One Piece" c1044' not in terms  # not quoted — raw name
        assert "One Piece c1044" in terms
        assert "One Piece chapter 1044" in terms

    def test_single_digit_chapter_is_zero_padded(self):
        build = _build()
        terms = build("Naruto", "5", None)
        assert "Naruto c005" in terms
        assert "Naruto chapter 005" in terms

    def test_two_digit_chapter_is_zero_padded(self):
        build = _build()
        terms = build("Bleach", "42", None)
        assert "Bleach c042" in terms
        assert "Bleach chapter 042" in terms

    def test_three_digit_chapter_no_extra_padding(self):
        build = _build()
        terms = build("Dragon Ball", "100", None)
        assert "Dragon Ball c100" in terms
        assert "Dragon Ball chapter 100" in terms

    def test_decimal_chapter(self):
        build = _build()
        terms = build("Chainsaw Man", "10.5", None)
        # Decimal chapters get formatted as e.g. "0010.5"
        assert any("c" in t and "10.5" in t for t in terms)
        assert any("chapter" in t and "10.5" in t for t in terms)

    def test_no_volume_term_when_volume_is_none(self):
        build = _build()
        terms = build("Naruto", "700", None)
        assert not any("v" in t.split()[-1] for t in terms if "c" not in t.split()[-1])


class TestBuildMangaSearchTermsVolumeOnly:
    """When only a volume number is provided (no chapter)."""

    def test_single_digit_volume(self):
        build = _build()
        terms = build("Bleach", None, "1")
        assert "Bleach v01" in terms

    def test_two_digit_volume(self):
        build = _build()
        terms = build("One Piece", None, "103")
        assert "One Piece v103" in terms

    def test_no_chapter_terms_when_chapter_is_none(self):
        build = _build()
        terms = build("Bleach", None, "5")
        assert not any("chapter" in t for t in terms)
        assert not any(" c0" in t or " c1" in t for t in terms)


class TestBuildMangaSearchTermsCombined:
    """When both chapter and volume are provided."""

    def test_combined_term_is_first(self):
        build = _build()
        terms = build("One Piece", "1044", "103")
        # Combined should be first (most specific)
        assert terms[0] == "One Piece v103c1044"

    def test_all_variations_present(self):
        build = _build()
        terms = build("One Piece", "1044", "103")
        assert "One Piece v103c1044" in terms
        assert "One Piece c1044" in terms
        assert "One Piece chapter 1044" in terms
        assert "One Piece v103" in terms

    def test_combined_zero_padding(self):
        build = _build()
        terms = build("Naruto", "5", "2")
        assert "Naruto v02c005" in terms
        assert "Naruto c005" in terms
        assert "Naruto v02" in terms


class TestBuildMangaSearchTermsEdgeCases:
    """Edge cases and error handling."""

    def test_empty_series_name_returns_empty(self):
        build = _build()
        assert build("", "1", "1") == []

    def test_none_series_name_returns_empty(self):
        build = _build()
        assert build(None, "1", "1") == []

    def test_both_none_returns_empty(self):
        build = _build()
        assert build("Test", None, None) == []

    def test_whitespace_stripped_from_name(self):
        build = _build()
        terms = build("  One Piece  ", "1", None)
        assert "One Piece c001" in terms

    def test_non_numeric_chapter_used_as_string(self):
        build = _build()
        terms = build("Test Series", "Special", None)
        assert any("cSpecial" in t for t in terms)

    def test_non_numeric_volume_used_as_string(self):
        build = _build()
        terms = build("Test Series", None, "TBD")
        assert any("vTBD" in t for t in terms)

    def test_chapter_zero(self):
        build = _build()
        terms = build("Test", "0", None)
        assert "Test c000" in terms
        assert "Test chapter 000" in terms

    def test_large_chapter_number(self):
        build = _build()
        terms = build("Test", "1500", None)
        assert "Test c1500" in terms

    def test_priority_order(self):
        """Combined terms should come before individual terms."""
        build = _build()
        terms = build("Series", "10", "5")
        combined_idx = terms.index("Series v05c010")
        chapter_idx = terms.index("Series c010")
        volume_idx = terms.index("Series v05")
        assert combined_idx < chapter_idx
        assert combined_idx < volume_idx
