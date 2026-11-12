#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Activity > Health: job result summaries and connection checks."""

import datetime
from types import SimpleNamespace

import pytest
import requests
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.app.system import connections, job_results
from comicarr.app.system import router as system_router
from comicarr.tables import acquisition_runs, activity_events, comics, importresults, metadata, weekly

T0 = datetime.datetime(2026, 11, 12, 6, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
def health_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _at(minutes):
    return (T0 + datetime.timedelta(minutes=minutes)).isoformat()


def _run(engine, run_id, kind, trigger, minutes, accepted, succeeded, failed=0):
    with engine.begin() as conn:
        conn.execute(
            insert(acquisition_runs).values(
                run_id=run_id,
                command_kind=kind,
                trigger=trigger,
                dispatch_state="accepted",
                completion_state="succeeded",
                accepted_count=accepted,
                terminal_count=accepted,
                succeeded_count=succeeded,
                failed_count=failed,
                created_at=_at(minutes),
                updated_at=_at(minutes),
            )
        )


def _event(engine, activity, status, minutes):
    with engine.begin() as conn:
        conn.execute(
            insert(activity_events).values(
                created_at=_at(minutes),
                activity=activity,
                status=status,
                subject_type="issue",
                subject_id="iss-%s" % minutes,
                subject_label="Saga #1",
            )
        )


def test_search_counts_only_runs_since_its_last_attempt(health_db):
    _run(health_db, "old", "search", "wanted_scan", -60, 9, 9)
    _run(health_db, "a", "search", "wanted_scan", 1, 1, 1)
    _run(health_db, "b", "search", "wanted_scan", 2, 1, 0)
    _run(health_db, "manual", "search", "manual_wanted_scan", 3, 5, 5)

    assert job_results.summarize("search", T0.timestamp()) == "1 grabbed of 2 searched"


def test_search_with_nothing_wanted_says_so(health_db):
    assert job_results.summarize("search", T0.timestamp()) == "Nothing wanted to search"


def test_rss_and_monitor_read_the_activity_log(health_db):
    assert job_results.summarize("rss", T0.timestamp()) == "No new matches"
    assert job_results.summarize("monitor", T0.timestamp()) == "Nothing to import"

    _event(health_db, "grab", "succeeded", 5)
    _event(health_db, "import", "succeeded", 6)
    _event(health_db, "import", "succeeded", 7)
    _event(health_db, "import", "failed", 8)
    _event(health_db, "import", "succeeded", -30)

    assert job_results.summarize("rss", T0.timestamp()) == "1 grab"
    assert job_results.summarize("monitor", T0.timestamp()) == "2 imported, 1 failed"


def test_library_refresh_counts_series(health_db):
    assert job_results.summarize("dbupdater", T0.timestamp()) is None
    _run(health_db, "r", "refresh", "scheduled", 1, 202, 202)
    assert job_results.summarize("dbupdater", T0.timestamp()) == "202 series up to date"


def test_weekly_counts_issues_for_followed_series(health_db, monkeypatch):
    monkeypatch.setattr(comicarr, "CURRENT_WEEKNUMBER", 46)
    monkeypatch.setattr(comicarr, "CURRENT_YEAR", 2026)
    with health_db.begin() as conn:
        conn.execute(insert(comics).values(ComicID="101", ComicName="Saga"))
        conn.execute(
            insert(weekly),
            [
                {"COMIC": "Saga", "ISSUE": "75", "ComicID": "101", "IssueID": "1", "weeknumber": "46", "year": "2026"},
                {"COMIC": "Other", "ISSUE": "1", "ComicID": "999", "IssueID": "2", "weeknumber": "46", "year": "2026"},
            ],
        )
    assert job_results.summarize("weekly", T0.timestamp()) == "1 new issue for your series"


def test_import_inbox_counts_files_waiting(health_db):
    with health_db.begin() as conn:
        conn.execute(
            insert(importresults),
            [
                {"impID": "1", "Status": "Not Imported", "IgnoreFile": 0},
                {"impID": "2", "Status": "Not Imported", "IgnoreFile": 1},
                {"impID": "3", "Status": "Imported", "IgnoreFile": 0},
            ],
        )
    assert job_results.summarize("importinbox", T0.timestamp()) == "1 file waiting for a pick"


def test_unknown_jobs_and_unrun_jobs_have_no_summary(health_db):
    assert job_results.summarize("ledger_retention", T0.timestamp()) is None
    assert job_results.summarize("search", None) is None


# ── connections ─────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _sab_config(**overrides):
    values = {
        "NZB_DOWNLOADER": 0,
        "SAB_HOST": "http://sab:8080/",
        "SAB_APIKEY": "secret-key",
        "SAB_VERIFY": False,
        "ENABLE_TORRENTS": False,
        "ENABLE_DDL": False,
        "NEWZNAB": False,
        "ENABLE_TORZNAB": False,
        "ENABLE_PROWLARR": False,
        "MANGADEX_ENABLED": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def _forget_connections():
    connections.reset()
    yield
    connections.reset()


def test_sabnzbd_check_reports_version_queue_and_latency(monkeypatch):
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append((url, params))
        if params["mode"] == "version":
            return FakeResponse(payload={"version": "4.3.2"})
        return FakeResponse(payload={"queue": {"noofslots": 3}})

    monkeypatch.setattr(connections.requests, "get", fake_get)
    result = connections.test_connection("sabnzbd", _sab_config())

    assert result["ok"] is True
    assert result["result"] == "Reachable"
    assert result["version"] == "4.3.2"
    assert result["active"] == 3
    assert result["latency_ms"] is not None
    assert calls[0][0] == "http://sab:8080/api"
    assert connections.snapshot(_sab_config())[0]["checked_at"] == result["checked_at"]


def test_sabnzbd_rejected_key_is_a_failure(monkeypatch):
    def fake_get(url, params=None, **kwargs):
        if params["mode"] == "version":
            return FakeResponse(payload={"version": "4.3.2"})
        return FakeResponse(payload={"status": False, "error": "API Key Incorrect"})

    monkeypatch.setattr(connections.requests, "get", fake_get)
    result = connections.test_connection("sabnzbd", _sab_config())
    assert result["ok"] is False
    assert result["result"] == "SABnzbd rejected the API key"


def test_unreachable_client_reads_plainly(monkeypatch):
    def fake_get(*args, **kwargs):
        raise requests.exceptions.ConnectionError("refused http://sab:8080/api?apikey=secret-key")

    monkeypatch.setattr(connections.requests, "get", fake_get)
    result = connections.test_connection("sabnzbd", _sab_config())
    assert result["ok"] is False
    assert result["result"] == "Couldn't reach SABnzbd"
    assert "secret-key" not in str(result)


def test_indexers_report_a_median_and_failures(monkeypatch):
    config = _sab_config(
        NEWZNAB=True,
        EXTRA_NEWZNABS=[
            ("geek", "https://geek.example", "1", "k1", "1#7030", "1", 1),
            ("slug", "https://slug.example/api", "1", "k2", "1#7030", "1", 2),
            ("dead", "https://dead.example", "1", "k3", "1#7030", "1", 3),
        ],
    )
    seen = []

    def fake_get(url, params=None, **kwargs):
        seen.append(url)
        if "dead" in url:
            return FakeResponse(status_code=503)
        return FakeResponse(text="<caps></caps>")

    monkeypatch.setattr(connections.requests, "get", fake_get)
    result = connections.test_connection("indexers", config)

    assert seen == ["https://geek.example/api", "https://slug.example/api", "https://dead.example/api"]
    assert result["ok"] is False
    assert result["result"].startswith("1 of 3 not responding")
    assert result["latency_label"] == "median"
    assert result["count"] == 3
    assert result["responding"] == 2


def test_snapshot_lists_unchecked_connections_without_answers():
    rows = connections.snapshot(_sab_config(ENABLE_DDL=True, DDL_LOCATION="/nope"))
    assert [row["key"] for row in rows] == ["sabnzbd", "ddl"]
    assert all(row["checked_at"] is None and row["ok"] is None for row in rows)


def test_folder_route_checks_the_folder(tmp_path):
    result = connections.test_connection("ddl", _sab_config(ENABLE_DDL=True, DDL_LOCATION=str(tmp_path)))
    assert result["ok"] is True
    assert result["result"] == "Ready"
    assert result["latency_ms"] is None


def test_router_404s_an_unconfigured_connection(monkeypatch):
    import asyncio

    monkeypatch.setattr(comicarr, "CONFIG", _sab_config(SAB_HOST=None, NZB_DOWNLOADER=3))
    response = asyncio.run(system_router.test_connection("sabnzbd"))
    assert response.status_code == 404


def test_summary_counts_reachable_connections():
    assert connections.summarize([]) == "Nothing to check"
    assert connections.summarize([{"ok": True}, {"ok": True}, {"ok": None}]) == "2 of 2 reachable"
    assert connections.summarize([{"ok": True}, {"ok": False}]) == "1 of 2 not responding"
