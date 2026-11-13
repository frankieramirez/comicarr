#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The library scan progress routes return the scanner's own progress payload (#1201)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from comicarr import comicsync, mangasync
from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import require_session
from comicarr.app.series.router import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "operator"
    app.dependency_overrides[get_context] = lambda: AppContext(config=None)
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("path", "module", "prefix"),
    [
        ("/api/import/manga/progress", mangasync, "MANGA"),
        ("/api/import/comic/progress", comicsync, "COMIC"),
    ],
)
def test_scan_progress_route_returns_scanner_state(client, monkeypatch, path, module, prefix):
    monkeypatch.setattr(module, prefix + "_SCAN_STATUS", "scanning")
    monkeypatch.setattr(module, prefix + "_SCAN_PROGRESS", {"current": 2, "total": 5})
    monkeypatch.setattr(module, prefix + "_SCAN_ID", "scan-1")
    monkeypatch.setattr(module, prefix + "_SCAN_RESULTS", [])

    response = client.get(path)

    assert response.status_code == 200
    assert response.json() == {
        "status": "scanning",
        "progress": {"current": 2, "total": 5},
        "scan_id": "scan-1",
        "results": [],
    }
