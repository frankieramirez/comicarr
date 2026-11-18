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

from comicarr.app.common import dates as common_dates
from comicarr.app.core import logger, runtime
from comicarr.app.system import service as system_service


class FolderCheck:
    """The scheduled ``monitor`` job."""

    def __init__(self):
        self.module = "[FOLDER-CHECK]"

    def run(self):
        if runtime.current().import_lock:
            logger.info(
                "There is an import currently running. In order to ensure successful import - deferring this until the import is finished."
            )
            return
        if runtime.current().config.CHECK_FOLDER is None:
            logger.warn(
                "%s Unable to initialise folder monitor properly - you need to specify a folder to monitor first"
                % self.module
            )
            runtime.current().scheduler.pause_job("monitor")
            runtime.current().monitor_status = "Paused"
            system_service.job_management(write=True)
        else:
            system_service.job_management(
                write=True, job="Folder Monitor", current_run=common_dates.utctimestamp(), status="Running"
            )
            runtime.current().monitor_status = "Running"
            from comicarr.app.downloads import postprocessing
            from comicarr.app.downloads.pp_commands import monitored_folders

            for folder in monitored_folders(runtime.current().config):
                if not os.path.isdir(folder) or not os.access(folder, os.R_OK | os.X_OK):
                    logger.warn("%s Skipping monitored folder %s: it is missing or unreadable" % (self.module, folder))
                    continue
                logger.info("%s Checking folder %s for newly snatched downloads" % (self.module, folder))
                outcome = postprocessing.run({"nzb_name": "Manual Run", "nzb_folder": folder, "source": "monitor"})
                if outcome.status == "busy":
                    runtime.current().monitor_status = "Waiting"
                    system_service.job_management(write=True, job="Folder Monitor", status="Waiting")
                    return {"status": "IN PROGRESS"}
            logger.info("%s Finished checking for newly snatched downloads" % self.module)
            system_service.job_management(
                write=True, job="Folder Monitor", last_run_completed=common_dates.utctimestamp(), status="Waiting"
            )
