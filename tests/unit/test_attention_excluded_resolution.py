#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Rows excluded from the operator queue must still be resolvable.

A non-actionable ``fail_reason`` is a *display* exclusion. If it also gated
resolution, the row would be unreachable in both directions: invisible in the
queue and refused by every action, so its release key could never be stamped
into a resolved status and never be reserved again.
"""

from types import SimpleNamespace

import pytest

import comicarr
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.attention import ResolutionRequest, read, resolve
from comicarr.app.attention._policy import is_actionable
from comicarr.app.core.context import AppContext
from comicarr.app.downloads import journal
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, issues, metadata

EXCLUDED_REASON = "torrent_hash_not_in_client"


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    monkeypatch.setattr(comicarr, "PROVIDER_BLOCKLIST", {}, raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            FAILED_DOWNLOAD_HANDLING=True,
            FAILED_AUTO=False,
            HIGHCOUNT=0,
            DDL_LOCATION=str(tmp_path / "ddl"),
            CACHE_DIR=str(tmp_path / "cache"),
            DESTINATION_DIR=str(tmp_path / "library"),
        ),
        raising=False,
    )
    engine = get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready
    yield
    shutdown_engine()


def _seed_excluded_manual_review():
    with get_engine().begin() as conn:
        conn.execute(
            comics.insert().values(
                ComicID="C1",
                ComicName="Saga",
                ComicYear="2012",
                Status="Active",
            )
        )
        conn.execute(
            issues.insert().values(
                IssueID="1001",
                ComicID="C1",
                ComicName="Saga",
                Issue_Number="1",
                Status="Snatched",
            )
        )

    release_key = "1001|rutracker"
    payload = {
        "issueid": "1001",
        "comicid": "C1",
        "comicname": "Saga",
        "issuenumber": "1",
        "provider": "rutracker",
        "nzbname": "Saga.001",
    }
    journal.record_transition(
        release_key,
        journal.SNATCHED,
        payload=payload,
        issueid="1001",
        provider="rutracker",
        nzbname="Saga.001",
    )
    journal.mark_manual_review(
        release_key,
        EXCLUDED_REASON,
        payload=payload,
        issueid="1001",
        provider="rutracker",
    )
    return release_key


def test_excluded_reason_is_hidden_from_the_queue_but_still_resolvable():
    assert is_actionable(EXCLUDED_REASON) is False
    release_key = _seed_excluded_manual_review()
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    # Display policy keeps it off the band...
    assert all(member.release_key != release_key for group in read().groups for member in group.members)

    # ...but the command path must still accept it, or the release key stays
    # un-reservable forever (never reaching a resolved status).
    report = resolve(
        ctx,
        ResolutionRequest(
            action="stop_wanting",
            release_keys=(release_key,),
            actor="operator",
        ),
    )

    assert report.succeeded == 1
    assert report.failed == 0
    item = report.results[0]
    assert item.ok is True
    assert item.problem is None
    assert item.status == "ignored"

    row = journal.read_one(release_key)
    assert row["status"] in journal.RESOLVED_STATUSES
