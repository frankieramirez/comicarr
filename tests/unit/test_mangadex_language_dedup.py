#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Regression coverage for multi-language chapter de-duplication.

MangaDex returns a chapter number once per translated language. The importer
keys issues by chapter number alone (``importer.py`` -> ``IssueID`` of
``<mangaid>-ch<num>``) and upserts last-wins, so before this fix an enabled
fallback language could silently overwrite the preferred one and the chapter
surfaced in the UI in a language the operator never chose. ``get_all_chapters``
now collapses each chapter number to a single entry in the earliest configured
(priority) language, keeping the fallback only where the preferred language has
no upload.
"""

from unittest.mock import patch

MANGA_ID = "15edb207-8ef9-4392-81b1-4ac92b31496b"


def _chapter(num, language, title):
    return {
        "id": f"{language}-{num}",
        "chapter": num,
        "volume": None,
        "title": title,
        "language": language,
        "pages": 20,
        "publish_at": None,
        "created_at": None,
        "updated_at": None,
        "scanlation_group": None,
        "external_url": None,
    }


class TestLanguageDedup:
    @patch("comicarr.mangadex.get_manga_chapters")
    def test_preferred_language_wins_and_fallback_fills_gaps(self, mock_chapters):
        from comicarr import mangadex

        mangadex.clear_cache()
        mock_chapters.return_value = {
            "chapters": [
                _chapter("1", "de", "Kapitel Eins"),
                _chapter("1", "en", "Chapter One"),  # en outranks de -> wins ch1
                _chapter("2", "fr", "Chapitre Deux"),
                _chapter("2", "de", "Kapitel Zwei"),  # de outranks fr -> wins ch2
                _chapter("3", "fr", "Chapitre Trois"),  # only fr available -> kept
            ],
            "pagination": {"total": 5, "limit": 100, "offset": 0, "returned": 5},
        }

        result = mangadex.get_all_chapters(MANGA_ID, languages=["en", "de", "fr"], include_unavailable=False)

        by_num = {c["chapter"]: c for c in result}
        assert by_num["1"]["language"] == "en"
        assert by_num["2"]["language"] == "de"
        assert by_num["3"]["language"] == "fr"  # fallback fills the gap
        assert len([c for c in result if c["chapter"] == "1"]) == 1  # no duplicate

    @patch("comicarr.mangadex.get_manga_chapters")
    def test_unnumbered_chapters_are_preserved(self, mock_chapters):
        from comicarr import mangadex

        mangadex.clear_cache()
        mock_chapters.return_value = {
            "chapters": [
                _chapter(None, "en", "Oneshot"),
                _chapter("1", "en", "Chapter One"),
            ],
            "pagination": {"total": 2, "limit": 100, "offset": 0, "returned": 2},
        }

        result = mangadex.get_all_chapters(MANGA_ID, languages=["en"], include_unavailable=False)

        assert any(c["chapter"] is None for c in result)
        assert any(c["chapter"] == "1" for c in result)
