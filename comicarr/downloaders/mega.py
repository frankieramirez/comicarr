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

import os
import sys

import comicarr
from comicarr import db, helpers, logger
from comicarr.downloaders import mega_public


class MegaNZ(object):
    def __init__(self, query=None):
        self.query = query
        self.dl_location = os.path.join(comicarr.CONFIG.DDL_LOCATION, "mega")
        self.wrote_tmp = False

    def ddl_download(self, link, filename, id, issueid=None, site=None):
        self.id = id
        if self.dl_location is not None and not os.path.isdir(self.dl_location):
            checkdirectory = comicarr.filechecker.validateAndCreateDirectory(self.dl_location, True)
            if not checkdirectory:
                logger.warn("[ABORTING] Error trying to validate/create DDL download directory: %s." % self.dl_location)
                return {"success": False, "filename": filename, "path": None}

        logger.info("trying link: %s" % (link,))
        logger.info("dl_location: %s / filename: %s" % (self.dl_location, filename))

        try:
            info = mega_public.resolve(link)
            logger.info("[MEGA] resolved %s [%s bytes]" % (info.name, info.size))
            db.upsert(
                "ddl_info",
                {
                    "filename": str(info.name),
                    "remote_filesize": str(info.size),
                    "size": helpers.human_size(str(info.size)),
                },
                {"ID": self.id},
            )
            filename = info.name
            downloaded = mega_public.download(info, self.dl_location, self._progress)
        except Exception as e:
            logger.warn("[MEGA][ERROR] %s: %s" % (getattr(e, "reason", type(e).__name__), e))
            return {"success": False, "filename": filename, "path": None, "link_type_failure": site}

        logger.info("[MEGA] successfully downloaded %s [%s bytes]" % (downloaded.name, downloaded.size))
        file, ext = os.path.splitext(downloaded.name)
        filename = "%s[__%s__]%s" % (file, issueid, ext)
        filepath = downloaded.path.with_name(filename)
        try:
            filepath = downloaded.path.replace(filepath)
        except Exception:
            logger.warn("unable to rename/replace %s with %s" % (downloaded.path, filepath))
        else:
            logger.info("ddl_linked - filename: %s" % filename)
        if ext == ".zip":
            ggc = comicarr.getcomics.GC()
            return ggc.zip_zip(id, str(filepath), filename)
        return {"success": True, "filename": filename, "path": str(filepath)}

    def _progress(self, written, total, partial_path):
        if not self.wrote_tmp:
            logger.info("[MEGA] writing to db: %s [%s]" % (partial_path, total))
            db.upsert("ddl_info", {"tmp_filename": str(partial_path)}, {"ID": self.id})
            self.wrote_tmp = True


if __name__ == "__main__":
    test = MegaNZ(sys.argv[1])
    test.ddl_search()
