#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Each outcome of ``postprocessing.run``: what the retry loop does and says."""

import json
import threading
import types

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr import failed as failed_mod
from comicarr import postprocessor
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.downloads import journal, postprocessing
from comicarr.app.search import commands
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import metadata, pipeline_journal


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(
            HIGHCOUNT=0,
            MANUAL_PP_FOLDER=str(tmp_path),
            POST_PROCESSING=True,
            ACQUISITION_WORKERS_BLOCKED=False,
            FAILED_DOWNLOAD_HANDLING=True,
            FAILED_AUTO=True,
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "ACQUISITION_WORKERS_BLOCKED", False, raising=False)
    monkeypatch.setattr(comicarr, "APILOCK", threading.Lock(), raising=False)
    engine = get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready
    yield tmp_path
    shutdown_engine()


@pytest.fixture
def processor_runs(monkeypatch):
    """Script the folder processor: each run posts the next queued message."""
    runs = []
    script = []

    class FakeProcessor:
        def __init__(self, nzb_name, nzb_folder, issueid=None, *, queue, journal_release_key=None, **kwargs):
            runs.append({"nzb_name": nzb_name, "issueid": issueid, "journal_release_key": journal_release_key})
            self.queue = queue

        def Process(self):
            message = script.pop(0) if script else None
            if message is not None:
                self.queue.put(message)

    monkeypatch.setattr(postprocessor, "PostProcessor", FakeProcessor)
    return runs, script


@pytest.fixture
def failed_runs(monkeypatch):
    runs = []
    script = []

    class FakeFailedProcessor:
        def __init__(self, *, queue, **kwargs):
            runs.append(kwargs)
            self.queue = queue

        def Process(self):
            self.queue.put(script.pop(0))

    monkeypatch.setattr(failed_mod, "FailedProcessor", FakeFailedProcessor)
    return runs, script


def _item(tmp_path, key, **overrides):
    item = {
        "nzb_name": "Saga.001.cbz",
        "nzb_folder": str(tmp_path),
        "issueid": "I1",
        "comicid": "C1",
        "failed": False,
        "apicall": True,
        "ddl": False,
        "download_info": {"id": "nzo-1", "provider": "sabnzbd"},
        "source": "queued",
        "journal_release_key": key,
    }
    item.update(overrides)
    return item


def _downloaded(key):
    with get_engine().begin() as conn:
        conn.execute(
            insert(pipeline_journal).values(
                release_key=key,
                stage=journal.DOWNLOADED,
                stage_rank=journal.stage_rank(journal.DOWNLOADED),
                issueid="I1",
                provider="sabnzbd",
                payload_json=json.dumps({}),
                updated_date="2026-11-13 00:00:00",
            )
        )


def _row(key):
    with get_engine().connect() as conn:
        row = conn.execute(select(pipeline_journal).where(pipeline_journal.c.release_key == key)).fetchone()
    return dict(row._mapping) if row else None


def test_a_processor_that_runs_to_its_end_is_completed(tmp_path, processor_runs, failed_runs):
    runs, script = processor_runs
    script.append([{"self.log": "", "mode": "stop"}])
    _downloaded("rk-success")

    result = postprocessing.run(_item(tmp_path, "rk-success"))

    assert result.status == "processed"
    assert result.outcome == postprocessing.COMPLETED
    assert result.fail_reason is None
    assert result.value == [{"self.log": "", "mode": "stop"}]
    assert [run["journal_release_key"] for run in runs] == ["rk-success"]
    assert failed_runs[0] == []


def test_a_failed_download_goes_to_failed_handling_and_back_to_search(
    tmp_path, monkeypatch, processor_runs, failed_runs
):
    runs, _ = processor_runs
    handed, script = failed_runs
    retry = {"self.log": "", "mode": "retry", "issueid": "I1", "comicid": "C1", "annchk": "no"}
    script.append([retry])
    retried = []
    monkeypatch.setattr(commands, "enqueue_failed_download_retry", retried.append)
    _downloaded("rk-failed")

    result = postprocessing.run(_item(tmp_path, "rk-failed", failed=True))

    assert result.status == "processed"
    assert result.outcome == postprocessing.FAILED
    assert runs == [], "a failed download is never processed as a folder"
    assert handed[0]["prov"] == "sabnzbd"
    assert handed[0]["id"] == "nzo-1"
    assert handed[0]["journal_release_key"] == "rk-failed"
    assert retried == [retry]


def test_failed_handling_off_closes_the_journal_with_its_reason(tmp_path, monkeypatch, processor_runs, failed_runs):
    monkeypatch.setattr(comicarr.CONFIG, "FAILED_DOWNLOAD_HANDLING", False)
    _downloaded("rk-left")

    result = postprocessing.run(_item(tmp_path, "rk-left", failed=True))

    assert result.outcome == postprocessing.FAILED
    assert result.fail_reason == failed_mod.FAIL_REASON_NO_AUTO_HANDLING
    assert failed_runs[0] == []
    row = _row("rk-left")
    assert row["stage"] == journal.FAILED
    assert row["fail_reason"] == failed_mod.FAIL_REASON_NO_AUTO_HANDLING


def test_a_download_outside_its_folder_is_retried_as_a_manual_run(tmp_path, processor_runs, failed_runs):
    runs, script = processor_runs
    script.append([{"self.log": "", "mode": "outside"}])
    script.append([{"self.log": "", "mode": "stop"}])
    _downloaded("rk-outside")

    result = postprocessing.run(_item(tmp_path, "rk-outside"))

    assert result.outcome == postprocessing.COMPLETED
    assert result.value == [{"self.log": "", "mode": "stop"}]
    assert runs == [
        {"nzb_name": "Saga.001.cbz", "issueid": "I1", "journal_release_key": "rk-outside"},
        {"nzb_name": "Manual Run", "issueid": None, "journal_release_key": "rk-outside"},
    ]
    assert failed_runs[0] == []


def test_a_fail_message_from_the_outside_rerun_is_failed(tmp_path, processor_runs, failed_runs):
    _, script = processor_runs
    script.append([{"self.log": "", "mode": "outside"}])
    script.append([{"self.log": "rerun", "mode": "fail"}])
    _downloaded("rk-outside-fail")

    result = postprocessing.run(_item(tmp_path, "rk-outside-fail"))

    assert result.outcome == postprocessing.FAILED
    assert result.value == [{"self.log": "rerun", "mode": "fail"}]
    assert failed_runs[0] == [], "the rerun's fail is reported, not handed to failed handling"


def test_a_fail_message_on_a_monitor_scan_is_failed(tmp_path, processor_runs):
    _, script = processor_runs
    script.append([{"self.log": "", "mode": "fail"}])

    result = postprocessing.run({"nzb_name": "Manual Run", "nzb_folder": str(tmp_path), "source": "monitor"})

    assert result.status == "processed"
    assert result.outcome == postprocessing.FAILED


def test_a_fail_message_keeps_its_log_when_failed_handling_is_off(tmp_path, monkeypatch, processor_runs, failed_runs):
    monkeypatch.setattr(comicarr.CONFIG, "FAILED_DOWNLOAD_HANDLING", False)
    _, script = processor_runs
    script.append([{"self.log": "why it failed", "mode": "fail"}])
    _downloaded("rk-fail-kept")

    result = postprocessing.run(_item(tmp_path, "rk-fail-kept"))

    assert result.outcome == postprocessing.FAILED
    assert result.fail_reason == failed_mod.FAIL_REASON_NO_AUTO_HANDLING
    assert result.value == [{"self.log": "why it failed", "mode": "fail"}]
    assert failed_runs[0] == []


def test_a_processor_that_posts_nothing_has_nothing_to_do(tmp_path, processor_runs):
    _downloaded("rk-quiet")

    result = postprocessing.run(_item(tmp_path, "rk-quiet"))

    assert result.status == "processed"
    assert result.outcome == postprocessing.NOTHING
    assert result.value is None


@pytest.mark.parametrize("source", ["manual", "monitor"])
def test_a_busy_run_is_deferred_and_touches_nothing(tmp_path, processor_runs, source):
    runs, _ = processor_runs
    _downloaded("rk-busy")
    assert comicarr.APILOCK.acquire(blocking=False)
    try:
        if source == "monitor":
            request = {"nzb_name": "Manual Run", "nzb_folder": str(tmp_path), "source": "monitor"}
        else:
            request = _item(tmp_path, "rk-busy")
        result = postprocessing.run(request)
    finally:
        comicarr.APILOCK.release()

    assert result.status == "busy"
    assert result.outcome == postprocessing.DEFERRED
    assert result.action == "retry"
    assert runs == []
    assert _row("rk-busy")["stage"] == journal.DOWNLOADED


def test_a_busy_direct_request_answers_409(tmp_path, monkeypatch, processor_runs):
    from comicarr.app.downloads import service

    assert comicarr.APILOCK.acquire(blocking=False)
    try:
        response = service.process_issue("C1", str(tmp_path), issueid="I1")
    finally:
        comicarr.APILOCK.release()

    assert response["status_code"] == 409
    assert processor_runs[0] == []


def test_process_module_is_gone_and_nothing_imports_it():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    assert not (root / "comicarr" / "process.py").exists()
    offenders = []
    for path in (root / "comicarr").rglob("*.py"):
        if "_vendor" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import) and any(alias.name == "comicarr.process" for alias in node.names):
                offenders.append(str(path))
            elif isinstance(node, ast.ImportFrom):
                if node.module == "comicarr.process" or (
                    node.module == "comicarr" and any(alias.name == "process" for alias in node.names)
                ):
                    offenders.append(str(path))
                elif node.level and node.module is None and any(alias.name == "process" for alias in node.names):
                    offenders.append(str(path))
    assert offenders == []
