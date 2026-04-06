#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for comicarr.app.ai.rate_limiter."""

import datetime
from unittest.mock import patch

import pytest

from comicarr.app.ai.rate_limiter import AIRateLimiter


class TestRPMLimit:
    def test_can_request_within_limit(self):
        rl = AIRateLimiter(rpm_limit=5, daily_token_limit=100000)
        assert rl.can_request() is True

    def test_can_request_returns_false_at_cap(self):
        rl = AIRateLimiter(rpm_limit=3, daily_token_limit=100000)
        rl.record_request(10)
        rl.record_request(10)
        rl.record_request(10)
        assert rl.can_request() is False

    def test_rpm_window_slides(self):
        rl = AIRateLimiter(rpm_limit=2, daily_token_limit=100000)
        # Inject old timestamps that fall outside the 60s window
        import time
        with rl._lock:
            rl._request_timestamps = [time.time() - 120, time.time() - 90]
            rl._today_requests = 2
            rl._today_tokens = 20
        assert rl.can_request() is True


class TestDailyTokenBudget:
    def test_daily_token_tracking(self):
        rl = AIRateLimiter(rpm_limit=100, daily_token_limit=500)
        rl.record_request(200)
        assert rl.today_tokens == 200
        rl.record_request(300)
        assert rl.today_tokens == 500
        assert rl.can_request() is False

    def test_daily_reset_on_date_change(self):
        rl = AIRateLimiter(rpm_limit=100, daily_token_limit=1000)
        rl.record_request(900)
        assert rl.today_tokens == 900

        # Simulate date change
        with rl._lock:
            rl._current_date = "1999-01-01"

        assert rl.today_tokens == 0
        assert rl.today_requests == 0
        assert rl.can_request() is True


class TestUpdateLimits:
    def test_update_limits(self):
        rl = AIRateLimiter(rpm_limit=5, daily_token_limit=1000)
        rl.update_limits(rpm_limit=50, daily_token_limit=500000)
        # Fill to old limit to verify new limit took effect
        for _ in range(10):
            rl.record_request(1)
        assert rl.can_request() is True


class TestProperties:
    def test_today_requests_property(self):
        rl = AIRateLimiter(rpm_limit=100, daily_token_limit=100000)
        assert rl.today_requests == 0
        rl.record_request(50)
        rl.record_request(100)
        assert rl.today_requests == 2

    def test_today_tokens_property(self):
        rl = AIRateLimiter(rpm_limit=100, daily_token_limit=100000)
        assert rl.today_tokens == 0
        rl.record_request(42)
        assert rl.today_tokens == 42
