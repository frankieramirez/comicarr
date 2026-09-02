#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""HTTP-boundary tests for the per-series content-kind contract."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comicarr.app.series import router as series_router


def _response_body(response):
    return json.loads(response.body)


@pytest.mark.parametrize(
    "request_body",
    [
        None,
        {},
        {"content_type": None},
        {"content_type": 1},
        {"content_type": True},
        {"content_type": "Comic"},
        {"content_type": " manga "},
        {"content_type": "print"},
    ],
)
def test_content_kind_route_rejects_every_value_outside_strict_wire_enum(monkeypatch, request_body):
    update = MagicMock()
    monkeypatch.setattr(series_router.series_service, "update_content_kind", update)

    response = series_router.update_series_content_kind("160294", request_body, SimpleNamespace())

    assert response.status_code == 400
    assert _response_body(response) == {"detail": "content_type must be one of: comic, manga"}
    update.assert_not_called()


@pytest.mark.parametrize("content_type", ["comic", "manga"])
def test_content_kind_route_accepts_enum_and_returns_service_result(monkeypatch, content_type):
    update = MagicMock(return_value={"success": True, "content_type": content_type})
    monkeypatch.setattr(series_router.series_service, "update_content_kind", update)
    ctx = SimpleNamespace()

    response = series_router.update_series_content_kind("160294", {"content_type": content_type}, ctx)

    assert response == {"success": True, "content_type": content_type}
    update.assert_called_once_with(ctx, "160294", content_type)


def test_content_kind_route_returns_repointed_location_from_service(monkeypatch):
    update = MagicMock(
        return_value={
            "success": True,
            "content_type": "manga",
            "location_repointed": True,
            "comic_location": "/manga/Berserk",
            "previous_location": "/comics/Berserk (2003)",
        }
    )
    monkeypatch.setattr(series_router.series_service, "update_content_kind", update)

    response = series_router.update_series_content_kind("160294", {"content_type": "manga"}, SimpleNamespace())

    assert response == {
        "success": True,
        "content_type": "manga",
        "location_repointed": True,
        "comic_location": "/manga/Berserk",
        "previous_location": "/comics/Berserk (2003)",
    }


def test_content_kind_route_maps_unknown_series_to_404(monkeypatch):
    monkeypatch.setattr(
        series_router.series_service,
        "update_content_kind",
        lambda *_args: {"success": False, "error": "ComicID missing not found in watchlist"},
    )

    response = series_router.update_series_content_kind("missing", {"content_type": "manga"}, SimpleNamespace())

    assert response.status_code == 404
    assert _response_body(response) == {"detail": "ComicID missing not found in watchlist"}
