#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Rebuild the upgrade-matrix fixtures from the release tags they stand for.

Usage::

    python3 tests/fixtures/upgrade_matrix/build.py           # rewrite every row
    python3 tests/fixtures/upgrade_matrix/build.py 0.5x      # rewrite one row
    python3 tests/fixtures/upgrade_matrix/build.py --check   # fail if a rebuild differs

Each row runs that release's own code, extracted from its git tag, to create
an empty database and upgrade it to the release's schema head. It also has
that code write the release's default ``config.ini``. The current code then
seeds the same synthetic library into every database and writes it out as SQL
text. Running the tag's code matters: ``0001_baseline`` creates tables from
the live ``comicarr.tables`` metadata, so upgrading to an old revision with
today's code produces today's schema, not the release's.

The script needs git, and fetches a missing tag from ``origin``.
"""

from __future__ import annotations

import argparse
import io
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

# Rows built from a release tag. Fresh needs no fixture.
ROWS = {
    "0.5x": ("v0.50.7", "0014_import_issue_readiness"),
}

# Written by the release's own upgrade and startup, then pinned so a rebuild
# reproduces the committed SQL byte for byte.
FIXED_TIMESTAMP = "2026-01-01T00:00:00+00:00"
GENERATED_ROWS = {
    "alembic_version": None,
    "acquisition_maintenance": None,
    "acquisition_reconciliation": "updated_at",
    "acquisition_schema_versions": "applied_at",
}

# Non-default settings, so a lost key changes a value the test can see.
CONFIG_OVERRIDES = """[General]
config_version = 19
destination_dir = /library/comics
manga_destination_dir = /library/manga

[Interface]
http_port = 8091
http_username = matrix-admin

[Import]
comic_dir = /library/inbox

[SABnzbd]
sab_host = http://sab.invalid:8080
sab_category = comics
"""

# Runs inside the extracted tag, with that tag's comicarr package first on the
# path. argv: database path, data directory.
ERA_SCRIPT = """
import sys
sys.path.insert(0, ".")
from unittest.mock import MagicMock
from sqlalchemy import create_engine
import comicarr
import comicarr.maintenance
from comicarr import config as config_module
from comicarr.app.core.schema import upgrade_database

database, data_dir = sys.argv[1], sys.argv[2]
engine = create_engine("sqlite:///" + database)
print(upgrade_database(engine))
engine.dispose()

comicarr.DATA_DIR = data_dir
comicarr.PROG_DIR = "."
comicarr.maintenance.Maintenance.backup_files = lambda self, **kwargs: True
cfg = config_module.Config(data_dir + "/config.ini")
cfg.configure = MagicMock()
cfg.provider_sequence = MagicMock()
cfg.read(startup=False)
"""


@dataclass(frozen=True)
class Seed:
    table: str
    rows: tuple[dict, ...]


def _comic(comic_id, name, year, status, location, **extra):
    row = {
        "ComicID": comic_id,
        "ComicName": name,
        "ComicSortName": name,
        "ComicYear": year,
        "ComicPublisher": "Matrix Press",
        "Status": status,
        "ComicLocation": location,
        "Have": 0,
        "Total": 0,
        "DateAdded": "2026-01-01",
        "LatestIssue": "1",
        "LatestDate": "2026-01-01",
        "Type": "Print",
        "ContentType": "comic",
    }
    row.update(extra)
    return row


def _issue(issue_id, comic_id, comic_name, number, status, intent, location=None, **extra):
    row = {
        "IssueID": issue_id,
        "ComicID": comic_id,
        "ComicName": comic_name,
        "Issue_Number": number,
        "Int_IssueNumber": int(float(number) * 1000),
        "IssueDate": "2026-01-01",
        "ReleaseDate": "2026-01-01",
        "DateAdded": "2026-01-01",
        "Status": status,
        "AcquisitionIntent": intent,
        "Location": location,
    }
    row.update(extra)
    return row


# One small made-up library, identical in every row.
SEED = (
    Seed(
        "comics",
        (
            _comic("900001", "Starfall Rangers", "2019", "Active", "/library/comics/Starfall Rangers (2019)"),
            _comic("900002", "Harbor Lights", "2021", "Paused", "/library/comics/Harbor Lights (2021)"),
            _comic("900003", "The Quiet Engine", "2015", "Active", "/library/comics/The Quiet Engine (2015)"),
            _comic(
                "md-0f5e1c2a-matrix",
                "Lantern Garden",
                "2020",
                "Active",
                "/library/manga/Lantern Garden (2020)",
                ContentType="manga",
                Type="Manga",
            ),
        ),
    ),
    Seed(
        "issues",
        (
            _issue("910001", "900001", "Starfall Rangers", "1", "Downloaded", "policy", "Starfall Rangers 001.cbz"),
            _issue("910002", "900001", "Starfall Rangers", "2", "Wanted", "wanted"),
            _issue("910003", "900001", "Starfall Rangers", "3", "Snatched", "wanted"),
            _issue("910004", "900001", "Starfall Rangers", "4", "Failed", "wanted"),
            _issue("910005", "900002", "Harbor Lights", "1", "Skipped", "skipped"),
            _issue("910006", "900002", "Harbor Lights", "2", "Ignored", "ignored"),
            _issue("910007", "900003", "The Quiet Engine", "1", "Archived", "policy", "The Quiet Engine 001.cbr"),
            _issue("910008", "900003", "The Quiet Engine", "2", "Downloaded", "policy", "The Quiet Engine 002.cbz"),
            _issue(
                "md-chapter-910009",
                "md-0f5e1c2a-matrix",
                "Lantern Garden",
                "1",
                "Downloaded",
                "policy",
                "Lantern Garden c001.cbz",
                ChapterNumber="1",
                VolumeNumber="1",
            ),
            _issue(
                "md-chapter-910010",
                "md-0f5e1c2a-matrix",
                "Lantern Garden",
                "2",
                "Wanted",
                "wanted",
                ChapterNumber="2",
                VolumeNumber="1",
            ),
        ),
    ),
    Seed(
        "annuals",
        (
            {
                "IssueID": "920001",
                "ComicID": "900001",
                "ComicName": "Starfall Rangers Annual",
                "ReleaseComicID": "900091",
                "ReleaseComicName": "Starfall Rangers Annual",
                "Issue_Number": "1",
                "Int_IssueNumber": 1000,
                "IssueDate": "2026-06-01",
                "ReleaseDate": "2026-06-01",
                "Status": "Downloaded",
                "AcquisitionIntent": "policy",
                "Location": "Starfall Rangers Annual 001.cbz",
                "Deleted": 0,
            },
        ),
    ),
    Seed(
        "storyarcs",
        tuple(
            {
                "StoryArcID": "930001",
                "CV_ArcID": "930001",
                "StoryArc": "The Long Night",
                "ComicName": name,
                "ComicID": comic_id,
                "IssueID": issue_id,
                "IssueArcID": "930001_%s" % issue_id,
                "IssueNumber": number,
                "ReadingOrder": order,
                "TotalIssues": "2",
                "Status": status,
                "Location": location,
                "Publisher": "Matrix Press",
                "Manual": "added",
            }
            for order, (name, comic_id, issue_id, number, status, location) in enumerate(
                (
                    ("Starfall Rangers", "900001", "910001", "1", "Downloaded", "Starfall Rangers 001.cbz"),
                    ("The Quiet Engine", "900003", "910008", "2", "Wanted", None),
                ),
                start=1,
            )
        ),
    ),
    Seed(
        "snatched",
        (
            {
                "IssueID": "910003",
                "ComicID": "900001",
                "ComicName": "Starfall Rangers",
                "Issue_Number": "3",
                "Size": 41000000,
                "DateAdded": "2026-01-02 10:00:00",
                "Status": "Snatched",
                "Provider": "MatrixNZB",
                "FolderName": "Starfall.Rangers.003.2019",
                "Hash": "matrixhash0003",
            },
            {
                "IssueID": "910001",
                "ComicID": "900001",
                "ComicName": "Starfall Rangers",
                "Issue_Number": "1",
                "Size": 40000000,
                "DateAdded": "2026-01-01 10:00:00",
                "Status": "Post-Processed",
                "Provider": "MatrixNZB",
                "FolderName": "Starfall.Rangers.001.2019",
                "Hash": "matrixhash0001",
            },
        ),
    ),
    Seed(
        "failed",
        (
            {
                "ID": "matrix-failed-1",
                "Status": "Failed",
                "ComicID": "900001",
                "IssueID": "910004",
                "Provider": "MatrixNZB",
                "ComicName": "Starfall Rangers",
                "Issue_Number": "4",
                "NZBName": "Starfall.Rangers.004.2019",
                "DateFailed": "2026-01-03 10:00:00",
            },
        ),
    ),
    Seed(
        "weekly",
        (
            {
                "SHIPDATE": "2026-01-07",
                "PUBLISHER": "Matrix Press",
                "ISSUE": "5",
                "COMIC": "Starfall Rangers",
                "STATUS": "Wanted",
                "ComicID": "900001",
                "IssueID": "910011",
                "weeknumber": "01",
                "year": "2026",
                "format": "print",
            },
            {
                "SHIPDATE": "2026-01-07",
                "PUBLISHER": "Elsewhere Comics",
                "ISSUE": "1",
                "COMIC": "Unwatched Horizon",
                "STATUS": "Skipped",
                "ComicID": "999901",
                "IssueID": "999911",
                "weeknumber": "01",
                "year": "2026",
                "format": "print",
            },
        ),
    ),
)


def _git(*args, **kwargs):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, **kwargs)


def _ensure_tag(tag):
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "refs/tags/%s^{commit}" % tag],
        cwd=ROOT,
        capture_output=True,
    )
    if probe.returncode != 0:
        _git("fetch", "--quiet", "--depth=1", "origin", "refs/tags/%s:refs/tags/%s" % (tag, tag))


def _extract_tag(tag, destination):
    _ensure_tag(tag)
    archive = _git("archive", "--format=tar", tag, "comicarr", "alembic", "alembic.ini").stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(destination, filter="data")


def _seed(connection):
    for seed in SEED:
        for row in seed.rows:
            columns = ", ".join('"%s"' % column for column in row)
            placeholders = ", ".join("?" for _ in row)
            connection.execute(
                'INSERT INTO "%s" (%s) VALUES (%s)' % (seed.table, columns, placeholders),
                tuple(row.values()),
            )


def _pin_generated_rows(connection):
    tables = [name for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    for table in tables:
        count = connection.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0]
        if count and table not in GENERATED_ROWS:
            raise SystemExit("%s has %d row(s) after the release upgrade; pin them in GENERATED_ROWS" % (table, count))
        column = GENERATED_ROWS.get(table)
        if column:
            connection.execute('UPDATE "%s" SET "%s" = ?' % (table, column), (FIXED_TIMESTAMP,))


def _literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return "X'%s'" % value.hex()
    if isinstance(value, (int, float)):
        return repr(value)
    return "'%s'" % str(value).replace("'", "''")


def dump_sql(connection):
    """Return the database as SQL text that is stable across Python versions."""

    lines = ["BEGIN TRANSACTION;"]
    objects = connection.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
        "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END, name"
    ).fetchall()
    for object_type, name, sql in objects:
        lines.append("%s;" % sql)
        if object_type != "table":
            continue
        for row in connection.execute('SELECT * FROM "%s" ORDER BY rowid' % name):
            lines.append('INSERT INTO "%s" VALUES(%s);' % (name, ",".join(_literal(value) for value in row)))
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def build_row(name):
    """Return ``(sql, config_ini)`` text for one release row."""

    tag, revision = ROWS[name]
    with tempfile.TemporaryDirectory(prefix="upgrade-matrix-") as scratch:
        scratch = Path(scratch)
        tree = scratch / "tree"
        data_dir = scratch / "data"
        tree.mkdir()
        data_dir.mkdir()
        _extract_tag(tag, tree)
        (data_dir / "config.ini").write_text(CONFIG_OVERRIDES, encoding="utf-8")
        database = scratch / "comicarr.db"

        result = subprocess.run(
            [sys.executable, "-I", "-W", "ignore", "-c", ERA_SCRIPT, str(database), str(data_dir)],
            cwd=tree,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SystemExit("%s: release upgrade failed\n%s" % (tag, result.stderr))
        reached = result.stdout.strip().splitlines()[-1]
        if reached != revision:
            raise SystemExit("%s upgraded to %s, expected %s" % (tag, reached, revision))

        connection = sqlite3.connect(database)
        try:
            _pin_generated_rows(connection)
            _seed(connection)
            connection.commit()
            sql = dump_sql(connection)
        finally:
            connection.close()
        config_ini = (data_dir / "config.ini").read_text(encoding="utf-8")
    if str(scratch) in config_ini:
        raise SystemExit("%s: config.ini embeds a build path" % tag)
    return sql, config_ini


def fixture_paths(name):
    return HERE / ("%s.sql" % name), HERE / ("%s.config.ini" % name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rows", nargs="*", choices=[[], *ROWS], help="rows to rebuild (default: all)")
    parser.add_argument("--check", action="store_true", help="fail when a rebuild differs from the committed files")
    args = parser.parse_args(argv)

    stale = []
    for name in args.rows or ROWS:
        sql, config_ini = build_row(name)
        for path, text in zip(fixture_paths(name), (sql, config_ini)):
            if args.check:
                if not path.exists() or path.read_text(encoding="utf-8") != text:
                    stale.append(path.relative_to(ROOT))
            else:
                path.write_text(text, encoding="utf-8")
                print("wrote %s" % path.relative_to(ROOT))
    if stale:
        print("Stale upgrade-matrix fixtures (rebuild with %s):" % Path(__file__).relative_to(ROOT))
        for path in stale:
            print("  %s" % path)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
