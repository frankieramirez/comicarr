#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comicarr import series_kind
from comicarr.app.common import library_roots
from comicarr.app.series import location as series_location
from comicarr.app.series import service as series_service


def _series(**overrides):
    values = {
        "ComicID": "4050-1",
        "ComicName": "Wizard: The Comics Magazine",
        "ComicLocation": "/comics/Wizard The Comics Magazine (1991)",
        "ContentType": "comic",
        "dirlocked": 0,
    }
    values.update(overrides)
    return values


def _run(monkeypatch, existing, dest="/magazines", relocated="/magazines/Wizard The Comics Magazine (1991)"):
    update = MagicMock()
    relocate = MagicMock(return_value={"comic_location": relocated})
    rows = iter([existing, dict(existing, ContentType="magazine", ComicLocation=relocated)])
    monkeypatch.setattr(series_service, "_magazine_destination", lambda: dest)
    monkeypatch.setattr(series_service.series_queries, "get_comic_content_kind", lambda _comic_id: next(rows))
    monkeypatch.setattr(series_service.series_queries, "update_comic_content_kind", update)
    monkeypatch.setattr(series_service.series_locations, "change_series_location", relocate)
    ctx = SimpleNamespace()
    result = series_service.update_content_kind(ctx, existing["ComicID"], "magazine")
    return update, relocate, ctx, result


def test_magazine_is_a_comic_for_acquisition():
    series = _series(ContentType="magazine", ContentKindSetBy="operator")

    assert series_kind.is_magazine(series)
    assert not series_kind.is_manga(series)
    assert not series_kind.is_magazine(_series())


def test_cataloging_as_magazine_moves_to_the_automatic_folder_keeping_files_readable(monkeypatch):
    update, relocate, ctx, result = _run(monkeypatch, _series())

    update.assert_called_once_with("4050-1", "magazine", set_by="operator")
    relocate.assert_called_once_with(ctx, "4050-1", None, move_files=False)
    assert result["location_repointed"] is True
    assert result["comic_location"] == "/magazines/Wizard The Comics Magazine (1991)"
    assert result["previous_location"] == "/comics/Wizard The Comics Magazine (1991)"


@pytest.mark.parametrize(
    "existing, dest",
    [
        (_series(dirlocked=1), "/magazines"),
        (_series(ComicLocation="/magazines/Wizard (1991)"), "/magazines"),
        (_series(), None),
    ],
    ids=["operator-folder", "already-under-root", "no-magazine-root"],
)
def test_cataloging_as_magazine_keeps_the_folder(monkeypatch, existing, dest):
    update, relocate, _ctx, result = _run(monkeypatch, existing, dest, relocated=existing["ComicLocation"])

    update.assert_called_once_with("4050-1", "magazine", set_by="operator")
    relocate.assert_not_called()
    assert result["location_repointed"] is False


def test_a_refused_move_still_catalogs_the_series(monkeypatch):
    monkeypatch.setattr(series_service.logger, "warn", MagicMock())
    refused = MagicMock(side_effect=series_service.series_locations.SeriesLocationError("overlaps"))
    rows = iter([_series(), _series(ContentType="magazine")])
    update = MagicMock()
    monkeypatch.setattr(series_service, "_magazine_destination", lambda: "/magazines")
    monkeypatch.setattr(series_service.series_queries, "get_comic_content_kind", lambda _comic_id: next(rows))
    monkeypatch.setattr(series_service.series_queries, "update_comic_content_kind", update)
    monkeypatch.setattr(series_service.series_locations, "change_series_location", refused)

    result = series_service.update_content_kind(SimpleNamespace(), "4050-1", "magazine")

    update.assert_called_once_with("4050-1", "magazine", set_by="operator")
    assert result["content_type"] == "magazine"
    assert result["location_repointed"] is False


def test_default_folder_for_a_magazine_is_under_the_magazine_root(monkeypatch):
    from comicarr import filers

    class FakeHandlers:
        def __init__(self, comic):
            self.comic = comic

        def folder_create(self):
            return {"comlocation": "/comics/Nintendo Power (1988)"}

    monkeypatch.setattr(filers, "FileHandlers", FakeHandlers)
    monkeypatch.setattr(series_service, "_magazine_destination", lambda: "/magazines")

    magazine = _series(ComicName="Nintendo Power", ContentType="magazine")
    comic = _series(ComicName="Nintendo Power")

    assert series_location.default_series_location(magazine) == "/magazines/Nintendo Power (1988)"
    assert series_location.default_series_location(comic) == "/comics/Nintendo Power (1988)"


def test_magazine_root_is_a_library_root():
    config = SimpleNamespace(DESTINATION_DIR="/comics", MAGAZINE_DESTINATION_DIR="/magazines")

    assert "/magazines" in library_roots.configured_library_roots(config)
