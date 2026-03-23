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
import re

import requests
from sqlalchemy import and_, delete

import comicarr
from comicarr import db, logger
from comicarr.helpers import ignored_publisher_check
from comicarr.tables import weekly


def locg(pulldate=None, weeknumber=None, year=None):

    todaydate = datetime.datetime.today().replace(second=0, microsecond=0)
    if pulldate:
        logger.info("pulldate is : " + str(pulldate))
        if pulldate is None or pulldate == "00000000":
            weeknumber = todaydate.strftime("%U")
        elif "-" in pulldate:
            # find the week number
            weektmp = datetime.date(*(int(s) for s in pulldate.split("-")))
            weeknumber = weektmp.strftime("%U")
            # we need to now make sure we default to the correct week
            weeknumber_new = todaydate.strftime("%U")
            if weeknumber_new > weeknumber:
                weeknumber = weeknumber_new

    else:
        if str(weeknumber).isdigit() and int(weeknumber) <= 52:
            # already requesting week #
            weeknumber = weeknumber
        else:
            logger.warn("Invalid date requested. Aborting pull-list retrieval/update at this time.")
            return {"status": "failure"}

    if year is None:
        year = todaydate.strftime("%Y")

    params = {"week": str(weeknumber), "year": str(year)}

    url = "https://walksoftly.itsaninja.party/newcomics.php"

    try:
        r = requests.get(
            url,
            params=params,
            verify=True,
            headers={
                "User-Agent": comicarr.USER_AGENT[: comicarr.USER_AGENT.find("/") + 7]
                + comicarr.USER_AGENT[comicarr.USER_AGENT.find("(") + 1]
            },
        )
    except requests.exceptions.RequestException as e:
        logger.warn("[PULL-LIST] Error encountered retrieving pull-list: %s" % (e,))
        comicarr.BACKENDSTATUS_WS = "down"
        return {"status": "failure"}

    if str(r.status_code) == "619":
        logger.warn("[%s] No date supplied, or an invalid date was provided [%s]" % (r.status_code, pulldate))
        return {"status": "failure"}
    elif str(r.status_code) == "522":
        logger.warn(
            "[%s] Walksoftly is currently offline. Data shown may be stale until it comes back online"
            % (r.status_code,)
        )
        comicarr.BACKENDSTATUS_WS = "down"
        return {"status": "failure"}
    elif str(r.status_code) == "999" or str(r.status_code) == "111":
        logger.warn(
            "[%s] Unable to retrieve data from site - this is a site.specific issue [%s]" % (r.status_code, pulldate)
        )
        comicarr.BACKENDSTATUS_WS = "down"
        return {"status": "failure"}
    elif str(r.status_code) == "200":
        data = r.json()

        comicarr.BACKENDSTATUS_WS = "up"

        logger.info("[WEEKLY-PULL] There are %s issues for week %s, %s" % (len(data), weeknumber, year))
        pull = []

        for x in data:
            # ignore specific publishers on a global scale here.
            if ignored_publisher_check(x["publisher"]):
                continue

            pull.append(
                {
                    "series": x["series"],
                    "alias": x["alias"],
                    "issue": x["issue"],
                    "publisher": x["publisher"],
                    "shipdate": x["shipdate"],
                    "coverdate": x["coverdate"],
                    "comicid": x["comicid"],
                    "issueid": x["issueid"],
                    "weeknumber": x["weeknumber"],
                    "annuallink": x["link"],
                    "year": x["year"],
                    "volume": x["volume"],
                    "seriesyear": x["seriesyear"],
                    "format": x["type"],
                }
            )
            x["shipdate"]

        # Ensure the weekly table exists (created via tables.py metadata)
        from comicarr.tables import metadata as table_metadata
        table_metadata.create_all(db.get_engine(), tables=[weekly], checkfirst=True)

        # clear out the upcoming table here so they show the new values properly.
        # if pulldate == '00000000':
        # 2021-07-03 -> we should always clear out the table to ensure we don't have old data mixed with fresh.
        if len(pull) == 0:
            logger.warn(
                "[PULL-LIST] Weekly pull for week %s, %s has no data. This is probably a back-end related error of some kind."
                % (weeknumber, year)
            )
            return {"status": "failure"}

        logger.info("Re-creating pullist to ensure everything's fresh.")
        with db.get_engine().begin() as conn:
            conn.execute(
                delete(weekly).where(
                    and_(
                        weekly.c.weeknumber == int(weeknumber),
                        weekly.c.year == int(year),
                    )
                )
            )

        for x in pull:
            comicid = None
            issueid = None
            comicname = x["series"]
            if x["comicid"] is not None:
                comicid = x["comicid"]
            if x["issueid"] is not None:
                issueid = x["issueid"]
            # if x['alias'] is not None:
            #    comicname = x['alias']

            cl_d = comicarr.filechecker.FileChecker()
            cl_dyninfo = cl_d.dynamic_replace(comicname)
            dynamic_name = re.sub(r"[\|\s]", "", cl_dyninfo["mod_seriesname"].lower()).strip()

            controlValueDict = {"DynamicName": dynamic_name, "ISSUE": re.sub("#", "", x["issue"]).strip()}

            newValueDict = {
                "SHIPDATE": x["shipdate"],
                "PUBLISHER": x["publisher"],
                "STATUS": "Skipped",
                "COMIC": comicname,
                "ComicID": comicid,
                "IssueID": issueid,
                "weeknumber": x["weeknumber"],
                "annuallink": x["annuallink"],
                "year": x["year"],
                "volume": x["volume"],
                "seriesyear": x["seriesyear"],
                "format": x["format"],
            }
            db.upsert("weekly", newValueDict, controlValueDict)

        logger.info("[PULL-LIST] Successfully populated pull-list into Comicarr for week %s of %s" % (weeknumber, year))
        # set the last poll date/time here so that we don't start overwriting stuff too much...
        comicarr.CONFIG.PULL_REFRESH = todaydate.strftime("%Y-%m-%d %H:%M:%S")
        comicarr.CONFIG.writeconfig(values={"pull_refresh": comicarr.CONFIG.PULL_REFRESH})

        return {"status": "success", "count": len(data), "weeknumber": weeknumber, "year": year}

    else:
        if str(r.status_code) == "666":
            logger.warn("[%s] The error returned is: %s" % (r.status_code, r.headers))
            return {"status": "update_required"}
        else:
            logger.warn("[%s] The error returned is: %s" % (r.status_code, r.headers))
            return {"status": "failure"}
