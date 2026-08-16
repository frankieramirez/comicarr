#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The single place that knows how Series identity is encoded.

Before this module the answer was re-derived at 23 call sites in three
spellings, and the copies drifted apart often enough to account for six
consecutive fixes.
"""

import pytest

from comicarr.series_kind import (
    MANGA_PROVIDERS,
    SeriesProvider,
    add_prefix,
    chapter_source_id,
    is_manga,
    provider_of,
    provider_page_links,
    strip_prefix,
)


class TestProviderOf:
    @pytest.mark.parametrize(
        ("series_id", "expected"),
        (
            ("md-uuid-1", SeriesProvider.MANGADEX),
            ("mal-161890", SeriesProvider.MYANIMELIST),
            ("12345", SeriesProvider.COMICVINE),
            ("4050-12345", SeriesProvider.COMICVINE),
        ),
    )
    def test_a_bare_id_is_read_from_its_prefix(self, series_id, expected):
        assert provider_of(series_id) is expected

    def test_a_row_is_read_from_its_comicid(self):
        assert provider_of({"ComicID": "md-uuid-1"}) is SeriesProvider.MANGADEX

    @pytest.mark.parametrize("series", (None, "", {}, {"ComicID": None}))
    def test_an_absent_id_is_comicvine(self, series):
        assert provider_of(series) is SeriesProvider.COMICVINE

    def test_a_non_string_id_does_not_raise(self):
        assert provider_of(12345) is SeriesProvider.COMICVINE

    def test_the_manga_providers_are_the_prefixed_ones(self):
        assert MANGA_PROVIDERS == {SeriesProvider.MANGADEX, SeriesProvider.MYANIMELIST}


class TestIsManga:
    @pytest.mark.parametrize("series_id", ("md-uuid-1", "mal-161890"))
    def test_a_provider_prefix_is_sufficient(self, series_id):
        assert is_manga(series_id) is True

    def test_a_comicvine_id_is_not_manga(self):
        assert is_manga("12345") is False

    def test_content_type_covers_a_row_with_no_prefix(self):
        """Manga added before the prefixes existed still answers True."""
        assert is_manga({"ComicID": "999", "ContentType": "manga"}) is True

    def test_content_type_is_matched_loosely(self):
        assert is_manga({"ComicID": "999", "ContentType": " Manga "}) is True

    def test_a_comic_row_is_not_manga(self):
        assert is_manga({"ComicID": "999", "ContentType": "comic"}) is False

    @pytest.mark.parametrize("series_id", ("md-uuid-1", "mal-161890"))
    def test_an_explicit_comic_kind_overrides_a_manga_provider(self, series_id):
        assert is_manga({"ComicID": series_id, "ContentType": "comic"}) is False

    @pytest.mark.parametrize("series_id", ("md-uuid-1", "mal-161890"))
    def test_a_null_kind_falls_back_to_the_provider(self, series_id):
        assert is_manga({"ComicID": series_id, "ContentType": None}) is True

    def test_a_row_with_neither_signal_is_not_manga(self):
        assert is_manga({"ComicID": "999"}) is False

    def test_a_bare_unprefixed_id_cannot_know_about_content_type(self):
        """A string carries no ContentType — callers holding one must pass the row."""
        assert is_manga("999") is False


class TestChapterSourceId:
    def test_a_mangadex_series_carries_its_uuid_in_the_comicid(self):
        assert chapter_source_id("md-uuid-1") == "uuid-1"

    def test_a_mangadex_row_is_read_the_same_way(self):
        assert chapter_source_id({"ComicID": "md-uuid-1"}) == "uuid-1"

    def test_a_mal_series_fetches_chapters_against_its_resolved_mangadex_uuid(self):
        """MAL supplies metadata; MangaDex always supplies chapters."""
        row = {"ComicID": "mal-161890", "MangaDexID": "uuid-2"}
        assert chapter_source_id(row) == "uuid-2"

    def test_a_mal_series_without_a_resolved_uuid_has_no_chapter_source(self):
        assert chapter_source_id({"ComicID": "mal-999", "MangaDexID": None}) is None
        assert chapter_source_id({"ComicID": "mal-999"}) is None

    def test_a_bare_mal_id_cannot_answer(self):
        """The uuid lives in a column, so the row is required."""
        assert chapter_source_id("mal-161890") is None

    def test_a_stored_uuid_keeps_working_if_it_was_written_with_a_prefix(self):
        row = {"ComicID": "mal-161890", "MangaDexID": "md-uuid-2"}
        assert chapter_source_id(row) == "uuid-2"

    def test_a_comicvine_series_has_no_mangadex_chapter_source(self):
        assert chapter_source_id("12345") is None
        assert chapter_source_id({"ComicID": "999", "ContentType": "manga"}) is None


class TestProviderPageLinks:
    def test_comicvine_id_builds_the_volume_page(self):
        links = provider_page_links("160294")
        assert links == [
            {
                "provider": "comicvine",
                "label": "ComicVine",
                "url": "https://comicvine.gamespot.com/volume/4050-160294/",
            }
        ]
        assert "volume/4050-160294" in links[0]["url"]
        assert "/-/" not in links[0]["url"]

    def test_comicvine_volume_prefix_is_not_doubled(self):
        links = provider_page_links("4050-160294")
        assert links[0]["url"] == "https://comicvine.gamespot.com/volume/4050-160294/"

    def test_mangadex_id_builds_the_title_page(self):
        assert provider_page_links("md-uuid-1") == [
            {
                "provider": "mangadex",
                "label": "MangaDex",
                "url": "https://mangadex.org/title/uuid-1",
            }
        ]

    def test_mal_series_includes_mangadex_when_both_ids_exist(self):
        links = provider_page_links({"ComicID": "mal-161890", "MangaDexID": "md-uuid-2"})
        assert links == [
            {
                "provider": "myanimelist",
                "label": "MyAnimeList",
                "url": "https://myanimelist.net/manga/161890",
            },
            {
                "provider": "mangadex",
                "label": "MangaDex",
                "url": "https://mangadex.org/title/uuid-2",
            },
        ]

    def test_mal_without_mangadex_id_is_only_myanimelist(self):
        assert provider_page_links("mal-161890") == [
            {
                "provider": "myanimelist",
                "label": "MyAnimeList",
                "url": "https://myanimelist.net/manga/161890",
            }
        ]


class TestPrefixes:
    @pytest.mark.parametrize(
        ("series_id", "expected"),
        (
            ("md-uuid-1", "uuid-1"),
            ("mal-161890", "161890"),
            ("12345", "12345"),
            ("", ""),
            (None, ""),
        ),
    )
    def test_strip_prefix(self, series_id, expected):
        assert strip_prefix(series_id) == expected

    @pytest.mark.parametrize(
        ("raw_id", "provider", "expected"),
        (
            ("uuid-1", SeriesProvider.MANGADEX, "md-uuid-1"),
            ("md-uuid-1", SeriesProvider.MANGADEX, "md-uuid-1"),
            ("161890", SeriesProvider.MYANIMELIST, "mal-161890"),
            ("mal-161890", SeriesProvider.MYANIMELIST, "mal-161890"),
            ("12345", SeriesProvider.COMICVINE, "12345"),
            (None, SeriesProvider.MANGADEX, ""),
        ),
    )
    def test_add_prefix_is_idempotent(self, raw_id, provider, expected):
        assert add_prefix(raw_id, provider) == expected

    def test_add_prefix_never_relabels_another_providers_id(self):
        """Rewriting md- to mal- would invent a Series that does not exist."""
        assert add_prefix("md-uuid-1", SeriesProvider.MYANIMELIST) == "md-uuid-1"
        assert add_prefix("mal-13", SeriesProvider.MANGADEX) == "mal-13"

    @pytest.mark.parametrize("series_id", ("md-uuid-1", "mal-161890", "12345"))
    def test_strip_then_add_round_trips(self, series_id):
        provider = provider_of(series_id)
        assert add_prefix(strip_prefix(series_id), provider) == series_id
