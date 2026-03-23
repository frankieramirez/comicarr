#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
SQLite-to-target database migration tool.

Migrates data from an existing SQLite database to PostgreSQL or MySQL/MariaDB.

Usage:
    python3 Comicarr.py migrate --from sqlite:///old.db --to postgresql://user:pass@host/db
    python3 Comicarr.py migrate --from sqlite:///old.db --to postgresql://... --validate-only
    python3 Comicarr.py migrate --from sqlite:///old.db --to postgresql://... --yes

Data cleaning during migration:
    - String "None" in TEXT columns -> NULL
    - Empty string "" in INTEGER columns -> NULL
    - Non-numeric strings in INTEGER columns -> NULL (logged)
    - Preserves NULL vs empty string distinction for TEXT columns
"""

import logging
import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from comicarr.db import _mask_password
from comicarr.tables import metadata

logger = logging.getLogger("comicarr.db_migrate")

# Table ordering respecting dependencies.
# Independent tables first, then dependent tables.
INDEPENDENT_TABLES = [
    "comics",
    "rssdb",
    "ref32p",
    "mylar_info",
    "searchresults",
    "weekly",
    "provider_searches",
    "jobhistory",
    "exceptions_log",
    "tmp_searches",
    "notifs",
    "ddl_info",
    "manualresults",
    "futureupcoming",
]

DEPENDENT_TABLES = [
    "issues",
    "annuals",
    "snatched",
    "upcoming",
    "nzblog",
    "importresults",
    "readlist",
    "failed",
    "storyarcs",
    "oneoffhistory",
]

ALL_TABLES = INDEPENDENT_TABLES + DEPENDENT_TABLES


def _validate_sqlite_file(path):
    """Check that the file is a real SQLite database."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"SQLite file not found: {path}")

    with open(path, "rb") as f:
        header = f.read(16)
    if not header.startswith(b"SQLite format 3\x00"):
        raise ValueError(f"File is not a valid SQLite database: {path}")


def _get_integer_columns(table_name):
    """Return set of column names that are INTEGER type for a table."""
    table = metadata.tables.get(table_name)
    if table is None:
        return set()
    int_cols = set()
    for col in table.columns:
        type_name = str(col.type).upper()
        if "INT" in type_name or "FLOAT" in type_name or "NUMERIC" in type_name or "REAL" in type_name:
            int_cols.add(col.name)
    return int_cols


def _get_text_columns(table_name):
    """Return set of column names that are TEXT/String type for a table."""
    table = metadata.tables.get(table_name)
    if table is None:
        return set()
    text_cols = set()
    for col in table.columns:
        type_name = str(col.type).upper()
        if "TEXT" in type_name or "VARCHAR" in type_name or "STRING" in type_name or "CLOB" in type_name:
            text_cols.add(col.name)
    return text_cols


def _clean_row(row_dict, table_name, int_columns, text_columns):
    """Clean a single row during migration.

    - String "None" in TEXT columns -> None (NULL)
    - Empty string in INTEGER columns -> None (NULL)
    - Non-numeric strings in INTEGER columns -> None (NULL, logged)
    """
    cleaned = {}
    conversions = []

    for key, value in row_dict.items():
        if value is None:
            cleaned[key] = None
            continue

        if key in text_columns:
            if value == "None":
                cleaned[key] = None
                conversions.append(f"  {key}: 'None' -> NULL")
            else:
                cleaned[key] = value

        elif key in int_columns:
            if value == "" or value == "None":
                cleaned[key] = None
                conversions.append(f"  {key}: '{value}' -> NULL")
            elif isinstance(value, str):
                try:
                    cleaned[key] = int(value) if "." not in value else float(value)
                except (ValueError, TypeError):
                    cleaned[key] = None
                    conversions.append(f"  {key}: '{value}' (non-numeric) -> NULL")
            else:
                cleaned[key] = value
        else:
            cleaned[key] = value

    return cleaned, conversions


def validate(source_url, target_url):
    """Dry-run validation: report type mismatches, duplicates, and row counts."""
    print("\n=== Validation Mode ===")
    print(f"Source: {_mask_password(source_url)}")
    print(f"Target: {_mask_password(target_url)}")
    print()

    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url)

    source_inspector = inspect(source_engine)
    source_tables = set(source_inspector.get_table_names())

    total_rows = 0
    total_cleaning = 0
    issues_found = []

    for table_name in ALL_TABLES:
        if table_name not in source_tables:
            print(f"  SKIP  {table_name:25s} (not in source)")
            continue

        with source_engine.connect() as conn:
            count_result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            row_count = count_result.scalar()
            total_rows += row_count

        int_cols = _get_integer_columns(table_name)
        text_cols = _get_text_columns(table_name)

        # Sample rows for cleaning analysis
        cleaning_count = 0
        with source_engine.connect() as conn:
            sample = conn.execute(text(f"SELECT * FROM {table_name} LIMIT 100"))
            for row in sample:
                _, conversions = _clean_row(dict(row._mapping), table_name, int_cols, text_cols)
                cleaning_count += len(conversions)

        total_cleaning += cleaning_count
        status = "OK" if cleaning_count == 0 else f"{cleaning_count} cleanings (sampled)"
        print(f"  {row_count:>8,d} rows  {table_name:25s}  {status}")

    # Check target is empty or has tables
    target_inspector = inspect(target_engine)
    target_tables = set(target_inspector.get_table_names())
    if target_tables:
        existing = target_tables & set(ALL_TABLES)
        if existing:
            issues_found.append(
                f"Target database already has tables: {', '.join(sorted(existing))}. "
                "Migration will FAIL on duplicate data. Drop tables first or use an empty database."
            )

    print(f"\n  Total: {total_rows:,d} rows across {len(ALL_TABLES)} tables")
    if total_cleaning > 0:
        print(f"  Data cleaning: ~{total_cleaning} conversions needed (based on 100-row sample)")

    if issues_found:
        print("\n  ISSUES:")
        for issue in issues_found:
            print(f"    ! {issue}")

    source_engine.dispose()
    target_engine.dispose()
    return len(issues_found) == 0


def migrate(source_url, target_url, batch_size=5000):
    """Migrate all data from source SQLite to target database.

    Args:
        source_url: SQLAlchemy URL for source SQLite database
        target_url: SQLAlchemy URL for target database
        batch_size: Number of rows per batch insert (default 5000)
    """
    print("\n=== Migration Starting ===")
    print(f"Source: {_mask_password(source_url)}")
    print(f"Target: {_mask_password(target_url)}")
    print(f"Batch size: {batch_size}")
    print()

    # Validate source
    if source_url.startswith("sqlite:///"):
        db_path = source_url.replace("sqlite:///", "")
        _validate_sqlite_file(db_path)

    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url)

    # Warn if target is non-localhost
    if "@" in target_url:
        host_part = target_url.split("@")[1].split("/")[0].split(":")[0]
        if host_part not in ("localhost", "127.0.0.1", "::1"):
            print(f"  WARNING: Target host is '{host_part}' (non-localhost)")

    # Create tables on target
    print("Creating tables on target...")
    metadata.create_all(target_engine)
    print("  Tables created.")

    source_inspector = inspect(source_engine)
    source_tables = set(source_inspector.get_table_names())

    total_migrated = 0
    total_cleaned = 0
    failed_tables = []

    for table_name in ALL_TABLES:
        if table_name not in source_tables:
            print(f"  SKIP  {table_name} (not in source)")
            continue

        int_cols = _get_integer_columns(table_name)
        text_cols = _get_text_columns(table_name)
        table_obj = metadata.tables.get(table_name)

        if table_obj is None:
            print(f"  SKIP  {table_name} (not in metadata)")
            continue

        # Get target column names to filter source data
        target_cols = {c.name for c in table_obj.columns}

        try:
            with source_engine.connect() as source_conn:
                count_result = source_conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                row_count = count_result.scalar()

                if row_count == 0:
                    print(f"  {table_name:25s}  0 rows (empty)")
                    continue

                # Read and insert in batches
                offset = 0
                table_migrated = 0
                table_cleaned = 0

                while offset < row_count:
                    rows = source_conn.execute(
                        text(f"SELECT * FROM {table_name} LIMIT :limit OFFSET :offset"),
                        {"limit": batch_size, "offset": offset},
                    )

                    batch = []
                    for row in rows:
                        row_dict = dict(row._mapping)
                        # Filter to only columns that exist in the target schema
                        row_dict = {k: v for k, v in row_dict.items() if k in target_cols}
                        cleaned, conversions = _clean_row(row_dict, table_name, int_cols, text_cols)
                        batch.append(cleaned)
                        table_cleaned += len(conversions)

                    if batch:
                        with target_engine.begin() as target_conn:
                            target_conn.execute(table_obj.insert(), batch)
                        table_migrated += len(batch)

                    offset += batch_size

                total_migrated += table_migrated
                total_cleaned += table_cleaned
                status = f"({table_cleaned} cleaned)" if table_cleaned else ""
                print(f"  {table_name:25s}  {table_migrated:>8,d} rows migrated  {status}")

        except (OperationalError, ProgrammingError) as e:
            failed_tables.append((table_name, str(e)))
            print(f"  FAIL  {table_name}: {e}")

    # --- Post-migration verification ---
    print("\n=== Verification ===")
    verify_ok = True
    for table_name in ALL_TABLES:
        if table_name not in source_tables:
            continue
        table_obj = metadata.tables.get(table_name)
        if table_obj is None:
            continue

        with source_engine.connect() as conn:
            src_count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
        with target_engine.connect() as conn:
            tgt_count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()

        match = "OK" if src_count == tgt_count else "MISMATCH"
        if src_count != tgt_count:
            verify_ok = False
        print(f"  {table_name:25s}  source={src_count:>8,d}  target={tgt_count:>8,d}  {match}")

    print("\n=== Migration Summary ===")
    print(f"  Total rows migrated: {total_migrated:,d}")
    print(f"  Data cleaning conversions: {total_cleaned:,d}")
    print(f"  Failed tables: {len(failed_tables)}")
    if failed_tables:
        for name, err in failed_tables:
            print(f"    FAILED: {name} — {err}")
    print(f"  Verification: {'PASSED' if verify_ok else 'FAILED'}")

    if verify_ok and not failed_tables:
        print("\n  Migration completed successfully.")
        print("  WARNING: Securely delete or encrypt the old SQLite file.")
    else:
        print("\n  Migration completed with issues. Review output above.")

    source_engine.dispose()
    target_engine.dispose()
    return verify_ok and not failed_tables


