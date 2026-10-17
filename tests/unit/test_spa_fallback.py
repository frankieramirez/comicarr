#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The SPA fallback serves index.html for client routes, never for ``/api``.

A removed or mistyped API route used to answer 200 with the SPA's HTML, so a
script calling it could not tell it was gone (ADR-0002, ADR-0003). Unknown
``/api`` paths now return the framework's JSON 404; every other path keeps the
index.html fallback and the existing cache headers.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from comicarr.app.main import CachedStaticFiles

INDEX = "<!doctype html><title>Comicarr</title>"


@pytest.fixture
def client(tmp_path):
    (tmp_path / "index.html").write_text(INDEX, encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    app = FastAPI()

    @app.get("/api/known")
    def known():
        return {"ok": True}

    app.mount("/", CachedStaticFiles(directory=str(tmp_path), html=True), name="frontend")
    return TestClient(app)


@pytest.mark.parametrize("path", ["/api/nope", "/api/activity/band", "/api/nested/deeper/path", "/api", "/api/"])
def test_unknown_api_path_is_a_json_404(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}


def test_unknown_api_post_is_not_answered_by_the_spa(client):
    response = client.post("/api/downloads/needs-attention/batch", json={})
    assert response.status_code in (404, 405)
    assert INDEX not in response.text


def test_known_api_route_is_unaffected(client):
    response = client.get("/api/known")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize("path", ["/activity/attention", "/series/42", "/apiary", "/apis/thing"])
def test_client_routes_still_fall_back_to_index(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["cache-control"] == "no-cache"


def test_root_and_assets_keep_their_cache_headers(client):
    root = client.get("/")
    assert root.status_code == 200
    assert root.text == INDEX
    assert root.headers["cache-control"] == "no-cache"

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
