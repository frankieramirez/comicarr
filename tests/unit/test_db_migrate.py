#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from sqlalchemy import create_engine, text

from comicarr.app.core.schema import current_revision, upgrade_database
from comicarr.db_migrate import migrate
from comicarr.tables import comics


def _sqlite_url(path):
    return f"sqlite:///{path}"


def _create_legacy_comics_database(path, rows):
    engine = create_engine(_sqlite_url(path))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE comics (ComicID TEXT, ComicName TEXT)"))
        conn.execute(
            text("INSERT INTO comics (ComicID, ComicName) VALUES (:comic_id, :comic_name)"),
            [{"comic_id": comic_id, "comic_name": comic_name} for comic_id, comic_name in rows],
        )
    engine.dispose()


def _create_legacy_snatched_database(path, rows):
    engine = create_engine(_sqlite_url(path))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE snatched (IssueID TEXT, Status TEXT, Provider TEXT, ComicName TEXT)"))
        conn.execute(
            text(
                "INSERT INTO snatched (IssueID, Status, Provider, ComicName) "
                "VALUES (:issue_id, :status, :provider, :comic_name)"
            ),
            [
                {
                    "issue_id": issue_id,
                    "status": status,
                    "provider": provider,
                    "comic_name": comic_name,
                }
                for issue_id, status, provider, comic_name in rows
            ],
        )
    engine.dispose()


def test_migrate_deduplicates_unique_keys_across_batches(tmp_path, capsys):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    _create_legacy_comics_database(
        source_path,
        [
            ("duplicate", "first row wins"),
            ("", "first empty key wins"),
            (None, "first null key remains allowed"),
            ("other", "other row"),
            ("duplicate", "later row is removed"),
            ("", "later empty key is removed"),
            (None, "second null key remains allowed"),
        ],
    )

    result = migrate(_sqlite_url(source_path), _sqlite_url(target_path), batch_size=2)

    output = capsys.readouterr().out
    assert result is True
    assert "5 rows migrated  (2 deduped)" in output
    assert "source=       7  target=       5  OK (2 deduped)" in output
    assert "Total rows migrated: 5" in output
    assert "Verification: PASSED" in output

    target_engine = create_engine(_sqlite_url(target_path))
    with target_engine.connect() as conn:
        rows = conn.execute(text("SELECT ComicID, ComicName FROM comics ORDER BY rowid")).mappings().all()
    assert current_revision(target_engine) == "0003_library_chat"
    target_engine.dispose()

    assert rows == [
        {"ComicID": "duplicate", "ComicName": "first row wins"},
        {"ComicID": "", "ComicName": "first empty key wins"},
        {"ComicID": None, "ComicName": "first null key remains allowed"},
        {"ComicID": "other", "ComicName": "other row"},
        {"ComicID": None, "ComicName": "second null key remains allowed"},
    ]


def test_migrate_deduplicates_composite_keys_with_empty_components(tmp_path, capsys):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    _create_legacy_snatched_database(
        source_path,
        [
            ("issue-a", "", "provider", "first empty component wins"),
            (None, "Wanted", "provider", "first null component remains allowed"),
            ("other", "Wanted", "provider", "other row"),
            ("issue-a", "", "provider", "later empty component is removed"),
            (None, "Wanted", "provider", "second null component remains allowed"),
        ],
    )

    result = migrate(_sqlite_url(source_path), _sqlite_url(target_path), batch_size=2)

    output = capsys.readouterr().out
    assert result is True
    assert "4 rows migrated  (1 deduped)" in output
    assert "source=       5  target=       4  OK (1 deduped)" in output
    assert "Verification: PASSED" in output

    target_engine = create_engine(_sqlite_url(target_path))
    with target_engine.connect() as conn:
        rows = (
            conn.execute(text("SELECT IssueID, Status, Provider, ComicName FROM snatched ORDER BY rowid"))
            .mappings()
            .all()
        )
    assert current_revision(target_engine) == "0003_library_chat"
    target_engine.dispose()

    assert rows == [
        {
            "IssueID": "issue-a",
            "Status": "",
            "Provider": "provider",
            "ComicName": "first empty component wins",
        },
        {
            "IssueID": None,
            "Status": "Wanted",
            "Provider": "provider",
            "ComicName": "first null component remains allowed",
        },
        {
            "IssueID": "other",
            "Status": "Wanted",
            "Provider": "provider",
            "ComicName": "other row",
        },
        {
            "IssueID": None,
            "Status": "Wanted",
            "Provider": "provider",
            "ComicName": "second null component remains allowed",
        },
    ]


def test_migrate_reports_target_integrity_conflicts(tmp_path, capsys):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    _create_legacy_comics_database(
        source_path,
        [
            ("first", "migrated before conflict"),
            ("second", "also migrated before conflict"),
            ("existing", "source row conflicts with target"),
        ],
    )

    target_engine = create_engine(_sqlite_url(target_path))
    upgrade_database(target_engine)
    with target_engine.begin() as conn:
        conn.execute(comics.insert().values(ComicID="existing", ComicName="target row"))
    target_engine.dispose()

    result = migrate(_sqlite_url(source_path), _sqlite_url(target_path), batch_size=2)

    output = capsys.readouterr().out
    assert result is False
    assert "FAIL  comics:" in output
    assert "Total rows migrated: 2" in output
    assert "Failed tables: 1" in output
    assert "Verification: FAILED" in output
    assert "Migration completed with issues" in output
    # Per-table verification must mark the failed table FAILED (not only MISMATCH).
    assert "source=       3  target=       3  FAILED" in output

    # Prior successful batches stay committed; conflict row must not overwrite target seed.
    target_engine = create_engine(_sqlite_url(target_path))
    with target_engine.connect() as conn:
        rows = {
            row["ComicID"]: row["ComicName"]
            for row in conn.execute(text("SELECT ComicID, ComicName FROM comics")).mappings()
        }
    target_engine.dispose()

    assert rows == {
        "first": "migrated before conflict",
        "second": "also migrated before conflict",
        "existing": "target row",
    }
