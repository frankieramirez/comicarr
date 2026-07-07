#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for comicarr.cv_cache ComicVine metadata cache."""

import sqlite3

from comicarr.cv_cache import CVCache


def test_init_creates_cache_table_and_expiry_index(tmp_path):
    db_path = str(tmp_path / "cv_cache.db")

    CVCache(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'cv_metadata_cache'
            """
        )
        assert cursor.fetchone()[0] == "cv_metadata_cache"

        cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index' AND name = 'idx_expires_at'
            """
        )
        assert cursor.fetchone()[0] == "idx_expires_at"
    finally:
        conn.close()


def test_stored_value_can_be_retrieved_before_expiry(tmp_path):
    cache = CVCache(str(tmp_path / "cv_cache.db"))
    url = "https://comicvine.gamespot.com/api/issues/?filter=name:Batman"
    response_data = b'{"results": [{"name": "Batman"}]}'

    cache.set(url, response_data, 60)

    assert cache.get(url) == response_data


def test_expired_value_returns_none(tmp_path):
    cache = CVCache(str(tmp_path / "cv_cache.db"))
    url = "https://comicvine.gamespot.com/api/issues/?filter=name:Expired"

    cache.set(url, b'{"results": []}', -1)

    assert cache.get(url) is None


def test_cache_connection_sets_busy_timeout(tmp_path):
    cache = CVCache(str(tmp_path / "cv_cache.db"))

    conn = cache._connect()
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA busy_timeout")
        assert cursor.fetchone()[0] == 15000
    finally:
        conn.close()


def test_cache_connection_uses_wal_journal_mode(tmp_path):
    cache = CVCache(str(tmp_path / "cv_cache.db"))

    conn = cache._connect()
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        assert cursor.fetchone()[0].lower() == "wal"
    finally:
        conn.close()
