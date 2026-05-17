#  Tests for comicarr.app.downloads.journal — the U1 forward-only journal facade.

import threading

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from unittest.mock import patch

import comicarr
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import metadata, pipeline_journal
from comicarr.app.downloads import journal


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own temporary SQLite database with the schema
    auto-created via SQLAlchemy metadata (same path dbcheck() uses)."""
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    if not hasattr(comicarr, "LOG_LEVEL") or comicarr.LOG_LEVEL is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    engine = get_engine()
    metadata.create_all(engine)
    yield
    shutdown_engine()


def _all_rows():
    with get_engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(select(pipeline_journal))]


def _row(key):
    with get_engine().connect() as conn:
        r = conn.execute(
            select(pipeline_journal).where(pipeline_journal.c.release_key == key)
        ).fetchone()
        return dict(r._mapping) if r else None


# ---------------------------------------------------------------------------
# Table auto-creation
# ---------------------------------------------------------------------------


def test_table_autocreated_on_fresh_db():
    from sqlalchemy import inspect

    tables = set(inspect(get_engine()).get_table_names())
    assert "pipeline_journal" in tables


def test_upsert_keys_registered():
    from comicarr.tables import UPSERT_KEYS

    assert UPSERT_KEYS.get("pipeline_journal") == ["release_key"]


# ---------------------------------------------------------------------------
# Happy path (AE1)
# ---------------------------------------------------------------------------


def test_snatched_then_downloaded_single_row_advances():
    key = journal.release_key("100", "nzb.su", nzbname="Batman_001.cbz")

    assert journal.record_transition(key, journal.SNATCHED) is True
    r1 = _row(key)
    assert r1["stage"] == "snatched"
    first_date = r1["updated_date"]

    assert journal.record_transition(key, journal.DOWNLOADED) is True
    rows = _all_rows()
    assert len(rows) == 1
    r2 = _row(key)
    assert r2["stage"] == "downloaded"
    assert r2["stage_rank"] == journal.STAGE_RANK["downloaded"]
    # updated_date advanced (or at minimum, not regressed)
    assert r2["updated_date"] >= first_date


def test_extra_fields_persisted():
    key = journal.release_key("7", "torznab", hash="abc")
    journal.record_transition(
        key,
        journal.SNATCHED,
        issueid="7",
        provider="torznab",
        downloader_type="torrent",
        hash="abc",
    )
    r = _row(key)
    assert r["issueid"] == "7"
    assert r["provider"] == "torznab"
    assert r["downloader_type"] == "torrent"
    assert r["hash"] == "abc"


# ---------------------------------------------------------------------------
# Monotonic guard (AE2/AE3)
# ---------------------------------------------------------------------------


def test_regression_against_post_processed_is_noop(capture_logs):
    key = journal.release_key("200", "prov")
    journal.record_transition(key, journal.SNATCHED)
    journal.record_transition(key, journal.DOWNLOADED)
    journal.record_transition(key, journal.POST_PROCESSING)
    journal.record_transition(key, journal.MOVED)
    journal.record_transition(key, journal.POST_PROCESSED)

    before = _row(key)
    won = journal.record_transition(key, journal.DOWNLOADED)
    after = _row(key)

    assert won is False
    assert after["stage"] == "post_processed"
    assert after["stage_rank"] == before["stage_rank"]
    assert "no-op" in capture_logs.text


def test_transition_against_failed_terminal_is_noop(capture_logs):
    key = journal.release_key("201", "prov")
    journal.record_transition(key, journal.SNATCHED)
    journal.mark_failed(key, "download gone")

    won = journal.record_transition(key, journal.DOWNLOADED)
    r = _row(key)

    assert won is False
    assert r["stage"] == "failed"
    assert r["fail_reason"] == "download gone"
    assert "no-op" in capture_logs.text


def test_new_stages_advance_and_downloaded_against_moved_is_noop():
    key = journal.release_key("300", "prov")
    journal.record_transition(key, journal.SNATCHED)
    journal.record_transition(key, journal.DOWNLOADED)
    assert journal.record_transition(key, journal.POST_PROCESSING) is True
    assert journal.record_transition(key, journal.MOVED) is True

    # downloaded against a moved row is a no-op
    assert journal.record_transition(key, journal.DOWNLOADED) is False
    assert _row(key)["stage"] == "moved"

    assert journal.record_transition(key, journal.POST_PROCESSED) is True
    assert _row(key)["stage"] == "post_processed"


def test_same_stage_rewrite_is_noop():
    key = journal.release_key("301", "prov")
    assert journal.record_transition(key, journal.SNATCHED) is True
    # rewriting the same stage is not an advance
    assert journal.record_transition(key, journal.SNATCHED) is False


# ---------------------------------------------------------------------------
# release_key derivation (AE3)
# ---------------------------------------------------------------------------


def test_standard_release_key_shape():
    assert journal.release_key("42", "nzb.su", nzbname="X.cbz") == "42|nzb.su|X.cbz"
    # falls back to hash when nzbname absent
    assert journal.release_key("42", "torznab", hash="deadbeef") == "42|torznab|deadbeef"


def test_oneoff_release_key_reproducible_across_two_builds():
    # Synthetic HIGHCOUNT issueid differs across restart, but a stable
    # discriminant (downloader id) reproduces the same key.
    k1 = journal.release_key(900001, "prov", nzbname="One.cbz", discriminant="dl-77")
    k2 = journal.release_key(900123, "prov", nzbname="One.cbz", discriminant="dl-77")
    assert k1 == k2
    assert k1.startswith("oneoff|")


def test_two_distinct_oneoffs_same_provider_empty_nzbname_differ():
    k1 = journal.release_key(900001, "prov", nzbname="", discriminant="dl-1")
    k2 = journal.release_key(900002, "prov", nzbname="", discriminant="dl-2")
    assert k1 != k2


def test_oneoff_without_discriminant_logs_collision_warning(capture_logs):
    journal.release_key(900001, "prov", nzbname="")
    assert "NO collision-resistant discriminant" in capture_logs.text


def test_derive_release_key_from_item_dict_disambiguates_oneoffs():
    item_a = {"issueid": 900001, "provider": "prov", "nzbname": "", "comicid": "A"}
    item_b = {"issueid": 900002, "provider": "prov", "nzbname": "", "comicid": "B"}
    assert journal.derive_release_key(item_a) != journal.derive_release_key(item_b)


# ---------------------------------------------------------------------------
# read_open
# ---------------------------------------------------------------------------


def test_read_open_excludes_terminal_rows():
    journal.record_transition(journal.release_key("1", "p"), journal.SNATCHED)
    journal.record_transition(journal.release_key("2", "p"), journal.DOWNLOADED)
    journal.record_transition(journal.release_key("3", "p"), journal.POST_PROCESSING)
    journal.record_transition(journal.release_key("4", "p"), journal.MOVED)
    journal.mark_done(journal.release_key("5", "p"))
    journal.mark_failed(journal.release_key("6", "p"), "gone")

    open_rows = journal.read_open()
    open_stages = sorted(r["stage"] for r in open_rows)
    assert open_stages == ["downloaded", "moved", "post_processing", "snatched"]
    keys = {r["release_key"] for r in open_rows}
    assert journal.release_key("5", "p") not in keys
    assert journal.release_key("6", "p") not in keys


# ---------------------------------------------------------------------------
# Atomic claim — concurrent downloaded -> post_processing
# ---------------------------------------------------------------------------


def test_concurrent_claim_exactly_one_winner():
    key = journal.release_key("claim1", "prov")
    journal.record_transition(key, journal.SNATCHED)
    journal.record_transition(key, journal.DOWNLOADED)

    results = []
    barrier = threading.Barrier(2)

    def claimer():
        barrier.wait()
        results.append(journal.record_transition(key, journal.POST_PROCESSING))

    t1 = threading.Thread(target=claimer)
    t2 = threading.Thread(target=claimer)
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert sorted(results) == [False, True]
    assert _row(key)["stage"] == "post_processing"
    assert len(_all_rows()) == 1


# ---------------------------------------------------------------------------
# Error path — retry exhaustion surfaces
# ---------------------------------------------------------------------------


def test_transition_raises_after_retry_cap_exhausted():
    key = journal.release_key("err1", "prov")

    with patch("comicarr.app.downloads.journal.db.get_engine") as mock_engine:
        ctx = mock_engine.return_value.begin.return_value.__enter__
        ctx.return_value.execute.side_effect = OperationalError(
            "database is locked", None, None
        )
        with pytest.raises(OperationalError):
            journal.record_transition(key, journal.SNATCHED)


def test_non_lock_db_error_raises_immediately():
    key = journal.release_key("err2", "prov")

    with patch("comicarr.app.downloads.journal.db.get_engine") as mock_engine:
        ctx = mock_engine.return_value.begin.return_value.__enter__
        ctx.return_value.execute.side_effect = OperationalError(
            "no such table", None, None
        )
        with pytest.raises(OperationalError):
            journal.record_transition(key, journal.SNATCHED)


# ---------------------------------------------------------------------------
# Caller-supplied conn participates in the caller's transaction
# ---------------------------------------------------------------------------


def test_caller_conn_rolls_back_with_caller_txn():
    key = journal.release_key("txn1", "prov")
    try:
        with get_engine().begin() as conn:
            won = journal.record_transition(key, journal.SNATCHED, conn=conn)
            assert won is True
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass
    # The journal write must have rolled back with the caller's txn.
    assert _row(key) is None


def test_caller_conn_commits_with_caller_txn():
    key = journal.release_key("txn2", "prov")
    with get_engine().begin() as conn:
        journal.record_transition(key, journal.SNATCHED, conn=conn)
    assert _row(key)["stage"] == "snatched"


def test_no_conn_is_its_own_transaction():
    key = journal.release_key("txn3", "prov")
    journal.record_transition(key, journal.SNATCHED)
    # Committed independently and immediately visible.
    assert _row(key)["stage"] == "snatched"


# ---------------------------------------------------------------------------
# payload_json round-trips
# ---------------------------------------------------------------------------


def test_payload_round_trips_torrent_item():
    key = journal.release_key("pl1", "torznab", hash="h1")
    payload = {"hash": "h1", "issueid": "555", "comicid": "999"}
    journal.record_transition(key, journal.SNATCHED, payload=payload)
    r = _row(key)
    assert journal.load_payload(r["payload_json"]) == payload


def test_payload_round_trips_nzb_pp_dict():
    key = journal.release_key("pl2", "sab")
    payload = {
        "nzb_name": "Saga_012.cbz",
        "nzb_folder": "/dl/Saga_012",
        "issueid": "888",
        "comicid": "777",
        "apicall": True,
    }
    journal.record_transition(key, journal.DOWNLOADED, payload=payload)
    r = _row(key)
    assert journal.load_payload(r["payload_json"]) == payload


def test_load_payload_handles_absent_and_corrupt():
    assert journal.load_payload(None) is None
    assert journal.load_payload("") is None
    assert journal.load_payload("{not valid json") is None


# ---------------------------------------------------------------------------
# Terminal predicate
# ---------------------------------------------------------------------------


def test_is_terminal_predicate():
    assert journal.is_terminal(journal.POST_PROCESSED) is True
    assert journal.is_terminal(journal.FAILED) is True
    assert journal.is_terminal(journal.SNATCHED) is False
    assert journal.is_terminal(journal.MOVED) is False
