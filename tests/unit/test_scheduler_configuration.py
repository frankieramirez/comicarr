#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import ast
from pathlib import Path

import comicarr

_INIT_PATH = Path(__file__).resolve().parents[2] / "comicarr" / "__init__.py"
_RECURRING_JOB_IDS = {
    "dbupdater",
    "search",
    "weekly",
    "rss",
    "version",
    "monitor",
    "importinbox",
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

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "_add_recurring_job":
            continue

        for keyword in node.keywords:
            if keyword.arg == "id" and isinstance(keyword.value, ast.Constant):
                helper_job_ids.add(keyword.value.value)

    missing_job_ids = _RECURRING_JOB_IDS - helper_job_ids

    assert not missing_job_ids
