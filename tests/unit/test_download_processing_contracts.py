#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import queue
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests
from sqlalchemy import insert, select

import comicarr
from comicarr import db, getcomics
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.downloads import pp_commands, recovery, router, service
from comicarr.app.downloads.ddl_commands import DDLCommand
from comicarr.downloaders import mediafire
from comicarr.tables import ddl_info, metadata


@pytest.fixture(autouse=True)
def _reset_ddl_process_ownership(monkeypatch):
    monkeypatch.setattr(comicarr, "DDL_QUEUED", set(), raising=False)


def _complete_ddl_payload(**overrides):
    payload = {
        "id": "ddl-1",
        "link": "https://downloads.invalid/issue.cbz",
        "site": "DDL(GetComics)",
        "series": "Saga",
        "year": "2026",
        "size": "10 MB",
        "comicid": "comic-1",
        "issueid": "issue-1",
        "oneoff": False,
        "link_type": "GC-Main",
        "filename": "Saga 001.cbz",
        "mainlink": "https://getcomics.invalid/saga",
        "comicinfo": [{"pack": False, "IssueID": "issue-1"}],
        "packinfo": None,
        "remote_filesize": 10_485_760,
        "resume": None,
        "issues": "1",
        "pack": False,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def sqlite_ddl_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    db.shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            DDL_LOCATION=str(tmp_path / "downloads"),
            CACHE_DIR=str(tmp_path / "cache"),
            ENFORCE_PERMS=False,
            CHMOD_FILE="0660",
            CHMOD_DIR="0777",
        ),
    )
    engine = db.get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready
    yield engine
    db.shutdown_engine()


def test_process_issue_passes_issueid_by_keyword(monkeypatch):
    process_instance = MagicMock()
    process_class = MagicMock(return_value=process_instance)
    monkeypatch.setattr(service.process, "Process", process_class)

    result = service.process_issue("comic-1", "/downloads/Saga", issueid="issue-1")

    assert result["success"] is True
    process_class.assert_called_once_with(
        nzb_name="comic-1",
        nzb_folder="/downloads/Saga",
        issueid="issue-1",
    )


def test_postprocess_command_rejects_traversal_prefix_collision_and_symlink_escape(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    valid = root / "job"
    valid.mkdir()
    outside = tmp_path / "downloads-evil"
    outside.mkdir()
    symlink = root / "escaped"
    symlink.symlink_to(outside, target_is_directory=True)

    command = pp_commands.validate_postprocess_item(
        {"nzb_name": "Saga.001.cbz", "nzb_folder": str(valid)},
        roots=[root],
    )
    assert command["nzb_folder"] == str(valid.resolve())

    for name, folder in (
        ("../Saga.001.cbz", valid),
        ("subdir/Saga.001.cbz", valid),
        (r"subdir\Saga.001.cbz", valid),
        ("Saga.001.cbz", outside),
        ("Saga.001.cbz", symlink),
    ):
        with pytest.raises(pp_commands.PostProcessCommandError):
            pp_commands.validate_postprocess_item(
                {"nzb_name": name, "nzb_folder": str(folder)},
                roots=[root],
            )


def test_postprocess_worker_quarantines_owned_failure_and_continues(sqlite_ddl_db, monkeypatch, tmp_path):
    first = {
        "nzb_name": "First.cbz",
        "nzb_folder": str(tmp_path),
        "issueid": "issue-first",
        "comicid": "comic-1",
        "failed": False,
        "apicall": True,
        "ddl": False,
        "download_info": None,
    }
    second = {**first, "nzb_name": "Second.cbz", "issueid": "issue-second"}
    q = queue.Queue()
    q.put(first)
    q.put(second)
    q.put("exit")
    calls = []

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            calls.append(args[0])

        def post_process(self):
            if calls[-1] == "First.cbz":
                raise RuntimeError("secret=/very/private/path")

    monkeypatch.setattr(service.process, "Process", FakeProcess)
    monkeypatch.setattr(service, "_configured_postprocess_roots", lambda: [tmp_path])

    service.postprocess_main(q)

    assert calls == ["First.cbz", "Second.cbz"]


def test_postprocess_maintenance_block_happens_before_claim(sqlite_ddl_db, monkeypatch, tmp_path):
    from comicarr.app.acquisition import maintenance
    from comicarr.app.downloads import journal

    folder = tmp_path / "downloads" / "fenced"
    folder.mkdir(parents=True)
    key = journal.release_key("fenced-issue", "nzb.su")
    journal.record_transition(
        key,
        journal.DOWNLOADED,
        payload={"issueid": "fenced-issue", "nzb_name": "Fenced.cbz", "nzb_folder": str(folder)},
        issueid="fenced-issue",
        provider="nzb.su",
    )
    item = {
        "nzb_name": "Fenced.cbz",
        "nzb_folder": str(folder),
        "issueid": "fenced-issue",
        "comicid": "comic-1",
        "failed": False,
        "apicall": True,
        "ddl": False,
        "download_info": None,
        "journal_release_key": key,
    }
    q = queue.Queue()
    q.put(item)
    q.put("exit")
    process_class = MagicMock()
    monkeypatch.setattr(service.process, "Process", process_class)
    monkeypatch.setattr(
        maintenance.MaintenanceController,
        "acquire_lease",
        MagicMock(side_effect=maintenance.MaintenanceBlocked("fenced")),
    )

    service.postprocess_main(q)

    assert journal.read_one(key)["stage"] == journal.DOWNLOADED
    process_class.assert_not_called()
    assert q.get_nowait()["journal_release_key"] == key


def test_torrent_downloaded_persistence_failure_never_hands_unowned_pp(sqlite_ddl_db, monkeypatch, tmp_path):
    from comicarr.app.downloads import journal

    artifact = tmp_path / "downloads" / "Torrent.cbz"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"comic")
    key = journal.release_key("torrent-issue", "torznab", nzbname="Torrent.cbz")
    journal.record_transition(
        key,
        journal.SNATCHED,
        payload={"issueid": "torrent-issue", "provider": "torznab", "route": "rtorrent", "hash": "hash"},
        issueid="torrent-issue",
        provider="torznab",
        downloader_type="rtorrent",
        hash="hash",
    )
    real_transition = journal.record_transition

    def fail_downloaded(*args, **kwargs):
        if args[1] == journal.DOWNLOADED:
            raise RuntimeError("journal unavailable")
        return real_transition(*args, **kwargs)

    monkeypatch.setattr(journal, "record_transition", fail_downloaded)
    pp_queue = queue.Queue()
    monkeypatch.setattr(comicarr, "PP_QUEUE", pp_queue)

    service._handle_torrent_monitor_result(
        {
            "issueid": "torrent-issue",
            "comicid": "comic-1",
            "provider": "torznab",
            "hash": "hash",
            "nzbname": "Torrent.cbz",
            "journal_release_key": key,
        },
        {"snatch_status": "MONITOR COMPLETE", "copied_filepath": str(artifact)},
    )

    assert pp_queue.empty()
    assert journal.read_one(key)["stage"] == journal.MANUAL_REVIEW


def test_nzb_downloaded_persistence_failure_never_hands_unowned_pp(sqlite_ddl_db, monkeypatch, tmp_path):
    from comicarr.app.downloads import journal

    folder = tmp_path / "downloads" / "sab-job"
    folder.mkdir(parents=True)
    (folder / "Saga.cbz").write_bytes(b"comic")
    key = journal.release_key("nzb-issue", "nzb.su")
    journal.record_transition(
        key,
        journal.SNATCHED,
        payload={"issueid": "nzb-issue", "provider": "nzb.su", "route": "sabnzbd", "nzo_id": "sab-id"},
        issueid="nzb-issue",
        provider="nzb.su",
        downloader_type="sabnzbd",
    )
    real_transition = journal.record_transition

    def fail_downloaded(*args, **kwargs):
        if args[1] == journal.DOWNLOADED:
            raise RuntimeError("journal unavailable")
        return real_transition(*args, **kwargs)

    monkeypatch.setattr(journal, "record_transition", fail_downloaded)
    monkeypatch.setattr("comicarr.helpers.check_file_condition", lambda path: {"status": True})
    pp_queue = queue.Queue()
    monkeypatch.setattr(comicarr, "PP_QUEUE", pp_queue)
    item = {
        "nzo_id": "sab-id",
        "journal_release_key": key,
        "clientmode": "sabnzbd",
    }
    nzstat = {
        "status": True,
        "failed": False,
        "name": "Saga.cbz",
        "location": str(folder),
        "issueid": "nzb-issue",
        "comicid": "comic-1",
        "apicall": True,
        "download_info": {"provider": "nzb.su", "id": "provider-result"},
    }

    service.cdh_monitor(queue.Queue(), item, nzstat)

    assert pp_queue.empty()
    assert journal.read_one(key)["stage"] == journal.MANUAL_REVIEW


def test_queue_ddl_persists_reconstructable_command_before_enqueue(monkeypatch):
    monkeypatch.setattr(comicarr, "DDL_QUEUED", set())
    operations = []
    persisted = {}
    queued = MagicMock()

    def fake_upsert(table, values, controls):
        operations.append("persist")
        persisted.update(values)
        assert table == "ddl_info"
        assert controls == {"ID": "ddl-1"}

    queued.put.side_effect = lambda item: operations.append(("enqueue", item))
    monkeypatch.setattr(service.db, "upsert", fake_upsert)
    monkeypatch.setattr(comicarr, "DDL_QUEUE", queued)

    result = service.queue_ddl_download(_complete_ddl_payload())

    assert result["success"] is True, result
    assert operations[0] == "persist"
    command = operations[1][1]
    assert command == _complete_ddl_payload()
    assert persisted["status"] == "Queued"
    assert persisted["oneoff"] == 0
    assert persisted["resume"] is None
    assert persisted["comicinfo"]
    assert persisted["packinfo"] is None
    assert DDLCommand.from_mapping({"ID": "ddl-1", **persisted}).to_queue_item() == _complete_ddl_payload()


def test_queue_ddl_keeps_persisted_row_queued_when_handoff_fails(monkeypatch):
    statuses = []
    monkeypatch.setattr(service.db, "upsert", MagicMock())
    monkeypatch.setattr(
        service.dl_queries,
        "update_ddl_status",
        lambda item_id, status: statuses.append((item_id, status)),
    )
    ddl_queue = MagicMock()
    ddl_queue.put.side_effect = RuntimeError("queue unavailable")
    monkeypatch.setattr(comicarr, "DDL_QUEUE", ddl_queue)

    result = service.queue_ddl_download(_complete_ddl_payload())

    assert result["success"] is False
    assert result["handoff_error"] is True
    assert statuses == []


def test_real_sqlite_mediafire_path_updates_ddl_row(sqlite_ddl_db, tmp_path):
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    with sqlite_ddl_db.begin() as conn:
        conn.execute(insert(ddl_info).values(ID="ddl-real", status="Downloading"))

    downloader = mediafire.MediaFire.__new__(mediafire.MediaFire)
    downloader.dl_location = str(download_dir)
    downloader.session = MagicMock(
        get=MagicMock(return_value=SimpleNamespace(iter_content=lambda chunk_size: iter([b"comic"])))
    )

    downloader.mediafire_dl(
        "https://downloads.invalid/issue.cbz",
        "ddl-real",
        {"filename": "issue.cbz", "filesize": 5},
        "issue-1",
    )

    with sqlite_ddl_db.connect() as conn:
        row = conn.execute(select(ddl_info).where(ddl_info.c.ID == "ddl-real")).mappings().one()
    assert row["tmp_filename"] == "issue.cbz"


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        ({"id": "ddl-1", "link": "https://example.invalid", "site": "DDL(GetComics)"}, "Missing"),
        (_complete_ddl_payload(site="DDL(Unknown)"), "Unsupported"),
        (_complete_ddl_payload(link_type="GC-Unknown"), "Unsupported"),
    ],
)
def test_queue_ddl_rejects_poison_jobs_before_mutation(monkeypatch, payload, expected_error):
    upsert = MagicMock()
    ddl_queue = MagicMock()
    monkeypatch.setattr(service.db, "upsert", upsert)
    monkeypatch.setattr(comicarr, "DDL_QUEUE", ddl_queue)

    result = service.queue_ddl_download(payload)

    assert result["success"] is False
    assert expected_error.lower() in result["error"].lower()
    upsert.assert_not_called()
    ddl_queue.put.assert_not_called()


def test_queue_ddl_router_returns_400_for_non_runnable_legacy_payload(monkeypatch):
    monkeypatch.setattr(service.db, "upsert", MagicMock())
    monkeypatch.setattr(comicarr, "DDL_QUEUE", MagicMock())

    response = router.queue_ddl_download({"id": "ddl-1", "link": "https://example.invalid", "site": "DDL(GetComics)"})

    assert response.status_code == 400


def test_requeue_reconstructs_and_enqueues_persisted_command(monkeypatch):
    monkeypatch.setattr(comicarr, "DDL_QUEUED", set())
    row = _complete_ddl_payload()
    row.update(
        {
            "ID": row.pop("id"),
            "oneoff": 0,
            "remote_filesize": str(row["remote_filesize"]),
            "comicinfo": '[{"pack": false, "IssueID": "issue-1"}]',
            "packinfo": None,
            "status": "Failed",
        }
    )
    ddl_queue = MagicMock()
    statuses = []
    monkeypatch.setattr(service.dl_queries, "get_ddl_item", lambda item_id: row)
    monkeypatch.setattr(service.dl_queries, "update_ddl_status", lambda item_id, status: statuses.append(status))
    monkeypatch.setattr(service.dl_queries, "claim_failed_ddl_retry", lambda item_id: statuses.append("Queued") or True)
    monkeypatch.setattr(comicarr, "DDL_QUEUE", ddl_queue)

    result = service.requeue_ddl_item("ddl-1")

    assert result["success"] is True
    ddl_queue.put.assert_called_once_with(_complete_ddl_payload())
    assert statuses == ["Queued"]


def test_requeue_rejects_active_downloading_status(monkeypatch):
    row = _complete_ddl_payload()
    row.update(
        {
            "ID": row.pop("id"),
            "oneoff": 0,
            "remote_filesize": str(row["remote_filesize"]),
            "comicinfo": '[{"pack": false, "IssueID": "issue-1"}]',
            "packinfo": None,
            "status": "Downloading",
        }
    )
    ddl_queue = MagicMock()
    statuses = []
    monkeypatch.setattr(service.dl_queries, "get_ddl_item", lambda item_id: row)
    monkeypatch.setattr(service.dl_queries, "update_ddl_status", lambda item_id, status: statuses.append(status))
    monkeypatch.setattr(service.dl_queries, "claim_failed_ddl_retry", lambda item_id: statuses.append("Queued") or True)
    monkeypatch.setattr(comicarr, "DDL_QUEUE", ddl_queue)

    result = service.requeue_ddl_item("ddl-1")

    assert result["success"] is False
    assert result.get("validation_error") is True
    assert "Downloading" in result["error"]
    assert statuses == []
    ddl_queue.put.assert_not_called()


def test_recover_skips_ids_already_owned_by_this_process(sqlite_ddl_db, monkeypatch):
    command = _complete_ddl_payload()
    _persist_queued_command(command)
    monkeypatch.setattr(comicarr, "DDL_QUEUED", {"ddl-1"})
    recovered_queue = queue.Queue()

    result = service.recover_queued_ddl_commands(recovered_queue)

    assert result["enqueued_ids"] == []
    assert recovered_queue.empty()


def test_requeue_does_not_mark_incomplete_persisted_item_queued(monkeypatch):
    statuses = []
    ddl_queue = MagicMock()
    monkeypatch.setattr(
        service.dl_queries,
        "get_ddl_item",
        lambda item_id: {"ID": item_id, "link": "https://example.invalid", "site": "DDL(GetComics)"},
    )
    monkeypatch.setattr(service.dl_queries, "update_ddl_status", lambda item_id, status: statuses.append(status))
    monkeypatch.setattr(comicarr, "DDL_QUEUE", ddl_queue)

    result = service.requeue_ddl_item("ddl-bad")

    assert result["success"] is False
    assert "missing" in result["error"].lower()
    assert statuses == []
    ddl_queue.put.assert_not_called()


def test_requeue_keeps_durable_queued_status_when_handoff_fails(monkeypatch):
    monkeypatch.setattr(comicarr, "DDL_QUEUED", set())
    row = _complete_ddl_payload()
    row.update(
        {
            "ID": row.pop("id"),
            "oneoff": 0,
            "comicinfo": '[{"pack": false, "IssueID": "issue-1"}]',
            "packinfo": None,
            "status": "Failed",
        }
    )
    statuses = []
    ddl_queue = MagicMock()
    ddl_queue.put.side_effect = RuntimeError("queue unavailable")
    monkeypatch.setattr(service.dl_queries, "get_ddl_item", lambda item_id: row)
    monkeypatch.setattr(service.dl_queries, "update_ddl_status", lambda item_id, status: statuses.append(status))
    monkeypatch.setattr(service.dl_queries, "claim_failed_ddl_retry", lambda item_id: statuses.append("Queued") or True)
    monkeypatch.setattr(comicarr, "DDL_QUEUE", ddl_queue)

    result = service.requeue_ddl_item("ddl-1")

    assert result["success"] is False
    assert result["handoff_error"] is True
    assert statuses == ["Queued"]


def test_requeue_returns_structured_operational_error(monkeypatch):
    monkeypatch.setattr(
        service.dl_queries,
        "get_ddl_item",
        MagicMock(side_effect=RuntimeError("database unavailable")),
    )

    result = service.requeue_ddl_item("ddl-1")

    assert result["success"] is False
    assert result["operational_error"] is True
    assert result.get("not_found") is not True


@pytest.mark.parametrize(
    ("result", "expected_status"),
    [
        ({"success": False, "error": "missing", "not_found": True}, 404),
        ({"success": False, "error": "invalid", "validation_error": True}, 400),
        ({"success": False, "error": "queue unavailable", "handoff_error": True}, 503),
        ({"success": False, "error": "database unavailable", "operational_error": True}, 500),
    ],
)
def test_requeue_router_maps_structured_failures(monkeypatch, result, expected_status):
    monkeypatch.setattr(service, "requeue_ddl_item", lambda item_id: result)

    response = router.requeue_ddl_item("ddl-1")

    assert response.status_code == expected_status


def _persist_queued_command(command):
    service.db.upsert("ddl_info", DDLCommand.from_mapping(command).to_persisted_values(), {"ID": command["id"]})


def test_startup_sweep_recovers_persisted_and_prejournal_crash(sqlite_ddl_db, monkeypatch):
    command = _complete_ddl_payload()
    _persist_queued_command(command)
    monkeypatch.setattr(comicarr, "DDL_QUEUED", set())

    first_process_queue = queue.Queue()
    first_result = service.recover_queued_ddl_commands(first_process_queue)
    dequeued_before_journal = first_process_queue.get_nowait()

    assert first_result == {"enqueued_ids": ["ddl-1"], "failed_ids": [], "handoff_failed_ids": []}
    assert dequeued_before_journal == command

    # Simulate process restart: in-memory ownership is lost, durable Queued remains.
    monkeypatch.setattr(comicarr, "DDL_QUEUED", set())
    restarted_process_queue = queue.Queue()
    second_result = service.recover_queued_ddl_commands(restarted_process_queue)

    assert second_result["enqueued_ids"] == ["ddl-1"]
    assert restarted_process_queue.get_nowait() == command


def test_startup_sweep_excludes_downloading_rows(sqlite_ddl_db, monkeypatch):
    monkeypatch.setattr(comicarr, "DDL_QUEUED", set())
    """Only Queued rows are recovered; Downloading belongs to journal recovery."""
    queued = _complete_ddl_payload(id="ddl-queued")
    downloading = _complete_ddl_payload(id="ddl-downloading")
    _persist_queued_command(queued)
    service.db.upsert(
        "ddl_info",
        DDLCommand.from_mapping(downloading).to_persisted_values(status="Downloading"),
        {"ID": "ddl-downloading"},
    )
    recovered_queue = queue.Queue()

    result = service.recover_queued_ddl_commands(recovered_queue)

    assert result["enqueued_ids"] == ["ddl-queued"]
    assert recovered_queue.get_nowait()["id"] == "ddl-queued"
    assert recovered_queue.empty()
    with sqlite_ddl_db.connect() as conn:
        status = conn.execute(select(ddl_info.c.status).where(ddl_info.c.ID == "ddl-downloading")).scalar_one()
    assert status == "Downloading"


def test_startup_sweep_marks_invalid_legacy_row_failed(sqlite_ddl_db, monkeypatch):
    monkeypatch.setattr(comicarr, "DDL_QUEUED", set())
    with sqlite_ddl_db.begin() as conn:
        conn.execute(
            insert(ddl_info).values(
                ID="ddl-invalid",
                status="Queued",
                link="https://downloads.invalid/issue.cbz",
                site="DDL(GetComics)",
            )
        )
    recovered_queue = queue.Queue()

    result = service.recover_queued_ddl_commands(recovered_queue)

    assert result == {"enqueued_ids": [], "failed_ids": ["ddl-invalid"], "handoff_failed_ids": []}
    assert recovered_queue.empty()
    with sqlite_ddl_db.connect() as conn:
        status = conn.execute(select(ddl_info.c.status).where(ddl_info.c.ID == "ddl-invalid")).scalar_one()
    assert status == "Failed"


def test_startup_sweep_queue_failure_keeps_row_recoverable(sqlite_ddl_db, monkeypatch):
    monkeypatch.setattr(comicarr, "DDL_QUEUED", set())
    command = _complete_ddl_payload()
    _persist_queued_command(command)
    unavailable_queue = MagicMock()
    unavailable_queue.put.side_effect = RuntimeError("queue unavailable")

    result = service.recover_queued_ddl_commands(unavailable_queue)

    assert result == {"enqueued_ids": [], "failed_ids": [], "handoff_failed_ids": ["ddl-1"]}
    with sqlite_ddl_db.connect() as conn:
        status = conn.execute(select(ddl_info.c.status).where(ddl_info.c.ID == "ddl-1")).scalar_one()
    assert status == "Queued"

    recovered_queue = queue.Queue()
    retry_result = service.recover_queued_ddl_commands(recovered_queue)
    assert retry_result["enqueued_ids"] == ["ddl-1"]


def test_ddl_startup_sweep_runs_before_worker_thread(monkeypatch):
    events = []
    work_queue = queue.Queue()
    monkeypatch.setattr(comicarr, "DDL_QUEUE", work_queue)
    monkeypatch.setattr(comicarr, "DDLPOOL", None)
    monkeypatch.setattr(
        comicarr.helpers,
        "recover_queued_ddl_commands",
        lambda ddl_queue: events.append("recovery"),
        raising=False,
    )
    monkeypatch.setattr(comicarr.helpers, "ddl_downloader", lambda ddl_queue: events.append("worker"))

    comicarr.queue_schedule("ddl_queue", "start")
    comicarr.DDLPOOL.join(timeout=2)

    assert events == ["recovery", "worker"]


def test_ddl_startup_sweep_is_skipped_when_worker_is_alive(monkeypatch):
    work_queue = queue.Queue()
    live_worker = MagicMock()
    live_worker.is_alive.return_value = True
    recover = MagicMock()
    worker = MagicMock()
    monkeypatch.setattr(comicarr, "DDL_QUEUE", work_queue)
    monkeypatch.setattr(comicarr, "DDLPOOL", live_worker)
    monkeypatch.setattr(comicarr.helpers, "recover_queued_ddl_commands", recover, raising=False)
    monkeypatch.setattr(comicarr.helpers, "ddl_downloader", worker)

    comicarr.queue_schedule("ddl_queue", "start")

    recover.assert_not_called()
    worker.assert_not_called()
    assert comicarr.DDLPOOL is live_worker


def test_recovery_preserves_complete_canonical_ddl_command():
    payload = _complete_ddl_payload()
    payload.update({"provider": "DDL", "ddl": True})

    kind, command = recovery._resume_item_from_row(
        {"downloader_type": "ddl", "issueid": "issue-1"},
        payload,
    )

    assert kind == "ddl"
    assert command == _complete_ddl_payload()


def _getcomics_link(site="Main Server", **overrides):
    link = {
        "series": "Saga",
        "year": "2026",
        "size": "10 MB",
        "issues": "1",
        "pack": False,
        "links": "https://downloads.invalid/issue.cbz",
        "site": site,
    }
    link.update(overrides)
    return link


def _getcomics_batch_downloader():
    downloader = getcomics.GC.__new__(getcomics.GC)
    downloader.issueid = "issue-1"
    downloader.comicid = "comic-1"
    downloader.oneoff = False
    return downloader


def test_getcomics_batch_validates_all_items_before_mutation(monkeypatch):
    queue_command = MagicMock()
    monkeypatch.setattr(service, "queue_ddl_download", queue_command)
    downloader = _getcomics_batch_downloader()

    result = downloader._queue_download_batch(
        "ddl-batch",
        "https://getcomics.invalid/saga",
        [_getcomics_link(), _getcomics_link(site="Unsupported Host")],
        "Saga (2026)",
        [{"pack": False, "IssueID": "issue-1"}],
        None,
    )

    assert result["success"] is False
    assert result["validation_error"] is True
    assert result["queued_ids"] == []
    assert result["failed_ids"] == ["ddl-batch-2"]
    queue_command.assert_not_called()


def test_getcomics_batch_reports_partial_handoff_without_total_failure(monkeypatch):
    queue_command = MagicMock(
        side_effect=[
            {"success": True},
            {"success": False, "error": "queue unavailable", "handoff_error": True},
        ]
    )
    monkeypatch.setattr(service, "queue_ddl_download", queue_command)
    downloader = _getcomics_batch_downloader()

    result = downloader._queue_download_batch(
        "ddl-batch",
        "https://getcomics.invalid/saga",
        [_getcomics_link(), _getcomics_link(site="Mega")],
        "Saga (2026)",
        [{"pack": False, "IssueID": "issue-1"}],
        None,
    )

    assert result == {
        "success": True,
        "partial": True,
        "site": "GC-Mega",
        "queued_ids": ["ddl-batch-1"],
        "failed_ids": ["ddl-batch-2"],
    }
    assert "https://" not in repr(result)


def test_getcomics_batch_none_comicinfo_returns_structured_validation(monkeypatch):
    """Missing comicinfo must not TypeError before DDLCommand validation."""
    queue_command = MagicMock()
    monkeypatch.setattr(service, "queue_ddl_download", queue_command)
    downloader = _getcomics_batch_downloader()
    downloader.issueid = None
    downloader.comicid = None

    result = downloader._queue_download_batch(
        "ddl-none-info",
        "https://getcomics.invalid/saga",
        [_getcomics_link()],
        "Saga (2026)",
        None,
        None,
    )

    assert result["success"] is False
    assert result.get("validation_error") is True
    assert "comicinfo" in result["error"].lower()
    queue_command.assert_not_called()


def test_worker_marks_poison_item_failed_and_continues_to_shutdown(monkeypatch):
    work = queue.Queue()
    work.put({"id": "ddl-bad", "link": "https://example.invalid", "site": "DDL(GetComics)"})
    work.put("exit")
    statuses = []
    monkeypatch.setattr(comicarr.DDL_LOCK, "locked", lambda: False)
    monkeypatch.setattr(comicarr, "DDL_QUEUED", {"ddl-bad"})
    monkeypatch.setattr(comicarr, "DDL_STUCK_NOTIFIED", {"ddl-bad"})
    monkeypatch.setattr(
        service.db,
        "upsert",
        lambda table, values, controls: statuses.append((table, values, controls)),
    )

    service.ddl_downloader(work)

    assert statuses[-1][1]["status"] == "Failed"
    assert "ddl-bad" not in comicarr.DDL_QUEUED
    assert "ddl-bad" not in comicarr.DDL_STUCK_NOTIFIED
    assert work.empty()


def _drive_ddl_worker(monkeypatch, ddzstat, *, on_parse=None, link_type_failure=None):
    """Run one DDL item through the worker loop, then shut down.

    Calls _ddl_downloader_loop directly rather than ddl_downloader: the public
    wrapper swallows any exception and discards DDL_QUEUED as poison recovery,
    which would mask whether the terminal branch released ownership itself.
    """

    class _FakeGC:
        def __init__(self, *args, **kwargs):
            pass

        def downloadit(self, **kwargs):
            return dict(ddzstat)

        def parse_downloadresults(self, *args, **kwargs):
            if on_parse is not None:
                on_parse()

    work = queue.Queue()
    work.put(_complete_ddl_payload())
    work.put("exit")

    monkeypatch.setattr(comicarr.DDL_LOCK, "locked", lambda: False)
    monkeypatch.setattr(comicarr, "DDL_QUEUED", {"ddl-1"})
    monkeypatch.setattr(comicarr, "DDL_STUCK_NOTIFIED", {"ddl-1"})
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(POST_PROCESSING=False), raising=False)

    statuses = []
    monkeypatch.setattr(
        service.db,
        "upsert",
        lambda table, values, controls: statuses.append((table, values, controls)),
    )
    monkeypatch.setattr(service, "reverse_the_pack_snatch", lambda *a, **k: None)
    monkeypatch.setattr(service, "ddl_cleanup", lambda *a, **k: None)
    monkeypatch.setattr(service.getcomics, "GC", _FakeGC)

    from comicarr.app.downloads import handoff

    def _fake_handoff(release_key, kind, side_effect, **kwargs):
        return side_effect()

    monkeypatch.setattr(handoff, "perform_handoff", _fake_handoff)

    # Seeded by default so the terminal branch's link_type_failure.pop finds a
    # key and the loop returns normally instead of unwinding into poison
    # recovery. Pass {} to exercise the first-attempt case.
    if link_type_failure is None:
        link_type_failure = {"ddl-1": ["GC-Main"]}
    service._ddl_downloader_loop(work, link_type_failure, {"value": None})
    return statuses


def test_worker_releases_queue_ownership_when_links_are_exhausted(monkeypatch):
    """A terminal DDL failure must not leave the id owned in-process (#784)."""
    statuses = _drive_ddl_worker(
        monkeypatch,
        {"success": False, "filename": None, "path": None, "links_exhausted": True},
    )

    assert statuses[-1][1]["status"] == "Failed"
    assert "ddl-1" not in comicarr.DDL_QUEUED
    assert "ddl-1" not in comicarr.DDL_STUCK_NOTIFIED


def test_worker_handles_links_exhausted_on_the_first_attempt(monkeypatch):
    """Links exhausted with no recorded link failure must not unwind the loop.

    link_type_failure only gains a key once a retry has recorded one, so a
    result that arrives already exhausted reaches the terminal branch with
    nothing to pop. An unguarded pop raised KeyError here, which unwound into
    ddl_downloader's catch-all and marked the item Failed as poison recovery,
    skipping reverse_the_pack_snatch and ddl_cleanup for that item.
    """
    statuses = _drive_ddl_worker(
        monkeypatch,
        {"success": False, "filename": None, "path": None, "links_exhausted": True},
        link_type_failure={},
    )

    assert statuses[-1][1]["status"] == "Failed"
    assert "ddl-1" not in comicarr.DDL_QUEUED
    assert "ddl-1" not in comicarr.DDL_STUCK_NOTIFIED


def test_worker_releases_queue_ownership_before_retrying_remaining_links(monkeypatch):
    """The retry re-queues the same id, so ownership must be released first (#784).

    getcomics._queue_download_batch reuses item_id when a result has a single
    link, so if DDL_QUEUED still held the id here _enqueue_ddl_queue_item would
    dedupe the retry away and the item would sit in Queued forever.
    """
    owned_during_retry = {}

    def _record():
        owned_during_retry["value"] = "ddl-1" in comicarr.DDL_QUEUED

    _drive_ddl_worker(
        monkeypatch,
        {"success": False, "filename": None, "path": None},
        on_parse=_record,
    )

    assert owned_during_retry["value"] is False


class _TrackingLock:
    def __init__(self):
        self._locked = False
        self.acquires = 0
        self.releases = 0

    def locked(self):
        return self._locked

    def acquire(self):
        assert not self._locked
        self._locked = True
        self.acquires += 1

    def release(self):
        assert self._locked, "attempted to release an unlocked DDL lock"
        self._locked = False
        self.releases += 1


class _Response:
    url = "https://downloads.invalid/Saga.zip"

    def __init__(self, chunks=(b"comic",), content_length="5"):
        self.headers = {"Content-length": content_length}
        self._chunks = chunks

    def iter_content(self, chunk_size):
        return iter(self._chunks)


def _downloader(monkeypatch, tmp_path, *, response=None):
    downloader = getcomics.GC.__new__(getcomics.GC)
    downloader.headers = {}
    downloader.session = MagicMock()
    downloader.session.get.return_value = response or _Response()
    downloader.cookie_receipt = MagicMock()
    lock = _TrackingLock()
    monkeypatch.setattr(comicarr, "DDL_LOCK", lock)
    monkeypatch.setattr(comicarr, "DDL_QUEUED", set())
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            DDL_LOCATION=str(tmp_path),
            ENFORCE_PERMS=False,
            CHMOD_FILE="0660",
            CHMOD_DIR="0777",
        ),
    )
    monkeypatch.setattr(getcomics.db, "upsert", lambda *args, **kwargs: None)
    return downloader, lock


@pytest.mark.parametrize("failure", ["cookie", "directory", "timeout", "download", "missing"])
def test_downloadit_releases_lock_once_on_early_failures(tmp_path, monkeypatch, failure):
    downloader, lock = _downloader(monkeypatch, tmp_path)

    if failure == "cookie":
        downloader.cookie_receipt.side_effect = RuntimeError("cookie failed")
    elif failure == "directory":
        missing = tmp_path / "missing"
        comicarr.CONFIG.DDL_LOCATION = str(missing)
        monkeypatch.setattr(comicarr.filechecker, "validateAndCreateDirectory", lambda *args: False)
    elif failure == "timeout":
        downloader.session.get.side_effect = requests.exceptions.Timeout("timed out")
    elif failure == "download":
        monkeypatch.setattr(getcomics, "write_chunks_atomically", MagicMock(side_effect=OSError("disk full")))
    elif failure == "missing":
        monkeypatch.setattr(getcomics, "write_chunks_atomically", lambda *args, **kwargs: None)

    result = downloader.downloadit(
        "ddl-1",
        "https://downloads.invalid/Saga.zip",
        "https://getcomics.invalid/saga",
        issueid="issue-1",
        remote_filesize=5,
        link_type="GC-Main",
    )

    assert result["success"] is False
    assert lock.locked() is False
    assert (lock.acquires, lock.releases) == (1, 1)


@pytest.mark.parametrize("extraction_succeeds", [False, True])
def test_downloadit_holds_lock_through_zip_publication(tmp_path, monkeypatch, extraction_succeeds):
    downloader, lock = _downloader(monkeypatch, tmp_path)

    def write_archive(destination, chunks):
        destination.write_bytes(b"zip")

    def extract_archive(source, destination):
        assert lock.locked(), "DDL lock must cover extraction and atomic publication"
        if not extraction_succeeds:
            raise OSError("invalid zip")
        destination.mkdir()
        return destination

    monkeypatch.setattr(getcomics, "write_chunks_atomically", write_archive)
    monkeypatch.setattr(getcomics, "extract_zip_atomically", extract_archive)

    result = downloader.downloadit(
        "ddl-1",
        "https://downloads.invalid/Saga.zip",
        "https://getcomics.invalid/saga",
        issueid="issue-1",
        remote_filesize=5,
        link_type="GC-Main",
    )

    assert result["success"] is extraction_succeeds
    assert lock.locked() is False
    assert (lock.acquires, lock.releases) == (1, 1)
