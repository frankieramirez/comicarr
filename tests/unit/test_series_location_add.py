#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import queue
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select

import comicarr
from comicarr import importer
from comicarr.app.search import service as search_service
from comicarr.app.series import service as series_service
from comicarr.tables import comics, metadata


def _config(tmp_path):
    return SimpleNamespace(
        DESTINATION_DIR=str(tmp_path / "Comics"),
        MANGA_DESTINATION_DIR=str(tmp_path / "Manga"),
        COMIC_DIR=None,
        MANGA_DIR=None,
        MULTIPLE_DEST_DIRS=None,
        NEWCOM_DIR=None,
        ADDITIONAL_LIBRARY_ROOTS=str(tmp_path / "Magazines"),
        MANGADEX_ENABLED=True,
        CREATE_FOLDERS=False,
        FOLDER_FORMAT="$Series ($Year)",
    )


@pytest.fixture
def empty_library(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    monkeypatch.setattr(comicarr.db, "get_engine", lambda: engine)
    config = _config(tmp_path)
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)
    return SimpleNamespace(engine=engine, ctx=SimpleNamespace(config=config), tmp_path=tmp_path)


def test_the_mass_add_queue_carries_a_chosen_folder_to_the_importer():
    series_queue = queue.Queue()
    series_queue.put({"comicid": "18692", "comicname": None, "location": "/srv/Magazines/Wizard"})
    series_queue.put("exit")

    with patch("comicarr.importer.addComictoDB") as add, patch("comicarr.importer.time.sleep"):
        importer.addvialist(series_queue, queue.Queue())

    add.assert_called_once_with("18692", location="/srv/Magazines/Wizard")


@pytest.mark.parametrize(
    "add",
    [
        lambda ctx, folder: series_service.add_comic(ctx, "4050-18692", folder=folder),
        lambda ctx, folder: search_service.add_comic(ctx, "18692", folder=folder),
        lambda ctx, folder: search_service.add_manga(ctx, "abc-uuid", folder=folder),
    ],
    ids=["series", "search", "search-manga"],
)
def test_every_add_command_validates_the_folder_before_queueing(empty_library, add):
    chosen = str(empty_library.tmp_path / "Magazines" / "Wizard")

    with patch("comicarr.importer.importer_thread") as thread:
        accepted = add(empty_library.ctx, chosen)
        refused = add(empty_library.ctx, str(empty_library.tmp_path / "Elsewhere" / "Wizard"))

    assert accepted["success"] is True
    assert thread.call_args_list[0].args[0][0]["location"] == chosen
    assert refused["success"] is False
    assert refused["status"] == 400
    assert "library root" in refused["error"]
    assert thread.call_count == 1


def test_an_omitted_folder_keeps_todays_add(empty_library):
    with patch("comicarr.importer.importer_thread") as thread:
        series_service.add_comic(empty_library.ctx, "18692")

    assert thread.call_args.args[0] == [{"comicid": "18692", "comicname": None, "seriesyear": None}]


def test_a_folder_for_a_series_already_in_the_library_points_at_the_series_page(empty_library):
    with empty_library.engine.begin() as conn:
        conn.execute(comics.insert(), {"ComicID": "18692", "ComicName": "Wizard"})

    with patch("comicarr.importer.importer_thread") as thread:
        result = series_service.add_comic(
            empty_library.ctx, "18692", folder=str(empty_library.tmp_path / "Magazines" / "Wizard")
        )

    assert result["success"] is False
    assert result["status"] == 409
    thread.assert_not_called()


def _mal_details():
    return {
        "name": "One Piece",
        "alt_titles": [],
        "description": "Pirates",
        "year": "1997",
        "status": "ongoing",
        "last_chapter": None,
        "author": "Oda",
        "cover_url": None,
        "url": "https://myanimelist.net/manga/13",
    }


def test_a_manga_added_to_a_chosen_folder_keeps_it_through_refresh(empty_library, monkeypatch):
    chosen = str(empty_library.tmp_path / "Magazines" / "One Piece")
    monkeypatch.setattr(comicarr, "COMICSORT", None, raising=False)
    monkeypatch.setattr("comicarr.myanimelist.get_manga_details", lambda _id: _mal_details())
    monkeypatch.setattr("comicarr.mangadex.find_by_mal_id", lambda *a, **k: None)
    monkeypatch.setattr("comicarr.config.get_manga_destination", lambda: str(empty_library.tmp_path / "Manga"))
    monkeypatch.setattr(importer.helpers, "getImage", lambda *a, **k: {"status": "failed"})
    monkeypatch.setattr(importer, "_populate_manga_chapters", lambda *a, **k: None)
    monkeypatch.setattr(importer.helpers, "ComicSort", lambda **k: None)

    importer.addMangaToDB_MAL("mal-13", location=chosen)
    importer.addMangaToDB_MAL("mal-13")

    with empty_library.engine.connect() as conn:
        row = conn.execute(select(comics).where(comics.c.ComicID == "mal-13")).mappings().one()
    assert row["ComicLocation"] == chosen
    assert row["dirlocked"] == 1
