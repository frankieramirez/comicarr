#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Download progress for Releases: journal rows mapped to the client's queue."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.app.downloads import progress
from comicarr.tables import activity_events, metadata, pipeline_journal


@pytest.fixture
def progress_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(SAB_HOST="http://sab:8080", SAB_APIKEY="k"))
    monkeypatch.setattr(comicarr, "USE_SABNZBD", True, raising=False)
    monkeypatch.setattr(comicarr, "USE_NZBGET", False, raising=False)
    monkeypatch.setattr(comicarr, "USE_QBITTORRENT", False, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    progress.reset_cache()
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()
    progress.reset_cache()


def _journal(conn, key, issue, stage, payload, downloader="nzb"):
    conn.execute(
        insert(pipeline_journal).values(
            release_key=key,
            issueid=issue,
            downloader_type=downloader,
            stage=stage,
            stage_rank=20,
            payload_json=json.dumps(payload),
            updated_date="2026-11-12 10:00:00",
        )
    )


class _Response:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def test_sabnzbd_queue_percent_is_mapped_back_to_the_issue(progress_db, monkeypatch):
    with progress_db.begin() as conn:
        _journal(conn, "rk-1", "iss-1", "snatched", {"nzo_id": "SABnzbd_nzo_1"})
        _journal(conn, "rk-2", "iss-2", "post_processing", {"nzo_id": "SABnzbd_nzo_2"})
        _journal(conn, "rk-3", "iss-3", "snatched", {}, downloader="ddl")
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params["mode"])
        return _Response({"queue": {"slots": [{"nzo_id": "SABnzbd_nzo_1", "percentage": "64", "timeleft": "0:03:10"}]}})

    monkeypatch.setattr(progress.requests, "get", fake_get)

    found = progress.progress_by_issue(["iss-1", "iss-2", "iss-3", "iss-none"])

    assert found["iss-1"] == {"phase": "downloading", "percent": 64, "time_left": "0:03:10"}
    assert found["iss-2"] == {"phase": "importing", "percent": None, "time_left": None}
    # DDL has no cheap queue read: downloading, percent unknown.
    assert found["iss-3"]["percent"] is None
    assert "iss-none" not in found
    # One queue read, then the cache answers.
    progress.progress_by_issue(["iss-1", "iss-2", "iss-3", "iss-none"])
    assert calls == ["queue"]


def test_an_unreachable_client_reports_no_percent(progress_db, monkeypatch):
    with progress_db.begin() as conn:
        _journal(conn, "rk-1", "iss-1", "snatched", {"nzo_id": "SABnzbd_nzo_1"})

    def boom(*args, **kwargs):
        raise progress.requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(progress.requests, "get", boom)
    assert progress.progress_by_issue(["iss-1"]) == {
        "iss-1": {"phase": "downloading", "percent": None, "time_left": None}
    }


def test_upcoming_rows_carry_progress_downloaded_time_and_the_attention_reason(progress_db, monkeypatch):
    from comicarr.app.storyarcs import service

    monkeypatch.setattr(
        service.arc_queries,
        "get_upcoming",
        lambda *a, **k: [
            {"IssueID": "iss-1", "Status": "Snatched"},
            {"IssueID": "iss-9", "Status": "Downloaded"},
        ],
    )
    monkeypatch.setattr(service, "_attention_reasons", lambda: {"iss-1": ("import failed", "postprocess_script")})
    monkeypatch.setattr(
        progress, "progress_by_issue", lambda ids: {"iss-1": {"phase": "downloading", "percent": 10, "time_left": None}}
    )
    with progress_db.begin() as conn:
        conn.execute(
            insert(activity_events).values(
                created_at="2026-11-11T21:40:00+00:00",
                activity="import",
                status="succeeded",
                subject_type="issue",
                subject_id="iss-9",
                subject_label="Dandadan Ch. 213",
            )
        )

    rows = service.get_upcoming(week="45", year="2026")

    assert rows[0]["attention"] == "import failed"
    assert rows[0]["attention_reason"] == "postprocess_script"
    assert rows[0]["download"]["percent"] == 10
    assert rows[1]["downloaded_at"] == "2026-11-11T21:40:00+00:00"
    assert rows[1]["download"] is None
