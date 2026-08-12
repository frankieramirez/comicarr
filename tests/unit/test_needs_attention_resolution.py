#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""#483 — needs-attention band resolution actions.

Seams under test (agreed):
  1. attention.read / journal.stamp_resolution
  2. ignore_issue intent helper
  3. search_issue scoped entry
  4. service actions: retry / search-again / ignore / import
  5. acquisition_repair evidence skips resolved statuses
  6. same-provider re-snatch: SNATCHED against failed wins
"""

import queue as queuelib
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

import comicarr
from comicarr import db
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.attention import read as read_attention
from comicarr.app.core.context import AppContext
from comicarr.app.downloads import journal
from comicarr.app.downloads import service as dl_service
from comicarr.app.search import service as search_service
from comicarr.app.series import queries as series_queries
from comicarr.app.system.acquisition_repair import RepairService
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, issues, metadata, pipeline_journal


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if not hasattr(comicarr, "LOG_LEVEL") or comicarr.LOG_LEVEL is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    monkeypatch.setattr(comicarr, "PROVIDER_BLOCKLIST", {}, raising=False)
    monkeypatch.setattr(comicarr, "SEARCH_QUEUE", queuelib.Queue(), raising=False)
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


def _seed_issue(*, issueid="1001", comicid="C1", status="Failed", intent=None):
    with get_engine().begin() as conn:
        conn.execute(
            comics.insert().values(
                ComicID=comicid,
                ComicName="Saga",
                ComicYear="2012",
                Status="Active",
            )
        )
        conn.execute(
            issues.insert().values(
                IssueID=issueid,
                ComicID=comicid,
                ComicName="Saga",
                Issue_Number="1",
                Status=status,
                AcquisitionIntent=intent,
            )
        )


def _seed_failed_row(
    *,
    key="1001|nzbgeek",
    issueid="1001",
    provider="nzbgeek",
    status=None,
    retry_count=None,
    payload=None,
):
    journal.record_transition(
        key,
        journal.SNATCHED,
        payload=payload
        or {
            "issueid": issueid,
            "provider": provider,
            "nzbname": "Saga.001",
            "comicname": "Saga",
            "issuenumber": "1",
        },
        issueid=issueid,
        provider=provider,
        nzbname="Saga.001",
    )
    journal.mark_failed(key, "download_failed_no_auto_handling", issueid=issueid, provider=provider)
    if status is not None or retry_count is not None:
        with get_engine().begin() as conn:
            values = {}
            if status is not None:
                values["status"] = status
            if retry_count is not None:
                values["retry_count"] = retry_count
            conn.execute(pipeline_journal.update().where(pipeline_journal.c.release_key == key).values(**values))
    return key


def _seed_manual_review_row(
    *,
    key="1001|ddl",
    issueid="1001",
    provider="ddl",
    nzb_name="Saga.001.cbz",
    nzb_folder=None,
):
    payload = {
        "issueid": issueid,
        "provider": provider,
        "nzb_name": nzb_name,
        "nzbname": nzb_name,
        "nzb_folder": nzb_folder or "/tmp/pp/Saga.001",
    }
    journal.record_transition(
        key,
        journal.SNATCHED,
        payload=payload,
        issueid=issueid,
        provider=provider,
        nzbname=nzb_name,
    )
    journal.record_transition(key, journal.DOWNLOADED, payload=payload)
    journal.mark_manual_review(key, "path_unsafe", payload=payload, issueid=issueid, provider=provider)
    return key


def _issue_row(issueid="1001"):
    return db.select_one(select(issues).where(issues.c.IssueID == issueid))


def _journal_row(key):
    return journal.read_one(key)


def _attention_release_keys():
    return {member.release_key for group in read_attention().groups for member in group.members}


# ---------------------------------------------------------------------------
# 1. Band query + stamp_resolution
# ---------------------------------------------------------------------------


def test_attention_read_settled_predicate():
    _seed_issue()
    on_band = _seed_failed_row(key="1001|a")
    off_retried = _seed_failed_row(key="1001|b", status=journal.STATUS_RETRIED)
    off_ignored = _seed_failed_row(key="1001|c", status=journal.STATUS_IGNORED)
    off_imported = _seed_failed_row(key="1001|d", status=journal.STATUS_IMPORTED)
    open_key = journal.release_key("1001", "open")
    journal.record_transition(open_key, journal.SNATCHED, issueid="1001", provider="open")

    keys = _attention_release_keys()
    assert on_band in keys
    assert off_retried not in keys
    assert off_ignored not in keys
    assert off_imported not in keys
    assert open_key not in keys


def test_stamp_resolution_retried_increments_retry_count_without_stage_change():
    _seed_issue()
    key = _seed_failed_row()
    before = _journal_row(key)
    assert before["stage"] == journal.FAILED
    assert before.get("retry_count") in (None, 0)

    assert journal.stamp_resolution(key, journal.STATUS_RETRIED, increment_retry=True) is True

    after = _journal_row(key)
    assert after["stage"] == journal.FAILED
    assert after["stage_rank"] == before["stage_rank"]
    assert after["status"] == journal.STATUS_RETRIED
    assert after["retry_count"] == 1
    assert key not in _attention_release_keys()


def test_stamp_resolution_rejects_open_stage():
    key = journal.release_key("9", "p")
    journal.record_transition(key, journal.SNATCHED, issueid="9", provider="p")
    assert journal.stamp_resolution(key, journal.STATUS_IGNORED) is False
    assert _journal_row(key)["stage"] == journal.SNATCHED
    assert _journal_row(key).get("status") is None


# ---------------------------------------------------------------------------
# 6. Same-provider re-snatch (SNATCHED against failed wins)
# ---------------------------------------------------------------------------


def test_snatched_against_failed_resets_and_wins():
    """NZB/torrent snatch path writes SNATCHED, not RESERVED — must not silent-no-op."""
    key = journal.release_key("500", "nzbgeek")
    journal.record_transition(key, journal.SNATCHED, issueid="500", provider="nzbgeek")
    journal.mark_failed(key, "gone")
    journal.stamp_resolution(key, journal.STATUS_RETRIED, increment_retry=True)

    won = journal.record_transition(
        key,
        journal.SNATCHED,
        payload={"issueid": "500", "provider": "nzbgeek", "nzbname": "retry.cbz"},
        issueid="500",
        provider="nzbgeek",
        nzbname="retry.cbz",
    )

    assert won is True
    row = _journal_row(key)
    assert row["stage"] == journal.SNATCHED
    assert row["fail_reason"] is None
    assert row.get("status") is None  # reset clears resolution stamp for new attempt


# ---------------------------------------------------------------------------
# 2. ignore_issue
# ---------------------------------------------------------------------------


def test_ignore_issue_sets_ignored_intent_and_status():
    _seed_issue(status="Failed")
    series_queries.ignore_issue("1001", "operator")
    row = _issue_row()
    assert row["AcquisitionIntent"] == "ignored"
    assert row["Status"] == "Ignored"


def test_ignore_issue_requires_audit_identity():
    _seed_issue()
    with pytest.raises(ValueError, match="audit identity"):
        series_queries.ignore_issue("1001", "")


# ---------------------------------------------------------------------------
# 3. search_issue
# ---------------------------------------------------------------------------


def test_search_issue_blocked_when_no_viable_route(monkeypatch):
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *a, **k: {"viable_route": False, "routes": {}},
    )
    result = search_service.search_issue(ctx, "1001")
    assert result["success"] is False
    assert result["status"] == "blocked"


def test_search_issue_enqueues_when_route_ready(monkeypatch):
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *a, **k: {
            "viable_route": True,
            "routes": {"nzb": {"ready": True, "viable": True}},
        },
    )
    fake_cmd = SimpleNamespace(run_id="run-1", issueid="1001")
    with patch("comicarr.app.search.commands.enqueue_search_command", return_value=fake_cmd) as enq:
        result = search_service.search_issue(ctx, "1001", trigger="band_retry")
    assert result["success"] is True
    assert result["run_id"] == "run-1"
    enq.assert_called_once()
    assert enq.call_args.kwargs["trigger"] == "band_retry"


# ---------------------------------------------------------------------------
# 4. Service actions
# ---------------------------------------------------------------------------


def test_retry_failed_wants_stamps_and_searches(monkeypatch):
    _seed_issue(status="Failed")
    key = _seed_failed_row()
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *a, **k: {"viable_route": True, "routes": {"nzb": {"ready": True}}},
    )
    with patch(
        "comicarr.app.search.commands.enqueue_search_command",
        return_value=SimpleNamespace(run_id="r1", issueid="1001"),
    ):
        result = dl_service.resolve_needs_attention(ctx, key, "retry", audit_identity="op")

    assert result["success"] is True
    assert _issue_row()["Status"] == "Wanted"
    assert _issue_row()["AcquisitionIntent"] == "wanted"
    row = _journal_row(key)
    assert row["status"] == journal.STATUS_RETRIED
    assert row["retry_count"] == 1
    assert row["stage"] == journal.FAILED
    assert key not in _attention_release_keys()


def test_retry_blocked_does_not_stamp(monkeypatch):
    _seed_issue(status="Failed")
    key = _seed_failed_row()
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *a, **k: {"viable_route": False, "routes": {}},
    )
    result = dl_service.resolve_needs_attention(ctx, key, "retry", audit_identity="op")
    assert result["success"] is False
    assert result["status"] == "blocked"
    assert _journal_row(key).get("status") not in journal.RESOLVED_STATUSES
    assert key in _attention_release_keys()


def test_stop_wanting_failed_stamps_and_sets_intent():
    _seed_issue(status="Failed")
    key = _seed_failed_row()
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    result = dl_service.resolve_needs_attention(ctx, key, "stop_wanting", audit_identity="op")
    assert result["success"] is True
    assert result["action"] == "stop_wanting"
    assert _issue_row()["AcquisitionIntent"] == "ignored"
    assert _issue_row()["Status"] == "Ignored"
    # The durable stamp keeps its old spelling — renaming a persisted status
    # would re-admit every row already stamped.
    assert _journal_row(key)["status"] == journal.STATUS_IGNORED
    assert _journal_row(key)["stage"] == journal.FAILED


def test_retired_ignore_action_id_is_rejected():
    _seed_issue(status="Failed")
    key = _seed_failed_row()
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    result = dl_service.resolve_needs_attention(ctx, key, "ignore", audit_identity="op")
    assert result["success"] is False
    assert result["status_code"] == 400
    assert key in _attention_release_keys()


def test_search_again_manual_review(monkeypatch):
    _seed_issue(status="Snatched")
    key = _seed_manual_review_row()
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *a, **k: {"viable_route": True, "routes": {"nzb": {"ready": True}}},
    )
    with patch(
        "comicarr.app.search.commands.enqueue_search_command",
        return_value=SimpleNamespace(run_id="r2", issueid="1001"),
    ):
        result = dl_service.resolve_needs_attention(ctx, key, "search_again", audit_identity="op")
    assert result["success"] is True
    assert _issue_row()["Status"] == "Wanted"
    assert _journal_row(key)["status"] == journal.STATUS_RETRIED
    assert _journal_row(key)["stage"] == journal.MANUAL_REVIEW


def test_import_stamps_only_on_success(tmp_path, monkeypatch):
    _seed_issue()
    root = tmp_path / "pp"
    root.mkdir()
    folder = root / "job"
    folder.mkdir()
    key = _seed_manual_review_row(nzb_folder=str(folder), nzb_name="Saga.001.cbz")
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
            MANUAL_PP_FOLDER=str(root),
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "PP_QUEUE", queuelib.Queue(), raising=False)
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    result = dl_service.resolve_needs_attention(ctx, key, "import", audit_identity="op")
    assert result["success"] is True
    assert _journal_row(key)["status"] == journal.STATUS_IMPORTED
    assert _journal_row(key)["stage"] == journal.MANUAL_REVIEW
    assert not comicarr.PP_QUEUE.empty()
    queued = comicarr.PP_QUEUE.get_nowait()
    assert "journal_release_key" not in queued


def test_import_validation_failure_keeps_band(tmp_path, monkeypatch):
    _seed_issue()
    # folder outside any configured root / missing
    key = _seed_manual_review_row(nzb_folder=str(tmp_path / "evil" / "path"), nzb_name="Saga.001.cbz")
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            MANUAL_PP_FOLDER=str(tmp_path / "pp"),
            DDL_LOCATION=str(tmp_path / "ddl"),
            CACHE_DIR=str(tmp_path / "cache"),
            DESTINATION_DIR=str(tmp_path / "library"),
        ),
        raising=False,
    )
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    result = dl_service.resolve_needs_attention(ctx, key, "import", audit_identity="op")
    assert result["success"] is False
    assert "error" in result
    assert _journal_row(key).get("status") != journal.STATUS_IMPORTED
    assert key in _attention_release_keys()


def test_retry_not_allowed_on_manual_review():
    _seed_issue()
    key = _seed_manual_review_row()
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    result = dl_service.resolve_needs_attention(ctx, key, "retry", audit_identity="op")
    assert result["success"] is False


def test_import_not_allowed_on_failed():
    _seed_issue()
    key = _seed_failed_row()
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    result = dl_service.resolve_needs_attention(ctx, key, "import", audit_identity="op")
    assert result["success"] is False


def test_already_resolved_returns_409_without_side_effects(monkeypatch):
    _seed_issue(status="Failed")
    key = _seed_failed_row(status=journal.STATUS_RETRIED, retry_count=1)
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    enqueued = []
    monkeypatch.setattr(
        "comicarr.app.search.commands.enqueue_search_command",
        lambda *a, **k: enqueued.append(1) or SimpleNamespace(run_id="x", issueid="1001"),
    )
    result = dl_service.resolve_needs_attention(ctx, key, "retry", audit_identity="op")
    assert result["success"] is False
    assert result.get("status_code") == 409
    assert enqueued == []
    assert _issue_row()["Status"] == "Failed"
    assert _journal_row(key)["status"] == journal.STATUS_RETRIED


# ---------------------------------------------------------------------------
# 7. Bulk fan-out (#525)
# ---------------------------------------------------------------------------


def test_batch_stop_wanting_clears_every_member():
    _seed_issue(issueid="1001", comicid="C1", status="Failed")
    _seed_issue(issueid="1002", comicid="C2", status="Failed")
    keys = [
        _seed_failed_row(key="1001|a", issueid="1001"),
        _seed_failed_row(key="1002|b", issueid="1002"),
    ]
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    result = dl_service.resolve_needs_attention_batch(ctx, "stop_wanting", keys, audit_identity="op")

    assert result["success"] is True
    assert result["partial"] is False
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["capped"] is False
    assert {r["release_key"] for r in result["results"]} == set(keys)
    assert not _attention_release_keys() & set(keys)


def test_batch_is_best_effort_and_reports_partials():
    """One bad member must not cost its siblings their resolution."""
    _seed_issue(issueid="1001", comicid="C1", status="Failed")
    good = _seed_failed_row(key="1001|a", issueid="1001")
    # No issueid on the row or in its payload — stop_wanting cannot resolve it.
    orphan = journal.release_key("orphan", "p")
    journal.record_transition(orphan, journal.SNATCHED, payload={"provider": "p"}, provider="p")
    journal.mark_failed(orphan, "download_failed_no_auto_handling", provider="p")
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    result = dl_service.resolve_needs_attention_batch(ctx, "stop_wanting", [good, orphan], audit_identity="op")

    assert result["success"] is True
    assert result["partial"] is True
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    by_key = {r["release_key"]: r for r in result["results"]}
    assert by_key[good]["ok"] is True
    assert by_key[orphan]["ok"] is False
    assert by_key[orphan]["error"]
    # The failed member stays on the band for another try; the sibling leaves.
    on_band = _attention_release_keys()
    assert orphan in on_band
    assert good not in on_band


def test_batch_caps_at_25_newest_first():
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    keys = []
    for index in range(30):
        issueid = "20%02d" % index
        _seed_issue(issueid=issueid, comicid="C%d" % index, status="Failed")
        key = _seed_failed_row(key="%s|p" % issueid, issueid=issueid)
        # Oldest first, so the cap has something meaningful to order.
        with get_engine().begin() as conn:
            conn.execute(
                pipeline_journal.update()
                .where(pipeline_journal.c.release_key == key)
                .values(updated_date="2026-07-%02d 10:00:00" % (index + 1))
            )
        keys.append(key)

    result = dl_service.resolve_needs_attention_batch(ctx, "stop_wanting", keys, audit_identity="op")

    assert result["requested"] == 30
    assert result["processed"] == dl_service.BAND_BATCH_CAP == 25
    assert result["capped"] is True
    assert result["skipped_for_cap"] == 5
    # Newest processed first: the five oldest are what got left behind.
    still_on_band = _attention_release_keys()
    assert still_on_band == set(keys[:5])


def test_batch_keeps_unknown_keys_where_they_were_submitted():
    """A cap must not quietly eat the keys whose failure the operator needs.

    Unknown keys fail per-item and that failure is the useful output. Ranking
    them behind every dated row would let a capped batch drop them silently.
    """
    _seed_issue(issueid="1001", comicid="C1", status="Failed")
    _seed_issue(issueid="1002", comicid="C2", status="Failed")

    older = _seed_failed_row(key="1001|old", issueid="1001")
    newer = _seed_failed_row(key="1002|new", issueid="1002")
    with get_engine().begin() as conn:
        conn.execute(
            pipeline_journal.update()
            .where(pipeline_journal.c.release_key == older)
            .values(updated_date="2026-07-01 10:00:00")
        )
        conn.execute(
            pipeline_journal.update()
            .where(pipeline_journal.c.release_key == newer)
            .values(updated_date="2026-07-20 10:00:00")
        )

    # Unknown keys both before and between the dated rows.
    submitted = ["ghost-a", older, "ghost-b", newer]
    ordered = dl_service._batch_order(submitted)

    assert ordered[0] == "ghost-a"
    assert ordered[2] == "ghost-b"
    # The two dated slots are filled newest-first.
    assert [ordered[1], ordered[3]] == [newer, older]


def test_reason_to_stage_is_a_function():
    """No base ``fail_reason`` token may be written at two different stages.

    Band grouping keys on ``(comicid, base_reason)``, so while this holds, a
    *newly written* group is single-stage and gets group-level actions. It is
    not a safety net: unresolved band rows are never pruned, so a database
    written by an older Comicarr can still hold a mixed group today — which is
    why members carry their own ``available_actions`` regardless.

    Breaking this invariant is therefore a UX regression, not a correctness
    one: mixed groups would stop being rare, and every one of them costs the
    operator a row-by-row selection instead of one click.
    """
    import ast
    import collections
    import pathlib

    stage_of_writer = {
        "Failure": journal.FAILED,
        "ManualReview": journal.MANUAL_REVIEW,
        "mark_failed": journal.FAILED,
        "mark_manual_review": journal.MANUAL_REVIEW,
    }
    stages_by_token = collections.defaultdict(set)
    unresolved = set()
    direct_journal_writers = set()

    # Derived from the installed package, not the working directory, so the
    # scan cannot silently cover nothing when pytest runs from elsewhere.
    package_root = pathlib.Path(comicarr.__file__).resolve().parent
    repo_root = package_root.parent

    for path in package_root.rglob("*.py"):
        if "_vendor" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

        def enclosing_function(node):
            while node in parents:
                node = parents[node]
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return node.name
            return "<module>"

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name not in stage_of_writer:
                continue
            relative_path = path.relative_to(repo_root).as_posix()
            owner = enclosing_function(node)
            if name in {"Failure", "ManualReview"}:
                reason = next((kw.value for kw in node.keywords if kw.arg == "reason"), None)
                if reason is None:
                    continue
            else:
                direct_journal_writers.add((relative_path, owner, name))
                if len(node.args) >= 2:
                    reason = node.args[1]
                else:
                    reason = next(
                        (kw.value for kw in node.keywords if kw.arg in {"reason", "fail_reason"}),
                        None,
                    )
                if reason is None:
                    continue
            token = None
            if isinstance(reason, ast.Constant) and isinstance(reason.value, str):
                token = reason.value
            elif isinstance(reason, ast.JoinedStr) and reason.values:
                head = reason.values[0]
                token = head.value if isinstance(head, ast.Constant) else None
            elif isinstance(reason, ast.BinOp) and isinstance(reason.left, ast.Constant):
                token = reason.left.value
            if not isinstance(token, str):
                # Parameterized helper — record structural ownership plus the
                # exact source expression rather than source line numbers. Its
                # callers pin the concrete tokens, while the typed entry pins
                # the terminal stage; pinning the expression means a second
                # dynamic reason inside the same function cannot hide behind
                # an already-allowed (path, owner, name, stage) tuple.
                unresolved.add((relative_path, owner, name, stage_of_writer[name], ast.unparse(reason)))
                continue
            stages_by_token[token.split(":", 1)[0]].add(stage_of_writer[name])

    assert stages_by_token, "found no terminal record call sites — scan is broken"

    crossovers = {token: stages for token, stages in stages_by_token.items() if len(stages) > 1}
    assert not crossovers, "base tokens written at more than one stage: %s" % crossovers

    # Low-level journal writes are private to Attention.record. Every producer
    # must choose a typed Failure or ManualReview entry instead.
    assert direct_journal_writers == {
        ("comicarr/app/attention/_recording.py", "_record_on_connection", "mark_failed"),
        (
            "comicarr/app/attention/_recording.py",
            "_record_on_connection",
            "mark_manual_review",
        ),
    }

    # Dynamic reasons are allowed only at explicit typed pass-through seams,
    # and the reason expression itself is pinned (via ``ast.unparse``, which
    # is stable across source formatting): any *new* dynamic expression at an
    # allowed seam fails loudly instead of riding an existing tuple. Function
    # identity is stable across formatting and unrelated line edits.
    assert unresolved == {
        (
            "comicarr/app/attention/_recording.py",
            "_record_on_connection",
            "mark_failed",
            journal.FAILED,
            "entry.reason",
        ),
        (
            "comicarr/app/attention/_recording.py",
            "_record_on_connection",
            "mark_manual_review",
            journal.MANUAL_REVIEW,
            "entry.reason",
        ),
        (
            "comicarr/app/downloads/handoff.py",
            "record_acceptance",
            "ManualReview",
            journal.MANUAL_REVIEW,
            "reason",
        ),
        (
            "comicarr/app/downloads/recovery_classify.py",
            "apply_verdict",
            "Failure",
            journal.FAILED,
            "FAIL_REASON_GONE",
        ),
        (
            "comicarr/app/downloads/service.py",
            "_quarantine_postprocess_item",
            "ManualReview",
            journal.MANUAL_REVIEW,
            "reason",
        ),
        (
            "comicarr/failed.py",
            "terminalize_failed_download",
            "Failure",
            journal.FAILED,
            "fail_reason",
        ),
    }, "a dynamic typed terminal seam changed: %s" % sorted(unresolved)


def test_batch_import_derives_paths_from_each_row_payload(tmp_path, monkeypatch):
    """Batch import sends no per-key overrides — every row uses its own payload."""
    _seed_issue()
    root = tmp_path / "pp"
    root.mkdir()
    folder = root / "job"
    folder.mkdir()
    key = _seed_manual_review_row(nzb_folder=str(folder), nzb_name="Saga.001.cbz")
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
            MANUAL_PP_FOLDER=str(root),
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "PP_QUEUE", queuelib.Queue(), raising=False)
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    result = dl_service.resolve_needs_attention_batch(ctx, "import", [key], audit_identity="op")

    assert result["success"] is True
    assert result["succeeded"] == 1
    assert _journal_row(key)["status"] == journal.STATUS_IMPORTED
    queued = comicarr.PP_QUEUE.get_nowait()
    assert queued["nzb_name"] == "Saga.001.cbz"
    assert queued["nzb_folder"] == str(folder)


def test_batch_rejects_unknown_action_and_empty_keys():
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    unknown = dl_service.resolve_needs_attention_batch(ctx, "nuke", ["k"], audit_identity="op")
    assert unknown["success"] is False
    assert unknown["status_code"] == 400

    empty = dl_service.resolve_needs_attention_batch(ctx, "retry", [], audit_identity="op")
    assert empty["success"] is False
    assert empty["status_code"] == 400


def test_batch_rejects_action_the_member_stage_disallows():
    _seed_issue(status="Snatched")
    key = _seed_manual_review_row()
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    result = dl_service.resolve_needs_attention_batch(ctx, "retry", [key], audit_identity="op")

    assert result["success"] is False
    assert result["status_code"] == 409
    assert result["results"][0]["ok"] is False
    assert key in _attention_release_keys()


# ---------------------------------------------------------------------------
# 5. Repair evidence skips resolved statuses
# ---------------------------------------------------------------------------


def test_journal_evidence_skips_retried_failed_row():
    _seed_issue(status="Wanted", intent="wanted")
    key = _seed_failed_row(status=journal.STATUS_RETRIED)
    service = RepairService(get_engine())
    with get_engine().connect() as conn:
        evidence = service._journal_evidence(conn, "1001")
    assert evidence is None or evidence.get("reason") != "journal_failed"
    # If another journal row existed we might get different evidence; with only
    # the resolved failed row, evidence must not propose Failed.
    if evidence is not None:
        assert evidence.get("target_status") != "Failed"
    # Explicit: resolved row alone yields no journal evidence.
    with get_engine().begin() as conn:
        conn.execute(pipeline_journal.delete().where(pipeline_journal.c.release_key == key))
    # re-seed only resolved failed
    _seed_failed_row(key=key, status=journal.STATUS_RETRIED)
    with get_engine().connect() as conn:
        assert service._journal_evidence(conn, "1001") is None
