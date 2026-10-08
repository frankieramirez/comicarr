#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Refuse adding the same manga from both MangaDex and MyAnimeList."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select

import comicarr
from comicarr import db, importer
from comicarr.app.manga.duplicates import find_existing_manga_series
from comicarr.app.search.service import add_manga
from comicarr.app.series.service import listLibrary
from comicarr.tables import comics, metadata


MD_UUID = "aaaaaaaa-bbbb-cccc-dddd-onepiece01"
MAL_ID = "13"


@pytest.fixture
def manga_db(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(importer.db, "get_engine", lambda: engine)
    monkeypatch.setattr(comicarr, "COMICSORT", None, raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            MANGA_DIR=str(tmp_path),
            FOLDER_FORMAT="$Series",
            REPLACE_SPACES=False,
            CREATE_FOLDERS=False,
            ENFORCE_PERMS=False,
            ANNUALS_ON=False,
        ),
        raising=False,
    )
    return engine


def _insert(engine, **values):
    with engine.begin() as conn:
        conn.execute(comics.insert(), values)


def _row(engine, comic_id):
    with engine.connect() as conn:
        return conn.execute(select(comics).where(comics.c.ComicID == comic_id)).mappings().fetchone()


def _md_details(**overrides):
    details = {
        "id": "md-" + MD_UUID,
        "name": "One Piece",
        "year": 1997,
        "status": "ongoing",
        "author": "Oda",
        "description": "",
        "cover_url": None,
        "url": "https://mangadex.org/title/" + MD_UUID,
        "alt_titles": [],
        "mal_id": MAL_ID,
    }
    details.update(overrides)
    return details


def _mal_details(**overrides):
    details = {
        "name": "One Piece",
        "year": 1997,
        "status": "ongoing",
        "author": "Oda",
        "description": "",
        "cover_url": None,
        "url": "https://myanimelist.net/manga/" + MAL_ID,
        "alt_titles": [],
        "last_chapter": None,
    }
    details.update(overrides)
    return details


def _patch_add_side_effects(monkeypatch, tmp_path, *, md_details=None, mal_details=None, mal_to_md=MD_UUID):
    from comicarr import config as comicarr_config
    import comicarr.mangadex as mangadex
    import comicarr.myanimelist as myanimelist

    monkeypatch.setattr(mangadex, "get_manga_details", lambda *a, **k: md_details or _md_details())
    monkeypatch.setattr(myanimelist, "get_manga_details", lambda *a, **k: mal_details or _mal_details())
    monkeypatch.setattr(mangadex, "find_by_mal_id", lambda *a, **k: mal_to_md)
    monkeypatch.setattr(importer, "_populate_manga_chapters", lambda *a, **k: 0)
    monkeypatch.setattr(importer.helpers, "getImage", lambda *a, **k: None)
    monkeypatch.setattr(importer.helpers, "ComicSort", lambda **k: None)
    monkeypatch.setattr(comicarr_config, "get_manga_destination", lambda: str(tmp_path))


def test_find_existing_matches_mal_id_on_mangadex_row(manga_db):
    _insert(
        manga_db,
        ComicID="md-" + MD_UUID,
        ComicName="One Piece",
        MangaDexID=MD_UUID,
        MalID=MAL_ID,
        Status="Active",
    )

    found = find_existing_manga_series(comic_id="mal-" + MAL_ID, mal_id=MAL_ID)
    assert found["ComicID"] == "md-" + MD_UUID


def test_find_existing_matches_mangadex_id_on_mal_row(manga_db):
    _insert(
        manga_db,
        ComicID="mal-" + MAL_ID,
        ComicName="One Piece",
        MangaDexID=MD_UUID,
        MalID=MAL_ID,
        Status="Active",
    )

    found = find_existing_manga_series(comic_id="md-" + MD_UUID, mangadex_id=MD_UUID)
    assert found["ComicID"] == "mal-" + MAL_ID


def test_find_existing_ignores_the_same_comic_id(manga_db):
    _insert(
        manga_db,
        ComicID="md-" + MD_UUID,
        ComicName="One Piece",
        MangaDexID=MD_UUID,
        MalID=MAL_ID,
        Status="Active",
    )

    assert find_existing_manga_series(comic_id="md-" + MD_UUID, mangadex_id=MD_UUID, mal_id=MAL_ID) is None


def test_mangadex_add_stores_mal_id(manga_db, monkeypatch, tmp_path):
    _patch_add_side_effects(monkeypatch, tmp_path)

    result = importer.addMangaToDB("md-" + MD_UUID)

    assert result["status"] == "complete"
    row = _row(manga_db, "md-" + MD_UUID)
    assert row["MangaDexID"] == MD_UUID
    assert row["MalID"] == MAL_ID


def test_adding_mal_id_is_refused_when_mangadex_row_has_that_mal_id(manga_db, monkeypatch, tmp_path):
    _insert(
        manga_db,
        ComicID="md-" + MD_UUID,
        ComicName="One Piece",
        MangaDexID=MD_UUID,
        MalID=MAL_ID,
        Status="Active",
    )
    _patch_add_side_effects(monkeypatch, tmp_path)

    result = importer.addMangaToDB_MAL("mal-" + MAL_ID)

    assert result["status"] == "duplicate"
    assert result["comicid"] == "md-" + MD_UUID
    assert "md-" + MD_UUID in result["error"]
    assert _row(manga_db, "mal-" + MAL_ID) is None


def test_adding_mangadex_id_is_refused_when_mal_row_has_that_uuid(manga_db, monkeypatch, tmp_path):
    _insert(
        manga_db,
        ComicID="mal-" + MAL_ID,
        ComicName="One Piece",
        MangaDexID=MD_UUID,
        MalID=MAL_ID,
        Status="Active",
    )
    _patch_add_side_effects(monkeypatch, tmp_path)

    result = importer.addMangaToDB("md-" + MD_UUID)

    assert result["status"] == "duplicate"
    assert result["comicid"] == "mal-" + MAL_ID
    assert _row(manga_db, "md-" + MD_UUID) is None


def test_refreshing_an_existing_series_is_not_refused(manga_db, monkeypatch, tmp_path):
    _insert(
        manga_db,
        ComicID="md-" + MD_UUID,
        ComicName="One Piece",
        MangaDexID=MD_UUID,
        MalID=None,
        Status="Active",
        ComicLocation=str(tmp_path),
    )
    _patch_add_side_effects(monkeypatch, tmp_path)

    result = importer.addMangaToDB("md-" + MD_UUID)

    assert result["status"] == "complete"
    row = _row(manga_db, "md-" + MD_UUID)
    assert row["MalID"] == MAL_ID
    assert row["Status"] == "Active"


def test_add_manga_search_refuses_known_mal_id_without_queueing(manga_db):
    _insert(
        manga_db,
        ComicID="md-" + MD_UUID,
        ComicName="One Piece",
        MangaDexID=MD_UUID,
        MalID=MAL_ID,
        Status="Active",
    )
    ctx = SimpleNamespace(config=SimpleNamespace(MANGADEX_ENABLED=True, MAL_ENABLED=True, MAL_CLIENT_ID="client"))
    with patch("comicarr.importer.importer_thread") as mock_thread:
        result = add_manga(ctx, "mal-" + MAL_ID)

    assert result["success"] is False
    assert result["status"] == 409
    assert result["comicid"] == "md-" + MD_UUID
    mock_thread.assert_not_called()


def test_add_manga_search_refuses_known_mangadex_id_without_queueing(manga_db):
    _insert(
        manga_db,
        ComicID="mal-" + MAL_ID,
        ComicName="One Piece",
        MangaDexID=MD_UUID,
        MalID=MAL_ID,
        Status="Active",
    )
    ctx = SimpleNamespace(config=SimpleNamespace(MANGADEX_ENABLED=True, MAL_ENABLED=False, MAL_CLIENT_ID=None))
    with patch("comicarr.importer.importer_thread") as mock_thread:
        result = add_manga(ctx, "md-" + MD_UUID)

    assert result["success"] is False
    assert result["status"] == 409
    assert result["comicid"] == "mal-" + MAL_ID
    mock_thread.assert_not_called()


def test_list_library_marks_mal_id_in_library_for_mangadex_row(manga_db):
    _insert(
        manga_db,
        ComicID="md-" + MD_UUID,
        ComicName="One Piece",
        ComicYear="1997",
        MangaDexID=MD_UUID,
        MalID=MAL_ID,
        Status="Active",
    )

    library = listLibrary()

    assert "mal-" + MAL_ID in library
    assert library["mal-" + MAL_ID]["comicid"] == "md-" + MD_UUID


def test_mal_add_does_not_refuse_a_fuzzy_mangadex_title_match(manga_db, monkeypatch, tmp_path):
    """A 60% title hit is not the same work. The MAL-add guard must use
    exact mal_id / links.mal only, or a sequel already on MangaDex blocks
    adding the MAL series."""
    fuzzy_uuid = "ffffffff-eeee-dddd-cccc-sequel0001"
    _insert(
        manga_db,
        ComicID="md-" + fuzzy_uuid,
        ComicName="One Piece Sequel",
        MangaDexID=fuzzy_uuid,
        MalID=None,
        Status="Active",
    )
    _patch_add_side_effects(monkeypatch, tmp_path, mal_to_md=fuzzy_uuid)

    def fake_find(*_a, allow_title_match=True, **_k):
        return fuzzy_uuid if allow_title_match else None

    monkeypatch.setattr("comicarr.mangadex.find_by_mal_id", fake_find)

    result = importer.addMangaToDB_MAL("mal-" + MAL_ID)

    assert result["status"] == "complete"
    assert result["comicid"] == "mal-" + MAL_ID
    assert _row(manga_db, "mal-" + MAL_ID) is not None
    assert _row(manga_db, "md-" + fuzzy_uuid) is not None
