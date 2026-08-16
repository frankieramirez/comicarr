#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Prefix-safe manga sync selection and empty-ledger healing."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.app.manga.sync import empty_ledger_series, heal_empty_ledgers, list_active_manga_series
from comicarr.tables import comics, issues, metadata


@pytest.fixture
def query_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def test_list_active_manga_includes_prefix_rows_stamped_comic(query_db):
    with query_db.begin() as conn:
        conn.execute(
            insert(comics),
            [
                {
                    "ComicID": "md-onepiece",
                    "ComicName": "One Piece",
                    "Status": "Active",
                    "ContentType": "comic",
                },
                {
                    "ComicID": "mal-13",
                    "ComicName": "One Piece MAL",
                    "Status": "Active",
                    "ContentType": "comic",
                },
                {
                    "ComicID": "4050-1",
                    "ComicName": "A Comic",
                    "Status": "Active",
                    "ContentType": "comic",
                },
                {
                    "ComicID": "md-paused",
                    "ComicName": "Paused",
                    "Status": "Paused",
                    "ContentType": "manga",
                },
            ],
        )
    ids = {row["ComicID"] for row in list_active_manga_series()}
    assert ids == {"md-onepiece", "mal-13"}


def test_empty_ledger_series_are_those_with_zero_issues(query_db):
    with query_db.begin() as conn:
        conn.execute(
            insert(comics),
            [
                {"ComicID": "md-empty", "ComicName": "Empty", "Status": "Active", "ContentType": "manga"},
                {"ComicID": "md-full", "ComicName": "Full", "Status": "Active", "ContentType": "manga"},
            ],
        )
        conn.execute(
            insert(issues),
            [{"IssueID": "md-full-ch1", "ComicID": "md-full", "Issue_Number": "1"}],
        )
    ids = {row["ComicID"] for row in empty_ledger_series()}
    assert ids == {"md-empty"}


def test_heal_empty_ledgers_reruns_add_for_md_and_mal():
    series = [
        {"ComicID": "md-empty"},
        {"ComicID": "mal-664"},
    ]
    with (
        patch("comicarr.app.manga.sync.empty_ledger_series", return_value=series),
        patch("comicarr.importer.addMangaToDB") as add_md,
        patch("comicarr.importer.addMangaToDB_MAL") as add_mal,
    ):
        assert heal_empty_ledgers() == 2
    add_md.assert_called_once_with("md-empty")
    add_mal.assert_called_once_with("mal-664")
