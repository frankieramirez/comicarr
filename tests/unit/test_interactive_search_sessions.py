#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Security and lifecycle contracts for Interactive search persistence."""

import datetime
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, func, select

from comicarr.app.search.interactive_sessions import (
    JOB_ID,
    JOB_NAME,
    MAX_CANDIDATES,
    InteractiveSearchAuthorizationError,
    InteractiveSearchExpired,
    InteractiveSearchLimitError,
    create_session,
    purge_expired_sessions,
    read_server_candidate,
    read_session,
)
from comicarr.app.system import service as system_service
from comicarr.search_filer import ReleaseCandidateEvaluation
from comicarr.tables import interactive_search_candidates, interactive_search_sessions, metadata

NOW = datetime.datetime(2026, 8, 11, 15, 0, tzinfo=datetime.timezone.utc)


def _evaluation(
    title="Batman 125 (2022)",
    *,
    accepted=True,
    overrideable=False,
    legacy_match=None,
    reconstruction_hint=None,
):
    return ReleaseCandidateEvaluation(
        candidate={
            "title": title,
            "provider": "Indexer",
            "source_kind": "usenet",
            "published_at": "2026-08-11T12:00:00+00:00",
            "size_bytes": 42,
            "pack": False,
            "metrics": {"grabs": 8},
        },
        verdict={
            "status": "accepted" if accepted else "rejected",
            "accepted": accepted,
            "overrideable": overrideable,
            "reason_code": "accepted.issue" if accepted else "rejected.wrong_issue",
            "reasons": [{"code": "test", "message": "Stable test verdict"}],
            "match_kind": "issue" if accepted else "none",
        },
        legacy_match=legacy_match,
        reconstruction_hint=reconstruction_hint,
    )


@pytest.fixture
def engine(tmp_path):
    value = create_engine("sqlite:///%s" % (tmp_path / "interactive-search.db"))
    metadata.create_all(value)
    yield value
    value.dispose()


def _create(engine, evaluations=None, **overrides):
    values = {
        "actor": "alice",
        "browser_session": "raw-session-cookie",
        "entity_type": "issue",
        "entity_id": "issue-125",
        "series_id": "series-batman",
        "evaluations": [_evaluation()] if evaluations is None else evaluations,
        "now": NOW,
    }
    values.update(overrides)
    return create_session(engine, **values)


def test_session_is_opaque_ordered_and_public_only(engine):
    result = _create(
        engine,
        [
            _evaluation("first"),
            _evaluation("second", accepted=False, overrideable=True),
            _evaluation("third", accepted=False),
        ],
    )

    assert result["candidate_count"] == 3
    assert [item["candidate"]["title"] for item in result["candidates"]] == ["first", "second", "third"]
    assert [item["state"] for item in result["candidates"]] == ["available", "available", "unavailable"]
    assert result["session_id"] not in {"issue-125", "series-batman", "raw-session-cookie"}
    assert all("reconstruction" not in item for item in result["candidates"])
    assert all(item["candidate_id"] not in item["candidate"]["title"] for item in result["candidates"])


def test_overrideable_rejection_keeps_credential_free_reconstruction_identity(engine):
    result = _create(
        engine,
        [
            _evaluation(
                accepted=False,
                overrideable=True,
                reconstruction_hint={
                    "provider_config_id": 42,
                    "provider_type": "torznab",
                    "provider_item_id": "torrent-item-7",
                },
            )
        ],
    )

    private = read_server_candidate(
        engine,
        session_id=result["session_id"],
        candidate_id=result["candidates"][0]["candidate_id"],
        actor="alice",
        browser_session="raw-session-cookie",
        now=NOW,
    )
    assert private["state"] == "available"
    assert private["reconstruction"]["provider_config_id"] == 42
    assert private["reconstruction"]["provider_type"] == "torznab"
    assert private["reconstruction"]["provider_item_id"] == "torrent-item-7"


def test_persisted_rows_never_contain_credentials_urls_or_raw_cookie(engine):
    secret = "super-secret-api-key"
    raw_url = "https://user:password@example.invalid/download?apikey=%s" % secret
    evaluation = _evaluation(
        raw_url,
        legacy_match={
            "link": raw_url,
            "nzbid": raw_url,
            "entry": {"id": raw_url, "download": raw_url},
            "provider_stat": {
                "id": 17,
                "type": "newznab",
                "apikey": secret,
                "host": raw_url,
            },
        },
    )
    evaluation.candidate["provider"] = raw_url

    result = _create(engine, [evaluation])
    with engine.connect() as conn:
        session_row = dict(conn.execute(select(interactive_search_sessions)).mappings().one())
        candidate_row = dict(conn.execute(select(interactive_search_candidates)).mappings().one())
    persisted = json.dumps({"session": session_row, "candidate": candidate_row}, sort_keys=True)

    assert secret not in persisted
    assert raw_url not in persisted
    assert "raw-session-cookie" not in persisted
    assert "alice" not in persisted
    assert "password" not in persisted
    assert "apikey" not in persisted
    assert result["candidates"][0]["candidate"]["title"] == "[redacted URL]"

    private = read_server_candidate(
        engine,
        session_id=result["session_id"],
        candidate_id=result["candidates"][0]["candidate_id"],
        actor="alice",
        browser_session="raw-session-cookie",
        now=NOW,
    )
    assert set(private["reconstruction"]) == {
        "provider_config_id",
        "provider_type",
        "provider_name",
        "source_kind",
        "provider_item_id",
        "provider_item_digest",
        "match_kind",
        "pack",
    }
    assert private["reconstruction"]["provider_config_id"] == 17
    assert private["reconstruction"]["provider_item_id"] is None
    assert private["reconstruction"]["provider_name"] == "[redacted URL]"
    assert private["reconstruction"]["provider_type"] == "newznab"
    assert len(private["reconstruction"]["provider_item_digest"]) == 64


@pytest.mark.parametrize(
    ("actor", "browser_session"),
    [("mallory", "raw-session-cookie"), ("alice", "different-cookie")],
)
def test_session_requires_both_actor_and_browser_ownership(engine, actor, browser_session):
    result = _create(engine)

    with pytest.raises(InteractiveSearchAuthorizationError, match="not available"):
        read_session(
            engine,
            session_id=result["session_id"],
            actor=actor,
            browser_session=browser_session,
            now=NOW,
        )


def test_latest_creation_supersedes_one_actor_browser_item_slot(engine):
    first = _create(engine, [_evaluation("first")])
    second = _create(engine, [_evaluation("second")])
    other_item = _create(engine, [_evaluation("other")], entity_id="issue-126")

    assert first["session_id"] != second["session_id"]
    with pytest.raises(InteractiveSearchAuthorizationError, match="not available"):
        read_session(
            engine,
            session_id=first["session_id"],
            actor="alice",
            browser_session="raw-session-cookie",
            now=NOW,
        )
    assert (
        read_session(
            engine,
            session_id=second["session_id"],
            actor="alice",
            browser_session="raw-session-cookie",
            now=NOW,
        )["candidates"][0]["candidate"]["title"]
        == "second"
    )
    assert other_item["entity_id"] == "issue-126"
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(interactive_search_sessions)).scalar_one() == 2
        assert conn.execute(select(func.count()).select_from(interactive_search_candidates)).scalar_one() == 2


def test_concurrent_replacements_both_return_and_leave_one_complete_slot(engine):
    def create(title):
        return _create(engine, [_evaluation(title)])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ("first", "second")))

    assert len({result["session_id"] for result in results}) == 2
    with engine.connect() as conn:
        sessions = conn.execute(select(interactive_search_sessions)).mappings().all()
        candidates = conn.execute(select(interactive_search_candidates)).mappings().all()
    assert len(sessions) == 1
    assert len(candidates) == 1
    assert candidates[0]["session_id"] == sessions[0]["session_id"]
    assert sessions[0]["candidate_count"] == 1


def test_expiry_fails_closed_and_cleanup_is_bounded(engine):
    first = _create(engine, entity_id="issue-expired-1", ttl_seconds=1)
    _create(engine, entity_id="issue-expired-2", ttl_seconds=1)

    after_expiry = NOW + datetime.timedelta(seconds=2)
    with pytest.raises(InteractiveSearchExpired, match="expired"):
        read_session(
            engine,
            session_id=first["session_id"],
            actor="alice",
            browser_session="raw-session-cookie",
            now=after_expiry,
        )

    assert purge_expired_sessions(engine, now=after_expiry, batch_size=1) == {
        "sessions": 1,
        "candidates": 1,
    }
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(interactive_search_sessions)).scalar_one() == 1
    assert purge_expired_sessions(engine, now=after_expiry) == {"sessions": 1, "candidates": 1}


def test_session_survives_service_restart_boundary(engine):
    created = _create(engine)

    loaded = read_session(
        engine,
        session_id=created["session_id"],
        actor="alice",
        browser_session="raw-session-cookie",
        now=NOW + datetime.timedelta(seconds=30),
    )

    assert loaded == created


def test_candidate_and_record_limits_fail_before_any_write(engine):
    with pytest.raises(InteractiveSearchLimitError, match="candidate count"):
        _create(engine, [_evaluation()] * (MAX_CANDIDATES + 1))
    oversized = _evaluation()
    oversized.candidate["metrics"] = {"metric-%s" % index: index for index in range(10_000)}
    with pytest.raises(InteractiveSearchLimitError, match="per-record"):
        _create(engine, [oversized])

    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(interactive_search_sessions)).scalar_one() == 0
        assert conn.execute(select(func.count()).select_from(interactive_search_candidates)).scalar_one() == 0


def test_scheduler_job_name_matches_retention_service():
    assert JOB_ID == "interactive_search_retention"
    assert system_service.SCHEDULER_JOB_NAMES[JOB_ID] == JOB_NAME
