#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Language-priority de-duplication for MangaDex chapter lists (#937).

Numbered chapters that exist in several configured languages must keep the
earliest language in ``mangadex_languages``, not whichever upload MangaDex
returned last. Fallback languages fill gaps only.
"""

from unittest.mock import patch

import pytest

REPORTER_LANGUAGES = ["en", "ca", "el", "ro", "de", "fr", "pt-br", "es", "id", "ar"]


def _chapter(chapter_id, number, language, title=None):
    return {
        "id": chapter_id,
        "chapter": number,
        "language": language,
        "title": title or ("%s %s" % (language, number)),
    }


@pytest.fixture(autouse=True)
def _clear_mangadex_cache():
    from comicarr import mangadex

    mangadex.clear_cache()
    yield
    mangadex.clear_cache()


class TestPreferChapterUploads:
    def test_keeps_preferred_language_when_fallback_arrives_last(self):
        from comicarr import mangadex

        chapters = [
            _chapter("en-10", "10", "en", "English title"),
            _chapter("de-10", "10", "de", "Deutscher Titel"),
            _chapter("ar-10", "10", "ar", "عنوان عربي"),
        ]

        result = mangadex._prefer_chapter_uploads(chapters, REPORTER_LANGUAGES)

        assert [ch["id"] for ch in result] == ["en-10"]
        assert result[0]["title"] == "English title"

    def test_prefers_earlier_config_language_regardless_of_arrival_order(self):
        from comicarr import mangadex

        chapters = [
            _chapter("ar-10", "10", "ar"),
            _chapter("de-10", "10", "de"),
            _chapter("en-10", "10", "en"),
        ]

        result = mangadex._prefer_chapter_uploads(chapters, REPORTER_LANGUAGES)

        assert result[0]["id"] == "en-10"

    def test_falls_back_when_preferred_language_has_no_upload(self):
        from comicarr import mangadex

        chapters = [
            _chapter("fr-42", "42", "fr"),
            _chapter("de-42", "42", "de"),
        ]

        result = mangadex._prefer_chapter_uploads(chapters, REPORTER_LANGUAGES)

        assert [ch["id"] for ch in result] == ["de-42"]

    def test_selects_each_chapter_number_independently(self):
        from comicarr import mangadex

        chapters = [
            _chapter("en-1", "1", "en"),
            _chapter("de-1", "1", "de"),
            _chapter("fr-2", "2", "fr"),
            _chapter("en-3", "3", "en"),
            _chapter("ar-3", "3", "ar"),
        ]

        result = mangadex._prefer_chapter_uploads(chapters, ["en", "de", "fr", "ar"])
        by_number = {ch["chapter"]: ch["id"] for ch in result}

        assert by_number == {"1": "en-1", "2": "fr-2", "3": "en-3"}

    def test_oneshots_pass_through_without_collapsing(self):
        from comicarr import mangadex

        chapters = [
            _chapter("os-en", None, "en", "Oneshot EN"),
            _chapter("os-de", None, "de", "Oneshot DE"),
            _chapter("ch1-en", "1", "en"),
            _chapter("ch1-de", "1", "de"),
        ]

        result = mangadex._prefer_chapter_uploads(chapters, ["en", "de"])
        ids = [ch["id"] for ch in result]

        assert ids == ["ch1-en", "os-en", "os-de"]


class TestGetAllChaptersLanguagePriority:
    @patch("comicarr.mangadex.get_manga_chapters")
    def test_get_all_chapters_collapses_to_preferred_language(self, mock_chapters):
        from comicarr import mangadex

        mock_chapters.return_value = {
            "chapters": [
                _chapter("de-1", "1", "de", "Kapitel 1"),
                _chapter("en-1", "1", "en", "Chapter 1"),
                _chapter("fr-2", "2", "fr", "Chapitre 2"),
                _chapter("oneshot", None, "de", "Oneshot"),
            ],
            "pagination": {"total": 4, "limit": 100, "offset": 0, "returned": 4},
        }

        result = mangadex.get_all_chapters(
            "15edb207-8ef9-4392-81b1-4ac92b31496b",
            languages=["en", "de", "fr"],
            include_unavailable=False,
        )

        numbered = {ch["chapter"]: ch for ch in result if ch.get("chapter") is not None}
        oneshots = [ch for ch in result if ch.get("chapter") is None]

        assert numbered["1"]["id"] == "en-1"
        assert numbered["1"]["title"] == "Chapter 1"
        assert numbered["2"]["id"] == "fr-2"
        assert [ch["id"] for ch in oneshots] == ["oneshot"]
        assert [ch["chapter"] for ch in result if ch.get("chapter") is not None] == ["1", "2"]
