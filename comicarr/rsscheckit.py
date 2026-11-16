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


import datetime
import threading

import comicarr
from comicarr import helpers, logger, rsscheck

rss_lock = threading.Lock()


class tehMain:
    def __init__(self):
        pass

    def run(self, forcerss=None):
        with rss_lock:
            firstrun = "no"
            if (
                comicarr.SCHED_RSS_LAST is None
                or comicarr.SCHED_RSS_LAST == ""
                or comicarr.SCHED_RSS_LAST == "0"
                or forcerss
            ):
                logger.info("[RSS-FEEDS] RSS Feed Check Initalizing....")
                firstrun = "yes"
                duration_diff = 0
            else:
                tstamp = float(comicarr.SCHED_RSS_LAST)
                duration_diff = abs(helpers.utctimestamp() - tstamp) / 60
            if firstrun == "no" and duration_diff < int(comicarr.CONFIG.RSS_CHECKINTERVAL):
                logger.fdebug(
                    "[RSS-FEEDS] RSS Check has taken place less than the threshold - not initiating at this time."
                )
                return

            helpers.job_management(write=True, job="RSS Feeds", current_run=helpers.utctimestamp(), status="Running")
            comicarr.RSS_STATUS = "Running"

            if comicarr.CONFIG.ENABLE_TORRENT_SEARCH:
                logger.info("[RSS-FEEDS] Initiating Torrent RSS Check.")
                if comicarr.CONFIG.ENABLE_PUBLIC:
                    logger.info("[RSS-FEEDS] Initiating Torrent RSS Feed Check on Demonoid / WorldWideTorrents.")
                    rsscheck.torrents(pickfeed="Public")

            logger.info("[RSS-FEEDS] Initiating RSS Feed Check for NZB Providers.")
            rsscheck.nzbs(forcerss=forcerss)
            if comicarr.CONFIG.ENABLE_DDL is True:
                logger.info("[RSS-FEEDS] Initiating RSS Feed Check for DDL Provider.")
                rsscheck.ddl(forcerss=forcerss)
            logger.info("[RSS-FEEDS] RSS Feed Check/Update Complete")
            logger.info("[RSS-FEEDS] Watchlist Check for new Releases")
            rss_start = datetime.datetime.now()
            from comicarr.app.search.backlog import mark_rssdb_refreshed

            mark_rssdb_refreshed()
            comicarr.search.searchforissue(rsschecker="yes")
            logger.fdebug("[RSS-FEEDS] RSS dbsearch/matching took: %s" % (datetime.datetime.now() - rss_start))
            logger.info("[RSS-FEEDS] Watchlist Check complete.")
            if forcerss:
                logger.info("[RSS-FEEDS] Successfully ran a forced RSS Check.")
            helpers.job_management(
                write=True, job="RSS Feeds", last_run_completed=helpers.utctimestamp(), status="Waiting"
            )
            comicarr.RSS_STATUS = "Waiting"
            return True
