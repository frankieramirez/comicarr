#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Process locks that read like the booleans they replaced."""

import threading


class ThreadSafeLock:
    """
    Thread-safe lock that provides boolean-like interface for backwards
    compatibility while using proper threading primitives.

    Usage:
        lock = ThreadSafeLock()
        if lock:  # or lock == True or lock.locked()
            print("locked")
        lock.acquire()  # instead of lock = True
        lock.release()  # instead of lock = False
    """

    def __init__(self):
        self._lock = threading.Lock()

    def __bool__(self):
        """Allow `if lock:` syntax."""
        return self._lock.locked()

    def __eq__(self, other):
        """Allow `lock == True` or `lock is True` style comparisons."""
        if isinstance(other, bool):
            return self._lock.locked() == other
        return NotImplemented

    def acquire(self, blocking=True, timeout=-1):
        """Acquire the lock (equivalent to setting to True)."""
        return self._lock.acquire(blocking=blocking, timeout=timeout)

    def release(self):
        """
        Release the lock (equivalent to setting to False).
        Safe to call even if not locked.
        """
        try:
            self._lock.release()
        except RuntimeError:
            pass

    def locked(self):
        """Check if the lock is currently held."""
        return self._lock.locked()

    def __enter__(self):
        """Support context manager usage."""
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Support context manager usage."""
        self._lock.release()
        return False
