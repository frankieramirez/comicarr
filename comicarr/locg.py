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
from email.utils import parsedate_to_datetime

import requests
from sqlalchemy import and_, delete

import comicarr
from comicarr import db, logger
from comicarr.helpers import ignored_publisher_check
from comicarr.tables import weekly

CLOUDFLARE_ORIGIN_ERRORS = {
    "520": "returned an unknown error",
    "521": "is down",
    "522": "timed out while connecting",
    "523": "is unreachable",
    "524": "timed out while responding",
}


def _retry_advice(retry_after):
    """Phrase a Retry-After value, which is either delta-seconds or an HTTP date."""
    value = str(retry_after or "").strip()
    if not value:
        return ""
    if value.isdigit():
        return " Upstream asked us to retry in %s seconds." % value
    return " Upstream asked us to retry after %s." % value


def _retry_after_seconds(retry_after):
    """Parse a Retry-After header into whole seconds from now, or None."""
    value = str(retry_after or "").strip()
    if not value:
        return None
    if value.isdigit():
        seconds = int(value)
    else:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=datetime.timezone.utc)
        seconds = int((retry_at - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
    return seconds if seconds > 0 else None


def locg(pulldate=None, weeknumber=None, year=None):

    todaydate = datetime.datetime.today().replace(second=0, microsecond=0)
    if pulldate:
        logger.info("pulldate is : " + str(pulldate))
        if pulldate is None or pulldate == "00000000":
            weeknumber = todaydate.strftime("%U")
        elif "-" in pulldate:
            weektmp = datetime.date(*(int(s) for s in pulldate.split("-")))
            weeknumber = weektmp.strftime("%U")
            weeknumber_new = todaydate.strftime("%U")
            if weeknumber_new > weeknumber:
                weeknumber = weeknumber_new

    else:
        if str(weeknumber).isdigit() and int(weeknumber) <= 52:
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
    elif str(r.status_code) in CLOUDFLARE_ORIGIN_ERRORS:
        logger.warn(
            "[%s] Walksoftly %s, so it is currently unreachable. Data shown may be stale until it comes back online.%s"
            % (
                r.status_code,
                CLOUDFLARE_ORIGIN_ERRORS[str(r.status_code)],
                _retry_advice(r.headers.get("Retry-After")),
            )
        )
        comicarr.BACKENDSTATUS_WS = "down"
        failure = {"status": "failure"}
        retry_after = _retry_after_seconds(r.headers.get("Retry-After"))
        if retry_after is not None:
            failure["retry_after"] = retry_after
        return failure
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

        from comicarr.tables import metadata as table_metadata

        table_metadata.create_all(db.get_engine(), tables=[weekly], checkfirst=True)

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
        pull_refresh = todaydate.strftime("%Y-%m-%d %H:%M:%S")
        comicarr.CONFIG.writeconfig(values={"pull_refresh": pull_refresh})

        return {"status": "success", "count": len(data), "weeknumber": weeknumber, "year": year}

    else:
        if str(r.status_code) == "666":
            logger.warn("[%s] The error returned is: %s" % (r.status_code, r.headers))
            return {"status": "update_required"}
        else:
            logger.warn("[%s] The error returned is: %s" % (r.status_code, r.headers))
            return {"status": "failure"}
