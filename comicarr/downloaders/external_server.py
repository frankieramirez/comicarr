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

"""DDL(External) search seam used by ``comicarr.search``.

Mylar3 shipped this module as a placeholder (``EXT_SERVER = False``) for an
optional drop-in that defined ``MegaNZ``. Comicarr still constructs
``external_server.MegaNZ`` for DDL(External) search and snatch. This module
exposes that constructor and the two methods ``search.py`` calls so a missing
add-on cannot raise ``AttributeError``.

``comicarr.downloaders.mega.MegaNZ`` is a different class: it downloads
Mega.nz links (GetComics GC-Mega) and is not a search client.
"""

from comicarr import logger

EXT_SERVER = False


class MegaNZ(object):
    def __init__(self, query=None, provider_stat=None):
        self.query = query
        self.provider_stat = provider_stat

    def ddl_search(self, is_info=None):
        logger.warn("[DDL(External)] External search server client is not available; returning no results.")
        return "no results"

    def queue_the_download(self, cinfo, comicinfo=None, pack_info=None):
        logger.warn("[DDL(External)] External search server client is not available; cannot queue a download.")
        return {"success": False}
