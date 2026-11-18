#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import importlib
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comicarr.app.core import runtime
from comicarr.app.series import service


@pytest.mark.parametrize(
    ("scan", "config_key", "path", "error"),
    [
        (service.comic_library_scan, "COMIC_DIR", "/missing/comics", "Comic folder not found"),
        (service.manga_library_scan, "MANGA_DIR", "/missing/manga", "Manga folder not found"),
    ],
)
def test_library_scan_rejects_missing_mount(monkeypatch, scan, config_key, path, error):
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(**{config_key: path}))
    monkeypatch.setattr(service.os.path, "isdir", MagicMock(return_value=False))
    start_background_thread = MagicMock()
    monkeypatch.setattr(service, "start_background_thread", start_background_thread)

    result = scan(SimpleNamespace(background_workers=MagicMock()))

    assert result["success"] is False
    assert error in result["error"]
    start_background_thread.assert_not_called()


@pytest.mark.parametrize(
    ("scan", "scanner", "config_key", "path", "status_attr", "lock_attr"),
    [
        (
            service.comic_library_scan,
            "comicarr.app.series.comicsync",
            "COMIC_DIR",
            "/library/comics",
            "COMIC_SCAN_STATUS",
            "_SCAN_LOCK",
        ),
        (
            service.manga_library_scan,
            "comicarr.app.manga.mangasync",
            "MANGA_DIR",
            "/library/manga",
            "MANGA_SCAN_STATUS",
            "_SCAN_LOCK",
        ),
    ],
)
def test_library_scan_rejects_duplicate_request_before_starting_another_worker(
    monkeypatch, scan, scanner, config_key, path, status_attr, lock_attr
):
    scanner_module = importlib.import_module(scanner)
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(**{config_key: path}))
    monkeypatch.setattr(service.os.path, "isdir", MagicMock(return_value=True))
    monkeypatch.setattr(scanner_module, status_attr, None)
    monkeypatch.setattr(scanner_module, lock_attr, threading.Lock())
    start_background_thread = MagicMock()
    monkeypatch.setattr(service, "start_background_thread", start_background_thread)
    ctx = SimpleNamespace(background_workers=MagicMock())

    first = scan(ctx)
    duplicate = scan(ctx)

    assert first["success"] is True
    assert duplicate == {"success": False, "error": "A library scan is already in progress"}
    start_background_thread.assert_called_once()
