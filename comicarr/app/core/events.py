#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
EventBus — thread-safe pub/sub replacing GLOBAL_MESSAGES.

Each SSE subscriber gets its own asyncio.Queue. Background threads
publish via publish_sync(), which uses loop.call_soon_threadsafe()
to safely enqueue events from non-async threads.
"""

import asyncio
import threading
from dataclasses import dataclass


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

    def set_loop(self, loop):
        """Called during lifespan startup to capture the running event loop."""
        self._loop = loop

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

    def publish_sync(self, event_type, payload):
        """Thread-safe publish from background threads into async queues.

        Uses loop.call_soon_threadsafe() to ensure the event loop is
        properly woken up when events are published from worker threads.
        """
        if self._loop is None:
            return

        event = AppEvent(event_type, payload)
        with self._lock:
            snapshot = list(self._subscribers.values())

        for q in snapshot:
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, event)
            except asyncio.QueueFull:
                pass  # Slow consumer — drop oldest would be better but skip for now
            except RuntimeError:
                pass  # Event loop closed during shutdown

    @property
    def subscriber_count(self):
        with self._lock:
            return len(self._subscribers)
