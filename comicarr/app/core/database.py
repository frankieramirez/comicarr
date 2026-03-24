#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Database — thin wrapper over existing db.py engine.

Provides access to the SQLAlchemy engine and connection helpers
for domain queries.py files. Does not replace db.py — bridges to it.
"""

from contextlib import contextmanager

from comicarr import db


def get_engine():
    """Return the SQLAlchemy engine (lazy-initialized via db.py)."""
    return db.get_engine()


@contextmanager
def get_connection():
    """Context manager yielding a SQLAlchemy Connection."""
    with db.get_connection() as conn:
        yield conn


def get_dialect():
    """Return the dialect name: 'sqlite', 'postgresql', or 'mysql'."""
    return db.get_dialect()
