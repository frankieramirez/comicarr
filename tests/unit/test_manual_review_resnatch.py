#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The manual_review re-snatch wedge, at the handoff seam (#562).

`manual_review` is terminal (rank 55), so a release_key that ends there used to
refuse every later grab at `handoff.reserve` — including the operator's own
`retry` / `search again`, which re-wants the issue and queues a search but
leaves the journal row terminal. That made the operator exit unreachable for
that issue+provider: the sweep retried into the same wall every SEARCH_INTERVAL
and narrated nothing.

The boundary that stays: an *unresolved* manual_review row is an open
obligation on the needs-attention band and still blocks — but it now says why.
"""

import types

import pytest
from sqlalchemy import select

import comicarr
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.core.db import get_engine, shutdown_engine
from comicarr.app.core.tables import metadata, pipeline_journal
from comicarr.app.downloads import handoff, journal


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if not hasattr(comicarr, "LOG_LEVEL") or comicarr.LOG_LEVEL is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(HIGHCOUNT=0, POST_PROCESSING=False),
        raising=False,
    )
    engine = get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready
    yield
    shutdown_engine()


def _row(key):
    with get_engine().connect() as conn:
        row = conn.execute(select(pipeline_journal).where(pipeline_journal.c.release_key == key)).fetchone()
        return dict(row._mapping) if row else None


def _accepting_sender():
    return lambda: {"hash": "abc123"}


def _strand_in_manual_review(key, reason="submission_outcome_unknown:NameError"):
    """Drive a real handoff into manual review, the way a broken sender does."""

    def raising_sender():
        raise NameError("name 'r' is not defined")

    with pytest.raises(NameError):
        handoff.perform_handoff(key, "qbittorrent", raising_sender)
    assert _row(key)["stage"] == journal.MANUAL_REVIEW
    assert _row(key)["fail_reason"] == reason


def test_regrab_after_operator_resolution_no_longer_wedges():
    """The wedge itself: the operator's retry must be able to reach the sender."""
    key = "I1|qbittorrent"
    _strand_in_manual_review(key)

    # What the band's retry / search_again action does to the row.
    assert journal.stamp_resolution(key, journal.STATUS_RETRIED, increment_retry=True) is True

    response, acceptance = handoff.perform_handoff(key, "qbittorrent", _accepting_sender())

    assert response == {"hash": "abc123"}
    assert acceptance.restart_safe is True
    assert _row(key)["stage"] == journal.SNATCHED


def test_repeated_operator_retries_keep_working():
    """Not a one-shot unwedge — a later attempt that strands again resolves the
    same way, rather than the row becoming permanently stuck on round two."""
    key = "I2|qbittorrent"
    _strand_in_manual_review(key)

    for _ in range(2):
        assert journal.stamp_resolution(key, journal.STATUS_RETRIED, increment_retry=True) is True
        handoff.perform_handoff(key, "qbittorrent", _accepting_sender())
        assert _row(key)["stage"] == journal.SNATCHED
        # The re-grabbed attempt strands again, the way a route with no pollable
        # identity does on every single acceptance.
        assert journal.mark_manual_review(key, "route_not_restart_safe:watchdir") is True


def test_unresolved_manual_review_still_blocks_and_says_why(capture_logs):
    """The operator-exit boundary the activity-center doc draws, intact.

    An unresolved row means the client may already hold this release, so an
    automatic sweep must not reset it out from under the band. What changes is
    that the refusal is legible instead of a bare reservation error.
    """
    key = "I3|qbittorrent"
    _strand_in_manual_review(key)

    with pytest.raises(handoff.HandoffReservationError) as excinfo:
        handoff.perform_handoff(key, "qbittorrent", _accepting_sender())

    assert "awaiting operator review" in str(excinfo.value)
    assert "submission_outcome_unknown:NameError" in str(excinfo.value)
    assert "reservation refused" in capture_logs.text
    # And the band row is untouched.
    row = _row(key)
    assert row["stage"] == journal.MANUAL_REVIEW
    assert row["fail_reason"] == "submission_outcome_unknown:NameError"


def test_blocked_regrab_never_reaches_the_sender():
    """A refused reservation must not produce a second delivery."""
    key = "I4|qbittorrent"
    _strand_in_manual_review(key)

    calls = []

    def counting_sender():
        calls.append(1)
        return {"hash": "abc123"}

    with pytest.raises(handoff.HandoffReservationError):
        handoff.perform_handoff(key, "qbittorrent", counting_sender)

    assert calls == []


def test_failed_terminal_still_supersedes_without_operator_action():
    """The pre-existing failed -> re-snatch rule is unchanged."""
    key = "I5|qbittorrent"
    handoff.perform_handoff(key, "qbittorrent", lambda: "fail")
    assert _row(key)["stage"] == journal.FAILED

    handoff.perform_handoff(key, "qbittorrent", _accepting_sender())

    assert _row(key)["stage"] == journal.SNATCHED
