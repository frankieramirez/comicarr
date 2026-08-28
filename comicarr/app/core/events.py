#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
EventBus — thread-safe pub/sub, sole transport for server-sent events.

Each SSE subscriber gets its own asyncio.Queue. Background threads
publish via publish_sync(), which uses loop.call_soon_threadsafe()
to safely enqueue events from non-async threads.
"""

import asyncio
import threading
import time
from dataclasses import dataclass

from comicarr import logger

_OVERFLOW_LOG_INTERVAL_SEC = 5.0
_last_overflow_log = 0.0
_overflow_log_lock = threading.Lock()


@dataclass
class AppEvent:
    event_type: str
    payload: dict


class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers = {}
        self._counter = 0
        self._loop = None
        self._closing = False

    def set_loop(self, loop):
        """Called during lifespan startup to capture the running event loop."""
        with self._lock:
            self._loop = loop

    def close(self):
        """Reject future publishes once the runtime begins shutting down.

        The close flag and publisher snapshot share one lock. A publish that
        has already acquired the lock may still be delivered, but no caller
        can enqueue a new event after this method returns.
        """
        with self._lock:
            self._closing = True

    def subscribe(self):
        """Create a new subscriber queue. Returns (sub_id, queue)."""
        q = asyncio.Queue(maxsize=256)
        with self._lock:
            self._counter += 1
            sub_id = self._counter
            self._subscribers[sub_id] = q
        return sub_id, q

    def unsubscribe(self, sub_id):
        """Remove a subscriber."""
        with self._lock:
            self._subscribers.pop(sub_id, None)

    @staticmethod
    def _log_overflow_drop(event):
        """Emit a rate-limited debug line when oldest events are dropped."""
        global _last_overflow_log
        now = time.monotonic()
        with _overflow_log_lock:
            if now - _last_overflow_log < _OVERFLOW_LOG_INTERVAL_SEC:
                return
            _last_overflow_log = now
        event_type = getattr(event, "event_type", "?")
        logger.fdebug("[EventBus] Dropped oldest subscriber event to retain newest type=%s" % event_type)

    @staticmethod
    def _enqueue_latest(q, event):
        """Enqueue on the event-loop thread, retaining the newest event."""
        try:
            q.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass

        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass

        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            return

        EventBus._log_overflow_drop(event)

    def publish_sync(self, event_type, payload):
        """Thread-safe publish from background threads into async queues.

        Uses loop.call_soon_threadsafe() to ensure the event loop is
        properly woken up when events are published from worker threads.
        """
        with self._lock:
            if self._closing or self._loop is None:
                return False

            event = AppEvent(event_type, payload)
            for q in self._subscribers.values():
                try:
                    self._loop.call_soon_threadsafe(self._enqueue_latest, q, event)
                except RuntimeError:
                    pass
        return True

    @property
    def subscriber_count(self):
        with self._lock:
            return len(self._subscribers)
