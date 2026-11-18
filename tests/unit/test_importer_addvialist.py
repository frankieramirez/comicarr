#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Tests for add_workers.run_mass_add_queue — mass-add queue handling.
"""

import queue
from unittest.mock import MagicMock, patch

import comicarr
from comicarr.app.core import runtime
from comicarr.app.core.context import AppContext
from comicarr.app.series import add_workers, comic_add
from comicarr.app.series.add_workers import run_mass_add_queue


def _run_single_item(series_queue, issue_queue, item):
    """Process one queue item then exit the addvialist loop."""
    series_queue.put(item)
    series_queue.put("exit")

    with patch("comicarr.app.series.comic_add.add_comic") as mock_add:
        with patch("comicarr.app.series.add_workers.time.sleep"):
            with patch.object(runtime.current(), "add_list", queue.Queue()):
                run_mass_add_queue(series_queue, issue_queue)

    return mock_add


class TestAddvialistSeriesyear:
    def test_comicid_only_without_seriesyear(self):
        series_queue = queue.Queue()
        issue_queue = queue.Queue()
        item = {"comicid": "12345", "comicname": None}

        mock_add = _run_single_item(series_queue, issue_queue, item)

        mock_add.assert_called_once_with("12345")

    def test_comicname_without_seriesyear_key(self):
        series_queue = queue.Queue()
        issue_queue = queue.Queue()
        item = {"comicid": "12345", "comicname": "Spider-Man"}

        mock_add = _run_single_item(series_queue, issue_queue, item)

        mock_add.assert_called_once_with("12345")

    def test_comicname_with_seriesyear(self):
        """In-flight mass-add narrates nothing per item (#484); seriesyear is passed through."""
        series_queue = queue.Queue()
        issue_queue = queue.Queue()
        item = {"comicid": "12345", "comicname": "Spider-Man", "seriesyear": "2020"}

        mock_add = _run_single_item(series_queue, issue_queue, item)

        mock_add.assert_called_once_with("12345")
        assert item["seriesyear"] == "2020"


class TestAddComicPayloads:
    def test_search_service_includes_seriesyear(self):
        from unittest.mock import MagicMock, patch

        from comicarr.app.search.service import add_comic

        ctx = MagicMock()
        with patch("comicarr.app.series.add_workers.queue_series_adds") as mock_thread:
            result = add_comic(ctx, "4050-99999")

        assert result["success"] is True
        mock_thread.assert_called_once_with([{"comicid": "4050-99999", "comicname": None, "seriesyear": None}])

    def test_series_service_includes_seriesyear(self):
        from unittest.mock import MagicMock, patch

        from comicarr.app.series.service import add_comic

        ctx = MagicMock()
        with patch("comicarr.app.series.add_workers.queue_series_adds") as mock_thread:
            result = add_comic(ctx, "4050-12345")

        assert result["success"] is True
        mock_thread.assert_called_once_with([{"comicid": "12345", "comicname": None, "seriesyear": None}])


def test_importer_thread_projects_mass_add_pool_to_canonical_runtime(monkeypatch):
    """The DB-writing MASS_ADD thread must share the lifecycle-owned pool reference."""
    ctx = AppContext()
    pool = MagicMock(name="mass_add_pool")
    monkeypatch.setattr(runtime, "_runtime", ctx)
    monkeypatch.setattr(comicarr, "MASS_ADD", None)
    monkeypatch.setattr(add_workers.threading, "Thread", MagicMock(return_value=pool))

    add_workers.queue_series_adds([{"comicid": "12345", "comicname": None}])

    assert ctx.mass_add_pool is pool
    assert comicarr.MASS_ADD is pool
    assert ctx.add_list.get_nowait() == {"comicid": "12345", "comicname": None}
    pool.start.assert_called_once()


def test_refresh_worker_projects_pool_to_canonical_runtime(monkeypatch):
    """The on-demand refresh worker must share the lifecycle-owned pool and queue."""
    ctx = AppContext()
    pool = MagicMock(name="mass_refresh_pool")
    thread = MagicMock(return_value=pool)
    monkeypatch.setattr(runtime, "_runtime", ctx)
    monkeypatch.setattr(comicarr, "MASS_REFRESH", None)
    monkeypatch.setattr(add_workers.threading, "Thread", thread)

    assert add_workers._start_refresh_worker() is True

    assert ctx.mass_refresh_pool is pool
    assert comicarr.MASS_REFRESH is pool
    thread.assert_called_once_with(
        target=add_workers.watchlist_refresh.run_refresh_queue, args=(ctx.refresh_queue,), name="mass-refresh"
    )
    pool.start.assert_called_once()

    monkeypatch.setattr(add_workers.threading, "current_thread", lambda: pool)
    assert add_workers.refresh_worker_should_retire(ctx.refresh_queue) is True
    assert ctx.mass_refresh_pool is None
    assert comicarr.MASS_REFRESH is None


def test_add_queued_while_mass_add_worker_retires_still_runs(monkeypatch):
    """#1322: an add that lands as the idle worker retires gets a worker of its own."""
    import threading

    ctx = AppContext()
    monkeypatch.setattr(runtime, "_runtime", ctx)
    # set_runtime_field mirrors the pool onto the legacy global; restore it.
    monkeypatch.setattr(comicarr, "MASS_ADD", None)
    monkeypatch.setattr(add_workers.time, "sleep", lambda *_: None)
    added = []
    done = threading.Event()

    def fake_add(comicid, **_kwargs):
        added.append(comicid)
        done.set()

    monkeypatch.setattr(comic_add, "add_comic", fake_add)

    producer = {}
    real_empty = ctx.add_list.empty

    def empty_with_racing_producer():
        # The worker is inside its retirement check, holding the worker lock.
        # A producer queues an add right now; it must wait for the decision.
        if "thread" not in producer:
            producer["thread"] = threading.Thread(
                target=add_workers.queue_series_adds, args=([{"comicid": "777", "comicname": None}],)
            )
            producer["thread"].start()
            producer["thread"].join(timeout=0.2)
            assert producer["thread"].is_alive(), "producer must block on the worker lock"
        return real_empty()

    monkeypatch.setattr(ctx.add_list, "empty", empty_with_racing_producer)

    first = threading.Thread(target=add_workers.run_mass_add_queue, args=(ctx.add_list, ctx.issue_watch_list))
    add_workers._set_mass_add_pool(ctx, first)
    first.start()
    first.join(timeout=5)
    producer["thread"].join(timeout=5)

    assert not first.is_alive()
    assert done.wait(timeout=5), "the add queued during retirement never ran"
    assert added == ["777"]
    second = ctx.mass_add_pool
    if second is not None:
        second.join(timeout=5)


def test_mass_add_worker_does_not_retire_while_work_is_queued(monkeypatch):
    ctx = AppContext()
    monkeypatch.setattr(runtime, "_runtime", ctx)
    monkeypatch.setattr(comicarr, "MASS_ADD", None)
    sentinel = MagicMock(name="other_worker")
    add_workers._set_mass_add_pool(ctx, sentinel)

    ctx.issue_watch_list.put("i1")
    assert add_workers.mass_add_worker_should_retire(ctx.add_list, ctx.issue_watch_list) is False
    ctx.issue_watch_list.get_nowait()

    # Retiring from a thread that is not the published worker leaves it alone.
    assert add_workers.mass_add_worker_should_retire(ctx.add_list, ctx.issue_watch_list) is True
    assert ctx.mass_add_pool is sentinel
