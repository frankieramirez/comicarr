#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for comicarr.app.ai.circuit_breaker."""

import threading
import time
from unittest.mock import patch

import pytest

from comicarr.app.ai.circuit_breaker import (
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
    CircuitBreaker,
)


class TestCircuitBreakerStates:
    """Test state transitions: CLOSED -> OPEN -> HALF-OPEN -> CLOSED."""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(threshold=3, cooldown=10)
        assert cb.state == STATE_CLOSED
        assert cb.allow_request() is True

    def test_closed_to_open_after_threshold_failures(self):
        cb = CircuitBreaker(threshold=3, cooldown=10)
        cb.record_failure()
        assert cb.state == STATE_CLOSED
        cb.record_failure()
        assert cb.state == STATE_CLOSED
        cb.record_failure()
        assert cb.state == STATE_OPEN
        assert cb.allow_request() is False

    def test_open_to_half_open_after_cooldown(self):
        cb = CircuitBreaker(threshold=2, cooldown=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == STATE_OPEN

        time.sleep(1.1)
        assert cb.state == STATE_HALF_OPEN
        assert cb.allow_request() is True

    def test_half_open_to_closed_on_success(self):
        cb = CircuitBreaker(threshold=2, cooldown=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == STATE_OPEN

        time.sleep(1.1)
        assert cb.state == STATE_HALF_OPEN

        cb.record_success()
        assert cb.state == STATE_CLOSED
        assert cb.allow_request() is True

    def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker(threshold=2, cooldown=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == STATE_OPEN

        time.sleep(1.1)
        assert cb.state == STATE_HALF_OPEN

        # Another failure in half-open should re-open
        cb.record_failure()
        assert cb.state == STATE_OPEN
        assert cb.allow_request() is False


class TestForceReset:
    def test_force_reset_from_open(self):
        cb = CircuitBreaker(threshold=2, cooldown=300)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == STATE_OPEN

        cb.force_reset()
        assert cb.state == STATE_CLOSED
        assert cb.allow_request() is True

    def test_force_reset_clears_failure_count(self):
        cb = CircuitBreaker(threshold=3, cooldown=300)
        cb.record_failure()
        cb.record_failure()  # 2 failures, below threshold
        cb.force_reset()
        cb.record_failure()  # 1 failure after reset
        assert cb.state == STATE_CLOSED


class TestThreadSafety:
    def test_concurrent_failures(self):
        cb = CircuitBreaker(threshold=50, cooldown=300)
        errors = []

        def hammer():
            try:
                for _ in range(25):
                    cb.record_failure()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=hammer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert cb.state == STATE_OPEN

    def test_concurrent_allow_request(self):
        cb = CircuitBreaker(threshold=5, cooldown=300)
        results = []

        def check():
            results.append(cb.allow_request())

        threads = [threading.Thread(target=check) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r is True for r in results)
