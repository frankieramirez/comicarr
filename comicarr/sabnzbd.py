#!/usr/bin/python
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

import ntpath
import os
import re
import time

import requests
from packaging.version import parse as parse_version

import comicarr
from comicarr import cdh_mapping, logger
from comicarr.app.common.redaction import redact_sensitive_text


class SABnzbd(object):
    def __init__(self, params):
        self.sab_url = comicarr.CONFIG.SAB_HOST + "/api"
        self.params = params

    def sender(self, nzbpath=None, chkstatus=False):
        """Hand an NZB to SABnzbd, or query the queue when chkstatus is set.

        ``nzbpath`` is the .nzb already cached by search.py. It is uploaded as
        multipart content (``mode=addfile``), so the handoff completes inside
        this one request and SAB never reaches back into Comicarr for the file.
        See docs/adr/0002-handoff-no-callback.md.
        """
        try:
            from requests.packages.urllib3 import disable_warnings

            disable_warnings()
        except:
            logger.warn("Unable to disable https warnings. Expect some spam if using https nzb providers.")

        files = None
        if chkstatus is not True:
            if not nzbpath:
                logger.error("No nzb file path was provided to send to SABnzbd.")
                return {"status": False}
            try:
                with open(nzbpath, "rb") as nzb_file:
                    nzb_content = nzb_file.read()
            except OSError as e:
                logger.error("Unable to read the cached nzb at %s: %s" % (nzbpath, e))
                return {"status": False}
            files = {"name": (os.path.basename(nzbpath), nzb_content, "application/x-nzb")}

        try:
            if chkstatus is True:
                sendit = requests.get(self.sab_url, params=self.params, verify=comicarr.CONFIG.SAB_VERIFY, timeout=30)
            else:
                tmp_apikey = self.params.pop("apikey")
                logger.fdebug("parameters set to %s" % self.params)
                self.params["apikey"] = tmp_apikey
                logger.fdebug("sending now to %s" % self.sab_url)
                sendit = requests.post(
                    self.sab_url,
                    data=self.params,
                    files=files,
                    verify=comicarr.CONFIG.SAB_VERIFY,
                    timeout=30,
                )
        except Exception as e:
            logger.warn(
                "[SAB-SEND] Failed to send to client. Error returned: %s"
                % redact_sensitive_text(e, secrets=(getattr(comicarr.CONFIG, "SAB_APIKEY", None),))
            )
            return {"status": False}
        else:
            sendresponse = sendit.json()
            if chkstatus is True:
                queueinfo = sendresponse["queue"]
                if str(queueinfo["status"]).lower() == "paused":
                    return {"status": True}
                else:
                    return {"status": False}

            if sendresponse["status"] is True:
                queue_params = {
                    "status": True,
                    "nzo_id": "".join(sendresponse["nzo_ids"]),
                    "queue": {
                        "mode": "queue",
                        "search": "".join(sendresponse["nzo_ids"]),
                        "output": "json",
                        "apikey": comicarr.CONFIG.SAB_APIKEY,
                    },
                }

            else:
                queue_params = {"status": False}

            return queue_params

    def processor(self):
        self.params["nzo_id"]
        try:
            logger.fdebug("sending now to %s" % self.sab_url)
            tmp_apikey = self.params["queue"].pop("apikey")
            self.params["queue"].pop("search")
            self.params["queue"]["nzo_ids"] = self.params["nzo_id"]
            if comicarr.CONFIG.SAB_CATEGORY is not None:
                self.params["queue"]["category"] = comicarr.CONFIG.SAB_CATEGORY
            logger.fdebug("[SAB-QUEUE] parameters set to %s" % self.params)
            self.params["queue"]["apikey"] = tmp_apikey
            time.sleep(5)
            h = requests.get(self.sab_url, params=self.params["queue"], verify=comicarr.CONFIG.SAB_VERIFY, timeout=30)
        except Exception as e:
            logger.fdebug(
                "[SAB-QUEUE] uh-oh: %s"
                % redact_sensitive_text(e, secrets=(getattr(comicarr.CONFIG, "SAB_APIKEY", None),))
            )
            return self.historycheck(self.params)
        else:
            queueresponse = h.json()
            logger.fdebug("successfully queried the queue for status")
            try:
                if queueresponse["noofslots"] == 1:
                    queueinfo = queueresponse["queue"]["slots"][0]
                    logger.info(
                        "monitoring ... detected download - %s [%s]" % (queueinfo["filename"], queueinfo["status"])
                    )
            except Exception:
                logger.warn("Unable to locate item within sabnzbd active queue - it could be finished already?")
                queueinfo = queueresponse["queue"]
            try:
                logger.fdebug("SABnzbd Queued item status : %s" % queueinfo["status"])
                logger.fdebug("SABnzbd Queued item mbleft : %s" % queueinfo["mbleft"])
                if str(queueinfo["status"]) == "Paused":
                    logger.warn("[WARNING] SABnzbd has the active queue Paused. CDH will not work in this state.")
                    return {"status": "queue_paused", "failed": False}
                while (
                    any(
                        [
                            str(queueinfo["status"]) == "Downloading",
                            str(queueinfo["status"]) == "Idle",
                            str(queueinfo["status"]) == "Queued",
                        ]
                    )
                    and float(queueinfo["mbleft"]) > 0
                ):
                    no_findie = False
                    tmp_queue = self.params["queue"]
                    try:
                        tmp_queue.pop("nzo_ids")
                    except Exception:
                        logger.fdebug("unable to pop nzo_id - possibly already done/finished/does not exist")
                        no_findie = True
                    tmp_queue["nzo_ids"] = self.params["nzo_id"]
                    queue_resp = requests.get(
                        self.sab_url, params=tmp_queue, verify=comicarr.CONFIG.SAB_VERIFY, timeout=30
                    )
                    queueresponse = queue_resp.json()
                    try:
                        queueinfo = queueresponse["queue"]["slots"][0]
                    except Exception:
                        try:
                            tmp_queue.pop("nzo_ids")
                        except Exception:
                            no_findie = True
                        else:
                            tmp_queue["nzo_ids"] = self.params["nzo_id"]
                            queueinfo = queueresponse["queue"]

                    logger.fdebug(
                        "status: %s -- mb_left: %s -- time_left: %s"
                        % (queueinfo["status"], queueinfo["mbleft"], queueinfo["timeleft"])
                    )
                    time.sleep(5)
                    if no_findie:
                        break
            except Exception as e:
                logger.warn("error: %s" % e)

            logger.info("File has now downloaded!")
            return self.historycheck(self.params)

    def historycheck(self, nzbinfo, roundtwo=False, extract_counter=1):
        sendresponse = nzbinfo["nzo_id"]
        hist_params = {"mode": "history", "failed": 0, "output": "json", "apikey": comicarr.CONFIG.SAB_APIKEY}

        if comicarr.CONFIG.SAB_CATEGORY is not None:
            hist_params["category"] = comicarr.CONFIG.SAB_CATEGORY

        sab_check = None
        if comicarr.CONFIG.SAB_VERSION is None:
            sab_check = self.sab_versioncheck()

        if sab_check == "some value":
            hist_params["limit"] = 200
        else:
            try:
                min_sab = "3.2.0"
                sab_vers = comicarr.CONFIG.SAB_VERSION
                if parse_version(sab_vers) >= parse_version(min_sab):
                    logger.fdebug("SABnzbd version is higher than 3.2.0. Querying history based on nzo_id directly.")
                    hist_params["nzo_ids"] = sendresponse
                else:
                    logger.fdebug("SABnzbd version is less than 3.2.0. Querying history based on history size of 200.")
                    hist_params["limit"] = 200
            except Exception as e:
                logger.warn(
                    "[SABNZBD-VERSION-CHECK] Exception encountered trying to compare installed version [%s] to [%s]. Setting history length to last 200 items. (error: %s)"
                    % (comicarr.CONFIG.SAB_VERSION, min_sab, e)
                )
                hist_params["limit"] = 200

        hist = requests.get(self.sab_url, params=hist_params, verify=comicarr.CONFIG.SAB_VERIFY, timeout=30)
        historyresponse = hist.json()
        histqueue = historyresponse["history"]
        found = {"status": False}
        nzo_exists = False

        try:
            for hq in histqueue["slots"]:
                logger.fdebug("nzo_id: %s --- %s [%s]" % (hq["nzo_id"], sendresponse, hq["status"]))
                if hq["nzo_id"] == sendresponse and any(
                    [hq["status"] == "Completed", hq["status"] == "Running", "comicrn" in hq["script"].lower()]
                ):
                    if hq["storage"] == "" and not roundtwo:
                        logger.fdebug(
                            f"[{hq['status']}] Storage entry was empty for Completed job.  Sleeping for {comicarr.CONFIG.SAB_MOVING_DELAY}s to allow the process to fully finish before trying again."
                        )
                        time.sleep(comicarr.CONFIG.SAB_MOVING_DELAY)
                        return self.historycheck(nzbinfo, roundtwo=True)

                    nzo_exists = True
                    logger.info("found matching completed item in history. Job has a status of %s" % hq["status"])
                    if "comicrn" in hq["script"].lower():
                        logger.warn(
                            "ComicRN has been detected as being active for this category & download. Completed Download Handling will NOT be performed due to this."
                        )
                        logger.warn(
                            "Either disable Completed Download Handling for SABnzbd within Comicarr, or remove ComicRN from your category script in SABnzbd."
                        )
                        self.remove_history(hq["nzo_id"], hq["status"])
                        return {"status": "double-pp", "failed": False}

                    if os.path.isfile(hq["storage"]):
                        logger.fdebug("location found @ %s" % hq["storage"])
                        found = {
                            "status": True,
                            "name": ntpath.basename(hq["storage"]),
                            "location": os.path.abspath(os.path.join(hq["storage"], os.pardir)),
                            "failed": False,
                            "issueid": nzbinfo["issueid"],
                            "comicid": nzbinfo["comicid"],
                            "apicall": True,
                            "ddl": False,
                            "download_info": nzbinfo["download_info"],
                        }
                        self.remove_history(hq["nzo_id"], hq["status"])
                        break

                    elif all(
                        [
                            comicarr.CONFIG.SAB_DIRECT_UNPACK,
                            comicarr.CONFIG.SAB_DIRECTORY is not None,
                            comicarr.CONFIG.SAB_DIRECTORY != "None",
                        ]
                    ):
                        try:
                            np = cdh_mapping.CDH_MAP(hq["storage"], sab=True)
                            new_path = np.the_sequence()
                        except Exception as e:
                            logger.warn(
                                "[ERROR] error returned during attempt to map [%s] --> root dir:[%s]. Error: %s"
                                % (hq["storage"], comicarr.CONFIG.SAB_DIRECTORY, e)
                            )
                            self.remove_history(hq["nzo_id"], hq["status"])
                            return {"status": "file not found", "failed": False}
                        else:
                            if new_path is None:
                                logger.warn(
                                    "[ERROR] Unable to remap the directory from SAB to Comicarr's configuration."
                                )
                                self.remove_history(hq["nzo_id"], hq["status"])
                                return {"status": "file not found", "failed": False}
                            elif not os.path.isfile(new_path):
                                logger.fdebug(
                                    "[ERROR] Unable to locate path (%s) on the machine that is running Comicarr. If Comicarr and sabnzbd are on separate machines, you need to set a directory location that is accessible to both"
                                    % (new_path)
                                )
                                self.remove_history(hq["nzo_id"], hq["status"])
                                return {"status": "file not found", "failed": False}

                        logger.fdebug("location found @ %s" % new_path)
                        found = {
                            "status": True,
                            "name": ntpath.basename(new_path),
                            "location": os.path.abspath(os.path.join(new_path, os.pardir)),
                            "failed": False,
                            "issueid": nzbinfo["issueid"],
                            "comicid": nzbinfo["comicid"],
                            "apicall": True,
                            "ddl": False,
                            "download_info": nzbinfo["download_info"],
                        }
                        self.remove_history(hq["nzo_id"], hq["status"])
                        break

                    else:
                        logger.error(
                            "no file found where it should be @ %s - is there another script that moves things after completion ?"
                            % hq["storage"]
                        )
                        self.remove_history(hq["nzo_id"], hq["status"])
                        return {"status": "file not found", "failed": False}

                elif hq["nzo_id"] == sendresponse and hq["status"] == "Failed":
                    nzo_exists = True
                    stage = hq["stage_log"]
                    logger.fdebug("stage: %s" % (stage,))
                    for x in stage:
                        if "Failed" in x["actions"] and any([x["name"] == "Unpack", x["name"] == "Repair"]):
                            if "moving" in x["actions"]:
                                logger.warn(
                                    "There was a failure in SABnzbd during the unpack/repair phase that caused a failure: %s"
                                    % x["actions"]
                                )
                            else:
                                logger.warn(
                                    "Failure occured during the Unpack/Repair phase of SABnzbd. This is probably a bad file: %s"
                                    % x["actions"]
                                )
                                if comicarr.FAILED_DOWNLOAD_HANDLING is True:
                                    found = {
                                        "status": True,
                                        "name": re.sub(".nzb", "", hq["nzb_name"]).strip(),
                                        "location": os.path.abspath(os.path.join(hq["storage"], os.pardir)),
                                        "failed": True,
                                        "issueid": nzbinfo["issueid"],
                                        "comicid": nzbinfo["comicid"],
                                        "apicall": True,
                                        "ddl": False,
                                        "download_info": nzbinfo["download_info"],
                                    }
                            self.remove_history(hq["nzo_id"], hq["status"])
                            break
                    if found["status"] is False:
                        self.remove_history(hq["nzo_id"], hq["status"])
                        return {"status": "failed_in_sab", "failed": False}
                    else:
                        break
                elif hq["nzo_id"] == sendresponse:
                    nzo_exists = True
                    logger.fdebug(
                        "nzo_id: %s found while processing queue in an unhandled status: %s"
                        % (hq["nzo_id"], hq["status"])
                    )
                    if (
                        hq["status"] in ["Queued", "Moving", "Extracting", "QuickCheck", "Repairing", "Verifying"]
                        and not roundtwo
                    ):
                        logger.fdebug(
                            "[%s(%s)] sleeping for %ss to allow the process to finish before trying again.."
                            % (hq["status"], extract_counter, comicarr.CONFIG.SAB_MOVING_DELAY)
                        )
                        time.sleep(comicarr.CONFIG.SAB_MOVING_DELAY)
                        if hq["status"] == "Extracting":
                            try:
                                to_delay = int(int(hq["bytes"]) / 25000000) + 2
                            except Exception:
                                to_delay = 4

                            if extract_counter < to_delay:
                                extract_counter += 1
                                return self.historycheck(nzbinfo, roundtwo=False, extract_counter=extract_counter)
                        return self.historycheck(nzbinfo, roundtwo=True)
                    else:
                        self.remove_history(hq["nzo_id"], hq["status"])
                        return {"failed": False, "status": "unhandled status of: %s" % (hq["status"])}

            if not nzo_exists:
                logger.error("Cannot find nzb %s in the queue.  Was it removed?" % sendresponse)
                logger.fdebug(
                    "sleeping for %ss to allow the process to finish before trying again.."
                    % (comicarr.CONFIG.SAB_MOVING_DELAY)
                )
                time.sleep(comicarr.CONFIG.SAB_MOVING_DELAY)
                if roundtwo is False:
                    return self.historycheck(nzbinfo, roundtwo=True)
                else:
                    return {"status": "nzb removed", "failed": False}
        except Exception as e:
            logger.warn("error %s" % (e,))
            self.remove_history(hq["nzo_id"], hq["status"])
            return {"status": False, "failed": False}

        return found

    def remove_history(self, nzo_id, status):
        logger.info("[Sabnzbd Completed History Removal] Download is complete - removing item from history..")
        if all([status == "Failed", comicarr.CONFIG.SAB_REMOVE_FAILED]) or comicarr.CONFIG.SAB_REMOVE_COMPLETED:
            hist_params = {
                "mode": "history",
                "name": "delete",
                "value": nzo_id,
                "output": "json",
                "apikey": comicarr.CONFIG.SAB_APIKEY,
            }

            if comicarr.CONFIG.SAB_REMOVE_FAILED:
                hist_params["del_files"] = 1

            try:
                rh = requests.get(self.sab_url, params=hist_params, verify=comicarr.CONFIG.SAB_VERIFY, timeout=30)
                rhistory = rh.json()
            except Exception as e:
                logger.warn("[Sabnzbd Completed History Removal] Unable to remove item - error returned: %s" % e)
            else:
                if rhistory["status"] is True:
                    logger.info("[Sabnzbd Completed History Removal] Item successfully removed from history..")
                else:
                    logger.warn("[Sabnzbd Completed History Removal] Unable to remove item from history..")

    def sab_versioncheck(self):
        params = {"mode": "version", "output": "json", "apikey": comicarr.CONFIG.SAB_APIKEY}
        try:
            response = requests.get(
                self.sab_url,
                params=params,
                verify=comicarr.CONFIG.SAB_VERIFY,
                timeout=30,
            )
        except Exception as e:
            logger.warn(
                "[SABNZBD-VERSION-TEST] Exception encountered trying to retrieve SABnzbd version: %s. Setting history length to last 200 items."
                % e
            )
            return "some value"

        if response.status_code != 200:
            logger.warn(
                "[SABNZBD-VERSION-TEST] SABnzbd version endpoint returned status %s. Setting history length to last 200 items."
                % response.status_code
            )
            return "some value"

        try:
            payload = response.json()
        except (TypeError, ValueError):
            version = response.text.strip()
        else:
            version = payload.get("version") if isinstance(payload, dict) else response.text.strip()

        if not version:
            logger.warn("[SABNZBD-VERSION-TEST] SABnzbd returned no version. Setting history length to last 200 items.")
            return "some value"

        comicarr.CONFIG.SAB_VERSION = str(version)
        logger.fdebug("[SABNZBD-VERSION-TEST] Detected SABnzbd version: %s" % comicarr.CONFIG.SAB_VERSION)
        return None
