#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""#541 — band actionability predicate and clause-2 reconciliation."""

import os
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr import db
from comicarr.app.activity import queries, reasons
from comicarr.app.activity import reconcile as band_reconcile
from comicarr.tables import comics, failed, issues, metadata, nzblog, pipeline_journal


@pytest.fixture
def activity_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _journal(**overrides):
    base = {
        "release_key": "rk-1",
        "issueid": "iss-1",
        "provider": "DDL",
        "stage": "failed",
        "stage_rank": 60,
        "updated_date": "2026-07-10 12:00:00",
        "status": None,
        "fail_reason": "postprocess_error:OperationalError",
        "nzbname": "Saga.cbz",
    }
    base.update(overrides)
    return base


def test_registry_covers_exactly_twenty_three_bases():
    assert len(reasons.KNOWN_BASE_TOKENS) == 23
    assert len(reasons.REASON_PHRASES) == 15
    assert len(reasons.NON_ACTIONABLE_FLAT) == 7
    assert len(reasons.NON_ACTIONABLE_COMPOSITE) == 1
    # Every exclusion has a reconciliation obligation; no admitted token is excluded.
    for token in reasons.NON_ACTIONABLE_FLAT | reasons.NON_ACTIONABLE_COMPOSITE:
        assert token in reasons.RECONCILIATION
        assert token not in reasons.REASON_PHRASES
    for token in reasons.REASON_PHRASES:
        assert token not in reasons.RECONCILIATION


def test_is_actionable_fail_open_and_exclusions():
    assert reasons.is_actionable(None) is True
    assert reasons.is_actionable("") is True
    assert reasons.is_actionable("brand_new_writer_token") is True
    assert reasons.is_actionable("postprocess_error:ValueError") is True
    assert reasons.is_actionable("download_gone") is False
    assert reasons.is_actionable("ddl-worker-rejected") is False
    assert reasons.is_actionable("immutable_payload_conflict:issueid") is False
    assert reasons.is_actionable("immutable_payload_conflict") is False


def test_band_excludes_non_actionable_and_admits_null(activity_db):
    with activity_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(release_key="in-actionable", fail_reason="postprocess_error:X"),
                _journal(release_key="out-gone", fail_reason="download_gone"),
                _journal(release_key="out-hyphen", fail_reason="ddl-worker-rejected"),
                _journal(
                    release_key="out-composite",
                    fail_reason="immutable_payload_conflict:provider",
                    stage="manual_review",
                ),
                _journal(release_key="in-null", fail_reason=None),
                _journal(release_key="in-unknown", fail_reason="never_seen_before"),
                _journal(release_key="resolved-gone", fail_reason="download_gone", status="retried"),
            ],
        )

    keys = {row["release_key"] for row in queries.list_attention_band()}
    assert keys == {"in-actionable", "in-null", "in-unknown"}
    assert queries.count_attention_band() == 3


def test_band_and_count_stay_consistent(activity_db):
    """list and count share unresolved_band_condition — including actionability."""
    with activity_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(release_key="a", fail_reason="download_gone"),
                _journal(
                    release_key="b",
                    stage="manual_review",
                    stage_rank=55,
                    fail_reason="downloaded_invalid_artifact_command:PostProcessCommandError",
                ),
                _journal(
                    release_key="c",
                    stage="manual_review",
                    stage_rank=55,
                    fail_reason="postprocess_error:ValueError",
                ),
            ],
        )
    rows = queries.list_attention_band()
    assert queries.count_attention_band() == len(rows)
    assert {r["release_key"] for r in rows} == {"b", "c"}
    # Status open-work counts use the same predicate via attention_members.
    counts = queries.get_open_work_counts()
    assert counts["attention_members"] == 2


def test_reconcile_blocklist_and_rewant(activity_db):
    with activity_db.begin() as conn:
        conn.execute(
            insert(issues),
            [{"IssueID": "iss-9", "ComicID": "c1", "ComicName": "Saga", "Status": "Snatched"}],
        )

    result = band_reconcile.reconcile_excluded(
        "download_gone",
        issueid="iss-9",
        provider="DDL",
        nzbname="Saga.cbz",
        release_id="ddl-42",
        comicid="c1",
        comicname="Saga",
        issue_number="1",
    )
    assert result == "blocklisted_and_rewanted"

    issue = db.select_one(select(issues).where(issues.c.IssueID == "iss-9"))
    assert issue["Status"] == "Wanted"
    assert issue["AcquisitionIntent"] == "wanted"

    block = db.select_one(
        select(failed).where(
            failed.c.ID == "ddl-42",
            failed.c.Provider == "DDL",
            failed.c.NZBName == "Saga.cbz",
        )
    )
    assert block is not None
    assert block["Status"] == "Failed"
    assert block["IssueID"] == "iss-9"


def test_reconcile_rewant_only(activity_db):
    with activity_db.begin() as conn:
        conn.execute(
            insert(issues),
            [{"IssueID": "iss-7", "ComicID": "c1", "ComicName": "Saga", "Status": "Snatched"}],
        )

    result = band_reconcile.reconcile_excluded(
        "ddl-worker-rejected",
        issueid="iss-7",
        provider="DDL",
        nzbname="x.cbz",
        release_id="ddl-1",
    )
    assert result == "rewanted"
    issue = db.select_one(select(issues).where(issues.c.IssueID == "iss-7"))
    assert issue["Status"] == "Wanted"
    # No blocklist for attempt-dead tokens.
    assert db.select_one(select(failed)) is None


def test_reconcile_noop_for_admitted_and_already_done():
    assert band_reconcile.reconcile_excluded("postprocess_error:X") == "noop"
    assert band_reconcile.reconcile_excluded("download_failed_researching") == "none"


def test_reconcile_existing_excluded_rows(activity_db):
    with activity_db.begin() as conn:
        conn.execute(
            insert(issues),
            [
                {"IssueID": "iss-a", "ComicID": "c1", "ComicName": "A", "Status": "Snatched"},
                {"IssueID": "iss-b", "ComicID": "c1", "ComicName": "B", "Status": "Snatched"},
            ],
        )
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(
                    release_key="gone-1",
                    issueid="iss-a",
                    fail_reason="download_gone",
                    nzbname="a.cbz",
                    provider="DDL",
                    payload_json='{"ddl_id":"d1","filename":"a.cbz","provider":"DDL"}',
                ),
                _journal(
                    release_key="keep",
                    issueid="iss-b",
                    fail_reason="postprocess_error:X",
                    payload_json=None,
                ),
            ],
        )

    summary = band_reconcile.reconcile_existing_excluded_rows()
    assert summary["acted"] == 1
    assert summary["skipped_actionable"] == 1
    issue = db.select_one(select(issues).where(issues.c.IssueID == "iss-a"))
    assert issue["Status"] == "Wanted"
    # Actionable row's issue stays Snatched (operator still needs to act).
    other = db.select_one(select(issues).where(issues.c.IssueID == "iss-b"))
    assert other["Status"] == "Snatched"


def _placed_library_file(tmp_path, name="Saga v01.cbz"):
    """Create a real series root + issue file so placement evidence is genuine."""
    series = tmp_path / "library" / "Saga"
    series.mkdir(parents=True, exist_ok=True)
    issue_file = series / name
    issue_file.write_bytes(b"x")
    return str(series), str(issue_file)


def _seed_parked_row(conn, *, status, location, release_key="done-1", issueid="iss-done", series_dir=None):
    conn.execute(insert(comics), [{"ComicID": "c1", "ComicLocation": series_dir}])
    conn.execute(
        insert(issues),
        [{"IssueID": issueid, "ComicID": "c1", "ComicName": "Saga", "Status": status, "Location": location}],
    )
    conn.execute(insert(nzblog), [{"IssueID": issueid, "NZBName": "Saga.cbz", "PROVIDER": "DDL", "ID": "n1"}])
    conn.execute(
        insert(pipeline_journal),
        [
            _journal(
                release_key=release_key,
                issueid=issueid,
                stage="manual_review",
                stage_rank=55,
                fail_reason="recovered_postprocess_error:TypeError",
            )
        ],
    )


def test_reconcile_closes_parked_row_whose_work_is_already_done(activity_db, tmp_path):
    """An ACTIONABLE parked row is closed when its work is provably finished.

    `manual_review` is terminal, so replay never revisits it; without this the
    row asks an operator for an action that cannot change anything, forever.
    """
    series_dir, issue_file = _placed_library_file(tmp_path)
    with activity_db.begin() as conn:
        _seed_parked_row(conn, status="Downloaded", location=issue_file, series_dir=series_dir)

    summary = band_reconcile.reconcile_existing_excluded_rows()

    row = db.select_one(select(pipeline_journal).where(pipeline_journal.c.release_key == "done-1"))
    # Stamped resolved WITHOUT regressing the forward-only lattice: manual_review
    # (55) outranks post_processed (50), so a stage advance would be a silent no-op.
    assert row["status"] == "imported"
    assert row["stage"] == "manual_review"
    # Anchor cleared -- the same end state a successful operator Import reaches.
    assert db.select_one(select(nzblog).where(nzblog.c.IssueID == "iss-done")) is None
    assert summary["closed_fulfilled"] == 1
    assert summary["skipped_actionable"] == 0


def test_reconcile_keeps_parked_row_when_file_is_missing(activity_db, tmp_path):
    """Control: `Downloaded` alone is not evidence. No file -> stays in the band."""
    series_dir, issue_file = _placed_library_file(tmp_path)
    os.remove(issue_file)
    with activity_db.begin() as conn:
        _seed_parked_row(conn, status="Downloaded", location=issue_file, series_dir=series_dir)

    summary = band_reconcile.reconcile_existing_excluded_rows()

    assert summary["closed_fulfilled"] == 0
    assert summary["skipped_actionable"] == 1
    row = db.select_one(select(pipeline_journal).where(pipeline_journal.c.release_key == "done-1"))
    assert row["status"] is None
    assert db.select_one(select(nzblog).where(nzblog.c.IssueID == "iss-done")) is not None


def test_reconcile_keeps_parked_row_when_issue_not_downloaded(activity_db, tmp_path):
    """Control: a real file under a still-`Snatched` issue is not fulfilment."""
    series_dir, issue_file = _placed_library_file(tmp_path)
    with activity_db.begin() as conn:
        _seed_parked_row(conn, status="Snatched", location=issue_file, series_dir=series_dir)

    summary = band_reconcile.reconcile_existing_excluded_rows()

    assert summary["closed_fulfilled"] == 0
    assert summary["skipped_actionable"] == 1
    row = db.select_one(select(pipeline_journal).where(pipeline_journal.c.release_key == "done-1"))
    assert row["status"] is None
