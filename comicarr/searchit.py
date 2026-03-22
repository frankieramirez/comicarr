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

from comicarr import logger, helpers

class CurrentSearcher():
    def __init__(self, **kwargs):
        pass

    def run(self):

        logger.info('[SEARCH] Running Search for Wanted.')
        helpers.job_management(write=True, job='Auto-Search', current_run=helpers.utctimestamp(), status='Running')
        comicarr.SEARCH_STATUS = 'Running'
        comicarr.search.searchforissue()
        helpers.job_management(write=True, job='Auto-Search', last_run_completed=helpers.utctimestamp(), status='Waiting')
        #comicarr.SEARCH_STATUS = 'Waiting'
        #comicarr.SCHED_SEARCH_LAST = helpers.now()
