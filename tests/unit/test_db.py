#  Tests for comicarr.db — SQLAlchemy engine, shim, and helpers.

import os
import tempfile
import threading

import pytest
from sqlalchemy import inspect, text

import comicarr
from unittest.mock import patch

from sqlalchemy.exc import OperationalError

from comicarr.db import (
    DBConnection,
    _convert_positional_to_named,
    _get_database_url,
    _mask_password,
    ci_compare,
    get_dialect,
    get_engine,
    shutdown_engine,
    upsert,
)
from comicarr.tables import comics, issues, metadata


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own temporary SQLite database."""
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    # Clear any cached engine
    shutdown_engine()
    # Ensure no DATABASE_URL env var interferes
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Ensure CONFIG is absent so default SQLite path is used
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    # Ensure LOG_LEVEL is set (logger.fdebug compares it with >)
    if not hasattr(comicarr, "LOG_LEVEL") or comicarr.LOG_LEVEL is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    yield
    shutdown_engine()


# ---------------------------------------------------------------------------
# Engine lifecycle
# ---------------------------------------------------------------------------


class TestEngine:
    def test_engine_creates_sqlite_by_default(self):
        engine = get_engine()
        assert engine is not None
        assert engine.dialect.name == "sqlite"

    def test_get_dialect_returns_sqlite(self):
        get_engine()
        assert get_dialect() == "sqlite"

    def test_engine_is_singleton(self):
        e1 = get_engine()
        e2 = get_engine()
        assert e1 is e2

    def test_shutdown_and_recreate(self):
        e1 = get_engine()
        shutdown_engine()
        e2 = get_engine()
        assert e1 is not e2

    def test_metadata_create_all(self):
        engine = get_engine()
        metadata.create_all(engine)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "comics" in tables
        assert "issues" in tables
        assert "storyarcs" in tables
        assert "mylar_info" in tables

    def test_sqlite_pragmas_applied(self):
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode"))
            mode = result.scalar()
            assert mode == "wal"

            result = conn.execute(text("PRAGMA foreign_keys"))
            fk = result.scalar()
            assert fk == 1


# ---------------------------------------------------------------------------
# Query parameter conversion
# ---------------------------------------------------------------------------


class TestParamConversion:
    def test_simple_positional(self):
        query, params = _convert_positional_to_named(
            "SELECT * FROM comics WHERE ComicID = ?",
            ["12345"],
        )
        assert ":param_0" in query
        assert "?" not in query
        assert params["param_0"] == "12345"

    def test_multiple_params(self):
        query, params = _convert_positional_to_named(
            "SELECT * FROM issues WHERE ComicID = ? AND Status = ?",
            ["123", "Downloaded"],
        )
        assert ":param_0" in query
        assert ":param_1" in query
        assert params["param_0"] == "123"
        assert params["param_1"] == "Downloaded"

    def test_no_params(self):
        query, params = _convert_positional_to_named("SELECT * FROM comics")
        assert query == "SELECT * FROM comics"
        assert params == {}

    def test_question_mark_in_string_literal(self):
        query, _ = _convert_positional_to_named(
            "SELECT * FROM comics WHERE name = 'What?'"
        )
        # The ? inside quotes should NOT be converted
        assert "param_" not in query
        assert "'What?'" in query

    def test_escaped_quotes(self):
        query, params = _convert_positional_to_named(
            "SELECT * FROM comics WHERE name = 'it''s' AND id = ?",
            ["123"],
        )
        assert ":param_0" in query
        assert params["param_0"] == "123"

    def test_tuple_args(self):
        query, params = _convert_positional_to_named(
            "INSERT INTO comics (ComicID, ComicName) VALUES (?, ?)",
            ("id1", "Batman"),
        )
        assert params["param_0"] == "id1"
        assert params["param_1"] == "Batman"


# ---------------------------------------------------------------------------
# DBConnection shim
# ---------------------------------------------------------------------------


class TestDBConnectionShim:
    @pytest.fixture(autouse=True)
    def _setup_tables(self):
        engine = get_engine()
        metadata.create_all(engine)

    def test_action_insert(self):
        db = DBConnection()
        db.action(
            "INSERT INTO comics (ComicID, ComicName) VALUES (?, ?)",
            ["test1", "Test Comic"],
        )
        rows = db.select("SELECT ComicID, ComicName FROM comics WHERE ComicID = ?", ["test1"])
        assert len(rows) == 1
        assert rows[0]["ComicID"] == "test1"
        assert rows[0]["ComicName"] == "Test Comic"

    def test_select_returns_list_of_dicts(self):
        db = DBConnection()
        db.action("INSERT INTO comics (ComicID, ComicName) VALUES (?, ?)", ["d1", "Dict Test"])
        rows = db.select("SELECT * FROM comics WHERE ComicID = ?", ["d1"])
        assert isinstance(rows, list)
        assert isinstance(rows[0], dict)
        assert rows[0]["ComicID"] == "d1"

    def test_selectone_returns_dict(self):
        db = DBConnection()
        db.action("INSERT INTO comics (ComicID, ComicName) VALUES (?, ?)", ["s1", "Single"])
        row = db.selectone("SELECT * FROM comics WHERE ComicID = ?", ["s1"])
        assert isinstance(row, dict)
        assert row["ComicName"] == "Single"

    def test_selectone_empty_returns_list(self):
        db = DBConnection()
        row = db.selectone("SELECT * FROM comics WHERE ComicID = ?", ["nonexistent"])
        assert row == []

    def test_select_empty_returns_empty_list(self):
        db = DBConnection()
        rows = db.select("SELECT * FROM comics WHERE ComicID = ?", ["nonexistent"])
        assert rows == []

    def test_action_update(self):
        db = DBConnection()
        db.action("INSERT INTO comics (ComicID, ComicName) VALUES (?, ?)", ["u1", "Before"])
        db.action("UPDATE comics SET ComicName = ? WHERE ComicID = ?", ["After", "u1"])
        rows = db.select("SELECT ComicName FROM comics WHERE ComicID = ?", ["u1"])
        assert rows[0]["ComicName"] == "After"

    def test_action_delete(self):
        db = DBConnection()
        db.action("INSERT INTO comics (ComicID, ComicName) VALUES (?, ?)", ["del1", "Delete Me"])
        db.action("DELETE FROM comics WHERE ComicID = ?", ["del1"])
        rows = db.select("SELECT * FROM comics WHERE ComicID = ?", ["del1"])
        assert rows == []

    def test_action_no_args(self):
        db = DBConnection()
        db.action("INSERT INTO comics (ComicID, ComicName) VALUES ('na1', 'No Args')")
        rows = db.select("SELECT * FROM comics WHERE ComicID = 'na1'")
        assert len(rows) == 1

    def test_action_none_query_is_noop(self):
        db = DBConnection()
        db.action(None)  # Should not raise

    def test_fetch_none_query_returns_none(self):
        db = DBConnection()
        result = db.fetch(None)
        assert result is None

    def test_executemany(self):
        db = DBConnection()
        db.action(
            "INSERT INTO comics (ComicID, ComicName) VALUES (?, ?)",
            [("em1", "Batch 1"), ("em2", "Batch 2"), ("em3", "Batch 3")],
            executemany=True,
        )
        rows = db.select("SELECT ComicID FROM comics ORDER BY ComicID")
        assert len(rows) == 3
        assert rows[0]["ComicID"] == "em1"


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


class TestUpsert:
    @pytest.fixture(autouse=True)
    def _setup_tables(self):
        engine = get_engine()
        metadata.create_all(engine)

    def test_upsert_insert(self):
        upsert("comics", {"ComicName": "New Comic"}, {"ComicID": "up1"})
        db = DBConnection()
        rows = db.select("SELECT * FROM comics WHERE ComicID = ?", ["up1"])
        assert len(rows) == 1
        assert rows[0]["ComicName"] == "New Comic"

    def test_upsert_update(self):
        upsert("comics", {"ComicName": "Original"}, {"ComicID": "up2"})
        upsert("comics", {"ComicName": "Updated"}, {"ComicID": "up2"})
        db = DBConnection()
        rows = db.select("SELECT * FROM comics WHERE ComicID = ?", ["up2"])
        assert len(rows) == 1
        assert rows[0]["ComicName"] == "Updated"

    def test_upsert_composite_key(self):
        upsert(
            "weekly",
            {"COMIC": "Batman", "STATUS": "Wanted"},
            {"ComicID": "c1", "IssueID": "i1"},
        )
        upsert(
            "weekly",
            {"COMIC": "Batman", "STATUS": "Downloaded"},
            {"ComicID": "c1", "IssueID": "i1"},
        )
        db = DBConnection()
        rows = db.select("SELECT STATUS FROM weekly WHERE ComicID = ? AND IssueID = ?", ["c1", "i1"])
        assert len(rows) == 1
        assert rows[0]["STATUS"] == "Downloaded"

    def test_upsert_issues(self):
        upsert("issues", {"ComicName": "Test", "Status": "Wanted"}, {"IssueID": "iss1"})
        upsert("issues", {"ComicName": "Test", "Status": "Downloaded"}, {"IssueID": "iss1"})
        db = DBConnection()
        rows = db.select("SELECT Status FROM issues WHERE IssueID = ?", ["iss1"])
        assert len(rows) == 1
        assert rows[0]["Status"] == "Downloaded"


# ---------------------------------------------------------------------------
# ci_compare
# ---------------------------------------------------------------------------


class TestCiCompare:
    def test_sqlite_uses_plain_equality(self):
        engine = get_engine()
        metadata.create_all(engine)
        # ci_compare on SQLite should return a plain == expression
        expr = ci_compare(comics.c.ComicName, "Batman")
        # Just verify it produces a valid clause (not func.lower)
        assert "lower" not in str(expr).lower() or get_dialect() == "postgresql"


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_reads_and_writes(self):
        engine = get_engine()
        metadata.create_all(engine)
        errors = []

        def writer(n):
            try:
                upsert("comics", {"ComicName": f"Comic {n}"}, {"ComicID": f"thread_{n}"})
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                db = DBConnection()
                db.select("SELECT * FROM comics")
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(10):
            threads.append(threading.Thread(target=writer, args=(i,)))
            threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Thread errors: {errors}"


# ---------------------------------------------------------------------------
# _mask_password
# ---------------------------------------------------------------------------


class TestMaskPassword:
    def test_simple_password(self):
        url = "postgresql://user:secret@localhost/dbname"
        masked = _mask_password(url)
        assert "secret" not in masked
        assert "user" in masked
        assert "localhost" in masked

    def test_password_containing_at_sign(self):
        url = "postgresql://user:p%40ss%40word@localhost/dbname"
        masked = _mask_password(url)
        assert "p%40ss%40word" not in masked
        assert "localhost" in masked

    def test_sqlite_url_unchanged(self):
        url = "sqlite:///path/to/db.sqlite"
        masked = _mask_password(url)
        assert "path/to/db.sqlite" in masked

    def test_password_with_special_chars(self):
        url = "mysql://admin:p@ss:w0rd!#@dbhost:3306/mydb"
        masked = _mask_password(url)
        assert "p@ss:w0rd!#" not in masked
        assert "dbhost" in masked


# ---------------------------------------------------------------------------
# DATABASE_URL env var override
# ---------------------------------------------------------------------------


class TestDatabaseUrlOverride:
    def test_env_var_overrides_default(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/testdb")
        result = _get_database_url()
        assert result == "postgresql://u:p@host/testdb"

    def test_default_sqlite_when_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
        result = _get_database_url()
        assert result.startswith("sqlite:///")
        assert "comicarr.db" in result


# ---------------------------------------------------------------------------
# Retry exhaustion
# ---------------------------------------------------------------------------


class TestRetryExhaustion:
    def test_upsert_raises_after_retries(self):
        engine = get_engine()
        metadata.create_all(engine)

        with patch("comicarr.db.get_engine") as mock_engine:
            # Set up dialect so upsert() can determine the insert strategy
            mock_engine.return_value.dialect.name = "sqlite"
            ctx = mock_engine.return_value.begin.return_value.__enter__
            ctx.return_value.execute.side_effect = OperationalError(
                "database is locked", None, None
            )
            with pytest.raises(OperationalError):
                upsert("comics", {"ComicName": "Test"}, {"ComicID": "retry1"})
