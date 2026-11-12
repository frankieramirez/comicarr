#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Sign-in cover wall: opt-in, adult-free, cached covers only, no ids out."""

import random
from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.app.system import cover_wall
from comicarr.app.system import router as system_router
from comicarr.tables import comics, metadata


@pytest.fixture
def wall_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    cache = tmp_path / "cache"
    cache.mkdir()
    rows = [
        ("c1", "comic", None),
        ("c2", "comic", "Teen"),
        ("c3", "comic", "Mature 17+"),
        ("m1", "manga", "safe"),
        ("m2", "manga", "erotica"),
        ("m3", "manga", None),
        ("nocover", "comic", None),
    ]
    with engine.begin() as conn:
        conn.execute(
            insert(comics),
            [
                {"ComicID": cid, "ComicName": cid, "ContentType": kind, "AgeRating": rating}
                for cid, kind, rating in rows
            ],
        )
    for cid, _, _ in rows:
        if cid != "nocover":
            (cache / ("%s.jpg" % cid)).write_bytes(b"jpg")
    cover_wall.reset()
    yield str(cache)
    cover_wall.reset()
    db.shutdown_engine()


@pytest.mark.parametrize(
    "rating,safe",
    [
        (None, True),
        ("", True),
        ("All Ages", True),
        ("Teen", True),
        ("Mature", False),
        ("Adult", False),
        ("Explicit Content", False),
        ("pornographic", False),
        ("suggestive", False),
        ("R18+", False),
        ("M", False),
    ],
)
def test_rating_policy(rating, safe):
    assert cover_wall.is_safe_rating(rating) is safe


def test_picks_safe_cached_covers_alternating_kinds(wall_db):
    ids = cover_wall.select_covers(wall_db, rng=random.Random(1))
    assert set(ids) == {"c1", "c2", "m1", "m3"}
    kinds = ["manga" if i.startswith("m") else "comic" for i in ids]
    assert kinds == ["comic", "manga", "comic", "manga"]


def test_off_by_default_and_reports_nothing(wall_db):
    config = SimpleNamespace(CACHE_DIR=wall_db)
    ctx = SimpleNamespace(config=config)
    assert system_router.get_cover_wall(ctx=ctx) == {"enabled": False, "tiles": 0}
    assert system_router.get_cover_wall_tile(0, ctx=ctx).status_code == 404


def test_serves_tiles_by_slot_without_naming_series(wall_db):
    config = SimpleNamespace(CACHE_DIR=wall_db, LOGIN_COVER_WALL=True)
    ctx = SimpleNamespace(config=config)

    summary = system_router.get_cover_wall(ctx=ctx)
    assert summary == {"enabled": True, "tiles": 4}

    tile = system_router.get_cover_wall_tile(0, ctx=ctx)
    assert tile.path.endswith(".jpg")
    assert system_router.get_cover_wall_tile(4, ctx=ctx).status_code == 404
    assert system_router.get_cover_wall_tile(-1, ctx=ctx).status_code == 404


def test_endpoints_need_no_session():
    public = {
        route.path: route.dependencies
        for route in system_router.router.routes
        if getattr(route, "path", "").startswith("/api/auth/cover-wall")
    }
    assert set(public) == {"/api/auth/cover-wall", "/api/auth/cover-wall/{slot}"}
    assert all(not deps for deps in public.values())
