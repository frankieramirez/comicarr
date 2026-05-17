#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""U7 — Single ordered clean-shutdown drain (FastAPI lifespan authoritative).

Characterization-first: the first test class pins the *post-collapse* contract
that the FastAPI lifespan is the single authoritative ordered drain. The legacy
pre-collapse topology was:

    SIGTERM -> handler_sigterm sets comicarr.SIGNAL='shutdown'
            -> uvicorn/lifespan shutdown runs:
                 scheduler.shutdown(wait=False)
                 q.put('exit') for all 5 queues  (NO join)
                 ai/cv client close
                 engine.dispose()                 (main.py:203)
                 executor.shutdown(wait=False)     (main.py:209)
                 if not comicarr.SIGNAL: SIGNAL='shutdown'
            -> uvicorn.run() returns
            -> main thread (Comicarr.py:574-579) -> comicarr.shutdown()
                 -> halt(): SCHED.shutdown(wait=False)
                            queue_schedule('all','shutdown')
                              -> per pool: queue.put('exit'); pool.join(5)
                              -> except AssertionError: os._exit(0)  (LANDMINE)
                 -> pidfile removal
                 -> terminal os.execv (restart) / os._exit(0) (shutdown)

The defect: ``engine.dispose()`` ran in the lifespan *before* any worker join
(which only happened later, in ``halt()`` / ``queue_schedule``). An in-flight
worker journal write could therefore hit a disposed engine, and the
``except AssertionError: os._exit(0)`` short-circuited past the terminal
``os.execv``, degrading a restart to a plain stop.

Post-U7 the lifespan owns the single ordered sequence:
  1. scheduler.shutdown(wait=False)               (stop new pipeline work)
  2. q.put('exit') for all 5 queues               (stop intake)
  3. bounded pool.join, OFF the event loop, on a DEDICATED executor
     (final journal flush == workers fully drained)
  4. ai/cv client close
  5. engine.dispose()                             (AFTER the drain)
  6. executor.shutdown / drain-executor shutdown  (AFTER the drain)
  7. if not comicarr.SIGNAL: SIGNAL='shutdown'

``halt()`` is reduced to idempotent SIGNAL signalling only; ``shutdown()``
keeps the pidfile removal + terminal os.execv/os._exit branch plus a single
unconditional, non-blocking hard-kill backstop. The
``except AssertionError: os._exit(0)`` landmine is removed from
``queue_schedule``.
"""

import ast
import asyncio
import inspect
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

import comicarr
from comicarr.app.core.context import AppContext
from comicarr.app.downloads import journal
from comicarr.app.main import lifespan
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import metadata, pipeline_journal

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_signal():
    """comicarr.SIGNAL is process-global; isolate every test."""
    saved = comicarr.SIGNAL
    comicarr.SIGNAL = None
    yield
    comicarr.SIGNAL = saved


@pytest.fixture
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    if not hasattr(comicarr, "LOG_LEVEL") or comicarr.LOG_LEVEL is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    engine = get_engine()
    metadata.create_all(engine)
    yield
    shutdown_engine()


def _make_ctx(scheduler=None):
    """Minimal AppContext for driving the lifespan shutdown half.

    Real queue.Queue objects so ``q.put('exit')`` works; the scheduler and
    clients are mocks.
    """
    import queue as _q

    ctx = AppContext(
        scheduler=scheduler,
        snatched_queue=_q.Queue(),
        nzb_queue=_q.Queue(),
        pp_queue=_q.Queue(),
        search_queue=_q.Queue(),
        ddl_queue=_q.Queue(),
    )
    ctx.ai_async_client = None
    ctx.cv_session = None
    return ctx


class _FakePool:
    """Stand-in for a worker thread pool exposing is_alive()/join()."""

    def __init__(self, drain_after=0.0, never_joins=False, raise_assertion=False):
        self._drain_after = drain_after
        self._never_joins = never_joins
        self._raise_assertion = raise_assertion
        self.join_calls = []
        self._joined = False

    def is_alive(self):
        if self._never_joins:
            return True
        # Alive until join() has been called (so the production
        # skip-if-not-alive guard still lets the bounded join run once).
        return not self._joined

    def join(self, timeout=None):
        self.join_calls.append(timeout)
        if self._raise_assertion:
            raise AssertionError("simulated join landmine")
        if self._never_joins:
            # Honour the bounded timeout; never actually finishes.
            if timeout:
                time.sleep(min(timeout, 0.2))
            return
        if self._drain_after:
            time.sleep(min(self._drain_after, timeout or self._drain_after))
        self._joined = True


async def _run_shutdown(ctx, scheduler=None):
    """Drive only the shutdown half of the async lifespan context manager."""
    app = MagicMock()
    app.state = MagicMock()
    cm = lifespan(app)

    async def _fake_startup():
        # We don't want the real startup body (it builds the full context
        # from globals). Replace app.state.ctx after entering.
        return None

    # Enter the lifespan; its startup builds a context from globals which is
    # heavy. Patch _build_context_from_globals to return our ctx.
    with patch("comicarr.app.main._build_context_from_globals", return_value=ctx):
        await cm.__aenter__()
    await cm.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Characterization — pin the collapsed-path source contract
# ---------------------------------------------------------------------------


class TestCharacterization:
    """Pins the structural contract of the collapsed shutdown path.

    These assertions describe the *post-U7* code. They are the executable
    record of the redesign documented in the module docstring (the
    pre-collapse ordering is captured there in prose because it cannot be
    re-instantiated once the paths are collapsed)."""

    def test_lifespan_join_runs_before_engine_dispose_in_source(self):
        src = inspect.getsource(lifespan)
        tree = ast.parse(src.lstrip())
        join_line = None
        dispose_line = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = getattr(fn, "attr", getattr(fn, "id", ""))
                if name == "dispose" and dispose_line is None:
                    dispose_line = node.lineno
                if name in ("run_in_executor", "to_thread") and join_line is None:
                    join_line = node.lineno
        assert join_line is not None, "lifespan must run the bounded join off-loop"
        assert dispose_line is not None, "lifespan must dispose the engine"
        assert join_line < dispose_line, (
            "the off-loop bounded join must be scheduled BEFORE engine.dispose() (load-bearing teardown reordering)"
        )

    def test_queue_schedule_assertion_landmine_removed(self):
        from comicarr import queue_schedule

        src = inspect.getsource(queue_schedule)
        # Strip comments/strings: only executable statements matter.
        code_only = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
        assert "os._exit" not in code_only, (
            "the `except AssertionError: os._exit(0)` landmine must be removed from queue_schedule"
        )

    def test_halt_no_longer_drains_queues_or_scheduler(self):
        src = inspect.getsource(comicarr.halt)
        tree = ast.parse(src.lstrip())
        fn = tree.body[0]
        # Drop the docstring node; unparse only the executable body.
        body = fn.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        code_only = "\n".join(ast.unparse(n) for n in body)
        assert "queue_schedule" not in code_only, "halt() must not drive queue_schedule"
        assert "SCHED.shutdown" not in code_only, "halt() must not shut the scheduler"

    def test_shutdown_keeps_terminal_branch(self):
        src = inspect.getsource(comicarr.shutdown)
        assert "os.execv" in src, "shutdown() keeps the restart os.execv branch"
        assert "os._exit" in src, "shutdown() keeps the terminal os._exit branch"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_idle_queues_ordered_stop_drain_dispose(self, _isolated_db):
        scheduler = MagicMock()
        ctx = _make_ctx(scheduler=scheduler)

        order = []
        real_dispose = get_engine().dispose

        snpool = _FakePool(drain_after=0.0)
        with (
            patch.object(comicarr, "SNPOOL", snpool, create=True),
            patch.object(comicarr, "NZBPOOL", None, create=True),
            patch.object(comicarr, "SEARCHPOOL", None, create=True),
            patch.object(comicarr, "PPPOOL", None, create=True),
            patch.object(comicarr, "DDLPOOL", None, create=True),
        ):

            def _track_dispose():
                order.append("dispose")
                return real_dispose()

            scheduler.shutdown.side_effect = lambda *a, **k: order.append("sched")
            with patch.object(get_engine(), "dispose", side_effect=_track_dispose):
                await _run_shutdown(ctx, scheduler)

        # scheduler stopped, then drain (join called), then dispose.
        assert order[0] == "sched"
        assert snpool.join_calls, "the bounded pool.join must have run"
        assert "dispose" in order
        assert order.index("sched") < order.index("dispose")
        # Idle-queue happy path leaves SIGNAL defaulting to shutdown.
        assert comicarr.SIGNAL == "shutdown"


# ---------------------------------------------------------------------------
# AE5 — in-flight journal write completes before engine.dispose()
# ---------------------------------------------------------------------------


class TestAE5InFlightJournal:
    @pytest.mark.asyncio
    async def test_in_flight_write_completes_before_dispose_and_reads_consistent(self, _isolated_db):
        """A worker mid-pipeline writes a transition while shutdown drains.

        The write MUST land before engine.dispose(); the next startup's
        read_open() must return a consistent (non-partial) record. Designed so
        U8 can reuse the assertion as an integration test.
        """
        comicarr.SIGNAL = "restart"  # restart initiated
        scheduler = MagicMock()
        ctx = _make_ctx(scheduler=scheduler)

        rkey = journal.release_key("4711", "nzb.su", nzbname="Series 001")
        # Pre-seed an in-flight (snatched) obligation.
        journal.record_transition(rkey, "snatched", issueid="4711", provider="nzb.su")

        write_done = threading.Event()

        class _SlowWorkerPool:
            def is_alive(self):
                return not write_done.is_set()

            def join(self, timeout=None):
                # Simulate the worker finishing its synchronous journal write
                # while the drain waits for it.
                journal.record_transition(rkey, "downloaded", issueid="4711", provider="nzb.su")
                write_done.set()

        dispose_seen_rows = {}
        real_dispose = get_engine().dispose

        def _capture_then_dispose():
            with get_engine().connect() as conn:
                rows = [
                    dict(r._mapping)
                    for r in conn.execute(select(pipeline_journal).where(pipeline_journal.c.release_key == rkey))
                ]
            dispose_seen_rows["rows"] = rows
            return real_dispose()

        pool = _SlowWorkerPool()
        with (
            patch.object(comicarr, "SNPOOL", pool, create=True),
            patch.object(comicarr, "NZBPOOL", None, create=True),
            patch.object(comicarr, "SEARCHPOOL", None, create=True),
            patch.object(comicarr, "PPPOOL", None, create=True),
            patch.object(comicarr, "DDLPOOL", None, create=True),
            patch.object(get_engine(), "dispose", side_effect=_capture_then_dispose),
        ):
            await _run_shutdown(ctx, scheduler)

        # At engine.dispose() time the in-flight write had already landed.
        assert dispose_seen_rows["rows"], "journal write must precede engine.dispose()"
        assert dispose_seen_rows["rows"][0]["stage"] == "downloaded"

        # Next startup reads a consistent, non-partial record.
        new_engine = get_engine()
        metadata.create_all(new_engine)
        open_rows = journal.read_open()
        match = [r for r in open_rows if r["release_key"] == rkey]
        assert len(match) == 1
        assert match[0]["stage"] == "downloaded"
        assert match[0]["issueid"] == "4711"

        # restart intent survived the drain (NOT clobbered to shutdown).
        assert comicarr.SIGNAL == "restart"


# ---------------------------------------------------------------------------
# Edge — worker exceeds the bounded drain
# ---------------------------------------------------------------------------


class TestBoundedDrainExceeded:
    @pytest.mark.asyncio
    async def test_slow_worker_drain_returns_after_bound_process_still_exits(self, _isolated_db, monkeypatch):
        from comicarr.app import main as appmain

        monkeypatch.setattr(appmain, "SHUTDOWN_DRAIN_TIMEOUT", 0.15)
        scheduler = MagicMock()
        ctx = _make_ctx(scheduler=scheduler)

        rkey = journal.release_key("99", "nzb.su", nzbname="Stuck 001")
        journal.record_transition(rkey, "downloaded", issueid="99", provider="nzb.su")

        stuck = _FakePool(never_joins=True)
        t0 = time.monotonic()
        with (
            patch.object(comicarr, "SNPOOL", stuck, create=True),
            patch.object(comicarr, "NZBPOOL", None, create=True),
            patch.object(comicarr, "SEARCHPOOL", None, create=True),
            patch.object(comicarr, "PPPOOL", None, create=True),
            patch.object(comicarr, "DDLPOOL", None, create=True),
        ):
            await _run_shutdown(ctx, scheduler)
        elapsed = time.monotonic() - t0

        # Drain returned bounded (not hung forever).
        assert elapsed < 5.0
        assert stuck.join_calls and stuck.join_calls[0] == pytest.approx(0.15, abs=0.01)
        # Item left in a consistent resumable stage for replay.
        rows = journal.read_open()
        match = [r for r in rows if r["release_key"] == rkey]
        assert match and match[0]["stage"] in ("downloaded", "snatched")


# ---------------------------------------------------------------------------
# Error — restart/update intent preserved across the drain
# ---------------------------------------------------------------------------


class TestRestartIntentPreserved:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("intent", ["restart", "update"])
    async def test_signal_not_clobbered_then_terminal_branch_taken(self, _isolated_db, intent):
        comicarr.SIGNAL = intent
        scheduler = MagicMock()
        ctx = _make_ctx(scheduler=scheduler)

        with (
            patch.object(comicarr, "SNPOOL", _FakePool(), create=True),
            patch.object(comicarr, "NZBPOOL", None, create=True),
            patch.object(comicarr, "SEARCHPOOL", None, create=True),
            patch.object(comicarr, "PPPOOL", None, create=True),
            patch.object(comicarr, "DDLPOOL", None, create=True),
        ):
            await _run_shutdown(ctx, scheduler)

        # Lifespan must NOT clobber a pre-existing restart/update signal.
        assert comicarr.SIGNAL == intent

        # halt() must remain idempotent and preserve the signal too.
        with patch.object(comicarr, "_INITIALIZED", True, create=True):
            comicarr.halt()
        assert comicarr.SIGNAL == intent

        # shutdown(restart=True) reaches os.execv, NOT os._exit, for a restart.
        with (
            patch("comicarr.os.execv") as m_execv,
            patch("comicarr.os._exit"),
            patch.object(comicarr, "CREATEPID", False, create=True),
            patch.object(comicarr, "ARGS", [], create=True),
            patch.object(comicarr, "FULL_PATH", "/tmp/Comicarr.py", create=True),
        ):
            comicarr.shutdown(restart=True)
        assert m_execv.called, "restart MUST reach os.execv (not degrade to a stop)"
        # os._exit may be called as the unconditional non-blocking backstop,
        # but only AFTER os.execv was attempted.


# ---------------------------------------------------------------------------
# Error — AssertionError during the join does not short-circuit
# ---------------------------------------------------------------------------


class TestAssertionLandmineRemoved:
    @pytest.mark.asyncio
    async def test_assertion_in_join_does_not_skip_flush_and_dispose(self, _isolated_db):
        scheduler = MagicMock()
        ctx = _make_ctx(scheduler=scheduler)
        dispose_called = []
        real_dispose = get_engine().dispose

        bad = _FakePool(raise_assertion=True)
        with (
            patch.object(comicarr, "SNPOOL", bad, create=True),
            patch.object(comicarr, "NZBPOOL", None, create=True),
            patch.object(comicarr, "SEARCHPOOL", None, create=True),
            patch.object(comicarr, "PPPOOL", None, create=True),
            patch.object(comicarr, "DDLPOOL", None, create=True),
            patch("comicarr.os._exit") as m_exit,
            patch.object(
                get_engine(),
                "dispose",
                side_effect=lambda: (dispose_called.append(1), real_dispose())[1],
            ),
        ):
            await _run_shutdown(ctx, scheduler)

        # An AssertionError in the bounded join must NOT short-circuit to
        # os._exit before engine.dispose().
        assert not m_exit.called, "no os._exit short-circuit during the drain"
        assert dispose_called, "engine.dispose() still runs after a join AssertionError"


# ---------------------------------------------------------------------------
# Error — hard-kill liveness with a permanently-wedged worker
# ---------------------------------------------------------------------------


class TestHardKillLiveness:
    def test_wedged_worker_still_terminates_via_post_drain_hardkill(self):
        """The terminal hard-kill backstop is non-blocking: a worker wedged
        forever in native code cannot prevent process termination."""
        # The terminal step is shutdown()'s os._exit / os.execv. Even with a
        # pool that never joins, halt() (signalling only) must return promptly
        # and shutdown() must reach the terminal branch without blocking.
        comicarr.SIGNAL = None

        class _WedgedPool:
            def is_alive(self):
                return True

            def join(self, timeout=None):
                # Would block forever if anyone called this unbounded.
                raise AssertionError("join must not be called from halt()")

        result = {}

        def _run():
            with (
                patch.object(comicarr, "SNPOOL", _WedgedPool(), create=True),
                patch.object(comicarr, "_INITIALIZED", True, create=True),
                patch("comicarr.os._exit") as m_exit,
                patch("comicarr.os.execv") as m_execv,
                patch.object(comicarr, "CREATEPID", False, create=True),
            ):
                comicarr.halt()
                comicarr.shutdown()
                result["exit"] = m_exit.called
                result["execv"] = m_execv.called

        t = threading.Thread(target=_run, name="hardkill-liveness")
        t.start()
        t.join(timeout=3.0)
        assert not t.is_alive(), "halt()+shutdown() must not block on a wedged worker"
        assert result.get("exit") is True, "the terminal hard-kill (os._exit) must run"


# ---------------------------------------------------------------------------
# Edge — bounded join runs OFF the event loop
# ---------------------------------------------------------------------------


class TestJoinOffEventLoop:
    @pytest.mark.asyncio
    async def test_event_loop_responsive_during_drain(self, _isolated_db, monkeypatch):
        from comicarr.app import main as appmain

        monkeypatch.setattr(appmain, "SHUTDOWN_DRAIN_TIMEOUT", 1.0)
        scheduler = MagicMock()
        ctx = _make_ctx(scheduler=scheduler)

        # Pool that blocks its join() for ~0.5s — if run ON the loop the
        # heartbeat below would stall.
        class _BlockingPool:
            def __init__(self):
                self.joined = False

            def is_alive(self):
                return not self.joined

            def join(self, timeout=None):
                time.sleep(0.5)
                self.joined = True

        ticks = []
        stop = threading.Event()

        async def _heartbeat():
            while not stop.is_set():
                ticks.append(time.monotonic())
                await asyncio.sleep(0.02)

        hb = asyncio.create_task(_heartbeat())
        with (
            patch.object(comicarr, "SNPOOL", _BlockingPool(), create=True),
            patch.object(comicarr, "NZBPOOL", None, create=True),
            patch.object(comicarr, "SEARCHPOOL", None, create=True),
            patch.object(comicarr, "PPPOOL", None, create=True),
            patch.object(comicarr, "DDLPOOL", None, create=True),
        ):
            await _run_shutdown(ctx, scheduler)
        stop.set()
        await hb

        # The heartbeat kept ticking through the ~0.5s blocking join: the
        # loop was not blocked, proving the join ran off-loop.
        assert len(ticks) >= 10, (
            "event loop stalled during the drain — the bounded join is NOT "
            "running off the event loop (ticks=%d)" % len(ticks)
        )


# ---------------------------------------------------------------------------
# Error — teardown order: engine alive throughout, join executor not torn down
# ---------------------------------------------------------------------------


class TestTeardownOrder:
    @pytest.mark.asyncio
    async def test_engine_alive_during_drain_and_join_executor_independent(self, _isolated_db):
        scheduler = MagicMock()
        ctx = _make_ctx(scheduler=scheduler)

        engine = get_engine()
        engine_disposed_during_join = {"flag": False}

        real_dispose = engine.dispose
        disposed = {"v": False}

        def _mark_disposed():
            disposed["v"] = True
            return real_dispose()

        class _CheckingPool:
            _joined = False

            def is_alive(self):
                return not self._joined

            def join(self, timeout=None):
                self._joined = True
                # Engine must still be usable mid-drain.
                if disposed["v"]:
                    engine_disposed_during_join["flag"] = True
                with engine.connect() as conn:
                    conn.execute(select(pipeline_journal))

        with (
            patch.object(comicarr, "SNPOOL", _CheckingPool(), create=True),
            patch.object(comicarr, "NZBPOOL", None, create=True),
            patch.object(comicarr, "SEARCHPOOL", None, create=True),
            patch.object(comicarr, "PPPOOL", None, create=True),
            patch.object(comicarr, "DDLPOOL", None, create=True),
            patch.object(engine, "dispose", side_effect=_mark_disposed),
        ):
            await _run_shutdown(ctx, scheduler)

        assert not engine_disposed_during_join["flag"], (
            "engine.dispose() ran mid-drain — must be AFTER the bounded join"
        )
        assert disposed["v"], "engine.dispose() must still run after the drain"


# ---------------------------------------------------------------------------
# Edge — engine.dispose() never called before the drain returns
# ---------------------------------------------------------------------------


class TestDisposeAfterDrain:
    @pytest.mark.asyncio
    async def test_dispose_strictly_after_drain(self, _isolated_db):
        scheduler = MagicMock()
        ctx = _make_ctx(scheduler=scheduler)

        events = []
        real_dispose = get_engine().dispose

        class _OrderingPool:
            _joined = False

            def is_alive(self):
                return not self._joined

            def join(self, timeout=None):
                self._joined = True
                events.append("join")

        with (
            patch.object(comicarr, "SNPOOL", _OrderingPool(), create=True),
            patch.object(comicarr, "NZBPOOL", None, create=True),
            patch.object(comicarr, "SEARCHPOOL", None, create=True),
            patch.object(comicarr, "PPPOOL", None, create=True),
            patch.object(comicarr, "DDLPOOL", None, create=True),
            patch.object(
                get_engine(),
                "dispose",
                side_effect=lambda: (events.append("dispose"), real_dispose())[1],
            ),
        ):
            await _run_shutdown(ctx, scheduler)

        assert "join" in events and "dispose" in events
        assert events.index("join") < events.index("dispose"), (
            "engine.dispose() must never run before the bounded drain returns"
        )
