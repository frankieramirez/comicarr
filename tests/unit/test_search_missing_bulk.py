#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Durable server-side Search all missing contracts."""

import queue
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import comicarr
from comicarr import db
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.core.context import AppContext
from comicarr.app.series import service as series_service
from comicarr.tables import acquisition_runs, acquisition_search_previews, annuals, comics, issues, metadata


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.setattr(comicarr, "SEARCH_QUEUE", queue.Queue(), raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("COMICARR_ACQUISITION_MAINTENANCE", raising=False)
    db.shutdown_engine()
    metadata.create_all(db.get_engine())
    assert ensure_acquisition_schema(db.get_engine()).ready
    yield
    db.shutdown_engine()


def _ctx():
    return AppContext(config=SimpleNamespace(ANNUALS_ON=True))


def _seed_series():
    with db.get_engine().begin() as conn:
        conn.execute(
            comics.insert().values(
                ComicID="160294",
                ComicName="Absolute Batman",
                ComicYear="2024",
                Status="Active",
                Have=0,
                Total=2,
            )
        )
        conn.execute(
            issues.insert().values(
                IssueID="issue-1",
                ComicID="160294",
                ComicName="Absolute Batman",
                Issue_Number="1",
                Int_IssueNumber=1,
                Status=None,
                AcquisitionIntent=None,
                ReleaseDate="2020-01-01",
            )
        )
        conn.execute(
            annuals.insert().values(
                IssueID="annual-1",
                ComicID="160294",
                ReleaseComicName="Absolute Batman",
                Issue_Number="Annual 1",
                Int_IssueNumber=1,
                Status=None,
                AcquisitionIntent=None,
                ReleaseDate="2020-01-01",
                Deleted=None,
            )
        )


def _ready_route(monkeypatch):
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *_args, **_kwargs: {
            "viable_route": True,
            "routes": {"ddl": {"ready": True}, "nzb": {}, "torrent": {}},
        },
    )


def test_confirmed_bulk_search_is_session_bound_idempotent_and_handles_annuals(monkeypatch):
    _seed_series()
    _ready_route(monkeypatch)

    preview = series_service.preview_search_all_missing(
        _ctx(),
        "160294",
        actor="frankie",
        session_id="browser-session",
    )

    assert preview["eligibleCount"] == 2
    assert preview["preview_token"]
    assert preview["fingerprint"]

    first = series_service.search_all_missing(
        _ctx(),
        "160294",
        "frankie",
        confirm=True,
        preview_token=preview["preview_token"],
        fingerprint=preview["fingerprint"],
        session_id="browser-session",
    )
    repeated = series_service.search_all_missing(
        _ctx(),
        "160294",
        "frankie",
        confirm=True,
        preview_token=preview["preview_token"],
        fingerprint=preview["fingerprint"],
        session_id="browser-session",
    )

    assert first["success"] is True
    assert first["accepted"] == 2
    assert first["run_id"]
    assert repeated["success"] is True
    assert repeated["run_id"] == first["run_id"]
    assert repeated["accepted"] == 2
    assert repeated["idempotent"] is True
    assert comicarr.SEARCH_QUEUE.qsize() == 2

    with db.get_engine().connect() as conn:
        run_rows = list(conn.execute(select(acquisition_runs)).mappings())
        issue_row = conn.execute(select(issues).where(issues.c.IssueID == "issue-1")).mappings().one()
        annual_row = conn.execute(select(annuals).where(annuals.c.IssueID == "annual-1")).mappings().one()
    assert len(run_rows) == 1
    assert run_rows[0]["scope_type"] == "series"
    assert run_rows[0]["scope_id"] == "160294"
    assert issue_row["AcquisitionIntent"] == "wanted"
    assert annual_row["AcquisitionIntent"] == "wanted"
    assert {
        (item["entity_type"], item["entity_id"]) for item in RunLedger(db.get_engine()).list_items(first["run_id"])
    } == {("issue", "issue-1"), ("annual", "annual-1")}


def test_bulk_search_keeps_same_id_issue_and_annual_as_distinct_obligations(monkeypatch):
    with db.get_engine().begin() as conn:
        conn.execute(
            comics.insert().values(
                ComicID="shared-series",
                ComicName="Shared identities",
                ComicYear="2024",
                Status="Active",
            )
        )
        conn.execute(
            issues.insert().values(
                IssueID="shared-id",
                ComicID="shared-series",
                ComicName="Shared identities",
                Issue_Number="1",
                Status=None,
                AcquisitionIntent=None,
                ReleaseDate="2020-01-01",
            )
        )
        conn.execute(
            annuals.insert().values(
                IssueID="shared-id",
                ComicID="shared-series",
                ReleaseComicName="Shared identities",
                Issue_Number="Annual 1",
                Status=None,
                AcquisitionIntent=None,
                ReleaseDate="2020-01-01",
                Deleted=None,
            )
        )
    _ready_route(monkeypatch)

    preview = series_service.preview_search_all_missing(
        _ctx(),
        "shared-series",
        actor="frankie",
        session_id="browser-session",
    )
    result = series_service.search_all_missing(
        _ctx(),
        "shared-series",
        "frankie",
        confirm=True,
        preview_token=preview["preview_token"],
        fingerprint=preview["fingerprint"],
        session_id="browser-session",
    )

    assert result["accepted"] == 2
    items = RunLedger(db.get_engine()).list_items(result["run_id"])
    assert {(item["entity_type"], item["entity_id"]) for item in items} == {
        ("issue", "shared-id"),
        ("annual", "shared-id"),
    }
    assert {comicarr.SEARCH_QUEUE.get_nowait()["entity_type"] for _ in range(2)} == {"issue", "annual"}


def test_explicit_annual_lookup_uses_null_deleted_row():
    from comicarr import search as legacy_search

    with db.get_engine().begin() as conn:
        conn.execute(comics.insert().values(ComicID="annual-series", Status="Active"))
        conn.execute(
            issues.insert().values(
                IssueID="shared-id",
                ComicID="annual-series",
                Issue_Number="1",
                Status="Wanted",
            )
        )
        conn.execute(
            annuals.insert().values(
                IssueID="shared-id",
                ComicID="annual-series",
                Issue_Number="Annual 1",
                Status="Wanted",
                Deleted=None,
            )
        )

    result, mode, oneoff = legacy_search._search_source_for_issue("shared-id", entity_type="annual")

    assert result["Issue_Number"] == "Annual 1"
    assert mode == "want_ann"
    assert oneoff is False


def test_bulk_search_rejects_stale_preview_without_mutating_sources(monkeypatch):
    _seed_series()
    _ready_route(monkeypatch)
    preview = series_service.preview_search_all_missing(
        _ctx(),
        "160294",
        actor="frankie",
        session_id="browser-session",
    )
    with db.get_engine().begin() as conn:
        conn.execute(issues.update().where(issues.c.IssueID == "issue-1").values(Status="Downloaded"))

    result = series_service.search_all_missing(
        _ctx(),
        "160294",
        "frankie",
        confirm=True,
        preview_token=preview["preview_token"],
        fingerprint=preview["fingerprint"],
        session_id="browser-session",
    )

    assert result["success"] is False
    assert result["status"] == "stale_preview"
    assert comicarr.SEARCH_QUEUE.empty()
    with db.get_engine().connect() as conn:
        annual_row = conn.execute(select(annuals).where(annuals.c.IssueID == "annual-1")).mappings().one()
    assert annual_row["AcquisitionIntent"] is None


def test_confirmed_bulk_search_retry_returns_same_run_after_preview_ttl(monkeypatch):
    _seed_series()
    _ready_route(monkeypatch)
    preview = series_service.preview_search_all_missing(
        _ctx(),
        "160294",
        actor="frankie",
        session_id="browser-session",
    )
    first = series_service.search_all_missing(
        _ctx(),
        "160294",
        "frankie",
        confirm=True,
        preview_token=preview["preview_token"],
        fingerprint=preview["fingerprint"],
        session_id="browser-session",
    )
    with db.get_engine().begin() as conn:
        conn.execute(
            acquisition_search_previews.update()
            .where(acquisition_search_previews.c.token_digest.is_not(None))
            .values(expires_at="2000-01-01T00:00:00+00:00")
        )

    repeated = series_service.search_all_missing(
        _ctx(),
        "160294",
        "frankie",
        confirm=True,
        preview_token=preview["preview_token"],
        fingerprint=preview["fingerprint"],
        session_id="browser-session",
    )

    assert first["success"] is True
    assert repeated["success"] is True
    assert repeated["run_id"] == first["run_id"]
    assert repeated["idempotent"] is True


def test_bulk_search_retries_only_the_failed_queue_handoff(monkeypatch):
    _seed_series()
    _ready_route(monkeypatch)
    attempted = []
    fail_annual = {"value": True}

    def dispatch(command, *, work_queue=None, maintenance=None):
        attempted.append(command.issueid)
        if command.entity_type == "annual" and fail_annual["value"]:
            raise RuntimeError("queue temporarily unavailable")
        (work_queue or comicarr.SEARCH_QUEUE).put(command.to_mapping())

    monkeypatch.setattr("comicarr.app.search.commands.dispatch_persisted_search_command", dispatch)
    preview = series_service.preview_search_all_missing(
        _ctx(),
        "160294",
        actor="frankie",
        session_id="browser-session",
    )
    first = series_service.search_all_missing(
        _ctx(),
        "160294",
        "frankie",
        confirm=True,
        preview_token=preview["preview_token"],
        fingerprint=preview["fingerprint"],
        session_id="browser-session",
    )

    assert first["status"] == "pending_dispatch"
    assert attempted == ["annual-1", "issue-1"]
    items = {item["entity_type"]: item for item in RunLedger(db.get_engine()).list_items(first["run_id"])}
    assert items["annual"]["dispatch_state"] == "error"
    assert items["issue"]["dispatch_state"] == "accepted"

    fail_annual["value"] = False
    repeated = series_service.search_all_missing(
        _ctx(),
        "160294",
        "frankie",
        confirm=True,
        preview_token=preview["preview_token"],
        fingerprint=preview["fingerprint"],
        session_id="browser-session",
    )

    assert repeated["status"] == "accepted"
    assert attempted == ["annual-1", "issue-1", "annual-1"]
    assert all(item["dispatch_state"] == "accepted" for item in RunLedger(db.get_engine()).list_items(first["run_id"]))
