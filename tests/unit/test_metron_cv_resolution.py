#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Regression coverage for adding series found via Metron search (#765).

Metron series ids are bare integers, indistinguishable from ComicVine volume
ids. Search results used to hand them straight to the CV-only add path, which
looked up an unrelated CV volume and died with "list index out of range".
Results now carry a "metron-" prefix and addComictoDB resolves it to the CV
volume id before any row is written.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import comicarr


class TestPrefixHelpers:
    def test_is_metron_id(self):
        from comicarr import metron

        assert metron.is_metron_id("metron-9253")
        assert not metron.is_metron_id("9253")
        assert not metron.is_metron_id(None)

    def test_strip_metron_prefix(self):
        from comicarr import metron

        assert metron.strip_metron_prefix("metron-9253") == "9253"
        assert metron.strip_metron_prefix("9253") == "9253"
        assert metron.strip_metron_prefix(None) == ""


class TestSearchSeriesIds:
    @patch("comicarr.metron._backfill_images")
    @patch("comicarr.metron.listLibrary", return_value={})
    def test_results_carry_metron_prefix(self, _mock_library, _mock_images):
        from comicarr import metron

        fake_series = SimpleNamespace(
            id=9253,
            display_name="Example Series (2020)",
            year_began=2020,
            issue_count=12,
            volume=1,
        )
        fake_api = MagicMock()
        fake_api.series_list.return_value = [fake_series]

        with patch.object(comicarr, "METRON_API", fake_api):
            result = metron.search_series("Example Series", limit=5)

        assert result["results"][0]["comicid"] == "metron-9253"
        assert result["results"][0]["metadata_source"] == "metron"


class TestGetCvId:
    def test_resolves_cv_id_from_series_detail(self):
        from comicarr import metron

        fake_api = MagicMock()
        fake_api.series.return_value = SimpleNamespace(cv_id=145678)

        with patch.object(comicarr, "METRON_API", fake_api):
            assert metron.get_cv_id("metron-9253") == "145678"

        fake_api.series.assert_called_once_with(9253)

    def test_returns_none_when_metron_has_no_mapping(self):
        from comicarr import metron

        fake_api = MagicMock()
        fake_api.series.return_value = SimpleNamespace(cv_id=None)

        with patch.object(comicarr, "METRON_API", fake_api):
            assert metron.get_cv_id("9253") is None

    def test_returns_none_when_api_not_initialized(self):
        from comicarr import metron

        with patch.object(comicarr, "METRON_API", None):
            assert metron.get_cv_id("9253") is None


class TestAddComictoDBResolution:
    def test_unresolvable_metron_id_raises_before_any_db_write(self):
        from comicarr import importer

        with (
            patch("comicarr.metron.get_cv_id", return_value=None),
            patch("comicarr.importer.db") as mock_db,
        ):
            with pytest.raises(ValueError, match="no ComicVine mapping"):
                importer.addComictoDB("metron-9253")

        mock_db.upsert.assert_not_called()

    def test_resolvable_metron_id_continues_with_cv_id(self):
        from comicarr import importer

        with (
            patch("comicarr.metron.get_cv_id", return_value="145678"),
            patch("comicarr.importer.db") as mock_db,
            patch("comicarr.importer.helpers"),
            patch("comicarr.importer.cv") as mock_cv,
            patch.object(comicarr, "COMICSORT", {}, create=True),
            patch.object(comicarr, "CONFIG", MagicMock(IMP_PATHS=False)),
        ):
            conn = mock_db.get_engine.return_value.connect.return_value.__enter__.return_value
            conn.execute.return_value = []
            mock_cv.getComic.return_value = None

            result = importer.addComictoDB("metron-9253")

        assert result == {"status": "incomplete"}
        mock_cv.getComic.assert_called_once_with("145678", "comic", series=True)


class TestAddComicServiceResolution:
    """The search add endpoint resolves metron- ids before queueing, so the id
    it queues, returns, and later narrates in activity events all agree - the
    frontend keys its comic-added settle/navigate handshake on that id."""

    def test_metron_id_resolved_before_queueing_and_returned(self):
        from comicarr.app.search import service

        with (
            patch("comicarr.metron.get_cv_id", return_value="145678") as mock_resolve,
            patch("comicarr.importer.importer_thread") as mock_thread,
        ):
            result = service.add_comic(None, "metron-9253")

        mock_resolve.assert_called_once_with("metron-9253")
        mock_thread.assert_called_once_with([{"comicid": "145678", "comicname": None, "seriesyear": None}])
        assert result["success"] is True
        assert result["comicid"] == "145678"

    def test_unmappable_metron_id_fails_without_queueing(self):
        from comicarr.app.search import service

        with (
            patch("comicarr.metron.get_cv_id", return_value=None),
            patch("comicarr.importer.importer_thread") as mock_thread,
        ):
            result = service.add_comic(None, "metron-9253")

        mock_thread.assert_not_called()
        assert result["success"] is False
        assert "no ComicVine mapping" in result["error"]

    def test_plain_comicvine_id_passes_through_untouched(self):
        from comicarr.app.search import service

        with (
            patch("comicarr.metron.get_cv_id") as mock_resolve,
            patch("comicarr.importer.importer_thread") as mock_thread,
        ):
            result = service.add_comic(None, "145678")

        mock_resolve.assert_not_called()
        mock_thread.assert_called_once_with([{"comicid": "145678", "comicname": None, "seriesyear": None}])
        assert result["comicid"] == "145678"


class TestAnnualSearchRouting:
    def test_annual_check_bypasses_metron(self):
        """The importer's annual sub-search matches CV volume ids inside CV
        description text (Metron results carry description=None and would
        crash it, then feed metron- ids to cv.getComic), so findComic must
        never route it to Metron."""
        from comicarr import mb

        class _StopSearch(Exception):
            pass

        fake_config = MagicMock(USE_METRON_SEARCH=True, MANGADEX_ENABLED=False)
        with (
            patch.object(comicarr, "CONFIG", fake_config),
            patch.object(comicarr, "METRON_API", MagicMock()),
            patch("comicarr.metron.search_series") as mock_metron_search,
            patch("comicarr.mb.listLibrary", side_effect=_StopSearch),
        ):
            with pytest.raises(_StopSearch):
                mb.findComic("Example Series annual", "series", issue=None, annual_check=True)

        mock_metron_search.assert_not_called()
