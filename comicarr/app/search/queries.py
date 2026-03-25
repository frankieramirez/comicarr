#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Search domain queries — provider search results, tmp_searches.

Most search operations go through search.py and mb.findComic rather
than direct DB access. This module covers auxiliary query needs.
"""

from sqlalchemy import select

from comicarr import db
from comicarr.tables import provider_searches as t_provider_searches


def get_provider_stats():
    """Get provider search statistics (last run, hit counts)."""
    stmt = select(t_provider_searches).order_by(t_provider_searches.c.provider)
    return db.select_all(stmt)
