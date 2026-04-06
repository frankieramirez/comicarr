#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
RPM + daily token budget rate limiter for AI provider calls.

Two limits enforced:
  1. Requests per minute (sliding window)
  2. Daily token budget (resets on date change)
"""

import datetime
import threading
import time


class AIRateLimiter:

    def __init__(self, rpm_limit=20, daily_token_limit=100000):
        self._rpm_limit = rpm_limit
        self._daily_token_limit = daily_token_limit
        self._request_timestamps = []
        self._today_tokens = 0
        self._today_requests = 0
        self._current_date = datetime.date.today().isoformat()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def can_request(self):
        with self._lock:
            self._maybe_reset_daily()
            self._prune_rpm_window()

            if len(self._request_timestamps) >= self._rpm_limit:
                return False
            if self._today_tokens >= self._daily_token_limit:
                return False
            return True

    def record_request(self, tokens):
        with self._lock:
            self._maybe_reset_daily()
            now = time.time()
            self._request_timestamps.append(now)
            self._today_tokens += tokens
            self._today_requests += 1

    def update_limits(self, rpm_limit, daily_token_limit):
        with self._lock:
            self._rpm_limit = rpm_limit
            self._daily_token_limit = daily_token_limit

    @property
    def today_tokens(self):
        with self._lock:
            self._maybe_reset_daily()
            return self._today_tokens

    @property
    def today_requests(self):
        with self._lock:
            self._maybe_reset_daily()
            return self._today_requests

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _prune_rpm_window(self):
        """Remove timestamps older than 60 seconds.

        Must be called while holding self._lock.
        """
        cutoff = time.time() - 60
        self._request_timestamps = [t for t in self._request_timestamps if t > cutoff]

    def _maybe_reset_daily(self):
        """Reset daily counters when the date changes.

        Must be called while holding self._lock.
        """
        today = datetime.date.today().isoformat()
        if today != self._current_date:
            self._current_date = today
            self._today_tokens = 0
            self._today_requests = 0
