#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Contract tests for the application-owned Alembic migration runner."""

import pytest
from sqlalchemy import Text, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

import comicarr
from comicarr.app.core.schema import (
    DatabaseState,
    MigrationStateError,
    autogenerate_include_object,
    classify_database,
    current_revision,
    upgrade_database,
)
from comicarr.tables import comics, metadata


def test_classifier_identifies_a_fresh_database(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "fresh.db"))

    assert classify_database(engine) is DatabaseState.FRESH


def test_autogenerate_only_equates_full_same_order_unique_indexes(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "unique-index-equivalence.db"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE comics (ComicID TEXT)"))
        conn.execute(text("CREATE UNIQUE INDEX uq_comics_comicid ON comics (ComicID) WHERE ComicID IS NOT NULL"))
        conn.execute(text("CREATE TABLE snatched (IssueID TEXT, Status TEXT, Provider TEXT)"))
        conn.execute(text("CREATE UNIQUE INDEX uq_snatched_reversed ON snatched (Provider, Status, IssueID)"))

    comic_id_unique = next(constraint for constraint in comics.constraints if isinstance(constraint, UniqueConstraint))
    snatched_unique = next(
        constraint for constraint in metadata.tables["snatched"].constraints if isinstance(constraint, UniqueConstraint)
    )
    with engine.connect() as connection:
        include_object = autogenerate_include_object(connection)
        assert include_object(comics, "comics", "table", False, None)
        assert include_object(comic_id_unique, comic_id_unique.name, "unique_constraint", False, None)
        assert include_object(snatched_unique, snatched_unique.name, "unique_constraint", False, None)

    with engine.begin() as conn:
        conn.execute(text("DROP INDEX uq_comics_comicid"))
        conn.execute(text("CREATE UNIQUE INDEX uq_comics_comicid ON comics (ComicID)"))

    with engine.connect() as connection:
        include_object = autogenerate_include_object(connection)
        assert not include_object(comic_id_unique, comic_id_unique.name, "unique_constraint", False, None)


def test_schema_diagnostic_errors_redact_connection_credentials():
    message = comicarr._redact_diagnostic_error(
        "connection failed: postgresql://comicarr:secret@db.example/comicarr?password=another-secret"
    )

    assert "secret" not in message
    assert "postgresql://[redacted]@db.example" in message


def test_mysql_baseline_uses_varchar_for_defaulted_comic_classification_fields():
    ddl = str(CreateTable(comics).compile(dialect=mysql.dialect()))

    assert "`ContentType` VARCHAR(16) DEFAULT 'comic'" in ddl
    assert "`ReadingDirection` VARCHAR(16) DEFAULT 'ltr'" in ddl


def test_mysql_baseline_uses_bounded_types_for_every_indexed_schema_key():
    for table in metadata.sorted_tables:
        key_columns = set(table.primary_key.columns.keys())
        for constraint in table.constraints:
            key_columns.update(column.name for column in constraint.columns)
        for index in table.indexes:
            key_columns.update(column.name for column in index.columns)

        for column_name in key_columns:
            mysql_type = table.c[column_name].type.dialect_impl(mysql.dialect())
            assert not isinstance(mysql_type, Text), "%s.%s remains TEXT in a MySQL key" % (table.name, column_name)


def test_classifier_identifies_a_known_unversioned_comicarr_database(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "legacy.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))

    assert classify_database(engine) is DatabaseState.LEGACY


def test_classifier_identifies_a_versioned_database(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "versioned.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0001_baseline')"))

    assert classify_database(engine) is DatabaseState.VERSIONED


def test_classifier_rejects_an_empty_alembic_version_table(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "empty-version.db"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE unrelated_data (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))

    with pytest.raises(MigrationStateError, match="version table is empty"):
        upgrade_database(engine)

    assert set(inspect(engine).get_table_names()) == {"alembic_version", "unrelated_data"}


@pytest.mark.parametrize("revision", ["not_comicarr", "0001"])
def test_classifier_rejects_an_unknown_or_partial_alembic_revision(tmp_path, revision):
    engine = create_engine("sqlite:///%s" % (tmp_path / ("untrusted-version-%s.db" % revision)))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE unrelated_data (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES (:revision)"), {"revision": revision})

    with pytest.raises(MigrationStateError, match="unknown Comicarr revision"):
        upgrade_database(engine)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == revision
    assert set(inspect(engine).get_table_names()) == {"alembic_version", "unrelated_data"}


def test_classifier_rejects_multiple_alembic_revisions(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "multiple-versions.db"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(
            text("INSERT INTO alembic_version(version_num) VALUES ('0001_baseline'), ('0002_legacy_adoption')")
        )

    with pytest.raises(MigrationStateError, match="exactly one revision"):
        upgrade_database(engine)

    with engine.connect() as conn:
        assert set(conn.execute(text("SELECT version_num FROM alembic_version")).scalars()) == {
            "0001_baseline",
            "0002_legacy_adoption",
        }


def test_classifier_rejects_a_known_revision_without_comicarr_provenance(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "spoofed-version.db"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE unrelated_data (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0001_baseline')"))

    with pytest.raises(MigrationStateError, match="versioned database is not a recognized Comicarr database"):
        upgrade_database(engine)

    assert set(inspect(engine).get_table_names()) == {"alembic_version", "unrelated_data"}


def test_classifier_rejects_a_known_revision_with_only_the_minimum_legacy_fingerprint(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "minimally-shaped-spoof.db"))
    for table_name in ("comics", "issues", "annuals", "mylar_info"):
        metadata.tables[table_name].create(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0001_baseline')"))

    with pytest.raises(MigrationStateError, match="missing tables required by its Comicarr revision"):
        upgrade_database(engine)

    assert set(inspect(engine).get_table_names()) == {
        "alembic_version",
        "annuals",
        "comics",
        "issues",
        "mylar_info",
    }


def test_upgrade_database_accepts_a_known_prior_comicarr_revision(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "prior-version.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0001_baseline')"))

    assert upgrade_database(engine) == "0006_interactive_search_sessions"
    assert current_revision(engine) == "0006_interactive_search_sessions"


def test_upgrade_database_accepts_pre_chat_revision_without_library_chat_tables(tmp_path):
    """Pre-#296 installs stamped at 0002 lack ai_chat_* tables until 0003 runs.

    Validation must require the schema for the *stamped* revision, not the head
    metadata, or upgrade is blocked and GET /api/ai/chat/threads 500s forever.
    """
    engine = create_engine("sqlite:///%s" % (tmp_path / "pre-chat-version.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE ai_chat_attachments"))
        conn.execute(text("DROP TABLE ai_chat_messages"))
        conn.execute(text("DROP TABLE ai_chat_threads"))
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0002_legacy_adoption')"))

    assert "ai_chat_threads" not in set(inspect(engine).get_table_names())
    assert classify_database(engine) is DatabaseState.VERSIONED
    assert upgrade_database(engine) == "0006_interactive_search_sessions"
    assert current_revision(engine) == "0006_interactive_search_sessions"
    assert {"ai_chat_threads", "ai_chat_messages", "ai_chat_attachments"}.issubset(
        set(inspect(engine).get_table_names())
    )


def test_revision_0003_still_requires_library_chat_tables(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "0003-missing-chat.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE ai_chat_attachments"))
        conn.execute(text("DROP TABLE ai_chat_messages"))
        conn.execute(text("DROP TABLE ai_chat_threads"))
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0003_library_chat')"))

    with pytest.raises(MigrationStateError, match="missing tables required by its Comicarr revision"):
        upgrade_database(engine)


def test_upgrade_database_accepts_pre_activity_revision_without_activity_events(tmp_path):
    """Pre-#477 installs stamped at 0003 lack activity_events until 0005 runs."""
    engine = create_engine("sqlite:///%s" % (tmp_path / "pre-activity-version.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE activity_events"))
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0003_library_chat')"))

    assert "activity_events" not in set(inspect(engine).get_table_names())
    assert classify_database(engine) is DatabaseState.VERSIONED
    assert upgrade_database(engine) == "0006_interactive_search_sessions"
    assert current_revision(engine) == "0006_interactive_search_sessions"
    assert "activity_events" in set(inspect(engine).get_table_names())

    activity_indexes = {index["name"] for index in inspect(engine).get_indexes("activity_events")}
    assert {
        "activity_events_created_at",
        "activity_events_parent_series_id",
        "activity_events_subject",
    }.issubset(activity_indexes)
    journal_indexes = {index["name"] for index in inspect(engine).get_indexes("pipeline_journal")}
    assert "pipeline_journal_stage" in journal_indexes


def test_head_revision_still_requires_activity_events(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "head-missing-activity.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE activity_events"))
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0005_activity_events')"))

    with pytest.raises(MigrationStateError, match="missing tables required by its Comicarr revision"):
        upgrade_database(engine)


def test_upgrade_accepts_pre_interactive_revision_without_session_tables(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "pre-interactive-version.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE interactive_search_candidates"))
        conn.execute(text("DROP TABLE interactive_search_sessions"))
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0005_activity_events')"))

    assert classify_database(engine) is DatabaseState.VERSIONED
    assert upgrade_database(engine) == "0006_interactive_search_sessions"
    assert {"interactive_search_sessions", "interactive_search_candidates"}.issubset(
        set(inspect(engine).get_table_names())
    )


def test_head_revision_requires_interactive_search_session_tables(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "head-missing-interactive.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE interactive_search_candidates"))
        conn.execute(text("DROP TABLE interactive_search_sessions"))
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0006_interactive_search_sessions')"))

    with pytest.raises(MigrationStateError, match="missing tables required by its Comicarr revision"):
        upgrade_database(engine)


def test_interactive_search_tables_match_security_contract():
    sessions = metadata.tables["interactive_search_sessions"]
    candidates = metadata.tables["interactive_search_candidates"]

    assert list(sessions.c.keys()) == [
        "session_id",
        "slot_digest",
        "actor_digest",
        "browser_digest",
        "entity_type",
        "entity_id",
        "series_id",
        "state",
        "candidate_count",
        "created_at",
        "updated_at",
        "expires_at",
    ]
    assert list(candidates.c.keys()) == [
        "candidate_id",
        "session_id",
        "ordinal",
        "state",
        "public_json",
        "reconstruction_json",
        "fingerprint",
        "created_at",
        "updated_at",
        "expires_at",
    ]
    assert sessions.c.session_id.primary_key
    assert candidates.c.candidate_id.primary_key
    assert not {"cookie", "credential", "url", "link", "payload"}.intersection(sessions.c.keys())
    assert not {"cookie", "credential", "url", "link", "payload"}.intersection(candidates.c.keys())


def test_activity_events_table_matches_field_contract():
    columns = {column.name: column for column in metadata.tables["activity_events"].columns}
    assert list(columns) == [
        "event_id",
        "created_at",
        "activity",
        "status",
        "subject_type",
        "subject_id",
        "subject_label",
        "reason_code",
        "reason_detail",
        "provider",
        "run_id",
        "release_key",
        "parent_series_id",
        "scope_type",
        "scope_id",
    ]
    assert columns["event_id"].primary_key
    for required in (
        "created_at",
        "activity",
        "status",
        "subject_type",
        "subject_id",
        "subject_label",
    ):
        assert columns[required].nullable is False


def test_upgrade_creates_pipeline_journal_stage_index_when_missing(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "missing-journal-stage-index.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX pipeline_journal_stage"))
        conn.execute(text("DROP TABLE activity_events"))
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0003_library_chat')"))

    assert "pipeline_journal_stage" not in {index["name"] for index in inspect(engine).get_indexes("pipeline_journal")}
    assert upgrade_database(engine) == "0006_interactive_search_sessions"
    assert "pipeline_journal_stage" in {index["name"] for index in inspect(engine).get_indexes("pipeline_journal")}


def test_classifier_refuses_to_adopt_an_unknown_nonempty_database(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "unknown.db"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE unrelated_data (id INTEGER PRIMARY KEY)"))

    with pytest.raises(MigrationStateError, match="not a recognized Comicarr database"):
        classify_database(engine)


def test_upgrade_database_builds_a_fresh_database_to_the_single_head(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "fresh-upgrade.db"))

    revision = upgrade_database(engine)

    assert revision == "0006_interactive_search_sessions"
    assert set(metadata.tables).issubset(set(inspect(engine).get_table_names()))


def test_head_includes_ledger_retention_indexes(tmp_path):
    """#478: four retention indexes land at head; pipeline_journal_stage stays."""

    engine = create_engine("sqlite:///%s" % (tmp_path / "retention-indexes.db"))
    assert upgrade_database(engine) == "0006_interactive_search_sessions"

    inspector = inspect(engine)
    expected = {
        "acquisition_run_items": "acquisition_run_items_state_completed",
        "acquisition_runs": "acquisition_runs_state_completed",
        "pipeline_journal": "pipeline_journal_stage_updated",
        "acquisition_maintenance_events": "acquisition_maintenance_events_created",
    }
    for table_name, index_name in expected.items():
        names = {index["name"] for index in inspector.get_indexes(table_name)}
        assert index_name in names, "missing %s on %s" % (index_name, table_name)

    journal_indexes = {index["name"] for index in inspector.get_indexes("pipeline_journal")}
    assert "pipeline_journal_stage" in journal_indexes


def test_upgrade_from_library_chat_creates_missing_retention_indexes(tmp_path):
    """Stamped 0003 DBs that lack the new indexes must gain them on upgrade."""

    engine = create_engine("sqlite:///%s" % (tmp_path / "pre-retention.db"))
    metadata.create_all(engine)
    retention_indexes = (
        "acquisition_run_items_state_completed",
        "acquisition_runs_state_completed",
        "pipeline_journal_stage_updated",
        "acquisition_maintenance_events_created",
    )
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0003_library_chat')"))
        for index_name in retention_indexes:
            conn.execute(text("DROP INDEX IF EXISTS %s" % index_name))

    assert upgrade_database(engine) == "0006_interactive_search_sessions"
    inspector = inspect(engine)
    for table_name, index_name in (
        ("acquisition_run_items", "acquisition_run_items_state_completed"),
        ("acquisition_runs", "acquisition_runs_state_completed"),
        ("pipeline_journal", "pipeline_journal_stage_updated"),
        ("acquisition_maintenance_events", "acquisition_maintenance_events_created"),
    ):
        names = {index["name"] for index in inspector.get_indexes(table_name)}
        assert index_name in names
    assert "pipeline_journal_stage" in {index["name"] for index in inspector.get_indexes("pipeline_journal")}


def test_upgrade_database_stamps_only_a_verified_legacy_database(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "legacy-upgrade.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))

    assert upgrade_database(engine) == "0006_interactive_search_sessions"
    assert current_revision(engine) == "0006_interactive_search_sessions"


def test_upgrade_database_never_stamps_an_unknown_database(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "unknown-upgrade.db"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE unrelated_data (id INTEGER PRIMARY KEY)"))

    with pytest.raises(MigrationStateError):
        upgrade_database(engine)

    assert "alembic_version" not in set(inspect(engine).get_table_names())


def test_legacy_adoption_restores_a_missing_safe_historical_column(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "legacy-column.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("ALTER TABLE comics DROP COLUMN MetadataSource"))

    upgrade_database(engine)

    assert "MetadataSource" in {column["name"] for column in inspect(engine).get_columns("comics")}


def test_legacy_adoption_restores_missing_single_column_unique_enforcement(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "legacy-unique.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("CREATE TABLE comics_without_unique AS SELECT * FROM comics"))
        conn.execute(text("DROP TABLE comics"))
        conn.execute(text("ALTER TABLE comics_without_unique RENAME TO comics"))

    upgrade_database(engine)

    unique_indexes = [
        index
        for index in inspect(engine).get_indexes("comics")
        if index.get("unique") and index.get("column_names") == ["ComicID"]
    ]
    assert unique_indexes
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO comics(ComicID) VALUES ('comic-1')"))
        with pytest.raises(IntegrityError):
            conn.execute(text("INSERT INTO comics(ComicID) VALUES ('comic-1')"))


def test_legacy_adoption_moves_a_known_readinglist_shape_to_storyarcs(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "readinglist.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("CREATE TABLE readinglist AS SELECT * FROM storyarcs"))
        conn.execute(
            text(
                "INSERT INTO readinglist(StoryArcID, ComicName, IssueNumber, StoryArc, IssueArcID) "
                "VALUES ('arc-1', 'Saga', '1', 'The Arc', 'arc-issue-1')"
            )
        )
        conn.execute(text("DROP TABLE storyarcs"))

    upgrade_database(engine)

    assert "readinglist" not in set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        assert conn.execute(text("SELECT ComicName FROM storyarcs WHERE IssueArcID = 'arc-issue-1'")).scalar() == "Saga"
