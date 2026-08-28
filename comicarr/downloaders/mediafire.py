# -*- coding: utf-8 -*-

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
import re
from email.message import Message

import requests

import comicarr
from comicarr import db, helpers, logger
from comicarr.app.common.remote_artifacts import (
    resolve_remote_artifact_path,
    safe_remote_filename,
    write_chunks_atomically,
)


class MediaFire(object):
    def __init__(self):
        self.dl_location = os.path.join(comicarr.CONFIG.DDL_LOCATION)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.5481.178 Safari/537.36"
        }
        self.session = requests.Session()

    def extractDownloadLink(self, contents):
        for line in contents.splitlines():
            m = re.search(r'href="((http|https)://download[^"]+)', line)
            if m:
                return m.groups()[0]

    def ddl_download(self, url, id, issueid):
        url_origin = url

        while True:
            t = self.session.get(url, verify=True, headers=self.headers, stream=True, timeout=(30, 30))

            if "Content-Disposition" in t.headers:
                break

            url = self.extractDownloadLink(t.text)

            if url is None:
                return {"success": False, "filename": None, "path": None, "link_type_failure": "GC-Media"}

        content_disposition = Message()
        content_disposition["Content-Disposition"] = t.headers["Content-Disposition"]
        filename = content_disposition.get_filename()
        if filename is None:
            return {"success": False, "filename": None, "path": None, "link_type_failure": "GC-Media"}
        try:
            filename = filename.encode("iso8859").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass

        file, ext = os.path.splitext(filename)
        try:
            filename = safe_remote_filename("%s[__%s__]%s" % (file, issueid, ext))
        except ValueError as e:
            logger.warn("[MediaFire] Refusing unsafe remote filename: %s" % e)
            return {"success": False, "filename": None, "path": None, "link_type_failure": "GC-Media"}

        try:
            filesize = int(t.headers["Content-Length"])
        except Exception:
            filesize = 0

        fileinfo = {"filename": filename, "filesize": filesize}

        logger.fdebug("Downloading...")
        logger.fdebug("%s [%s bytes]" % (filename, filesize))
        logger.fdebug("From: %s" % url_origin)
        logger.fdebug("To: %s" % os.path.join(self.dl_location, filename))

        logger.fdebug("[Writing to db: %s" % (filename))
        db.upsert(
            "ddl_info",
            {"filename": str(filename), "remote_filesize": str(filesize), "size": helpers.human_size(filesize)},
            {"ID": id},
        )
        return self.mediafire_dl(url, id, fileinfo, issueid)

    def mediafire_dl(self, url, id, fileinfo, issueid):
        try:
            filename = safe_remote_filename(fileinfo["filename"])
            filepath = resolve_remote_artifact_path(self.dl_location, filename)
        except ValueError as e:
            logger.warn("[MediaFire] Refusing unsafe download path: %s" % e)
            return {"success": False, "filename": None, "path": None, "link_type_failure": "GC-Media"}
        fileinfo = dict(fileinfo)
        fileinfo["filename"] = filename

        db.upsert(
            "ddl_info",
            {"tmp_filename": fileinfo["filename"]},
            {"ID": id},
        )

        try:
            response = self.session.get(url, verify=True, headers=self.headers, stream=True, timeout=(30, 30))

            logger.fdebug("[MediaFire] now writing....")
            write_chunks_atomically(filepath, response.iter_content(chunk_size=4096))

        except Exception as e:
            logger.fdebug("[MediaFire][ERROR] %s" % e)
            if "EBLOCKED" in str(e):
                logger.fdebug("[MediaFire] Content has been removed - we should move on to the next one at this point.")
            return {"success": False, "filename": None, "path": None, "link_type_failure": "GC-Media"}

        try:
            filesize = os.stat(filepath).st_size
        except FileNotFoundError:
            return {"success": False, "filename": None, "path": None}
        else:
            logger.fdebug("[MediaFire] download completed - downloaded %s / %s" % (filesize, fileinfo["filesize"]))

        logger.fdebug("[MediaFire] ddl_linked - filename: %s" % fileinfo["filename"])

        file, ext = os.path.splitext(fileinfo["filename"])
        if ext == ".zip":
            ggc = comicarr.getcomics.GC()
            return ggc.zip_zip(id, str(filepath), fileinfo["filename"])
        else:
            return {"success": True, "filename": fileinfo["filename"], "path": str(filepath)}
