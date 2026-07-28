#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Truthful acquisition health and route-readiness contracts."""

import time
from types import SimpleNamespace

import pytest

import comicarr
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema, refresh_runtime_state
from comicarr.app.acquisition.models import DispatchState, ItemOutcome
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.search import health
from comicarr.app.search import service as search_service
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import metadata


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    engine = get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready is True
    assert refresh_runtime_state(None, engine).blocked is False
    yield
    shutdown_engine()


def _config(tmp_path, **overrides):
    ddl = tmp_path / "ddl"
    ddl.mkdir()
    values = {
        "ENABLE_DDL": True,
        "ENABLE_GETCOMICS": True,
        "ENABLE_EXTERNAL_SERVER": False,
        "DDL_LOCATION": str(ddl),
        "NEWZNAB": True,
        "EXPERIMENTAL": False,
        "EXTRA_NEWZNABS": [["Indexer", "https://user:secret@indexer.test", "1", "key", "", "1"]],
        "NZB_DOWNLOADER": 0,
        "SAB_HOST": "https://user:secret@sab.test",
        "SAB_APIKEY": "top-secret-key",
        "SAB_DIRECTORY": "/downloads",
        "ENABLE_TORRENT_SEARCH": True,
        "ENABLE_TORRENTS": True,
        "ENABLE_32P": False,
        "ENABLE_PUBLIC": False,
        "ENABLE_TORZNAB": True,
        "EXTRA_TORZNABS": [["Torrent", "https://torrent.test", "1", "key", "", "1"]],
        "TORRENT_DOWNLOADER": 5,
        "QBITTORRENT_HOST": None,
        "PROVIDER_ORDER": {"0": "DDL(GetComics)", "1": "Indexer", "2": "Torrent"},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_route_readiness_is_independent_and_never_exposes_credentials(tmp_path):
    provider_stats = [
        {"provider": "DDL(GetComics)", "type": "ddl", "active": False, "lastrun": 100, "hits": 1},
        {"provider": "Indexer", "type": "nzb", "active": True, "lastrun": 200, "hits": 0},
        {"provider": "Torrent", "type": "torznab", "active": False, "lastrun": 300, "hits": 2},
    ]

    routes = health.build_route_readiness(
        _config(tmp_path),
        provider_stats=provider_stats,
        provider_blocklist=[{"site": "Indexer", "resume": int(time.time()) + 60, "reason": "token=secret outage"}],
    )

    assert routes["ddl"]["enabled"] is True
    assert routes["ddl"]["ready"] is True
    assert routes["nzb"]["enabled"] is True
    assert routes["nzb"]["active"] is True
    assert routes["nzb"]["running"] is True
    assert routes["nzb"]["blocked"] is True
    assert routes["torrent"]["enabled"] is True
    assert routes["torrent"]["ready"] is False
    # qBittorrent can be monitored now, so the blocker is the missing host
    # rather than the client being uncorrelatable.
    assert routes["torrent"]["restart_safe"] is True
    assert routes["torrent"]["reason"] == "client_not_ready"
    assert health.has_viable_route(routes) is True
    serialized = str(routes)
    assert "top-secret-key" not in serialized
    assert "user:secret" not in serialized
    assert "token=secret" not in serialized


def test_health_explains_configured_but_unattempted_torznab_without_secrets(tmp_path):
    routes = health.build_route_readiness(
        _config(tmp_path),
        provider_stats=[{"provider": "Torrent", "type": "torznab", "active": False, "lastrun": 0, "hits": 0}],
    )

    torrent = routes["torrent"]
    assert torrent["configured_provider_count"] == 1
    assert torrent["executable_provider_count"] == 1
    assert torrent["attempted_provider_count"] == 0
    assert torrent["providers"] == [
        {"name": "Torrent", "kind": "torznab", "blocked": False, "attempted": False, "last_attempt": None}
    ]
    assert "top-secret-key" not in str(torrent)


def test_health_tolerates_malformed_provider_and_history_timestamps(tmp_path):
    routes = health.build_route_readiness(
        _config(tmp_path),
        provider_stats=[
            {
                "provider": "DDL(GetComics)",
                "type": "ddl",
                "active": False,
                "lastrun": "not-a-timestamp",
                "hits": 0,
            }
        ],
        route_history={
            "ddl": {
                "prev_run_timestamp": "also-not-a-timestamp",
                "last_failure_timestamp": "invalid-failure-time",
                "last_error": "token=secret provider error",
            }
        },
    )

    ddl = routes["ddl"]
    assert ddl["last_attempt"] is None
    assert ddl["last_success"] is None
    assert ddl["last_failure"] is None
    assert "secret" not in str(ddl)


def test_disabled_torrent_handoff_is_not_reported_as_executable(tmp_path):
    routes = health.build_route_readiness(
        _config(tmp_path, ENABLE_TORRENTS=False),
        provider_stats=[{"provider": "Torrent", "type": "torznab", "active": False, "lastrun": 0, "hits": 0}],
    )

    assert routes["torrent"]["configured_provider_count"] == 1
    assert routes["torrent"]["executable_provider_count"] == 0


def test_watchfolder_is_never_reported_viable(tmp_path):
    """A watch folder hands the torrent off with no client-side identity to
    poll, so a restart cannot correlate it with anything."""
    routes = health.build_route_readiness(
        _config(tmp_path, TORRENT_DOWNLOADER=0, LOCAL_WATCHDIR=str(tmp_path)),
    )

    assert routes["torrent"]["enabled"] is True
    assert routes["torrent"]["restart_safe"] is False
    assert routes["torrent"]["ready"] is False
    assert routes["torrent"]["reason"] == "unsupported_restart_correlation"


@pytest.mark.parametrize(
    ("downloader", "host_key", "path_key"),
    [
        (1, "UTORRENT_HOST", None),
        (2, "RTORRENT_HOST", "RTORRENT_DIRECTORY"),
        (3, "TRANSMISSION_HOST", "TRANSMISSION_DIRECTORY"),
        (4, "DELUGE_HOST", "DELUGE_DOWNLOAD_DIRECTORY"),
        (5, "QBITTORRENT_HOST", "QBITTORRENT_FOLDER"),
    ],
)
def test_every_client_with_a_monitor_probe_is_restart_safe(tmp_path, downloader, host_key, path_key):
    """Each of these clients yields a hash at acceptance and can be polled by
    torrent.monitor.probe, so a restart can pick the download back up."""
    overrides = {host_key: "https://client.test"}
    if path_key:
        overrides[path_key] = str(tmp_path)
    routes = health.build_route_readiness(_config(tmp_path, TORRENT_DOWNLOADER=downloader, **overrides))

    assert routes["torrent"]["enabled"] is True
    assert routes["torrent"]["restart_safe"] is True
    assert routes["torrent"]["reason"] != "unsupported_restart_correlation"


def test_restart_safe_client_still_requires_a_mapped_postprocessing_path(tmp_path):
    routes = health.build_route_readiness(
        _config(tmp_path, POST_PROCESSING=True, SAB_DIRECTORY=str(tmp_path / "missing")),
    )

    assert routes["nzb"]["restart_safe"] is True
    assert routes["nzb"]["client_ready"] is True
    assert routes["nzb"]["path_ready"] is False
    assert routes["nzb"]["ready"] is False
    assert routes["nzb"]["reason"] == "path_not_ready"


def test_maintenance_blocks_handoff_without_hiding_route_configuration(tmp_path):
    routes = health.build_route_readiness(
        _config(tmp_path),
        maintenance={"blocked": True, "reason": "persistent_maintenance"},
    )

    assert all(route["enabled"] for route in routes.values())
    assert all(route["ready"] is False for route in routes.values())
    assert all(route["reason"] == "persistent_maintenance" for route in routes.values())
    assert health.has_viable_route(routes) is False
    assert health.blocking_route_reason(routes) == "persistent_maintenance"


def test_blocking_route_reason_names_the_smallest_remaining_gap(tmp_path):
    routes = health.build_route_readiness(
        _config(tmp_path, ENABLE_DDL=False, ENABLE_GETCOMICS=False, POST_PROCESSING=True, SAB_DIRECTORY=None)
    )

    assert health.has_viable_route(routes) is False
    assert routes["ddl"]["reason"] == "disabled"
    # DDL sorts first but is merely off; the NZB route is one directory away.
    assert health.blocking_route_reason(routes) == "path_not_ready"


def test_blocking_route_reason_falls_back_when_routes_report_nothing():
    assert health.blocking_route_reason({}) == health.NO_VIABLE_ROUTE
    assert health.blocking_route_reason({"ddl": {"ready": False}}) == health.NO_VIABLE_ROUTE


def test_dispatch_success_and_acquisition_completion_are_separate_projections():
    ledger = RunLedger(get_engine())
    ledger.create_run("scheduled-search", command_kind="search", trigger="scheduler")
    ledger.accept_item("scheduled-search", "issue", "issue-1")
    ledger.record_dispatch("scheduled-search", DispatchState.ACCEPTED)

    running = health.get_acquisition_health(engine=get_engine())

    assert running["search"]["dispatch"]["state"] == "accepted"
    assert running["search"]["completion"]["state"] == "running"
    assert running["search"]["accepted"] == 1
    assert running["search"]["processed"] == 0
    assert running["search"]["oldest_backlog"] is not None

    ledger.record_outcome("scheduled-search", "issue", "issue-1", ItemOutcome.NO_MATCH)
    completed = health.get_acquisition_health(engine=get_engine())

    assert completed["search"]["completion"]["state"] == "completed"
    assert completed["search"]["processed"] == 1
    assert completed["search"]["no_match"] == 1
    assert completed["search"]["oldest_backlog"] is None


def test_worker_heartbeat_is_restart_durable_and_sanitized():
    health.record_worker_heartbeat(
        "search",
        state="failed",
        error="https://user:secret@example.test token=secret",
        timestamp=1000.0,
        engine=get_engine(),
    )

    workers = health.get_worker_health(engine=get_engine(), now=1010.0, stale_after=60)

    assert workers["search"]["state"] == "failed"
    assert workers["search"]["last_heartbeat"] == 1000.0
    assert workers["search"]["alive"] is True
    assert workers["search"]["live"] is True
    assert workers["search"]["healthy"] is False
    assert "secret" not in workers["search"]["last_error"]

    health.record_worker_heartbeat("search", state="blocked", timestamp=1020.0, engine=get_engine())
    blocked = health.get_worker_health(engine=get_engine(), now=1030.0, stale_after=60)
    assert blocked["search"]["state"] == "blocked"
    assert blocked["search"]["alive"] is True
    assert blocked["search"]["live"] is True

    stale = health.get_worker_health(engine=get_engine(), now=1100.0, stale_after=60)
    assert stale["search"]["alive"] is False


def test_route_outcome_round_trips_sanitized_failure_history(tmp_path):
    health.record_route_outcome(
        "nzb",
        success=False,
        error="https://user:secret@example.test?apikey=top-secret failed",
        timestamp=500.0,
        blocked_until=time.time() + 60,
        engine=get_engine(),
    )

    result = health.get_search_health(_config(tmp_path), engine=get_engine())

    assert result["routes"]["nzb"]["last_attempt"] == 500.0
    assert result["routes"]["nzb"]["last_failure"] == 500.0
    assert result["routes"]["nzb"]["blocked"] is True
    assert result["routes"]["nzb"]["reason"] == "providers_temporarily_blocked"
    assert "secret" not in result["routes"]["nzb"]["last_error"]


def test_provider_service_preserves_list_shape_and_exposes_full_health_separately(monkeypatch):
    contract = {"providers": [{"provider": "Indexer", "active": False}], "routes": {}}
    monkeypatch.setattr(health, "get_search_health", lambda *args, **kwargs: contract)
    ctx = SimpleNamespace(config=SimpleNamespace(), provider_blocklist=[])

    assert search_service.get_provider_stats(ctx) == contract["providers"]
    assert search_service.get_health(ctx) == contract
