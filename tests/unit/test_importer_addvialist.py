"""
Tests for comicarr.importer.addvialist — mass-add queue handling.
"""

import queue
from unittest.mock import patch

import comicarr
from comicarr.importer import addvialist


def _run_single_item(series_queue, issue_queue, item):
    """Process one queue item then exit the addvialist loop."""
    series_queue.put(item)
    series_queue.put("exit")

    with patch("comicarr.importer.addComictoDB") as mock_add:
        with patch("comicarr.importer.time.sleep"):
            with patch.object(comicarr, "ADD_LIST", queue.Queue()):
                addvialist(series_queue, issue_queue)

    return mock_add


class TestAddvialistSeriesyear:
    def test_comicid_only_without_seriesyear(self):
        series_queue = queue.Queue()
        issue_queue = queue.Queue()
        item = {"comicid": "12345", "comicname": None}

        mock_add = _run_single_item(series_queue, issue_queue, item)

        mock_add.assert_called_once_with("12345")

    def test_comicname_without_seriesyear_key(self):
        series_queue = queue.Queue()
        issue_queue = queue.Queue()
        item = {"comicid": "12345", "comicname": "Spider-Man"}

        mock_add = _run_single_item(series_queue, issue_queue, item)

        mock_add.assert_called_once_with("12345")

    def test_comicname_with_seriesyear(self):
        series_queue = queue.Queue()
        issue_queue = queue.Queue()
        item = {"comicid": "12345", "comicname": "Spider-Man", "seriesyear": "2020"}

        mock_add = _run_single_item(series_queue, issue_queue, item)

        mock_add.assert_called_once_with("12345")
        assert comicarr.GLOBAL_MESSAGES["seriesyear"] == "2020"


class TestAddComicPayloads:
    def test_search_service_includes_seriesyear(self):
        from unittest.mock import MagicMock, patch

        from comicarr.app.search.service import add_comic

        ctx = MagicMock()
        with patch("comicarr.importer.importer_thread") as mock_thread:
            result = add_comic(ctx, "4050-99999")

        assert result["success"] is True
        mock_thread.assert_called_once_with(
            [{"comicid": "4050-99999", "comicname": None, "seriesyear": None}]
        )

    def test_series_service_includes_seriesyear(self):
        from unittest.mock import MagicMock, patch

        from comicarr.app.series.service import add_comic

        ctx = MagicMock()
        with patch("comicarr.importer.importer_thread") as mock_thread:
            result = add_comic(ctx, "4050-12345")

        assert result["success"] is True
        mock_thread.assert_called_once_with(
            [{"comicid": "12345", "comicname": None, "seriesyear": None}]
        )
