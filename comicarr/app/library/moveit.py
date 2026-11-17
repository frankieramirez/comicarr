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

import ast
import os
import shutil

import comicarr
from comicarr.app.core import db, logger
from comicarr.app.downloads import service as downloads_service
from comicarr.app.library.directories import validateAndCreateDirectory
from comicarr.app.series.rescan import rescan_series


def movefiles(comicid, comlocation, imported):
    files_moved = []
    try:
        imported = ast.literal_eval(imported)
    except ValueError:
        pass

    logger.fdebug("comlocation is : " + comlocation)
    logger.fdebug("original comicname is : " + imported["ComicName"])

    impres = imported["filelisting"]

    if impres is not None:
        if all([comicarr.CONFIG.CREATE_FOLDERS is False, not os.path.isdir(comlocation)]):
            checkdirectory = validateAndCreateDirectory(comlocation, True)
            if not checkdirectory:
                logger.warn("Error trying to validate/create directory. Aborting this process at this time.")
                return

        for impr in impres:
            srcimp = impr["comiclocation"]
            orig_filename = impr["comicfilename"]
            if comicarr.CONFIG.IMP_RENAME and comicarr.CONFIG.FILE_FORMAT != "":
                logger.fdebug("Renaming files according to configuration details : " + str(comicarr.CONFIG.FILE_FORMAT))
                renameit = downloads_service.rename_param(
                    comicid, imported["ComicName"], impr["issuenumber"], orig_filename
                )
                nfilename = renameit["nfilename"]
                dstimp = os.path.join(comlocation, nfilename)
            else:
                logger.fdebug("Renaming files not enabled, keeping original filename(s)")
                dstimp = os.path.join(comlocation, orig_filename)

            logger.info("moving " + srcimp + " ... to " + dstimp)
            try:
                shutil.move(srcimp, dstimp)
                files_moved.append(
                    {"srid": imported["srid"], "filename": impr["comicfilename"], "import_id": impr["import_id"]}
                )
            except (OSError, IOError):
                logger.error("Failed to move files - check directories and manually re-run.")

        logger.fdebug("all files moved.")

    if len(files_moved) > 0:
        logger.info("files_moved: " + str(files_moved))
        for result in files_moved:
            try:
                result["import_id"]
            except Exception:
                controlValue = {"ComicFilename": result["filename"], "SRID": result["srid"]}
                newValue = {"Status": "Imported", "ComicID": comicid}
            else:
                controlValue = {"impID": result["import_id"], "ComicFilename": result["filename"]}
                newValue = {"Status": "Imported", "SRID": result["srid"], "ComicID": comicid}
            db.upsert("importresults", newValue, controlValue)
    return


def archivefiles(comicid, comlocation, imported):
    try:
        imported = ast.literal_eval(imported)
    except Exception as e:
        logger.warn("[%s] Error encountered converting import data" % e)

    imported["ComicName"]
    impres = imported["filelisting"]

    if impres is not None:
        scandir = []
        for impr in impres:
            srcimp = impr["comiclocation"]
            impr["comicfilename"]

            if not any(os.path.abspath(os.path.join(srcimp, os.pardir)) == x for x in scandir):
                scandir.append(os.path.abspath(os.path.join(srcimp, os.pardir)))

        for sdir in scandir:
            logger.info("Updating issue information and setting status to Archived for location: " + sdir)
            rescan_series(comicid, archive=sdir)

        logger.info("Now scanning in files.")
        rescan_series(comicid)

        for result in impres:
            try:
                result["import_id"]
            except Exception:
                controlValue = {"ComicFilename": result["comicfilename"], "SRID": imported["srid"]}
                newValue = {"Status": "Imported", "ComicID": comicid}
            else:
                controlValue = {"impID": result["import_id"], "ComicFilename": result["comicfilename"]}
                newValue = {"Status": "Imported", "SRID": imported["srid"], "ComicID": comicid}
            db.upsert("importresults", newValue, controlValue)

    return
