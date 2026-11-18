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
from comicarr.app.common import dates as common_dates
from comicarr.app.core import logger, runtime
from comicarr.app.search import rss_feeds
from comicarr.app.system import service as system_service

rss_lock = threading.Lock()


class tehMain:
    def __init__(self):
        pass

    def run(self, forcerss=None):
        with rss_lock:
            firstrun = "no"
            if (
                runtime.current().sched_rss_last is None
                or runtime.current().sched_rss_last == ""
                or runtime.current().sched_rss_last == "0"
                or forcerss
            ):
                logger.info("[RSS-FEEDS] RSS Feed Check Initalizing....")
                firstrun = "yes"
                duration_diff = 0
            else:
                tstamp = float(runtime.current().sched_rss_last)
                duration_diff = abs(common_dates.utctimestamp() - tstamp) / 60
            if firstrun == "no" and duration_diff < int(runtime.current().config.RSS_CHECKINTERVAL):
                logger.fdebug(
                    "[RSS-FEEDS] RSS Check has taken place less than the threshold - not initiating at this time."
                )
                return

            system_service.job_management(
                write=True, job="RSS Feeds", current_run=common_dates.utctimestamp(), status="Running"
            )
            runtime.current().rss_status = "Running"

            if runtime.current().config.ENABLE_TORRENT_SEARCH:
                logger.info("[RSS-FEEDS] Initiating Torrent RSS Check.")
                if runtime.current().config.ENABLE_PUBLIC:
                    logger.info("[RSS-FEEDS] Initiating Torrent RSS Feed Check on Demonoid / WorldWideTorrents.")
                    rss_feeds.torrents(pickfeed="Public")

            logger.info("[RSS-FEEDS] Initiating RSS Feed Check for NZB Providers.")
            rss_feeds.nzbs(forcerss=forcerss)
            if runtime.current().config.ENABLE_DDL is True:
                logger.info("[RSS-FEEDS] Initiating RSS Feed Check for DDL Provider.")
                rss_feeds.ddl(forcerss=forcerss)
            logger.info("[RSS-FEEDS] RSS Feed Check/Update Complete")
            logger.info("[RSS-FEEDS] Watchlist Check for new Releases")
            rss_start = datetime.datetime.now()
            from comicarr.app.search.backlog import mark_rssdb_refreshed

            mark_rssdb_refreshed()
            comicarr.app.search.engine.searchforissue(rsschecker="yes")
            logger.fdebug("[RSS-FEEDS] RSS dbsearch/matching took: %s" % (datetime.datetime.now() - rss_start))
            logger.info("[RSS-FEEDS] Watchlist Check complete.")
            if forcerss:
                logger.info("[RSS-FEEDS] Successfully ran a forced RSS Check.")
            system_service.job_management(
                write=True, job="RSS Feeds", last_run_completed=common_dates.utctimestamp(), status="Waiting"
            )
            runtime.current().rss_status = "Waiting"
            return True
