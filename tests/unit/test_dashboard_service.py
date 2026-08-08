#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for the dashboard's panel-scoped reads."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comicarr.app.dashboard import service


@pytest.fixture(autouse=True)
def _dashboard_dependencies(monkeypatch):
    """Keep service tests focused on panel shape, not database transport."""
    runtime = SimpleNamespace(CONFIG=SimpleNamespace(COMIC_DIR=None, MANGA_DIR=None))
    monkeypatch.setattr(service, "comicarr", runtime)
    monkeypatch.setattr(service.dashboard_queries, "get_recent_activity", lambda cutoff: [])
    monkeypatch.setattr(service.dashboard_queries, "get_library_stats", lambda content_type=None: None)
    monkeypatch.setattr(service.dl_queries, "count_active_ddl_items", lambda: 0)
    monkeypatch.setattr(service.dl_queries, "get_active_ddl_preview", lambda limit: [])
    monkeypatch.setattr(service.storyarcs_service, "get_upcoming", lambda include_downloaded: [])


class TestLibraryPanel:
    """The KPI strip's aggregates."""

    def test_returns_combined_and_content_type_stats(self, monkeypatch):
        stats = {
            None: {"total_series": 10, "total_issues": 250, "total_expected": 500},
            "manga": {"manga_series": 2, "manga_have": 10, "manga_total": 20},
            "comic": {"comic_series": 8, "comic_have": 240, "comic_total": 480},
        }
        monkeypatch.setattr(
            service.dashboard_queries, "get_library_stats", lambda content_type=None: stats[content_type]
        )

        assert service.get_library_panel()["stats"] == {
            "total_series": 10,
            "total_issues": 250,
            "total_expected": 500,
            "completion_pct": 50.0,
            "manga_series": 2,
            "manga_have": 10,
            "manga_total": 20,
            "manga_completion_pct": 50.0,
            "comic_series": 8,
            "comic_have": 240,
            "comic_total": 480,
        }

    def test_completion_percentage_is_zero_when_no_expected_issues(self, monkeypatch):
        monkeypatch.setattr(
            service.dashboard_queries,
            "get_library_stats",
            lambda content_type=None: (
                {"total_series": 0, "total_issues": 0, "total_expected": 0} if content_type is None else None
            ),
        )

        assert service.get_library_panel()["stats"]["completion_pct"] == 0

    def test_a_failed_read_raises_instead_of_reporting_an_empty_library(self, monkeypatch):
        monkeypatch.setattr(
            service.dashboard_queries,
            "get_library_stats",
            MagicMock(side_effect=RuntimeError("connection failed")),
        )

        with pytest.raises(RuntimeError):
            service.get_library_panel()


class TestQueuePanel:
    """The active-download count and its preview."""

    def test_count_and_preview_share_the_active_predicate(self, monkeypatch):
        queue_items = [{"ID": "queued-1", "series": "Batman", "status": "Queued"}]
        get_active_preview = MagicMock(return_value=queue_items)
        monkeypatch.setattr(service.dl_queries, "count_active_ddl_items", lambda: 3)
        monkeypatch.setattr(service.dl_queries, "get_active_ddl_preview", get_active_preview)

        panel = service.get_queue_panel()

        get_active_preview.assert_called_once_with(limit=5)
        assert panel == {"count": 3, "items": queue_items}

    def test_a_failed_count_raises_instead_of_reporting_zero(self, monkeypatch):
        monkeypatch.setattr(
            service.dl_queries, "count_active_ddl_items", MagicMock(side_effect=RuntimeError("count failed"))
        )

        with pytest.raises(RuntimeError):
            service.get_queue_panel()


class TestActivityPanel:
    """The bounded recent-activity preview."""

    def test_returns_events_and_the_window_they_cover(self, monkeypatch):
        recent = [{"ComicName": "Spider-Man", "Issue_Number": "1", "IssueID": "200"}]
        monkeypatch.setattr(service.dashboard_queries, "get_recent_activity", lambda cutoff: recent)

        assert service.get_activity_panel() == {"events": recent, "days": 30}

    def test_uses_an_inclusive_30_day_cutoff(self, monkeypatch):
        seen = []
        monkeypatch.setattr(service, "recent_activity_cutoff", lambda: datetime(2026, 6, 10, 12, 0, 0))
        monkeypatch.setattr(service.dashboard_queries, "get_recent_activity", seen.append)

        service.get_activity_panel()

        assert seen == ["2026-06-10 12:00:00"]

    def test_a_failed_read_raises_instead_of_reporting_a_quiet_month(self, monkeypatch):
        monkeypatch.setattr(
            service.dashboard_queries,
            "get_recent_activity",
            MagicMock(side_effect=RuntimeError("connection failed")),
        )

        with pytest.raises(RuntimeError):
            service.get_activity_panel()


class TestUpcomingPanel:
    """This week's releases for series already in the library."""

    def test_returns_current_week_library_releases(self, monkeypatch):
        upcoming = [{"ComicName": "Batman", "IssueNumber": "5", "Status": "Wanted"}]
        get_upcoming = MagicMock(return_value=upcoming)
        monkeypatch.setattr(service.storyarcs_service, "get_upcoming", get_upcoming)

        panel = service.get_upcoming_panel()

        get_upcoming.assert_called_once_with(include_downloaded=True)
        assert panel == {"releases": upcoming}


class TestScanTargets:
    """Which libraries the header's scan action can start."""

    def test_reports_each_configured_directory(self):
        service.comicarr.CONFIG.COMIC_DIR = "/comics"
        service.comicarr.CONFIG.MANGA_DIR = "/manga"

        assert service.get_scan_targets() == {"comic": True, "manga": True}

    def test_unconfigured_directories_are_not_scan_targets(self):
        assert service.get_scan_targets() == {"comic": False, "manga": False}
