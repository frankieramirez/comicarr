#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Series API covers are same-origin, never a MangaDex hotlink."""

from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.app.series import queries as series_queries
from comicarr.app.series import service as series_service
from comicarr.tables import comics, metadata

MANGADEX_COVER = "https://uploads.mangadex.org/covers/uuid/cover.jpg"
MAL_COVER = "https://cdn.myanimelist.net/images/manga/2/253146l.jpg"


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


def _seed_manga(engine):
    with engine.begin() as conn:
        conn.execute(
            insert(comics),
            [
                {
                    "ComicID": "md-onepiece",
                    "ComicName": "One Piece",
                    "ComicSortName": "One Piece",
                    "ComicYear": "1997",
                    "Status": "Active",
                    "Have": 0,
                    "Total": 1100,
                    "ContentType": "manga",
                    "ComicImage": "cache/md-onepiece.jpg",
                    "ComicImageURL": MANGADEX_COVER,
                },
                {
                    "ComicID": "mal-13",
                    "ComicName": "One Piece",
                    "ComicSortName": "One Piece MAL",
                    "ComicYear": "1997",
                    "Status": "Active",
                    "Have": 0,
                    "Total": 1100,
                    "ContentType": "manga",
                    "ComicImage": "cache/mal-13.jpg",
                    "ComicImageURL": MAL_COVER,
                },
            ],
        )


def test_library_cover_src_is_same_origin_art_path():
    assert series_queries.library_cover_src("md-onepiece") == "/api/metadata/art/md-onepiece"
    assert series_queries.library_cover_src("mal-13") == "/api/metadata/art/mal-13"
    assert series_queries.library_cover_src(None) is None
    assert series_queries.library_cover_src("") is None


def test_with_library_cover_src_drops_provider_cdn():
    row = series_queries.with_library_cover_src(
        {
            "ComicID": "md-onepiece",
            "ComicImage": MANGADEX_COVER,
            "ComicImageURL": MANGADEX_COVER,
        }
    )
    assert row["ComicImage"] == "/api/metadata/art/md-onepiece"
    assert "uploads.mangadex.org" not in row["ComicImage"]
    assert row["ComicImageURL"] == MANGADEX_COVER


def test_query_projection_keeps_cached_path_and_external_url(query_db):
    _seed_manga(query_db)

    md = series_queries.get_comic("md-onepiece")[0]
    assert md["ComicImage"] == "cache/md-onepiece.jpg"
    assert md["ComicImageURL"] == MANGADEX_COVER
    assert md["ComicImage"] != md["ComicImageURL"]

    mal = series_queries.get_comic("mal-13")[0]
    assert mal["ComicImage"] == "cache/mal-13.jpg"
    assert mal["ComicImageURL"] == MAL_COVER


def test_series_api_comicimage_is_art_proxy_not_mangadex(query_db):
    _seed_manga(query_db)
    ctx = SimpleNamespace(config=SimpleNamespace(ANNUALS_ON=False))

    listed = series_service.list_comics(ctx)
    by_id = {row["ComicID"]: row for row in listed}
    assert by_id["md-onepiece"]["ComicImage"] == series_queries.library_cover_src("md-onepiece")
    assert by_id["mal-13"]["ComicImage"] == series_queries.library_cover_src("mal-13")
    assert "uploads.mangadex.org" not in by_id["md-onepiece"]["ComicImage"]
    assert by_id["md-onepiece"]["ComicImageURL"] == MANGADEX_COVER

    paged = series_service.list_comics(ctx, limit=10, offset=0)
    paged_by_id = {row["ComicID"]: row for row in paged["comics"]}
    assert paged_by_id["md-onepiece"]["ComicImage"] == "/api/metadata/art/md-onepiece"

    detail = series_service.get_comic_detail(ctx, "md-onepiece")
    comic = detail["comic"][0]
    assert comic["ComicImage"] == "/api/metadata/art/md-onepiece"
    assert "uploads.mangadex.org" not in comic["ComicImage"]
    assert comic["ComicImageURL"] == MANGADEX_COVER

    mal_detail = series_service.get_comic_detail(ctx, "mal-13")
    assert mal_detail["comic"][0]["ComicImage"] == "/api/metadata/art/mal-13"
