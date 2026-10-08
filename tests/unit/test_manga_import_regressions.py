#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Regression coverage for manga import failures reported in issue #278."""

from unittest.mock import MagicMock, patch

import requests


def _mal_payload():
    return {
        "id": 13,
        "title": "One Piece",
        "main_picture": {"large": "https://cdn.myanimelist.net/images/manga/2/253146l.jpg"},
        "alternative_titles": {"en": "One Piece", "ja": "ONE PIECE", "synonyms": []},
        "start_date": "1997-07-22",
        "status": "currently_publishing",
        "synopsis": "Pirates",
        "num_chapters": 0,
        "num_volumes": 0,
        "authors": [],
        "genres": [],
        "media_type": "manga",
    }


class TestMalCoverUrls:
    @patch("comicarr.myanimelist._make_request")
    def test_detail_cover_url_stays_absolute_for_backend_caching(self, mock_request):
        from comicarr import myanimelist

        mock_request.return_value = _mal_payload()

        result = myanimelist.get_manga_details("mal-13")

        assert result["cover_url"] == "https://cdn.myanimelist.net/images/manga/2/253146l.jpg"

    @patch("comicarr.myanimelist.listLibrary", return_value={})
    @patch("comicarr.myanimelist._make_request")
    def test_search_cover_url_remains_browser_proxied(self, mock_request, _mock_library):
        from comicarr import myanimelist

        mock_request.return_value = {"data": [{"node": _mal_payload()}], "paging": {}}

        result = myanimelist.search_manga("One Piece")

        assert result["results"][0]["comicimage"].startswith("/api/metadata/image-proxy?url=")


class TestMangaDexMalMatching:
    @patch("comicarr.mangadex._make_request")
    def test_alternate_title_recovers_after_primary_lookup_failure(self, mock_request):
        from comicarr import mangadex

        mock_request.side_effect = [
            None,
            {
                "result": "ok",
                "data": [
                    {
                        "id": "a1c7c817-4e59-43b7-9365-09675a149a6f",
                        "attributes": {"title": {"ja": "ワンピース"}, "altTitles": [], "links": {"mal": "13"}},
                    }
                ],
            },
        ]

        result = mangadex.find_by_mal_id("13", title_hint="One Piece", alternate_titles=["ワンピース"])

        assert result == "a1c7c817-4e59-43b7-9365-09675a149a6f"
        assert [call.kwargs["params"]["title"] for call in mock_request.call_args_list] == ["One Piece", "ワンピース"]

    @patch("comicarr.mangadex._make_request")
    def test_exact_mal_link_outranks_earlier_fuzzy_title_match(self, mock_request):
        from comicarr import mangadex

        mock_request.side_effect = [
            {
                "result": "ok",
                "data": [
                    {
                        "id": "fuzzy-candidate",
                        "attributes": {"title": {"en": "One Piece"}, "altTitles": [], "links": {}},
                    }
                ],
            },
            {
                "result": "ok",
                "data": [
                    {
                        "id": "exact-candidate",
                        "attributes": {"title": {"ja": "ワンピース"}, "altTitles": [], "links": {"mal": "13"}},
                    }
                ],
            },
        ]

        result = mangadex.find_by_mal_id("13", title_hint="One Piece", alternate_titles=["ワンピース"])

        assert result == "exact-candidate"

    @patch("comicarr.mangadex._make_request")
    def test_exact_only_lookup_skips_title_fallback(self, mock_request):
        from comicarr import mangadex

        mock_request.return_value = {
            "result": "ok",
            "data": [
                {
                    "id": "fuzzy-candidate",
                    "attributes": {"title": {"en": "One Piece"}, "altTitles": [], "links": {}},
                }
            ],
        }

        result = mangadex.find_by_mal_id(
            "13",
            title_hint="One Piece",
            allow_title_match=False,
        )

        assert result is None
        assert mangadex.find_by_mal_id("13", title_hint="One Piece") == "fuzzy-candidate"

    @patch("comicarr.mangadex._rate_limit")
    @patch("comicarr.mangadex.logger")
    @patch("comicarr.mangadex.requests.get")
    def test_bad_request_logs_bounded_provider_details(self, mock_get, mock_logger, _mock_rate_limit):
        from comicarr import mangadex

        response = MagicMock()
        response.status_code = 400
        response.text = "invalid parameter: " + ("x" * 1000)
        response.headers = {"x-request-id": "request-278"}
        response.raise_for_status.side_effect = requests.exceptions.HTTPError("400 Client Error", response=response)
        mock_get.return_value = response

        result = mangadex._make_request("/manga", params={"title": "One Piece"})

        assert result is None
        message = " ".join(str(part) for call in mock_logger.error.call_args_list for part in call.args)
        assert "request-278" in message
        assert "invalid parameter" in message
        assert len(message) < 800


class TestMangaChapterFallback:
    @patch("comicarr.importer.db")
    @patch("comicarr.CONFIG")
    def test_mal_total_creates_only_missing_placeholder_chapters(self, mock_config, mock_db):
        from comicarr import importer

        mock_config.MANGADEX_LANGUAGES = "en"
        mock_db.select_all.return_value = [{"Int_IssueNumber": 1000, "ChapterNumber": "1.0", "Issue_Number": "1.0"}]

        result = importer._populate_manga_chapters(
            "mal-13",
            "One Piece",
            mangadex_uuid=None,
            mal_num_chapters="3",
            controlValueDict={"ComicID": "mal-13"},
        )

        issue_upserts = [call.args[1] for call in mock_db.upsert.call_args_list if call.args[0] == "issues"]
        assert [values["IssueID"] for values in issue_upserts] == ["mal-13-ch2", "mal-13-ch3"]
        assert all(values["Status"] == "Skipped" for values in issue_upserts)
        assert result["total"] == 3
