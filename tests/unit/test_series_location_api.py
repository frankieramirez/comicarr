#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comicarr.app.series import location as series_location
from comicarr.app.series import router as series_router


def _body(response):
    return json.loads(response.body)


@pytest.mark.parametrize(
    ("request_body", "detail"),
    [
        (None, "Provide folder: a server path, or null for the automatic folder"),
        ({}, "Provide folder: a server path, or null for the automatic folder"),
        ({"folder": 7}, "folder must be a server path or null"),
        ({"folder": "/m/Wizard", "move_files": "yes"}, "move_files must be a boolean"),
    ],
)
def test_location_route_rejects_malformed_requests(monkeypatch, request_body, detail):
    change = MagicMock()
    monkeypatch.setattr(series_router.series_locations, "change_series_location", change)

    response = series_router.update_series_location("18692", request_body, SimpleNamespace())

    assert response.status_code == 400
    assert _body(response) == {"detail": detail}
    change.assert_not_called()


def test_location_route_passes_folder_and_move_choice_and_returns_the_report(monkeypatch):
    report = {"success": True, "comic_location": "/m/Wizard", "files_moved": 2}
    change = MagicMock(return_value=report)
    monkeypatch.setattr(series_router.series_locations, "change_series_location", change)
    ctx = SimpleNamespace()

    response = series_router.update_series_location("18692", {"folder": "/m/Wizard", "move_files": True}, ctx)

    assert response == report
    change.assert_called_once_with(ctx, "18692", "/m/Wizard", move_files=True)


def test_location_route_clears_the_override_with_null(monkeypatch):
    change = MagicMock(return_value={"success": True})
    monkeypatch.setattr(series_router.series_locations, "change_series_location", change)
    ctx = SimpleNamespace()

    series_router.update_series_location("18692", {"folder": None}, ctx)

    change.assert_called_once_with(ctx, "18692", None, move_files=False)


@pytest.mark.parametrize("status", [400, 404, 409])
def test_location_route_maps_refusals_to_their_status(monkeypatch, status):
    refusal = series_location.SeriesLocationError("refused", status=status)
    monkeypatch.setattr(series_router.series_locations, "change_series_location", MagicMock(side_effect=refusal))

    response = series_router.update_series_location("18692", {"folder": "/m/Wizard"}, SimpleNamespace())

    assert response.status_code == status
    assert _body(response) == {"detail": "refused"}


def test_a_partial_move_is_a_server_error_that_still_reports_what_moved(monkeypatch):
    report = {"success": False, "error": "Moved 1 of 2 files", "files_moved": 1, "files_left": 1}
    monkeypatch.setattr(series_router.series_locations, "change_series_location", MagicMock(return_value=report))

    response = series_router.update_series_location("18692", {"folder": "/m/Wizard", "move_files": True}, None)

    assert response.status_code == 500
    assert _body(response)["detail"] == "Moved 1 of 2 files"
    assert _body(response)["files_moved"] == 1
    assert _body(response)["files_left"] == 1
