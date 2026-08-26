#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Regression coverage for MangaDex aggregate shape quirks (#765).

The aggregate endpoint returns "volumes" (and sometimes "chapters") as a keyed
object normally, but as a bare JSON array when empty. Calling .items() on the
array aborted manga import for chapterless series with
"'list' object has no attribute 'items'".
"""

from unittest.mock import patch

MANGA_ID = "15edb207-8ef9-4392-81b1-4ac92b31496b"


class TestGetTotalChapterCount:
    @patch("comicarr.mangadex._make_request")
    def test_counts_unique_chapters_across_volumes(self, mock_request):
        from comicarr import mangadex

        mock_request.return_value = {
            "result": "ok",
            "volumes": {
                "1": {"chapters": {"1": {"chapter": "1"}, "2": {"chapter": "2"}}},
                "2": {"chapters": {"3": {"chapter": "3"}}},
            },
        }

        assert mangadex.get_total_chapter_count(MANGA_ID) == 3

    @patch("comicarr.mangadex._make_request")
    def test_empty_volumes_list_returns_zero(self, mock_request):
        # MangaDex returns "volumes": [] (a list) when a manga has no chapters.
        from comicarr import mangadex

        mock_request.return_value = {"result": "ok", "volumes": []}

        assert mangadex.get_total_chapter_count(MANGA_ID) == 0

    @patch("comicarr.mangadex._make_request")
    def test_volumes_as_list_of_volume_objects(self, mock_request):
        from comicarr import mangadex

        mock_request.return_value = {
            "result": "ok",
            "volumes": [
                {"chapters": {"1": {"chapter": "1"}}},
                {"chapters": {"2": {"chapter": "2"}}},
            ],
        }

        assert mangadex.get_total_chapter_count(MANGA_ID) == 2

    @patch("comicarr.mangadex._make_request")
    def test_chapters_as_list_inside_volume(self, mock_request):
        from comicarr import mangadex

        mock_request.return_value = {
            "result": "ok",
            "volumes": {"1": {"chapters": [{"chapter": "1"}, {"chapter": "1.5"}]}},
        }

        assert mangadex.get_total_chapter_count(MANGA_ID) == 2

    @patch("comicarr.mangadex._make_request")
    def test_failed_request_returns_zero(self, mock_request):
        from comicarr import mangadex

        mock_request.return_value = None

        assert mangadex.get_total_chapter_count(MANGA_ID) == 0


class TestAggregateValues:
    def test_dict_yields_values(self):
        from comicarr import mangadex

        assert list(mangadex._aggregate_values({"a": 1, "b": 2})) == [1, 2]

    def test_list_passes_through(self):
        from comicarr import mangadex

        assert mangadex._aggregate_values([1, 2]) == [1, 2]

    def test_none_yields_nothing(self):
        from comicarr import mangadex

        assert list(mangadex._aggregate_values(None)) == []
