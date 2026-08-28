#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Process-owned registry for finite background threads."""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from concurrent.futures import TimeoutError as FutureTimeoutError


class _FutureWorker:
    """Join-compatible view of work submitted to a shared executor."""

    def __init__(self, future, name):
        self.future = future
        self.name = name

    def is_alive(self):
        return not self.future.done()

    def join(self, timeout=None):
        try:
            self.future.result(timeout=timeout)
        except FutureTimeoutError:
            pass
        except Exception:
            pass


class BackgroundWorkerRegistry:
    """Start finite workers and retain their identities until completion."""

    def __init__(self):
        self._lock = threading.RLock()
        self._workers = set()
        self._accepting = True

    def start(self, target: Callable, *, args=(), kwargs=None, name=None, daemon=None):
        """Register a thread before starting it and retire it on completion."""

        def run():
            try:
                target(*args, **(kwargs or {}))
            except Exception:
                from comicarr import logger

                logger.error(
                    "[BACKGROUND-WORKER] %s failed:\n%s" % (threading.current_thread().name, traceback.format_exc())
                )
            finally:
                with self._lock:
                    self._workers.discard(threading.current_thread())

        worker = threading.Thread(target=run, name=name, daemon=daemon)
        with self._lock:
            if not self._accepting:
                raise RuntimeError("background worker registry is closed for shutdown")
            self._workers.add(worker)
            try:
                worker.start()
            except Exception:
                self._workers.discard(worker)
                raise
        return worker

    def close(self):
        """Atomically reject new work and return the workers to drain."""

        with self._lock:
            self._accepting = False
            return self.snapshot()

    def submit(self, executor, target: Callable, *, args=(), kwargs=None, name=None):
        """Atomically admit executor work and retain it until completion."""

        worker_name = name or getattr(target, "__name__", "background-future")

        def run():
            try:
                return target(*args, **(kwargs or {}))
            except Exception:
                from comicarr import logger

                logger.error("[BACKGROUND-WORKER] %s failed:\n%s" % (worker_name, traceback.format_exc()))
                raise

        with self._lock:
            if not self._accepting:
                raise RuntimeError("background worker registry is closed for shutdown")
            future = executor.submit(run)
            worker = _FutureWorker(future, worker_name)
            self._workers.add(worker)
            future.add_done_callback(lambda _future: self._discard(worker))
        return future

    def _discard(self, worker):
        with self._lock:
            self._workers.discard(worker)

    def snapshot(self):
        """Return the currently live registered workers."""

        with self._lock:
            stopped = {worker for worker in self._workers if not worker.is_alive()}
            self._workers.difference_update(stopped)
            return tuple(self._workers)


def _runtime_registry():
    from comicarr.app.core.runtime import get_runtime

    return get_runtime().background_workers


def start_background_thread(target: Callable, *, args=(), kwargs=None, name=None, daemon=None, registry=None):
    """Start a finite process worker through the shutdown-owned registry."""

    registry = registry if registry is not None else _runtime_registry()
    return registry.start(
        target,
        args=args,
        kwargs=kwargs,
        name=name,
        daemon=daemon,
    )


def submit_background_future(executor, target: Callable, *, args=(), kwargs=None, name=None, registry=None):
    """Submit finite executor work through the shutdown-owned registry."""

    registry = registry if registry is not None else _runtime_registry()
    return registry.submit(
        executor,
        target,
        args=args,
        kwargs=kwargs,
        name=name,
    )
