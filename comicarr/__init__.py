#  Copyright (C) 2012–2024 Mylar3 contributors
#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Originally based on Mylar3 (https://github.com/mylar3/mylar3).
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.


"""The Comicarr package.

Everything lives under ``comicarr.app``: the process lifecycle in
``comicarr.app.core.lifecycle`` and process state on ``AppContext``
(``comicarr.app.core.runtime``). This file keeps only the import paths that
landed Alembic revisions use, because a landed revision can never be edited.
"""

import importlib
import sys

# Landed revision 0021 runs ``from comicarr import logger``.
from comicarr.app.core import logger

__all__ = ["logger"]

# Landed Alembic revision 0001 runs ``from comicarr.tables import metadata``, and a
# landed revision can never be edited. Keep that import path working after the
# move to app/core (tests/unit/test_landed_revision_imports.py pins it).
sys.modules.setdefault("comicarr.tables", importlib.import_module("comicarr.app.core.tables"))
