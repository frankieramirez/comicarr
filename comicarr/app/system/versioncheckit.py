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


import comicarr
from comicarr import logger
from comicarr.app.common import dates as common_dates
from comicarr.app.system import service as system_service
from comicarr.app.system import versioncheck


class CheckVersion:
    def __init__(self):
        pass

    def run(self, scheduled_job=True):
        logger.info("[VersionCheck] Checking for new release on Github.")
        system_service.job_management(
            write=True, job="Check Version", current_run=common_dates.utctimestamp(), status="Running"
        )
        comicarr.VERSION_STATUS = "Running"
        cc = versioncheck.checkGithub()
        system_service.job_management(
            write=True, job="Check Version", last_run_completed=common_dates.utctimestamp(), status="Waiting"
        )
        if not scheduled_job:
            return cc
