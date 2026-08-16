#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""add-manga hands off to the mass-add thread instead of blocking the HTTP request."""

import queue
from types import SimpleNamespace
from unittest.mock import patch

from comicarr import importer
from comicarr.app.search.service import add_manga
from comicarr.importer import addvialist


def test_add_manga_queues_prefixed_mangadex_id_and_returns_immediately():
    ctx = SimpleNamespace(config=SimpleNamespace(MANGADEX_ENABLED=True, MAL_ENABLED=False, MAL_CLIENT_ID=None))
    with patch("comicarr.importer.importer_thread") as mock_thread:
        result = add_manga(ctx, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    assert result["success"] is True
    assert "queued" in result["message"].lower()
    assert result["comicid"] == "md-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    mock_thread.assert_called_once_with(
        [{"comicid": "md-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "comicname": None, "seriesyear": None}]
    )


def test_add_manga_keeps_mal_prefix_and_does_not_call_add_on_the_request_thread():
    ctx = SimpleNamespace(config=SimpleNamespace(MANGADEX_ENABLED=False, MAL_ENABLED=True, MAL_CLIENT_ID="client"))
    with (
        patch("comicarr.importer.importer_thread") as mock_thread,
        patch("comicarr.importer.addMangaToDB_MAL") as add_mal,
        patch("comicarr.importer.addMangaToDB") as add_md,
    ):
        result = add_manga(ctx, "mal-13")

    assert result["success"] is True
    assert result["comicid"] == "mal-13"
    mock_thread.assert_called_once_with([{"comicid": "mal-13", "comicname": None, "seriesyear": None}])
    add_mal.assert_not_called()
    add_md.assert_not_called()


def test_add_manga_does_not_queue_when_manga_integration_is_off():
    ctx = SimpleNamespace(config=SimpleNamespace(MANGADEX_ENABLED=False, MAL_ENABLED=False, MAL_CLIENT_ID=None))
    with patch("comicarr.importer.importer_thread") as mock_thread:
        result = add_manga(ctx, "md-abc")

    assert result["success"] is False
    mock_thread.assert_not_called()


def test_addvialist_narrates_add_failed_when_importer_raises():
    series_queue = queue.Queue()
    issue_queue = queue.Queue()
    series_queue.put({"comicid": "md-onepiece", "comicname": "One Piece"})
    series_queue.put("exit")

    with (
        patch("comicarr.importer.addComictoDB", side_effect=RuntimeError("rate limited")),
        patch("comicarr.importer.time.sleep"),
        patch.object(importer, "_emit_add_activity") as emit,
    ):
        addvialist(series_queue, issue_queue)

    emit.assert_called_once_with("failed", "md-onepiece", comicname="One Piece", reason_detail="rate limited")


def test_emit_add_activity_drives_the_series_activity_facade():
    with patch("comicarr.app.activity.producers.emit_series_activity") as emit:
        importer._emit_add_activity("failed", "md-onepiece", comicname="One Piece", reason_detail="boom")

    emit.assert_called_once_with(
        "add",
        "failed",
        "md-onepiece",
        comicname="One Piece",
        reason_code="import_failed",
        reason_detail="boom",
    )
