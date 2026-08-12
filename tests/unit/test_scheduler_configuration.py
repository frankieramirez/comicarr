#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import ast
import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
)

import comicarr
from comicarr import searchit
from comicarr.app.common.dates import normalize_utc_datetime, utc_date_to_local
from comicarr.app.system import service as system_service

_INIT_PATH = Path(__file__).resolve().parents[2] / "comicarr" / "__init__.py"
_RECURRING_JOB_IDS = {
    "dbupdater",
    "search",
    "weekly",
    "rss",
    "version",
    "monitor",
    "importinbox",
    "ddl_health",
    "ledger_retention",
    "activity_retention",
    "interactive_search_retention",
}


class _FakeScheduler:
    def __init__(self):
        self.calls = []

    def add_job(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs


def test_add_recurring_job_sets_single_instance_options(monkeypatch):
    scheduler = _FakeScheduler()
    job_func = object()
    monkeypatch.setattr(comicarr, "SCHED", scheduler)

    result = comicarr._add_recurring_job(func=job_func, id="example")

    assert result is scheduler.calls[0]
    assert scheduler.calls[0]["func"] is job_func
    assert scheduler.calls[0]["id"] == "example"
    assert scheduler.calls[0]["max_instances"] == 1
    assert scheduler.calls[0]["coalesce"] is True


def test_listed_recurring_jobs_use_recurring_helper():
    tree = ast.parse(_INIT_PATH.read_text(encoding="utf-8"))
    helper_job_ids = set()
    direct_interval_job_ids = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "_add_recurring_job":
            continue

        for keyword in node.keywords:
            if keyword.arg == "id" and isinstance(keyword.value, ast.Constant):
                helper_job_ids.add(keyword.value.value)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_job":
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "SCHED":
            continue

        has_interval_trigger = False
        job_id = "<unknown>"
        for keyword in node.keywords:
            if keyword.arg == "trigger" and isinstance(keyword.value, ast.Call):
                if isinstance(keyword.value.func, ast.Name) and keyword.value.func.id == "IntervalTrigger":
                    has_interval_trigger = True
            if keyword.arg == "id" and isinstance(keyword.value, ast.Constant):
                job_id = keyword.value.value

        if has_interval_trigger:
            direct_interval_job_ids.append(job_id)

    missing_job_ids = _RECURRING_JOB_IDS - helper_job_ids

    assert not missing_job_ids
    assert not direct_interval_job_ids


def test_datetime_normalization_accepts_aware_and_legacy_naive_values():
    utc = datetime.timezone.utc
    eastern = datetime.timezone(datetime.timedelta(hours=-4))

    assert normalize_utc_datetime(datetime.datetime(2026, 7, 10, 20, tzinfo=utc)) == datetime.datetime(
        2026, 7, 10, 20, tzinfo=utc
    )
    assert normalize_utc_datetime(datetime.datetime(2026, 7, 10, 16, tzinfo=eastern)) == datetime.datetime(
        2026, 7, 10, 20, tzinfo=utc
    )
    assert normalize_utc_datetime(datetime.datetime(2026, 7, 10, 20)) == datetime.datetime(2026, 7, 10, 20, tzinfo=utc)
    assert utc_date_to_local(datetime.datetime(2026, 7, 10, 20, tzinfo=utc)).tzinfo is not None


def test_scheduler_events_persist_distinct_terminal_dispatch_states(monkeypatch):
    upsert = MagicMock()
    monkeypatch.setattr(system_service.db, "upsert", upsert)
    scheduled = datetime.datetime(2026, 7, 10, 20, tzinfo=datetime.timezone.utc)

    cases = [
        (EVENT_JOB_EXECUTED, {}, "accepted"),
        (EVENT_JOB_ERROR, {"exception": RuntimeError("token=secret upstream failed")}, "error"),
        (EVENT_JOB_MISSED, {}, "missed"),
        (EVENT_JOB_MAX_INSTANCES, {"scheduled_run_times": [scheduled]}, "max_instances"),
    ]
    for code, extra, expected in cases:
        event = SimpleNamespace(code=code, job_id="search", scheduled_run_time=scheduled, **extra)
        system_service.persist_scheduler_event(event)
        assert upsert.call_args.args[0] == "jobhistory"
        assert upsert.call_args.args[2] == {"JobName": "Auto-Search"}
        assert upsert.call_args.args[1]["status"] == expected

    error_values = upsert.call_args_list[1].args[1]
    assert error_values["last_error"] == "token=[redacted] upstream failed"
    assert "secret" not in str(upsert.call_args_list)


def test_register_scheduler_listener_is_idempotent():
    scheduler = MagicMock()

    assert system_service.register_scheduler_health_listener(scheduler) is True
    assert system_service.register_scheduler_health_listener(scheduler) is False
    scheduler.add_listener.assert_called_once()


def test_scheduled_search_failure_is_supervised_and_propagated(monkeypatch):
    job_management = MagicMock()
    monkeypatch.setattr(searchit.helpers, "job_management", job_management)
    monkeypatch.setattr(searchit.helpers, "utctimestamp", lambda: 123.0)
    monkeypatch.setattr(comicarr.search, "searchforissue", MagicMock(side_effect=RuntimeError("provider down")))

    with pytest.raises(RuntimeError, match="provider down"):
        searchit.CurrentSearcher().run()

    assert comicarr.SEARCH_STATUS == "Error"
    assert job_management.call_args_list[-1].kwargs == {
        "write": True,
        "job": "Auto-Search",
        "last_run_completed": 123.0,
        "status": "Error",
        "failure": True,
        "failure_message": job_management.call_args_list[-1].kwargs["failure_message"],
    }
