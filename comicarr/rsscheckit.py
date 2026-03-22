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
from comicarr import auth32p, helpers, logger, rsscheck

rss_lock = threading.Lock()


class tehMain:
    def __init__(self):
        pass

    def run(self, forcerss=None):
        with rss_lock:
            # logger.info('[RSS-FEEDS] RSS Feed Check was last run at : ' + str(comicarr.SCHED_RSS_LAST))
            firstrun = "no"
            # check the last run of rss to make sure it's not hammering.
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
            # logger.fdebug('[RSS-FEEDS] Duration diff: %s' % duration_diff)
            if firstrun == "no" and duration_diff < int(comicarr.CONFIG.RSS_CHECKINTERVAL):
                logger.fdebug(
                    "[RSS-FEEDS] RSS Check has taken place less than the threshold - not initiating at this time."
                )
                return

            helpers.job_management(write=True, job="RSS Feeds", current_run=helpers.utctimestamp(), status="Running")
            comicarr.RSS_STATUS = "Running"
            # logger.fdebug('[RSS-FEEDS] Updated RSS Run time to : ' + str(comicarr.SCHED_RSS_LAST))

            # function for looping through nzbs/torrent feeds
            if comicarr.CONFIG.ENABLE_TORRENT_SEARCH:
                logger.info("[RSS-FEEDS] Initiating Torrent RSS Check.")
                if comicarr.CONFIG.ENABLE_PUBLIC:
                    logger.info("[RSS-FEEDS] Initiating Torrent RSS Feed Check on Demonoid / WorldWideTorrents.")
                    rsscheck.torrents(pickfeed="Public")  # TPSE = DEM RSS Check + WWT RSS Check
                if comicarr.CONFIG.ENABLE_32P is True:
                    logger.info("[RSS-FEEDS] Initiating Torrent RSS Feed Check on 32P.")
                    if comicarr.CONFIG.MODE_32P is False:
                        logger.fdebug("[RSS-FEEDS] 32P mode set to Legacy mode. Monitoring New Releases feed only.")
                        if any(
                            [
                                comicarr.CONFIG.PASSKEY_32P is None,
                                comicarr.CONFIG.PASSKEY_32P == "",
                                comicarr.CONFIG.RSSFEED_32P is None,
                                comicarr.CONFIG.RSSFEED_32P == "",
                            ]
                        ):
                            logger.error(
                                "[RSS-FEEDS] Unable to validate information from provided RSS Feed. Verify that the feed provided is a current one."
                            )
                        else:
                            rsscheck.torrents(pickfeed="1", feedinfo=comicarr.KEYS_32P)
                    else:
                        continue_search = True
                        logger.fdebug(
                            "[RSS-FEEDS] 32P mode set to Auth mode. Monitoring all personal notification feeds & New Releases feed"
                        )
                        if any(
                            [
                                comicarr.CONFIG.USERNAME_32P is None,
                                comicarr.CONFIG.USERNAME_32P == "",
                                comicarr.CONFIG.PASSWORD_32P is None,
                            ]
                        ):
                            logger.error(
                                "[RSS-FEEDS] Unable to sign-on to 32P to validate settings. Please enter/check your username password in the configuration."
                            )
                            continue_search = False
                        else:
                            if comicarr.KEYS_32P is None:
                                feed32p = auth32p.info32p(smode="RSS")
                                feedinfo = feed32p.authenticate()
                                if feedinfo["status"] is False and feedinfo["status_msg"] == "disable":
                                    helpers.disable_provider("32P")
                                    continue_search = False
                                elif feedinfo["status"] is False:
                                    logger.error(
                                        "[RSS-FEEDS] Unable to retrieve any information from 32P for RSS Feeds. Skipping for now."
                                    )
                                    continue_search = False
                                else:
                                    feeds = feedinfo["feedinfo"]
                            else:
                                feeds = comicarr.FEEDINFO_32P
                            if continue_search is True:
                                try:
                                    logger.fdebug("feedinfo: %s" % feedinfo)
                                except Exception:
                                    feedinfo = None
                                if feedinfo is None or all([len(feedinfo) == 0, feedinfo["status"] is False]):
                                    logger.error(
                                        "[RSS-FEEDS] Unable to retrieve any information from 32P for RSS Feeds. Skipping for now."
                                    )
                                else:
                                    rsscheck.torrents(pickfeed="1", feedinfo=comicarr.KEYS_32P)
                                    x = 0
                                    # assign personal feeds for 32p > +8
                                    for fi in feeds:
                                        x += 1
                                        pfeed_32p = str(7 + x)
                                        rsscheck.torrents(pickfeed=pfeed_32p, feedinfo=fi)

            logger.info("[RSS-FEEDS] Initiating RSS Feed Check for NZB Providers.")
            rsscheck.nzbs(forcerss=forcerss)
            if comicarr.CONFIG.ENABLE_DDL is True:
                logger.info("[RSS-FEEDS] Initiating RSS Feed Check for DDL Provider.")
                rsscheck.ddl(forcerss=forcerss)
            logger.info("[RSS-FEEDS] RSS Feed Check/Update Complete")
            logger.info("[RSS-FEEDS] Watchlist Check for new Releases")
            rss_start = datetime.datetime.now()
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
