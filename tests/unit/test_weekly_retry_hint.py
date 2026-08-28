#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Upstream Retry-After hint parsing and scheduler honoring tests."""

import datetime
from email.utils import format_datetime
from unittest.mock import MagicMock

from comicarr import locg, weeklypullit


def test_retry_after_seconds_parses_delta_seconds():
    assert locg._retry_after_seconds("120") == 120


def test_retry_after_seconds_parses_http_date():
    retry_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=300)
    seconds = locg._retry_after_seconds(format_datetime(retry_at))
    assert seconds is not None
    assert 290 <= seconds <= 300


def test_retry_after_seconds_rejects_garbage_and_past_dates():
    assert locg._retry_after_seconds(None) is None
    assert locg._retry_after_seconds("") is None
    assert locg._retry_after_seconds("soon") is None
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    assert locg._retry_after_seconds(format_datetime(past)) is None


def _job_with_next_run(next_run):
    job = MagicMock()
    job.next_run_time = next_run
    return job


def test_honor_upstream_retry_moves_next_run_earlier(monkeypatch):
    now = datetime.datetime.now(datetime.timezone.utc)
    job = _job_with_next_run(now + datetime.timedelta(hours=6))
    scheduler = MagicMock()
    scheduler.get_job.return_value = job
    monkeypatch.setattr(weeklypullit, "_get_weekly_runtime_value", lambda *_args: scheduler)

    weeklypullit._honor_upstream_retry(120)

    job.modify.assert_called_once()
    new_time = job.modify.call_args.kwargs["next_run_time"]
    assert new_time < now + datetime.timedelta(minutes=5)


def test_honor_upstream_retry_never_delays_a_sooner_schedule(monkeypatch):
    now = datetime.datetime.now(datetime.timezone.utc)
    job = _job_with_next_run(now + datetime.timedelta(seconds=30))
    scheduler = MagicMock()
    scheduler.get_job.return_value = job
    monkeypatch.setattr(weeklypullit, "_get_weekly_runtime_value", lambda *_args: scheduler)

    weeklypullit._honor_upstream_retry(120)

    job.modify.assert_not_called()


def test_honor_upstream_retry_ignores_bad_or_excessive_hints(monkeypatch):
    scheduler = MagicMock()
    monkeypatch.setattr(weeklypullit, "_get_weekly_runtime_value", lambda *_args: scheduler)

    weeklypullit._honor_upstream_retry(None)
    weeklypullit._honor_upstream_retry("soon")
    weeklypullit._honor_upstream_retry(-5)
    weeklypullit._honor_upstream_retry(7200)

    scheduler.get_job.assert_not_called()
