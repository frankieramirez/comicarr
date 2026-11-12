#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Sign-in "Keep me signed in": long cookie when ticked, browser session when not."""

import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from comicarr.app.core.context import get_context
from comicarr.app.core.security import COOKIE_NAME
from comicarr.app.system import router as system_router
from comicarr.app.system import service as system_service

SECRET = "x" * 64


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        system_service,
        "verify_login",
        lambda ctx, username, password, ip: {"success": True},
    )
    ctx = SimpleNamespace(
        config=SimpleNamespace(LOGIN_TIMEOUT=43800, ENABLE_HTTPS=False),
        runtime_lock=threading.Lock(),
        jwt_secret_key=SECRET,
        jwt_generation=0,
    )
    app = FastAPI()
    app.include_router(system_router.router)
    app.dependency_overrides[get_context] = lambda: ctx
    return TestClient(app)


def _login(client, **extra):
    return client.post("/api/auth/login", json={"username": "admin", "password": "pw", **extra})


def _token_minutes(response):
    token = response.cookies.get(COOKIE_NAME)
    exp = jwt.decode(token, SECRET, algorithms=["HS256"])["exp"]
    return (exp - datetime.now(tz=timezone.utc).timestamp()) / 60


def test_remembered_by_default_for_the_configured_timeout(client):
    response = _login(client)
    assert response.status_code == 200
    assert "Max-Age=2628000" in response.headers["set-cookie"]
    assert _token_minutes(response) == pytest.approx(43800, abs=2)


def test_ticked_box_keeps_the_long_session(client):
    response = _login(client, remember=True)
    assert "Max-Age=2628000" in response.headers["set-cookie"]


def test_unticked_box_gives_a_browser_session_capped_at_twelve_hours(client):
    response = _login(client, remember=False)
    assert response.status_code == 200
    assert "Max-Age" not in response.headers["set-cookie"]
    assert _token_minutes(response) == pytest.approx(system_router.SHORT_SESSION_MINUTES, abs=2)
