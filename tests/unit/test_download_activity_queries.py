#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event, insert, text
from sqlalchemy import inspect as sa_inspect

import comicarr
from comicarr.app.core import db, runtime
from comicarr.app.core.schema import upgrade_database
from comicarr.app.core.tables import ddl_info, metadata, snatched
from comicarr.app.downloads import queries, router, service


@pytest.fixture
def activity_db(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "data_dir", str(tmp_path))
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def test_queue_excludes_completed_rows_and_supports_search_sort_pagination(activity_db):
    with activity_db.begin() as conn:
        conn.execute(
            insert(ddl_info),
            [
                {
                    "ID": "queued-old",
                    "series": "Saga",
                    "status": "Queued",
                    "updated_date": "2026-07-09 09:00",
                },
                {
                    "ID": "queued-new",
                    "series": "Saga Deluxe",
                    "status": "Downloading",
                    "updated_date": "2026-07-10 09:00",
                },
                {
                    "ID": "failed",
                    "series": "Saga Failure",
                    "status": "Failed",
                    "updated_date": "2026-07-09 12:00",
                },
                {
                    "ID": "completed",
                    "series": "Saga Archive",
                    "status": "Completed",
                    "updated_date": "2026-07-10 10:00",
                },
                {
                    "ID": "done",
                    "series": "Finished Series",
                    "status": "Done",
                    "updated_date": "2026-07-10 11:00",
                },
                {
                    "ID": "unknown",
                    "series": "Unknown Series",
                    "status": None,
                    "updated_date": "2026-07-10 12:00",
                },
            ],
        )

    result = queries.get_ddl_queue(
        limit=1,
        offset=0,
        search="saga",
        sort="updated",
        order="desc",
    )

    assert result["total"] == 3
    assert result["has_more"] is True
    assert [row["ID"] for row in result["results"]] == ["queued-new"]
    assert queries.count_active_ddl_items() == 4
    assert "ddl_info_status_updated" in {index["name"] for index in sa_inspect(activity_db).get_indexes("ddl_info")}

    queued_only = queries.get_ddl_queue(limit=10, offset=0, status="queued")
    assert queued_only["total"] == 1
    assert queued_only["results"][0]["ID"] == "queued-old"

    preview = queries.get_active_ddl_preview()
    assert [row["ID"] for row in preview] == ["unknown", "queued-new", "failed", "queued-old"]


def test_history_supports_filtering_and_oldest_first_sort(activity_db):
    with activity_db.begin() as conn:
        conn.execute(
            insert(snatched),
            [
                {
                    "IssueID": "1",
                    "ComicName": "Batman",
                    "Issue_Number": "1",
                    "DateAdded": "2026-07-10 09:00:00",
                    "Status": "Snatched",
                    "Provider": "NZBGeek",
                },
                {
                    "IssueID": "2",
                    "ComicName": "Batman",
                    "Issue_Number": "2",
                    "DateAdded": "2026-07-09 09:00:00",
                    "Status": "Post-Processed",
                    "Provider": "NZBGeek",
                },
                {
                    "IssueID": "3",
                    "ComicName": "Superman",
                    "Issue_Number": "1",
                    "DateAdded": "2026-07-08 09:00:00",
                    "Status": "Snatched",
                    "Provider": "NZBGeek",
                },
            ],
        )

    result = queries.get_history(
        limit=10,
        offset=0,
        search="batman",
        sort="date",
        order="asc",
    )

    assert result["total"] == 2
    assert [row["IssueID"] for row in result["results"]] == ["2", "1"]

    processed = queries.get_history(limit=10, offset=0, status="post-processed")
    assert processed["total"] == 1
    assert processed["results"][0]["IssueID"] == "2"


def test_activity_routes_forward_query_controls(monkeypatch):
    history = MagicMock(return_value={"history": [], "pagination": {}})
    queue = MagicMock(return_value={"queue": [], "pagination": {}})
    monkeypatch.setattr(router.dl_service, "get_history", history)
    monkeypatch.setattr(router.dl_service, "get_ddl_queue", queue)

    router.get_history(
        limit=25,
        offset=50,
        q="flash",
        status="snatched",
        sort="date",
        order="asc",
    )
    router.get_ddl_queue(
        limit=25,
        offset=25,
        q="flash",
        status="queued",
        sort="updated",
        order="desc",
    )

    history.assert_called_once_with(
        limit=25,
        offset=50,
        search="flash",
        status="snatched",
        sort="date",
        order="asc",
    )
    queue.assert_called_once_with(
        limit=25,
        offset=25,
        search="flash",
        status="queued",
        sort="updated",
        order="desc",
    )


def test_activity_routes_preserve_unpaginated_compatibility(monkeypatch):
    history = MagicMock(return_value=[])
    queue = MagicMock(return_value=[])
    monkeypatch.setattr(router.dl_service, "get_history", history)
    monkeypatch.setattr(router.dl_service, "get_ddl_queue", queue)

    assert router.get_history(limit=None, offset=0, q=None, status=None, sort="date", order="desc") == []
    assert router.get_ddl_queue(limit=None, offset=0, q=None, status=None, sort="updated", order="desc") == []
    assert history.call_args.kwargs["limit"] is None
    assert queue.call_args.kwargs["limit"] is None


def test_unpaginated_service_preserves_filters_and_array_shape(monkeypatch):
    history = MagicMock(return_value=[{"IssueID": "1"}])
    queue = MagicMock(return_value=[{"ID": "queued"}])
    monkeypatch.setattr(service.dl_queries, "get_history", history)
    monkeypatch.setattr(service.dl_queries, "get_ddl_queue", queue)

    assert service.get_history(search="flash", status="snatched") == [{"IssueID": "1"}]
    assert service.get_ddl_queue(search="flash", status="failed") == [{"ID": "queued"}]
    history.assert_called_once_with(search="flash", status="snatched", sort=None, order="desc")
    queue.assert_called_once_with(search="flash", status="failed", sort=None, order="desc")


def test_legacy_ddl_schema_migration_adds_column_before_activity_index(tmp_path, monkeypatch):
    """A pre-activity database gets the indexed column before the index is built."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-activity.db'}")
    monkeypatch.setattr(comicarr.app.core.db, "_engine", engine)
    monkeypatch.setattr(runtime.current(), "data_dir", str(tmp_path))
    with engine.begin() as conn:
        metadata.create_all(conn)
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("DROP INDEX ddl_info_status_updated"))
        conn.execute(text("ALTER TABLE ddl_info DROP COLUMN updated_date"))

    statements = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture_sql)
    try:
        upgrade_database()
    finally:
        event.remove(engine, "before_cursor_execute", capture_sql)

    ddl_columns = {column["name"] for column in sa_inspect(engine).get_columns("ddl_info")}
    ddl_indexes = {index["name"] for index in sa_inspect(engine).get_indexes("ddl_info")}
    assert "updated_date" in ddl_columns
    assert "ddl_info_status_updated" in ddl_indexes

    column_add = next(
        index
        for index, statement in enumerate(statements)
        if "alter table ddl_info add column updated_date" in statement
    )
    index_create = next(
        index for index, statement in enumerate(statements) if "create index ddl_info_status_updated" in statement
    )
    assert column_add < index_create

    engine.dispose()
    monkeypatch.setattr(comicarr.app.core.db, "_engine", None)
