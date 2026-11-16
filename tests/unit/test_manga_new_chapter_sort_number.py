#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""New chapters found by the MangaDex check get the number post-processing matches on."""

import pytest
from sqlalchemy import select

import comicarr
from comicarr import db, rsscheck
from comicarr.tables import comics, issues, metadata

MANGA_ID = "md-00000000-0000-4000-8000-000000000002"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    metadata.create_all(db.get_engine())
    yield
    db.shutdown_engine()


def test_new_chapters_get_a_sort_number(monkeypatch):
    with db.get_engine().begin() as conn:
        conn.execute(
            comics.insert().values(
                ComicID=MANGA_ID, ComicName="Moon Garden", Status="Active", ContentType="manga", Type="Manga"
            )
        )
    monkeypatch.setattr(
        "comicarr.mangadex.get_all_chapters",
        lambda _uuid: [
            {"chapter": "12", "title": "Twelve", "publish_at": "2026-11-01T00:00:00"},
            {"chapter": "12.5", "title": "Extra", "publish_at": "2026-11-08T00:00:00"},
        ],
    )

    rsscheck.mangadexNewChapterCheck()

    with db.get_engine().connect() as conn:
        rows = {
            r.Issue_Number: r.Int_IssueNumber for r in conn.execute(select(issues).where(issues.c.ComicID == MANGA_ID))
        }
    assert rows == {"12": 12000, "12.5": 12500}
