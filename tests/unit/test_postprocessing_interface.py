#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Interface tests for the post-processing execution and recovery seam."""

import json
import threading
import types

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.downloads import journal, postprocessing
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, issues, metadata, nzblog, pipeline_journal


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
            FILE_OPTS="move",
            ENABLE_META=False,
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "ACQUISITION_WORKERS_BLOCKED", False, raising=False)
    engine = get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready
    yield tmp_path
    shutdown_engine()


@pytest.fixture
def apilock(monkeypatch):
    lock = threading.Lock()
    monkeypatch.setattr(comicarr, "APILOCK", lock, raising=False)
    return lock


def _row(key):
    with get_engine().connect() as conn:
        result = conn.execute(select(pipeline_journal).where(pipeline_journal.c.release_key == key)).fetchone()
    return dict(result._mapping) if result else None


def _item(tmp_path, **overrides):
    item = {
        "nzb_name": "Saga.001.cbz",
        "nzb_folder": str(tmp_path),
        "issueid": "I1",
        "comicid": "C1",
        "failed": False,
        "apicall": True,
        "ddl": False,
        "download_info": None,
        "source": "queued",
    }
    item.update(overrides)
    return item


def _insert_journal(key, stage, *, payload=None, issueid="I1", provider=None):
    with get_engine().begin() as conn:
        conn.execute(
            insert(pipeline_journal).values(
                release_key=key,
                stage=stage,
                stage_rank=journal.stage_rank(stage),
                issueid=issueid,
                provider=provider,
                payload_json=json.dumps(payload or {}),
                updated_date="2026-09-05 00:00:00",
            )
        )


def test_run_claims_canonical_key_and_executes_under_public_lock(monkeypatch, tmp_path, apilock):
    key = "provider-release-1"
    _insert_journal(key, journal.DOWNLOADED)
    seen = {}

    def execute(item):
        seen["item"] = item
        seen["locked"] = apilock.locked()
        return None

    monkeypatch.setattr(postprocessing, "_execute", execute)
    result = postprocessing.run(_item(tmp_path, journal_release_key=key))

    assert result.status == "processed"
    assert seen["locked"] is True
    assert _row(key)["stage"] == journal.POST_PROCESSING
    assert apilock.locked() is False


def test_run_busy_leaves_journal_untouched(monkeypatch, tmp_path, apilock):
    key = "busy-release"
    _insert_journal(key, journal.DOWNLOADED)
    assert apilock.acquire(blocking=False)
    before = _row(key)

    result = postprocessing.run(_item(tmp_path, journal_release_key=key))

    assert result.status == "busy"
    assert result.action == "retry"
    assert result.detail
    assert _row(key)["stage"] == before["stage"]
    apilock.release()


def test_run_duplicate_does_not_execute_or_regress(monkeypatch, tmp_path, monkeypatch_exec):
    key = "duplicate-release"
    _insert_journal(key, journal.POST_PROCESSING)
    result = postprocessing.run(_item(tmp_path, journal_release_key=key))
    assert result.status == "duplicate"
    assert _row(key)["stage"] == journal.POST_PROCESSING


@pytest.fixture
def monkeypatch_exec(monkeypatch):
    calls = []
    monkeypatch.setattr(postprocessing, "_execute", lambda item: calls.append(item))
    return calls


def test_run_propagated_key_claim_failure_is_retryable_and_does_not_execute(monkeypatch, tmp_path, apilock):
    key = "claim-failure"
    monkeypatch.setattr(
        postprocessing.journal, "record_transition", lambda *a, **k: (_ for _ in ()).throw(RuntimeError())
    )
    calls = []
    monkeypatch.setattr(postprocessing, "_execute", lambda item: calls.append(item))

    result = postprocessing.run(_item(tmp_path, journal_release_key=key))

    assert result.status == "busy"
    assert result.action == "retry"
    assert calls == []
    assert _row(key) is None
    assert apilock.locked() is False


def test_run_manual_without_key_keeps_legacy_fallback_when_journal_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        postprocessing.journal, "record_transition", lambda *a, **k: (_ for _ in ()).throw(RuntimeError())
    )
    calls = []
    monkeypatch.setattr(postprocessing, "_execute", lambda item: calls.append(item))

    result = postprocessing.run(_item(tmp_path, source="manual", journal_release_key=None))

    assert result.status == "processed"
    assert len(calls) == 1
    assert calls[0]["source"] == "manual"


@pytest.mark.parametrize("source", ["manual", "compat", "monitor"])
def test_unjournaled_compatibility_scans_are_not_suppressed_by_display_name(monkeypatch, tmp_path, source):
    calls = []
    monkeypatch.setattr(postprocessing, "validate_postprocess_item", lambda item: dict(item))
    monkeypatch.setattr(postprocessing, "_execute", lambda item: calls.append(item.copy()))

    first = postprocessing.run(_item(tmp_path, source=source, journal_release_key=None))
    second = postprocessing.run(_item(tmp_path, source=source, journal_release_key=None))

    assert first.status == "processed"
    assert second.status == "processed"
    assert len(calls) == 2
    assert all(call.get("journal_release_key") is None for call in calls)
    assert _row(journal.derive_release_key({"issueid": "I1", "comicid": "C1", "nzbname": "Saga.001.cbz"})) is None


def test_constructor_failure_releases_global_lock(monkeypatch, tmp_path, apilock):
    def constructor_failure(_item):
        raise TypeError("post-processor constructor failed")

    monkeypatch.setattr(postprocessing, "_execute", constructor_failure)
    result = postprocessing.run(_item(tmp_path, source="manual", journal_release_key=None))

    assert result.status == "failed"
    assert "constructor failed" in result.detail
    assert apilock.locked() is False


def test_nested_retry_outside_keeps_canonical_key_and_public_lock(monkeypatch, tmp_path, apilock):
    seen = []
    monkeypatch.setattr(comicarr.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)

    def process_once(self):
        seen.append((self.journal_release_key, self.apicall, apilock.locked()))
        mode = "outside" if len(seen) == 1 else "stop"
        self.queue.put([{"mode": mode}])

    monkeypatch.setattr(comicarr.postprocessor.PostProcessor, "Process", process_once)
    key = "nested-retry-release"
    _insert_journal(key, journal.DOWNLOADED)

    result = postprocessing.run(_item(tmp_path, journal_release_key=key, apicall=True))

    assert result.status == "processed"
    assert seen == [(key, True, True), (key, False, True)]
    assert apilock.locked() is False


@pytest.mark.parametrize("origin", ["monitor", "queued"])
def test_run_executes_real_legacy_manga_adapter_and_completes(tmp_path, monkeypatch, apilock, origin):
    comic_id = "md-real-manga"
    issue_id = "md-real-manga-ch1"
    manga_root = tmp_path / "manga"
    series_root = manga_root / "Real Manga"
    with get_engine().begin() as conn:
        conn.execute(
            insert(comics).values(
                ComicID=comic_id,
                ComicName="Real Manga",
                ContentType="manga",
                ComicLocation=str(series_root),
            )
        )
        conn.execute(
            insert(issues).values(
                IssueID=issue_id,
                ComicID=comic_id,
                ComicName="Real Manga",
                Issue_Number="1",
                ChapterNumber="1",
                Status="Wanted",
            )
        )
    release_key = "real-manga-release" if origin == "queued" else None
    if release_key:
        _insert_journal(
            release_key,
            journal.DOWNLOADED,
            payload={
                "issueid": issue_id,
                "comicid": comic_id,
                "nzb_name": "Real Manga Pack",
                "nzb_folder": str(tmp_path / "incoming"),
                "failed": False,
                "apicall": False,
                "ddl": False,
            },
            issueid=issue_id,
            provider="manga-test",
        )
        with get_engine().begin() as conn:
            conn.execute(insert(nzblog).values(IssueID=issue_id, PROVIDER="manga-test"))
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "Real Manga 1.cbz").write_bytes(b"comic")
    destination = series_root
    destination.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(comicarr.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)
    monkeypatch.setattr(comicarr.CONFIG, "FILE_OPTS", "move", raising=False)
    monkeypatch.setattr(
        "comicarr.postprocessor.get_manga_destination",
        lambda: str(manga_root),
    )
    stages = []
    record_transition = journal.record_transition

    def record_under_lock(key, stage, **kwargs):
        assert apilock.locked(), stage
        stages.append(stage)
        return record_transition(key, stage, **kwargs)

    monkeypatch.setattr(journal, "record_transition", record_under_lock)

    result = postprocessing.run(
        {
            "nzb_name": "Real Manga Pack",
            "nzb_folder": str(incoming),
            "issueid": None,
            "comicid": comic_id,
            "failed": False,
            "apicall": False,
            "ddl": False,
            "download_info": None,
            "source": origin,
            "journal_release_key": release_key,
        }
    )

    assert result.status == "processed", result
    assert journal.POST_PROCESSED in stages
    assert destination.joinpath("Real Manga 1.cbz").exists()
    with get_engine().connect() as conn:
        issue = conn.execute(select(issues).where(issues.c.IssueID == issue_id)).fetchone()
    assert issue._mapping["Status"] == "Downloaded"
    assert issue._mapping["Location"] == "Real Manga 1.cbz"
    if origin == "queued":
        assert _row(release_key)["stage"] == journal.POST_PROCESSED
        with get_engine().connect() as conn:
            assert conn.execute(select(nzblog).where(nzblog.c.IssueID == issue_id)).fetchall() == []
    assert apilock.locked() is False


def test_run_releases_only_its_lock_owner_after_early_failure(monkeypatch, tmp_path, apilock):
    def fail(_item):
        assert apilock.locked()
        raise RuntimeError("execution failed")

    monkeypatch.setattr(postprocessing, "_execute", fail)
    result = postprocessing.run(_item(tmp_path, journal_release_key=None, source="manual"))

    assert result.status == "failed"
    assert apilock.locked() is False


def test_recover_moved_finishes_db_facts_without_execution(monkeypatch, tmp_path):
    key = "moved-release"
    _insert_journal(key, journal.MOVED, payload={"issueid": "I1", "nzb_name": "Saga.001.cbz"})
    with get_engine().begin() as conn:
        conn.execute(insert(nzblog).values(IssueID="I1", PROVIDER="NZB"))
    calls = []
    monkeypatch.setattr(postprocessing, "_execute", lambda item: calls.append(item))

    result = postprocessing.recover(key)

    assert result.status == "processed"
    assert result.action == "moved-finish-dbfacts"
    assert calls == []
    assert _row(key)["stage"] == journal.POST_PROCESSED
    with get_engine().connect() as conn:
        assert conn.execute(select(nzblog)).fetchall() == []


def test_recover_post_processing_redrives_without_fresh_claim(monkeypatch, tmp_path, monkeypatch_exec):
    key = "redrive-release"
    _insert_journal(
        key,
        journal.POST_PROCESSING,
        payload={
            "issueid": "I1",
            "comicid": "C1",
            "nzb_name": "Saga.001.cbz",
            "nzb_folder": str(tmp_path),
            "failed": False,
            "apicall": True,
            "ddl": False,
        },
    )

    result = postprocessing.recover(key)

    assert result.status == "processed"
    assert result.action == "post_processing-redrive"
    assert len(monkeypatch_exec) == 1
    assert monkeypatch_exec[0]["journal_release_key"] == key
    assert _row(key)["stage"] == journal.POST_PROCESSING


def test_recover_terminal_or_changed_row_is_ignored(monkeypatch, tmp_path, monkeypatch_exec):
    key = "terminal-release"
    _insert_journal(key, journal.POST_PROCESSED)

    result = postprocessing.recover(key)

    assert result.status == "ignored"
    assert result.action == "ignored"
    assert monkeypatch_exec == []


def test_recover_busy_is_retryable_and_does_not_redrive(monkeypatch, tmp_path, apilock):
    key = "recover-busy"
    _insert_journal(
        key,
        journal.POST_PROCESSING,
        payload={"issueid": "I1", "nzb_name": "Saga.001.cbz", "nzb_folder": str(tmp_path)},
    )
    assert apilock.acquire(blocking=False)

    result = postprocessing.recover(key)

    assert result.status == "busy"
    assert result.action == "post_processing-busy"
    assert _row(key)["stage"] == journal.POST_PROCESSING
    apilock.release()
