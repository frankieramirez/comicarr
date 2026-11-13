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

"""The folder monitor: scan each monitored folder for finished downloads."""

import os

import comicarr
from comicarr import helpers, logger


class FolderCheck:
    """The scheduled ``monitor`` job."""

    def __init__(self):
        self.module = "[FOLDER-CHECK]"

    def run(self):
        if comicarr.IMPORTLOCK:
            logger.info(
                "There is an import currently running. In order to ensure successful import - deferring this until the import is finished."
            )
            return
        if comicarr.CONFIG.CHECK_FOLDER is None:
            logger.warn(
                "%s Unable to initialise folder monitor properly - you need to specify a folder to monitor first"
                % self.module
            )
            comicarr.SCHED.pause_job("monitor")
            comicarr.MONITOR_STATUS = "Paused"
            helpers.job_management(write=True)
        else:
            helpers.job_management(
                write=True, job="Folder Monitor", current_run=helpers.utctimestamp(), status="Running"
            )
            comicarr.MONITOR_STATUS = "Running"
            from comicarr.app.downloads import postprocessing
            from comicarr.app.downloads.pp_commands import monitored_folders

            for folder in monitored_folders(comicarr.CONFIG):
                if not os.path.isdir(folder) or not os.access(folder, os.R_OK | os.X_OK):
                    logger.warn("%s Skipping monitored folder %s: it is missing or unreadable" % (self.module, folder))
                    continue
                logger.info("%s Checking folder %s for newly snatched downloads" % (self.module, folder))
                outcome = postprocessing.run({"nzb_name": "Manual Run", "nzb_folder": folder, "source": "monitor"})
                if outcome.status == "busy":
                    comicarr.MONITOR_STATUS = "Waiting"
                    helpers.job_management(write=True, job="Folder Monitor", status="Waiting")
                    return {"status": "IN PROGRESS"}
            logger.info("%s Finished checking for newly snatched downloads" % self.module)
            helpers.job_management(
                write=True, job="Folder Monitor", last_run_completed=helpers.utctimestamp(), status="Waiting"
            )
