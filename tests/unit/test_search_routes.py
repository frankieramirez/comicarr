#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""One classifier and one published health read for Acquisition routes."""

import pytest

from comicarr.app.search import routes
from comicarr.app.search.providers import ProviderCandidate


class TestClassifyByKind:
    @pytest.mark.parametrize(
        ("kind", "route"),
        [
            ("torznab", "torrent"),
            ("torrent", "torrent"),
            ("newznab", "nzb"),
            ("experimental", "nzb"),
            ("ddl", "ddl"),
        ],
    )
    def test_every_provider_kind_maps_to_its_route(self, kind, route):
        candidate = ProviderCandidate(name="p", kind=kind, execution_name="p")
        assert routes.classify(candidate) == route
        assert candidate.route == route


class TestClassifyByStatsRow:
    @pytest.mark.parametrize(
        ("row", "route"),
        [
            ({"type": "ddl(getcomics)"}, "ddl"),
            ({"type": "torznab"}, "torrent"),
            ({"type": "newznab"}, "nzb"),
            ({"type": "", "provider": "DDL(External)"}, "ddl"),
            ({"type": "", "provider": "my torznab"}, "torrent"),
            ({"type": "", "provider": "32p"}, "torrent"),
            ({"type": "", "provider": "nzb.su"}, "nzb"),
        ],
    )
    def test_stats_rows_classify_by_type_then_name(self, row, route):
        assert routes.classify(row) == route


class TestClassifyBySiteName:
    class _Config:
        EXTRA_TORZNABS = [("prowlarr", "https://prowlarr.local/api", "1", "key", "8020", "1", 4)]

    @pytest.mark.parametrize(
        ("site", "route"),
        [
            ("DDL(GetComics)", "ddl"),
            ("external", "ddl"),
            ("32p", "torrent"),
            ("public torrents", "torrent"),
            ("prowlarr", "torrent"),
            ("https://prowlarr.local/api", "torrent"),
            ("nzb.su", "nzb"),
        ],
    )
    def test_bare_site_names_classify_with_the_config_fallback(self, site, route):
        assert routes.classify(site, config=self._Config()) == route


class TestRouteHealth:
    class _Ctx:
        config = object()
        provider_blocklist = []

    def test_blocked_when_no_route_is_viable(self, monkeypatch):
        from comicarr.app.search import health

        monkeypatch.setattr(health, "get_search_health", lambda *_a, **_k: {"routes": {"nzb": {"ready": False}}})
        monkeypatch.setattr(health, "blocking_route_reason", lambda _routes: "client_not_ready")
        result = routes.route_health(self._Ctx())
        assert result["success"] is False
        assert result["status"] == "blocked"
        assert result["error"] == "client_not_ready"

    def test_succeeds_when_any_route_is_ready(self, monkeypatch):
        from comicarr.app.search import health

        payload = {"routes": {"torrent": {"ready": True}}}
        monkeypatch.setattr(health, "get_search_health", lambda *_a, **_k: payload)
        result = routes.route_health(self._Ctx())
        assert result["success"] is True
        assert result["routes"] == payload["routes"]
