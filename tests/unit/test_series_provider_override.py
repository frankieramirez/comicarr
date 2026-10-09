#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""A Series' search provider override persists through the Series API (#1063)."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.app.core.context import AppContext
from comicarr.app.series import router as series_router
from comicarr.app.series import service as series_service
from comicarr.tables import comics, metadata


@pytest.fixture
def query_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(comics), [{"ComicID": "wizard", "ComicName": "Wizard", "Status": "Active"}])
    yield engine
    db.shutdown_engine()


def _ctx():
    return AppContext(
        config=SimpleNamespace(
            ENABLE_DDL=True,
            ENABLE_GETCOMICS=True,
            ENABLE_TORRENT_SEARCH=True,
            ENABLE_TORZNAB=True,
            EXTRA_TORZNABS=[["MagIndex", "https://mag.test/api", "1", "mag-secret", "5070", "1", 1]],
            PROVIDER_ORDER={"0": "DDL(GetComics)", "1": "MagIndex"},
            ANNUALS_ON=False,
        )
    )


def test_override_survives_a_restart_and_appears_on_the_series_detail(query_db):
    result = series_service.update_provider_override(
        _ctx(), "wizard", [" MagIndex ", "MagIndex"], ["DDL(GetComics)"]
    )
    assert result == {"success": True, "provider_override": {"order": ["MagIndex"], "exclude": ["DDL(GetComics)"]}}

    db.shutdown_engine()

    detail = series_service.get_comic_detail(_ctx(), "wizard")
    assert detail["searchProviders"] == {
        "available": ["DDL(GetComics)", "MagIndex"],
        "override": {"order": ["MagIndex"], "exclude": ["DDL(GetComics)"]},
    }
    assert "mag-secret" not in json.dumps(detail["searchProviders"])


def test_two_empty_lists_clear_the_override(query_db):
    series_service.update_provider_override(_ctx(), "wizard", ["MagIndex"], [])

    result = series_service.update_provider_override(_ctx(), "wizard", [], [])

    assert result == {"success": True, "provider_override": None}
    assert series_service.get_comic_detail(_ctx(), "wizard")["searchProviders"]["override"] is None


def test_unknown_series_is_a_404(query_db):
    response = series_router.update_series_search_providers("missing", {"order": ["MagIndex"]}, _ctx())

    assert response.status_code == 404


@pytest.mark.parametrize("body", ({"order": "MagIndex"}, {"exclude": [1]}, {"order": None}))
def test_names_must_be_lists_of_strings(query_db, body):
    response = series_router.update_series_search_providers("wizard", body, _ctx())

    assert response.status_code == 400
