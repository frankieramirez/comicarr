#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Service-backed legacy-adoption contract for every supported SQL dialect."""

import os

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from comicarr.app.acquisition.maintenance import CONTROL_ID, RECONCILIATION_CONTROL_ID
from comicarr.app.core.schema import MigrationStateError, alembic_config, current_revision, upgrade_database
from comicarr.tables import (
    acquisition_maintenance,
    acquisition_reconciliation,
    annuals,
    comics,
    issues,
    metadata,
    mylar_info,
    storyarcs,
)

pytestmark = pytest.mark.slow


def _reset_database(engine):
    reflected = MetaData()
    reflected.reflect(bind=engine)
    reflected.drop_all(bind=engine)


def _build_legacy_fixture(engine):
    metadata.create_all(engine)

    for table in reversed(metadata.sorted_tables):
        if table.name.startswith("acquisition_"):
            table.drop(engine, checkfirst=True)
    comics.drop(engine, checkfirst=True)
    storyarcs.drop(engine, checkfirst=True)

    legacy = MetaData()
    Table(
        "comics_legacy",
        legacy,
        *(
            Column(
                column.name,
                column.type,
                nullable=column.nullable,
                server_default=column.server_default.arg if column.server_default is not None else None,
            )
            for column in comics.columns
            if column.name != "MetadataSource"
        ),
    )
    readinglist = Table(
        "readinglist",
        legacy,
        *(Column(column.name, column.type, nullable=True) for column in storyarcs.columns),
    )
    legacy.create_all(engine)

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE comics_legacy RENAME TO comics"))
        connection.execute(mylar_info.insert().values(DatabaseVersion=0))
        connection.execute(comics.insert().values(ComicID="dialect-comic", ComicName="Saga"))
        connection.execute(issues.insert().values(IssueID="dialect-issue", ComicID="dialect-comic", ComicName="Saga"))
        connection.execute(annuals.insert().values(IssueID="dialect-annual", Issue_Number="1"))
        connection.execute(
            readinglist.insert().values(
                StoryArcID="dialect-arc",
                ComicName="Saga",
                IssueNumber="1",
                StoryArc="The Arc",
                IssueArcID="dialect-arc-issue",
            )
        )


def test_fresh_database_uses_application_runner_and_is_idempotent():
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    try:
        _reset_database(engine)

        assert upgrade_database(engine) == "0006_interactive_search_sessions"
        assert upgrade_database(engine) == "0006_interactive_search_sessions"
        assert current_revision(engine) == "0006_interactive_search_sessions"
        assert set(metadata.tables).issubset(set(inspect(engine).get_table_names()))
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("revisions", "error_pattern"),
    [
        ((), "version table is empty"),
        (("not_comicarr",), "unknown Comicarr revision"),
        (("0001",), "unknown Comicarr revision"),
        (("0001_baseline",), "versioned database is not a recognized Comicarr database"),
        (("0001_baseline", "0002_legacy_adoption"), "exactly one revision"),
    ],
)
def test_untrusted_revision_states_never_mutate_the_database(revisions, error_pattern):
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    try:
        _reset_database(engine)
        untrusted = MetaData()
        unrelated_data = Table("unrelated_data", untrusted, Column("id", Integer, primary_key=True))
        version_table = Table(
            "alembic_version",
            untrusted,
            Column("version_num", String(32), nullable=False),
        )
        untrusted.create_all(engine)
        with engine.begin() as connection:
            connection.execute(unrelated_data.insert().values(id=1))
            if revisions:
                connection.execute(version_table.insert(), [{"version_num": revision} for revision in revisions])

        with pytest.raises(MigrationStateError, match=error_pattern):
            upgrade_database(engine)

        assert set(inspect(engine).get_table_names()) == {"alembic_version", "unrelated_data"}
        with engine.connect() as connection:
            actual_revisions = tuple(connection.execute(select(version_table.c.version_num)).scalars())
            assert sorted(actual_revisions) == sorted(revisions)
            assert connection.execute(select(unrelated_data.c.id)).scalar_one() == 1
    finally:
        engine.dispose()


def test_minimally_shaped_database_cannot_spoof_a_known_revision():
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    try:
        _reset_database(engine)
        for table in (comics, issues, annuals, mylar_info):
            table.create(engine)
        version_table = Table(
            "alembic_version",
            MetaData(),
            Column("version_num", String(32), nullable=False),
        )
        version_table.create(engine)
        with engine.begin() as connection:
            connection.execute(version_table.insert().values(version_num="0001_baseline"))

        with pytest.raises(MigrationStateError, match="missing tables required by its Comicarr revision"):
            upgrade_database(engine)

        assert set(inspect(engine).get_table_names()) == {
            "alembic_version",
            "annuals",
            "comics",
            "issues",
            "mylar_info",
        }
    finally:
        engine.dispose()


def test_legacy_adoption_preserves_data_and_is_idempotent_across_dialects():
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    try:
        _reset_database(engine)
        _build_legacy_fixture(engine)

        assert upgrade_database(engine) == "0006_interactive_search_sessions"
        assert upgrade_database(engine) == "0006_interactive_search_sessions"
        assert current_revision(engine) == "0006_interactive_search_sessions"

        table_names = set(inspect(engine).get_table_names())
        assert "readinglist" not in table_names
        assert set(metadata.tables).issubset(table_names)
        assert "MetadataSource" in {column["name"] for column in inspect(engine).get_columns("comics")}

        unique_comic_ids = any(
            constraint.get("column_names") == ["ComicID"]
            for constraint in inspect(engine).get_unique_constraints("comics")
        ) or any(
            index.get("unique") and index.get("column_names") == ["ComicID"]
            for index in inspect(engine).get_indexes("comics")
        )
        assert unique_comic_ids

        with engine.connect() as connection:
            assert (
                connection.execute(select(comics.c.ComicName).where(comics.c.ComicID == "dialect-comic")).scalar_one()
                == "Saga"
            )
            assert (
                connection.execute(select(issues.c.ComicID).where(issues.c.IssueID == "dialect-issue")).scalar_one()
                == "dialect-comic"
            )
            assert (
                connection.execute(
                    select(storyarcs.c.ComicName).where(storyarcs.c.IssueArcID == "dialect-arc-issue")
                ).scalar_one()
                == "Saga"
            )
            assert connection.execute(select(acquisition_maintenance.c.control_id)).scalar_one() == CONTROL_ID
            assert (
                connection.execute(select(acquisition_reconciliation.c.control_id)).scalar_one()
                == RECONCILIATION_CONTROL_ID
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(comics.insert().values(ComicID="dialect-comic", ComicName="Duplicate"))

        command.check(alembic_config(engine))
    finally:
        engine.dispose()
