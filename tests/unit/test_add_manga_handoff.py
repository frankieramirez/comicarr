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

from comicarr.app.search.service import add_manga
from comicarr.app.series import add_activity, add_workers
from comicarr.app.series.add_workers import run_mass_add_queue


def test_add_manga_queues_prefixed_mangadex_id_and_returns_immediately():
    ctx = SimpleNamespace(config=SimpleNamespace(MANGADEX_ENABLED=True, MAL_ENABLED=False, MAL_CLIENT_ID=None))
    with (
        patch("comicarr.app.series.add_workers.queue_series_adds") as mock_thread,
        patch("comicarr.app.manga.mangadex.get_manga_details", return_value=None),
    ):
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
        patch("comicarr.app.series.add_workers.queue_series_adds") as mock_thread,
        patch("comicarr.app.manga.add.add_myanimelist") as add_mal,
        patch("comicarr.app.manga.add.add_mangadex") as add_md,
    ):
        result = add_manga(ctx, "mal-13")

    assert result["success"] is True
    assert result["comicid"] == "mal-13"
    mock_thread.assert_called_once_with([{"comicid": "mal-13", "comicname": None, "seriesyear": None}])
    add_mal.assert_not_called()
    add_md.assert_not_called()


def test_add_manga_does_not_queue_when_manga_integration_is_off():
    ctx = SimpleNamespace(config=SimpleNamespace(MANGADEX_ENABLED=False, MAL_ENABLED=False, MAL_CLIENT_ID=None))
    with patch("comicarr.app.series.add_workers.queue_series_adds") as mock_thread:
        result = add_manga(ctx, "md-abc")

    assert result["success"] is False
    mock_thread.assert_not_called()


def test_addvialist_narrates_add_failed_when_importer_raises():
    series_queue = queue.Queue()
    issue_queue = queue.Queue()
    series_queue.put({"comicid": "md-onepiece", "comicname": "One Piece"})
    series_queue.put("exit")

    with (
        patch("comicarr.app.series.comic_add.add_comic", side_effect=RuntimeError("rate limited")),
        patch("comicarr.app.series.add_workers.time.sleep"),
        patch.object(add_workers, "emit_add_activity") as emit,
    ):
        run_mass_add_queue(series_queue, issue_queue)

    emit.assert_called_once_with("failed", "md-onepiece", comicname="One Piece", reason_detail="rate limited")


def test_emit_add_activity_drives_the_series_activity_facade():
    with patch("comicarr.app.activity.producers.emit_series_activity") as emit:
        add_activity.emit_add_activity("failed", "md-onepiece", comicname="One Piece", reason_detail="boom")

    emit.assert_called_once_with(
        "add",
        "failed",
        "md-onepiece",
        comicname="One Piece",
        reason_code="import_failed",
        reason_detail="boom",
    )
