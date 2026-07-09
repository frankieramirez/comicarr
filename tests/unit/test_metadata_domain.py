"""
Tests for comicarr.app.metadata domain — Phase 2.

Covers: search routing, comic/issue info lookup, metatag operations,
artwork path validation and cover fetch allowlisting.
"""

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from comicarr.app.core.context import AppContext
from comicarr.app.metadata import service as metadata_service


def _make_test_ctx(**overrides):
    """Create a test AppContext for metadata domain tests."""
    config = MagicMock()
    config.MANGADEX_ENABLED = True
    config.CACHE_DIR = "/tmp/test_cache"
    config.HTTP_USERNAME = "admin"
    config.HTTP_PASSWORD = "hash"

    defaults = {
        "config": config,
        "jwt_secret_key": b"test_secret_key_32_bytes_padding!",
        "jwt_generation": 0,
    }
    defaults.update(overrides)
    return AppContext(**defaults)


def _jpeg_bytes(size=(2, 2), color="red"):
    """Minimal valid JPEG bytes for cache/fetch tests."""
    buf = BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="JPEG")
    return buf.getvalue()


# =============================================================================
# Search Service Tests
# =============================================================================


class TestSearchComics:
    def test_empty_name_returns_error(self):
        """Search with empty name returns error."""
        ctx = _make_test_ctx()
        result = metadata_service.search_comics(ctx, name="")
        assert "error" in result

    @patch("comicarr.mb")
    def test_comic_search_delegates_to_mb(self, mock_mb):
        """Comic search delegates to mb.findComic."""
        ctx = _make_test_ctx()
        mock_mb.findComic.return_value = [
            {"comicyear": "2020", "issues": 10, "haveit": "No"},
        ]

        result = metadata_service.search_comics(ctx, name="Batman")
        mock_mb.findComic.assert_called_once()
        assert "results" in result
        assert result["results"][0]["in_library"] is False

    @patch("comicarr.mb")
    def test_search_adds_in_library_flag(self, mock_mb):
        """Search adds in_library boolean based on haveit field."""
        ctx = _make_test_ctx()
        mock_mb.findComic.return_value = [
            {"comicyear": "2020", "issues": 5, "haveit": {"id": "123"}},
            {"comicyear": "2021", "issues": 3, "haveit": "No"},
        ]

        result = metadata_service.search_comics(ctx, name="Spider-Man")
        # Results are sorted by (comicyear, issues) descending — 2021 before 2020
        in_lib_flags = [r["in_library"] for r in result["results"]]
        assert True in in_lib_flags
        assert False in in_lib_flags

    @patch("comicarr.mb")
    def test_paginated_results_preserved(self, mock_mb):
        """Paginated results (dict with 'results' key) are preserved."""
        ctx = _make_test_ctx()
        mock_mb.findComic.return_value = {
            "results": [{"comicyear": "2020", "issues": 5, "haveit": "No"}],
            "pagination": {"total": 100, "limit": 10, "offset": 0},
        }

        result = metadata_service.search_comics(ctx, name="X-Men", limit=10, offset=0)
        assert "pagination" in result
        assert result["pagination"]["total"] == 100

    def test_invalid_pagination_returns_error(self):
        """Invalid pagination params return error."""
        ctx = _make_test_ctx()
        result = metadata_service.search_comics(ctx, name="Batman", limit="abc")
        assert "error" in result


class TestSearchManga:
    def test_manga_disabled_returns_error(self):
        """Manga search returns error when MangaDex is disabled."""
        ctx = _make_test_ctx()
        ctx.config.MANGADEX_ENABLED = False

        result = metadata_service.search_manga(ctx, name="One Piece")
        assert "error" in result

    @patch("comicarr.mangadex", create=True)
    def test_manga_search_delegates(self, mock_mangadex):
        """Manga search delegates to mangadex.search_manga."""
        ctx = _make_test_ctx()
        mock_mangadex.search_manga.return_value = {
            "results": [{"title": "One Piece"}],
            "pagination": {"total": 1},
        }

        metadata_service.search_manga(ctx, name="One Piece")
        mock_mangadex.search_manga.assert_called_once()


# =============================================================================
# Series Image Tests
# =============================================================================


class TestGetSeriesImage:
    def test_invalid_id_returns_none(self):
        """Non-numeric series ID returns None."""
        ctx = _make_test_ctx()
        result = metadata_service.get_series_image(ctx, "not-a-number")
        assert result is None

    @patch("comicarr.metron", create=True)
    def test_delegates_to_metron(self, mock_metron):
        """Valid series ID delegates to metron.get_series_image."""
        ctx = _make_test_ctx()
        mock_metron.get_series_image.return_value = "https://example.com/cover.jpg"

        result = metadata_service.get_series_image(ctx, "12345")
        assert result == "https://example.com/cover.jpg"


# =============================================================================
# Comic/Issue Info Tests
# =============================================================================


class TestGetComicInfo:
    @patch("comicarr.db")
    def test_returns_comic_data(self, mock_db):
        """get_comic_info returns comic data when found."""
        ctx = _make_test_ctx()
        mock_db.select_all.return_value = [{"ComicID": "123", "ComicName": "Batman"}]

        result = metadata_service.get_comic_info(ctx, "123")
        assert result["ComicName"] == "Batman"

    @patch("comicarr.db")
    def test_returns_none_when_not_found(self, mock_db):
        """get_comic_info returns None when comic not found."""
        ctx = _make_test_ctx()
        mock_db.select_all.return_value = []

        result = metadata_service.get_comic_info(ctx, "nonexistent")
        assert result is None


class TestGetIssueInfo:
    @patch("comicarr.db")
    def test_returns_issue_data(self, mock_db):
        """get_issue_info returns issue data when found."""
        ctx = _make_test_ctx()
        mock_db.select_all.return_value = [{"IssueID": "456", "Issue_Number": "1"}]

        result = metadata_service.get_issue_info(ctx, "456")
        assert result["Issue_Number"] == "1"


# =============================================================================
# Metatag Tests
# =============================================================================


class TestMetatag:
    @patch("comicarr.app.metadata.service._do_manual_metatag")
    def test_manual_metatag_success(self, mock_do_metatag):
        """manual_metatag calls internal _do_manual_metatag."""
        ctx = _make_test_ctx()

        result = metadata_service.manual_metatag(ctx, "issue123", "comic456")
        assert result["success"] is True
        mock_do_metatag.assert_called_once_with("issue123", comicid="comic456")

    @patch("comicarr.app.metadata.service._do_bulk_metatag")
    def test_bulk_metatag_success(self, mock_do_bulk):
        """bulk_metatag calls internal _do_bulk_metatag."""
        ctx = _make_test_ctx()

        issue_ids = ["issue1", "issue2", "issue3"]
        result = metadata_service.bulk_metatag(ctx, "comic456", issue_ids)
        assert result["success"] is True
        assert result["count"] == 3
        mock_do_bulk.assert_called_once_with("comic456", issue_ids)

    @patch("comicarr.app.metadata.service._do_manual_metatag")
    def test_metatag_handles_error(self, mock_do_metatag):
        """Metatag returns error on exception."""
        ctx = _make_test_ctx()
        mock_do_metatag.side_effect = Exception("tagging failed")

        result = metadata_service.manual_metatag(ctx, "issue123")
        assert result["success"] is False
        assert "tagging failed" in result["error"]


# =============================================================================
# Artwork path validation + cover fetch allowlist
# =============================================================================


class TestGetArtwork:
    @pytest.mark.parametrize(
        "comic_id",
        [
            "",
            "../etc/passwd",
            "/etc/passwd",
            "foo/bar",
            r"foo\bar",
            "..",
            "....//",
            None,
        ],
    )
    def test_rejects_unsafe_comic_id(self, comic_id, tmp_path):
        """Unsafe comic_id values return None without path escape."""
        ctx = _make_test_ctx()
        ctx.config.CACHE_DIR = str(tmp_path)

        with patch("comicarr.db") as mock_db:
            result = metadata_service.get_artwork(ctx, comic_id)
            assert result is None
            mock_db.select_all.assert_not_called()

    def test_accepts_numeric_and_prefixed_ids_cache_hit(self, tmp_path):
        """Safe ComicIDs (digits, 4050-N, md-*) return cached path on hit."""
        ctx = _make_test_ctx()
        ctx.config.CACHE_DIR = str(tmp_path)
        comic_id = "4050-12345"
        cache_file = tmp_path / (comic_id + ".jpg")
        cache_file.write_bytes(_jpeg_bytes())

        result = metadata_service.get_artwork(ctx, comic_id)
        assert result == str(cache_file)
        assert str(result).startswith(str(tmp_path))

    def test_md_comic_id_cache_hit(self, tmp_path):
        """MangaDex-style md-* ids are accepted for cache paths."""
        ctx = _make_test_ctx()
        ctx.config.CACHE_DIR = str(tmp_path)
        comic_id = "md-abc123"
        cache_file = tmp_path / (comic_id + ".jpg")
        cache_file.write_bytes(_jpeg_bytes())

        result = metadata_service.get_artwork(ctx, comic_id)
        assert result == str(cache_file)

    @patch("comicarr.app.metadata.image_fetch.requests.get")
    @patch("comicarr.db")
    def test_ssrf_url_does_not_call_network(self, mock_db, mock_get, tmp_path):
        """Loopback / evil hosts must not trigger requests.get; returns None."""
        ctx = _make_test_ctx()
        ctx.config.CACHE_DIR = str(tmp_path)
        mock_db.select_all.return_value = [
            {
                "ComicID": "12345",
                "ComicImageURL": "http://127.0.0.1/secret",
                "ComicImageALTURL": "https://evil.example/cover.jpg",
            }
        ]

        result = metadata_service.get_artwork(ctx, "12345")
        assert result is None
        mock_get.assert_not_called()

    @patch("comicarr.app.metadata.image_fetch.requests.get")
    @patch("comicarr.db")
    def test_allowlisted_fetch_writes_cache(self, mock_db, mock_get, tmp_path):
        """Allowlisted ComicVine host is fetched and written under CACHE_DIR."""
        ctx = _make_test_ctx()
        ctx.config.CACHE_DIR = str(tmp_path)
        comic_id = "12345"
        jpeg = _jpeg_bytes()
        mock_db.select_all.return_value = [
            {
                "ComicID": comic_id,
                "ComicImageURL": "https://comicvine.gamespot.com/a/uploads/scale_large/cover.jpg",
                "ComicImageALTURL": None,
            }
        ]
        mock_resp = _mock_image_response(jpeg)
        mock_get.return_value = mock_resp

        result = metadata_service.get_artwork(ctx, comic_id)
        expected = str(tmp_path / (comic_id + ".jpg"))
        assert result == expected
        assert (tmp_path / (comic_id + ".jpg")).read_bytes() == jpeg
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs.get("allow_redirects") is False
        assert call_kwargs.get("timeout") == (5, 10)
        assert call_kwargs.get("stream") is True

    @patch("comicarr.app.metadata.image_fetch.requests.get")
    @patch("comicarr.db")
    def test_allowlisted_metron_host(self, mock_db, mock_get, tmp_path):
        """static.metron.cloud is allowed for cover fetches."""
        ctx = _make_test_ctx()
        ctx.config.CACHE_DIR = str(tmp_path)
        comic_id = "99"
        jpeg = _jpeg_bytes(color="blue")
        mock_db.select_all.return_value = [
            {
                "ComicID": comic_id,
                "ComicImageURL": "https://static.metron.cloud/media/series/cover.jpg",
                "ComicImageALTURL": None,
            }
        ]
        mock_get.return_value = _mock_image_response(jpeg)

        result = metadata_service.get_artwork(ctx, comic_id)
        assert result == str(tmp_path / (comic_id + ".jpg"))
        mock_get.assert_called_once()

    def test_missing_cache_dir_returns_none(self):
        """No CACHE_DIR configured returns None."""
        ctx = _make_test_ctx()
        ctx.config.CACHE_DIR = None
        assert metadata_service.get_artwork(ctx, "12345") is None


def _mock_image_response(body, status_code=200, content_type="image/jpeg", content_length=None):
    """Mock requests response for streaming fetch_allowed_image."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    headers = {}
    if content_type is not None:
        headers["Content-Type"] = content_type
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    elif body is not None:
        headers["Content-Length"] = str(len(body))
    mock_resp.headers = headers
    mock_resp.iter_content = MagicMock(return_value=[body] if body else [])
    mock_resp.close = MagicMock()
    return mock_resp


# =============================================================================
# image_fetch allowlist + size/type guards
# =============================================================================


class TestImageFetch:
    def test_is_allowed_image_url_rejects_bad_urls(self):
        from comicarr.app.metadata.image_fetch import is_allowed_image_url

        assert is_allowed_image_url(None) is False
        assert is_allowed_image_url("") is False
        assert is_allowed_image_url("ftp://comicvine.gamespot.com/x.jpg") is False
        assert is_allowed_image_url("https://user:pass@comicvine.gamespot.com/x.jpg") is False
        assert is_allowed_image_url("https://evil.example/cover.jpg") is False
        assert is_allowed_image_url("https://evil.comicvine.gamespot.com/x.jpg") is False
        assert is_allowed_image_url("http://127.0.0.1/secret") is False

    def test_is_allowed_image_url_accepts_allowlisted(self):
        from comicarr.app.metadata.image_fetch import ALLOWED_IMAGE_DOMAINS, is_allowed_image_url

        for host in ALLOWED_IMAGE_DOMAINS:
            assert is_allowed_image_url("https://%s/cover.jpg" % host) is True

    @patch("comicarr.app.metadata.image_fetch.requests.get")
    def test_fetch_rejects_non_200(self, mock_get):
        from comicarr.app.metadata.image_fetch import fetch_allowed_image

        mock_get.return_value = _mock_image_response(b"x", status_code=302)
        assert fetch_allowed_image("https://comicvine.gamespot.com/c.jpg") is None

    @patch("comicarr.app.metadata.image_fetch.requests.get")
    def test_fetch_rejects_missing_content_type(self, mock_get):
        from comicarr.app.metadata.image_fetch import fetch_allowed_image

        mock_get.return_value = _mock_image_response(b"\xff\xd8", content_type=None)
        assert fetch_allowed_image("https://comicvine.gamespot.com/c.jpg") is None

    @patch("comicarr.app.metadata.image_fetch.requests.get")
    def test_fetch_rejects_disallowed_content_type(self, mock_get):
        from comicarr.app.metadata.image_fetch import fetch_allowed_image

        mock_get.return_value = _mock_image_response(b"{}", content_type="application/json")
        assert fetch_allowed_image("https://comicvine.gamespot.com/c.jpg") is None

    @patch("comicarr.app.metadata.image_fetch.requests.get")
    def test_fetch_rejects_content_length_over_cap(self, mock_get):
        from comicarr.app.metadata import image_fetch as image_fetch_mod

        mock_get.return_value = _mock_image_response(
            b"x",
            content_length=image_fetch_mod.MAX_IMAGE_BYTES + 1,
        )
        assert image_fetch_mod.fetch_allowed_image("https://comicvine.gamespot.com/c.jpg") is None
        mock_get.return_value.iter_content.assert_not_called()

    @patch("comicarr.app.metadata.image_fetch.requests.get")
    def test_fetch_aborts_when_stream_exceeds_cap(self, mock_get):
        from comicarr.app.metadata import image_fetch as image_fetch_mod

        oversized = b"a" * (image_fetch_mod.MAX_IMAGE_BYTES + 1)
        mock_resp = _mock_image_response(oversized, content_length=None)
        # omit Content-Length so only streaming budget applies
        mock_resp.headers = {"Content-Type": "image/jpeg"}
        mock_get.return_value = mock_resp
        assert image_fetch_mod.fetch_allowed_image("https://comicvine.gamespot.com/c.jpg") is None

    @patch("comicarr.app.metadata.image_fetch.requests.get")
    def test_fetch_success_returns_bytes_and_type(self, mock_get):
        from comicarr.app.metadata.image_fetch import fetch_allowed_image

        jpeg = _jpeg_bytes()
        mock_get.return_value = _mock_image_response(jpeg, content_type="image/jpeg; charset=binary")
        result = fetch_allowed_image("https://comicvine.gamespot.com/c.jpg")
        assert result == (jpeg, "image/jpeg")
        assert mock_get.call_args.kwargs.get("stream") is True


# =============================================================================
# image-proxy router (shared helper)
# =============================================================================


class TestImageProxy:
    def test_non_allowlisted_returns_403(self):
        from comicarr.app.metadata.router import image_proxy

        response = image_proxy(url="https://evil.example/cover.jpg")
        assert response.status_code == 403
        assert response.body  # JSONResponse
        assert b"Domain not allowed" in response.body

    @patch("comicarr.app.metadata.router.fetch_allowed_image")
    def test_allowlisted_fetch_failure_returns_502(self, mock_fetch):
        from comicarr.app.metadata.router import image_proxy

        mock_fetch.return_value = None
        response = image_proxy(url="https://comicvine.gamespot.com/c.jpg")
        assert response.status_code == 502
        assert b"Failed to fetch image" in response.body

    @patch("comicarr.app.metadata.router.fetch_allowed_image")
    def test_success_returns_image_bytes(self, mock_fetch):
        from comicarr.app.metadata.router import image_proxy

        jpeg = _jpeg_bytes()
        mock_fetch.return_value = (jpeg, "image/jpeg")
        response = image_proxy(url="https://comicvine.gamespot.com/c.jpg")
        assert response.status_code == 200
        assert response.body == jpeg
        assert response.media_type == "image/jpeg"
