#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
ComicVine API Rate Limiter

This module implements a token bucket algorithm for rate limiting ComicVine API requests.
It provides intelligent rate limiting that only sleeps when necessary, allowing burst
requests when tokens are available while maintaining the configured rate limit over time.
"""

import threading
import time


class ComicVineRateLimiter:
    """
    Token bucket rate limiter for ComicVine API.

    This implementation allows requests to proceed immediately when tokens are available,
    and only sleeps when the rate limit would be exceeded. This is more efficient than
    sleeping for a fixed duration before every request.

    Thread-safe for use across parallel requests.
    """

    def __init__(self, calls_per_second=0.5):
        """
        Initialize the rate limiter.

        Args:
            calls_per_second (float): Maximum calls per second (default 0.5 = 1 call per 2 seconds)
        """
        self.rate = calls_per_second  # Tokens added per second
        self.tokens = 1.0  # Start with 1 token available
        self.last_update = time.time()
        self.lock = threading.Lock()

    def acquire(self):
        """
        Acquire a token to make an API request.

        This method will sleep only if necessary to maintain the rate limit.
        If tokens are available, the request proceeds immediately.

        Thread-safe: Multiple threads can call this concurrently.
        """
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update

            # Add tokens based on elapsed time, up to maximum of 1.0
            self.tokens = min(1.0, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens >= 1.0:
                # Token available, proceed immediately
                self.tokens -= 1.0
                return  # No wait needed
            else:
                # Need to wait for token to accumulate
                wait_time = (1.0 - self.tokens) / self.rate
                self.tokens = 0
                time.sleep(wait_time)

    def set_rate(self, calls_per_second):
        """
        Update the rate limit dynamically.

        Args:
            calls_per_second (float): New maximum calls per second
        """
        with self.lock:
            self.rate = calls_per_second
