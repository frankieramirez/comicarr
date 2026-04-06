#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Thread-safe circuit breaker for AI provider calls.

States:
  CLOSED    — requests flow normally
  OPEN      — requests blocked after consecutive failures hit threshold
  HALF-OPEN — one probe request allowed after cooldown expires
"""

import threading
import time

STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half-open"


class CircuitBreaker:

    def __init__(self, threshold=5, cooldown=300):
        self._threshold = threshold
        self._cooldown = cooldown
        self._failure_count = 0
        self._state = STATE_CLOSED
        self._opened_at = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self):
        with self._lock:
            self._maybe_transition_half_open()
            return self._state

    def allow_request(self):
        with self._lock:
            self._maybe_transition_half_open()
            if self._state == STATE_CLOSED:
                return True
            if self._state == STATE_HALF_OPEN:
                return True
            return False

    def record_success(self):
        with self._lock:
            self._failure_count = 0
            self._state = STATE_CLOSED

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self._threshold:
                self._state = STATE_OPEN
                self._opened_at = time.time()

    def force_reset(self):
        with self._lock:
            self._failure_count = 0
            self._state = STATE_CLOSED
            self._opened_at = 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _maybe_transition_half_open(self):
        """Transition OPEN -> HALF-OPEN once cooldown has elapsed.

        Must be called while holding self._lock.
        """
        if self._state == STATE_OPEN and (time.time() - self._opened_at) >= self._cooldown:
            self._state = STATE_HALF_OPEN
