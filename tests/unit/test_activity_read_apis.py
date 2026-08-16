#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for Activity Center timeline, band, and open-work read APIs (#485).

Pagination choice (documented for clients): the API pages *events* ordered by
created_at, not pre-grouped stories. Client-side story grouping (25 stories)
remains a UI concern per the Activity Center ADR.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.tables import (
    acquisition_run_items,
    activity_events,
    annuals,
    issues,
    metadata,
    pipeline_journal,
)


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


def _event(**overrides):
    base = {
        "created_at": "2026-07-10 12:00:00",
        "activity": "import",
        "status": "succeeded",
        "subject_type": "issue",
        "subject_id": "iss-1",
        "subject_label": "Saga #1",
    }
    base.update(overrides)
    return base


def _journal(**overrides):
    base = {
        "release_key": "rk-1",
        "issueid": "iss-1",
        "provider": "DDL",
        "stage": "failed",
        "stage_rank": 60,
        "updated_date": "2026-07-10 12:00:00",
        "status": None,
        "fail_reason": "download_failed",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def test_timeline_returns_empty_page(activity_db):
    from comicarr.app.activity import queries

    page = queries.list_timeline_events(limit=25, offset=0)

    assert page["results"] == []
    assert page["total"] == 0
    assert page["limit"] == 25
    assert page["offset"] == 0
    assert page["has_more"] is False


def test_timeline_orders_newest_first_and_paginates(activity_db):
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(
            insert(activity_events),
            [
                _event(created_at="2026-07-10 10:00:00", subject_id="a", subject_label="A"),
                _event(created_at="2026-07-10 12:00:00", subject_id="b", subject_label="B"),
                _event(created_at="2026-07-10 11:00:00", subject_id="c", subject_label="C"),
            ],
        )

    page = queries.list_timeline_events(limit=2, offset=0)
    assert [row["subject_id"] for row in page["results"]] == ["b", "c"]
    assert page["total"] == 3
    assert page["has_more"] is True

    page2 = queries.list_timeline_events(limit=2, offset=2)
    assert [row["subject_id"] for row in page2["results"]] == ["a"]
    assert page2["has_more"] is False


def test_timeline_clamps_limit_to_pagination_bounds(activity_db):
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(
            insert(activity_events),
            [
                _event(subject_id=str(i), subject_label="E%s" % i, created_at="2026-07-10 12:%02d:00" % i)
                for i in range(5)
            ],
        )

    # Below minimum and above maximum are clamped (service/query seam).
    page_low = queries.list_timeline_events(limit=0, offset=0)
    assert page_low["limit"] == queries.TIMELINE_LIMIT_MIN
    assert len(page_low["results"]) == queries.TIMELINE_LIMIT_MIN

    page_high = queries.list_timeline_events(limit=10_000, offset=0)
    assert page_high["limit"] == queries.TIMELINE_LIMIT_MAX
    assert len(page_high["results"]) == 5


def test_timeline_issue_and_annual_scope_exact_subject_match(activity_db):
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(
            insert(activity_events),
            [
                _event(subject_type="issue", subject_id="iss-1", subject_label="Target issue"),
                _event(subject_type="issue", subject_id="iss-2", subject_label="Other issue"),
                _event(subject_type="annual", subject_id="iss-1", subject_label="Same id annual"),
                _event(subject_type="annual", subject_id="ann-9", subject_label="Target annual"),
            ],
        )

    issue_page = queries.list_timeline_events(scope_type="issue", scope_id="iss-1")
    assert [row["subject_label"] for row in issue_page["results"]] == ["Target issue"]

    annual_page = queries.list_timeline_events(scope_type="annual", scope_id="ann-9")
    assert [row["subject_label"] for row in annual_page["results"]] == ["Target annual"]


def test_timeline_series_scope_rollup(activity_db):
    """Series scope: parent_series_id + series subject + series-scoped runs."""
    from comicarr.app.activity import queries

    # Multi-row insert requires identical keys across parameter groups.
    rows = [
        _event(
            subject_type="issue",
            subject_id="iss-1",
            subject_label="Child issue",
            parent_series_id="ser-1",
            scope_type=None,
            scope_id=None,
        ),
        _event(
            subject_type="series",
            subject_id="ser-1",
            subject_label="Series subject",
            parent_series_id=None,
            scope_type=None,
            scope_id=None,
        ),
        _event(
            subject_type="run",
            subject_id="run-1",
            subject_label="Scoped run",
            parent_series_id=None,
            scope_type="series",
            scope_id="ser-1",
        ),
        _event(
            subject_type="issue",
            subject_id="iss-99",
            subject_label="Other series",
            parent_series_id="ser-2",
            scope_type=None,
            scope_id=None,
        ),
        _event(
            subject_type="run",
            subject_id="run-2",
            subject_label="Other scoped run",
            parent_series_id=None,
            scope_type="series",
            scope_id="ser-2",
        ),
    ]
    with activity_db.begin() as conn:
        conn.execute(insert(activity_events), rows)

    page = queries.list_timeline_events(scope_type="series", scope_id="ser-1")
    labels = {row["subject_label"] for row in page["results"]}
    assert labels == {"Child issue", "Series subject", "Scoped run"}


def test_timeline_rejects_incomplete_scope(activity_db):
    from comicarr.app.activity import queries

    with pytest.raises(ValueError, match="scope"):
        queries.list_timeline_events(scope_type="series", scope_id=None)

    with pytest.raises(ValueError, match="scope"):
        queries.list_timeline_events(scope_type=None, scope_id="ser-1")

    with pytest.raises(ValueError, match="scope"):
        queries.list_timeline_events(scope_type="arc", scope_id="1")


# ---------------------------------------------------------------------------
# Needs-attention band
# ---------------------------------------------------------------------------


def test_band_uses_r9_unresolved_predicate(activity_db):
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(release_key="open-failed", stage="failed", status=None),
                _journal(release_key="open-review", stage="manual_review", status=None, issueid="iss-2"),
                _journal(release_key="retried", stage="failed", status="retried", issueid="iss-3"),
                _journal(release_key="ignored", stage="failed", status="ignored", issueid="iss-4"),
                _journal(release_key="imported", stage="manual_review", status="imported", issueid="iss-5"),
                _journal(
                    release_key="still-open",
                    stage="snatched",
                    stage_rank=10,
                    status=None,
                    issueid="iss-6",
                ),
            ],
        )

    rows = queries.list_attention_band()
    keys = {row["release_key"] for row in rows}
    assert keys == {"open-failed", "open-review"}
    # Same updated_date → stable tie-break on release_key desc
    assert [row["release_key"] for row in rows] == ["open-review", "open-failed"]


def test_band_issue_scope_intersects(activity_db):
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(release_key="match", issueid="iss-1", stage="failed"),
                _journal(release_key="other", issueid="iss-2", stage="failed"),
            ],
        )

    rows = queries.list_attention_band(scope_type="issue", scope_id="iss-1")
    assert [row["release_key"] for row in rows] == ["match"]


def test_band_series_scope_via_issue_and_annual_membership(activity_db):
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(insert(issues), [{"IssueID": "iss-1", "ComicID": "ser-1", "ComicName": "Saga"}])
        conn.execute(insert(annuals), [{"IssueID": "ann-1", "ComicID": "ser-1", "ComicName": "Saga Annual"}])
        conn.execute(insert(issues), [{"IssueID": "iss-2", "ComicID": "ser-2", "ComicName": "Other"}])
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(release_key="issue-row", issueid="iss-1", stage="failed"),
                _journal(release_key="annual-row", issueid="ann-1", stage="manual_review"),
                _journal(release_key="other-series", issueid="iss-2", stage="failed"),
            ],
        )

    rows = queries.list_attention_band(scope_type="series", scope_id="ser-1")
    assert {row["release_key"] for row in rows} == {"issue-row", "annual-row"}


# ---------------------------------------------------------------------------
# Band grouping (#524 key contract)
# ---------------------------------------------------------------------------


def _payload(**fields):
    import json

    return json.dumps(fields)


def test_groups_key_on_comicid_and_base_reason(activity_db):
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(
                    release_key="a1",
                    issueid="iss-1",
                    stage="manual_review",
                    fail_reason="postprocess_error:OperationalError",
                    payload_json=_payload(comicid="42", comicname="Saga", issuenumber="1"),
                ),
                # Same series + same base token, different composite suffix → one group.
                _journal(
                    release_key="a2",
                    issueid="iss-2",
                    stage="manual_review",
                    fail_reason="postprocess_error:ValueError",
                    payload_json=_payload(comicid="42", comicname="Saga", issuenumber="2"),
                ),
                # Same series, different base token → its own group.
                _journal(
                    release_key="a3",
                    issueid="iss-3",
                    stage="failed",
                    fail_reason="submission_rejected",
                    payload_json=_payload(comicid="42", comicname="Saga", issuenumber="3"),
                ),
            ],
        )

    groups = queries.list_attention_groups()
    by_key = {group["group_key"]: group for group in groups}

    assert set(by_key) == {"42|postprocess_error", "42|submission_rejected"}
    assert by_key["42|postprocess_error"]["member_count"] == 2
    assert by_key["42|postprocess_error"]["series_label"] == "Saga"
    assert by_key["42|submission_rejected"]["member_count"] == 1
    assert queries.count_attention_groups() == 2


def test_groups_never_key_on_comicname(activity_db):
    """A typographic apostrophe must not split one series into two groups."""
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(
                    release_key="w1",
                    issueid="iss-1",
                    fail_reason="submission_rejected",
                    payload_json=_payload(comicid="141907", comicname="Batman/Superman: World's Finest"),
                ),
                _journal(
                    release_key="w2",
                    issueid="iss-2",
                    fail_reason="submission_rejected",
                    payload_json=_payload(comicid="141907", comicname="Batman/Superman: World’s Finest"),
                ),
            ],
        )

    groups = queries.list_attention_groups()
    assert len(groups) == 1
    assert groups[0]["member_count"] == 2


def test_rows_without_comicid_become_singletons(activity_db):
    """No catch-all bucket: an unlabelled row is its own group, not a pile."""
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(release_key="orphan-1", issueid="iss-1", fail_reason="submission_rejected", payload_json=None),
                _journal(release_key="orphan-2", issueid="iss-2", fail_reason="submission_rejected", payload_json=None),
            ],
        )

    groups = queries.list_attention_groups()
    assert len(groups) == 2
    assert all(group["member_count"] == 1 for group in groups)
    assert all(group["comicid"] is None for group in groups)


def test_group_label_ladder_falls_back_to_series_id(activity_db):
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(
                    release_key="nolabel",
                    issueid="iss-1",
                    fail_reason="submission_rejected",
                    payload_json=_payload(comicid="18839"),
                )
            ],
        )

    assert queries.list_attention_groups()[0]["series_label"] == "Series 18839"


def test_group_actions_are_the_stage_intersection(activity_db):
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(
                    release_key="m1",
                    issueid="iss-1",
                    stage="failed",
                    fail_reason="submission_rejected",
                    payload_json=_payload(comicid="7", comicname="Mixed"),
                ),
                _journal(
                    release_key="m2",
                    issueid="iss-2",
                    stage="manual_review",
                    fail_reason="submission_rejected",
                    payload_json=_payload(comicid="7", comicname="Mixed"),
                ),
                _journal(
                    release_key="f1",
                    issueid="iss-3",
                    stage="failed",
                    fail_reason="submission_rejected",
                    payload_json=_payload(comicid="8", comicname="Pure"),
                ),
            ],
        )

    by_key = {group["group_key"]: group for group in queries.list_attention_groups()}

    # Mixed stages offer no group primary action — selection only.
    mixed = by_key["7|submission_rejected"]
    assert mixed["stage"] == "mixed"
    assert mixed["available_actions"] == []

    # ...but every member still carries its own eligibility, so nothing in a
    # mixed group is unreachable — the operator selects the rows they mean.
    member_actions = {member["stage"]: member["available_actions"] for member in mixed["members"]}
    assert member_actions == {
        "failed": ["retry", "stop_wanting"],
        "manual_review": ["import", "search_again", "stop_wanting"],
    }

    pure = by_key["8|submission_rejected"]
    assert pure["stage"] == "failed"
    assert pure["available_actions"] == ["retry", "stop_wanting"]
    assert pure["members"][0]["available_actions"] == ["retry", "stop_wanting"]


def test_groups_rank_newest_first(activity_db):
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                # Bigger, but older: volume must not outrank recency.
                _journal(
                    release_key="old-1",
                    issueid="iss-1",
                    updated_date="2026-07-01 10:00:00",
                    fail_reason="submission_rejected",
                    payload_json=_payload(comicid="1", comicname="Old"),
                ),
                _journal(
                    release_key="old-2",
                    issueid="iss-2",
                    updated_date="2026-07-01 11:00:00",
                    fail_reason="submission_rejected",
                    payload_json=_payload(comicid="1", comicname="Old"),
                ),
                _journal(
                    release_key="new-1",
                    issueid="iss-3",
                    updated_date="2026-07-09 09:00:00",
                    fail_reason="submission_rejected",
                    payload_json=_payload(comicid="2", comicname="New"),
                ),
            ],
        )

    groups = queries.list_attention_groups()
    assert [group["series_label"] for group in groups] == ["New", "Old"]
    assert groups[1]["oldest_updated_at"] == "2026-07-01 10:00:00"
    assert groups[1]["newest_updated_at"] == "2026-07-01 11:00:00"


def test_scoped_band_filters_members_then_groups(activity_db):
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(insert(issues), [{"IssueID": "iss-1", "ComicID": "ser-1", "ComicName": "Saga"}])
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(
                    release_key="in-scope",
                    issueid="iss-1",
                    fail_reason="submission_rejected",
                    payload_json=_payload(comicid="42", comicname="Saga"),
                ),
                # Same group key, out of scope: must not join the scoped group.
                _journal(
                    release_key="out-of-scope",
                    issueid="iss-9",
                    fail_reason="submission_rejected",
                    payload_json=_payload(comicid="42", comicname="Saga"),
                ),
            ],
        )

    groups = queries.list_attention_groups(scope_type="series", scope_id="ser-1")
    assert len(groups) == 1
    assert groups[0]["member_count"] == 1
    assert groups[0]["members"][0]["release_key"] == "in-scope"


def test_reason_phrase_matches_on_base_token(activity_db):
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(
                    release_key="phrase-1",
                    issueid="iss-1",
                    stage="manual_review",
                    fail_reason="downloaded_invalid_artifact_command:PostProcessCommandError",
                    payload_json=_payload(comicid="42", comicname="Saga"),
                ),
                _journal(
                    release_key="phrase-2",
                    issueid="iss-2",
                    stage="manual_review",
                    fail_reason="some_brand_new_token",
                    payload_json=_payload(comicid="43", comicname="Other"),
                ),
            ],
        )

    by_label = {group["series_label"]: group for group in queries.list_attention_groups()}
    # Composite families resolve — the whole point of keying on the base token.
    assert by_label["Saga"]["reason_phrase"] == "downloaded file failed post-process checks"
    # Unknown tokens degrade to prose, never a raw snake_case token.
    assert by_label["Other"]["reason_phrase"] == "something went wrong"


# ---------------------------------------------------------------------------
# Open-work counts (authority rule)
# ---------------------------------------------------------------------------


def _seed_open_work_count_fixtures(conn):
    """2 accepted|running run items + 1 OPEN_STAGES journal (+ terminal noise)."""
    conn.execute(
        insert(activity_events),
        [
            _event(activity="search", status="started", subject_type="run", subject_id="r1"),
            _event(activity="grab", status="failed", subject_type="issue", subject_id="iss-1"),
        ],
    )
    conn.execute(
        insert(acquisition_run_items),
        [
            {
                "run_id": "run-1",
                "command_kind": "search_issue",
                "entity_type": "issue",
                "entity_id": "iss-1",
                "state": "accepted",
                "dispatch_state": "pending",
                "queue_priority": "routine",
                "attempt_count": 0,
                "created_at": "2026-07-10 10:00:00",
                "updated_at": "2026-07-10 10:00:00",
            },
            {
                "run_id": "run-1",
                "command_kind": "search_issue",
                "entity_type": "issue",
                "entity_id": "iss-2",
                "state": "running",
                "dispatch_state": "accepted",
                "queue_priority": "routine",
                "attempt_count": 1,
                "created_at": "2026-07-10 10:00:00",
                "updated_at": "2026-07-10 10:01:00",
            },
            {
                "run_id": "run-1",
                "command_kind": "search_issue",
                "entity_type": "issue",
                "entity_id": "iss-3",
                "state": "succeeded",
                "dispatch_state": "accepted",
                "queue_priority": "routine",
                "attempt_count": 1,
                "created_at": "2026-07-10 10:00:00",
                "updated_at": "2026-07-10 10:02:00",
                "completed_at": "2026-07-10 10:02:00",
            },
        ],
    )
    conn.execute(
        insert(pipeline_journal),
        [
            _journal(
                release_key="open-pp",
                stage="post_processing",
                stage_rank=30,
                status=None,
                issueid="iss-10",
            ),
            _journal(
                release_key="done",
                stage="post_processed",
                stage_rank=50,
                status=None,
                issueid="iss-11",
            ),
            _journal(release_key="need-attn", stage="failed", status=None, issueid="iss-12"),
            _journal(
                release_key="resolved",
                stage="failed",
                status="ignored",
                issueid="iss-13",
            ),
        ],
    )


def test_open_work_counts_from_ledgers_not_narrative(activity_db):
    """Authority rule: never aggregate activity_events for counts."""
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        _seed_open_work_count_fixtures(conn)

    counts = queries.get_open_work_counts()
    # 2 in-flight run items + 1 open journal stage
    assert counts["in_flight"] == 3
    assert counts["attention"] == 1
    assert "activity_events" not in counts


def test_list_in_flight_items_matches_open_work_count_rows(activity_db):
    """The listed rows are exactly the rows the in-flight count uses (#676)."""
    from comicarr.app.activity import queries

    with activity_db.begin() as conn:
        _seed_open_work_count_fixtures(conn)

    items = queries.list_in_flight_items()
    counts = queries.get_open_work_counts()
    assert len(items) == counts["in_flight"] == 3

    by_identity = {}
    for item in items:
        if item["kind"] == "run":
            by_identity[("run", item["entity_id"])] = item
        else:
            by_identity[("journal", item["release_key"])] = item

    assert set(by_identity) == {
        ("run", "iss-1"),
        ("run", "iss-2"),
        ("journal", "open-pp"),
    }
    accepted = by_identity[("run", "iss-1")]
    assert accepted["state"] == "accepted"
    assert accepted["run_id"] == "run-1"
    assert accepted["item_id"] is not None
    assert accepted["entity_type"] == "issue"
    running = by_identity[("run", "iss-2")]
    assert running["state"] == "running"
    assert running["item_id"] != accepted["item_id"]
    journal = by_identity[("journal", "open-pp")]
    assert journal["stage"] == "post_processing"
    assert journal["issueid"] == "iss-10"


def test_open_work_idle_when_ledgers_empty(activity_db):
    from comicarr.app.activity import queries

    counts = queries.get_open_work_counts()
    assert counts == {
        "in_flight": 0,
        "recovery_pending": 0,
        "attention": 0,
        "attention_members": 0,
    }


# ---------------------------------------------------------------------------
# Service / router surface
# ---------------------------------------------------------------------------


def test_service_timeline_and_status_shapes(activity_db):
    from comicarr.app.activity import service

    with activity_db.begin() as conn:
        conn.execute(insert(activity_events), [_event()])
        conn.execute(
            insert(pipeline_journal),
            [_journal(release_key="band-1", stage="failed", status=None)],
        )

    timeline = service.get_timeline(limit=10, offset=0)
    assert "results" in timeline
    assert timeline["total"] == 1
    assert timeline["results"][0]["event_id"] is not None

    band = service.get_attention_band()
    assert len(band["results"]) == 1
    assert band["results"][0]["members"][0]["release_key"] == "band-1"
    assert band["member_total"] == 1

    status = service.get_status()
    assert status["in_flight"] == 0
    assert status["attention"] == 1

    inflight = service.get_in_flight()
    assert inflight == {"results": [], "total": 0}


def test_band_endpoint_collapses_a_production_shaped_pile(activity_db):
    """The wire shape the frontend types mirror, at the volume that broke it.

    399 unresolved rows is what a real restart-replay left behind; the operator
    complaint was that every one of them rendered above the timeline.
    """
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from comicarr.app.activity.router import router
    from comicarr.app.core.security import require_session

    rows = []
    # One dominant series (a burst), plus a long tail of small ones.
    for index in range(173):
        rows.append(
            _journal(
                release_key="looney-%d" % index,
                issueid="lt-%d" % index,
                stage="manual_review",
                stage_rank=55,
                fail_reason="downloaded_invalid_artifact_command:PostProcessCommandError",
                payload_json=json.dumps({"comicid": "18839", "comicname": "Looney Tunes", "issuenumber": str(index)}),
            )
        )
    for index in range(226):
        rows.append(
            _journal(
                release_key="tail-%d" % index,
                issueid="tl-%d" % index,
                stage="manual_review",
                stage_rank=55,
                fail_reason="postprocess_error:OperationalError",
                payload_json=json.dumps({"comicid": "s%d" % (index % 38), "comicname": "Series %d" % (index % 38)}),
            )
        )

    with activity_db.begin() as conn:
        conn.execute(insert(pipeline_journal), rows)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "operator"

    with TestClient(app) as client:
        band = client.get("/api/activity/band")
        assert band.status_code == 200
        body = band.json()

        # 399 rows collapse to 39 groups — one per (series, base reason).
        assert body["member_total"] == 399
        assert body["total"] == 39
        assert len(body["results"]) == 39
        assert body["preview_cap"] == 5

        first = body["results"][0]
        assert set(first) >= {
            "group_key",
            "series_label",
            "base_reason",
            "reason_phrase",
            "member_count",
            "newest_updated_at",
            "oldest_updated_at",
            "stage",
            "available_actions",
            "members",
        }

        biggest = max(body["results"], key=lambda g: g["member_count"])
        assert biggest["series_label"] == "Looney Tunes"
        assert biggest["member_count"] == 173
        assert biggest["reason_phrase"] == "downloaded file failed post-process checks"
        assert biggest["available_actions"] == ["import", "search_again", "stop_wanting"]

        # The status line reports the same 39 the band does.
        status = client.get("/api/activity/status")
        assert status.json()["attention"] == 39
        assert status.json()["attention_members"] == 399


def test_in_flight_endpoint_returns_same_rows_as_count(activity_db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from comicarr.app.activity.router import router
    from comicarr.app.core.security import require_session

    with activity_db.begin() as conn:
        _seed_open_work_count_fixtures(conn)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "operator"

    with TestClient(app) as client:
        response = client.get("/api/activity/in-flight")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert len(body["results"]) == 3
        identities = {(item["kind"], item.get("entity_id") or item.get("release_key")) for item in body["results"]}
        assert identities == {
            ("run", "iss-1"),
            ("run", "iss-2"),
            ("journal", "open-pp"),
        }
        status = client.get("/api/activity/status")
        assert status.json()["in_flight"] == body["total"]


def test_router_registers_session_protected_routes():
    """Auth class matches other operator APIs (require_session dependency)."""
    from comicarr.app.activity.router import router
    from comicarr.app.core.security import require_session

    paths = {route.path for route in router.routes}
    assert "/api/activity/timeline" in paths
    assert "/api/activity/band" in paths
    assert "/api/activity/status" in paths
    assert "/api/activity/in-flight" in paths

    for route in router.routes:
        deps = getattr(route, "dependencies", None) or []
        callables = {getattr(d, "dependency", None) for d in deps}
        assert require_session in callables, "route %s missing require_session" % route.path
