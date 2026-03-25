#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Metadata domain service — ComicVine, Metron, MangaDex provider wrappers.

Module-level functions wrapping the existing provider modules.
Preserves ThreadPoolExecutor batch enrichment for cover image backfill.
"""

import json
import os
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path

import requests
from PIL import Image

import comicarr
from comicarr import db, getimage, logger, updater


def search_comics(
    ctx, name, issue=None, type_="comic", mode="series", limit=None, offset=None, sort=None, content_type=None
):
    """Search for comics across configured providers.

    Delegates to search domain's find_comic() to avoid duplicated logic.
    """
    from comicarr.app.search.service import find_comic

    return find_comic(
        ctx,
        name,
        issue=issue,
        type_=type_,
        mode=mode,
        limit=limit,
        offset=offset,
        sort=sort,
        content_type=content_type,
    )


def search_manga(ctx, name, limit=None, offset=None, sort=None):
    """Search for manga via MangaDex API."""
    if not ctx.config or not getattr(ctx.config, "MANGADEX_ENABLED", False):
        return {"error": "MangaDex integration is not enabled"}

    from comicarr import mangadex

    try:
        parsed_limit = int(limit) if limit else None
        parsed_offset = int(offset) if offset else None
    except (ValueError, TypeError):
        return {"error": "Invalid pagination parameters"}

    return mangadex.search_manga(name, limit=parsed_limit, offset=parsed_offset, sort=sort)


def get_series_image(ctx, series_id):
    """Get cover image URL for a Metron series (lazy loading)."""
    try:
        int(series_id)
    except (ValueError, TypeError):
        return None

    from comicarr import metron

    return metron.get_series_image(series_id)


def get_comic_info(ctx, comic_id):
    """Get comic metadata from database."""
    from sqlalchemy import select

    from comicarr import db
    from comicarr.tables import comics as t_comics

    stmt = select(t_comics).where(t_comics.c.ComicID == comic_id)
    results = db.select_all(stmt)
    if results and len(results) == 1:
        return results[0]
    return None


def get_issue_info(ctx, issue_id):
    """Get issue metadata from database."""
    from sqlalchemy import select

    from comicarr import db
    from comicarr.tables import issues as t_issues

    stmt = select(t_issues).where(t_issues.c.IssueID == issue_id)
    results = db.select_all(stmt)
    if results and len(results) == 1:
        return results[0]
    return None


def get_artwork(ctx, comic_id):
    """Get or cache comic artwork. Returns file path or None."""
    from PIL import Image

    cache_dir = getattr(ctx.config, "CACHE_DIR", None) if ctx.config else None
    if not cache_dir:
        return None

    image_path = os.path.join(cache_dir, str(comic_id) + ".jpg")

    if os.path.isfile(image_path):
        try:
            img = Image.open(image_path)
            if img.get_format_mimetype():
                return image_path
        except Exception:
            pass

    # Try fetching from DB URLs
    import urllib.request

    from sqlalchemy import select

    from comicarr import db
    from comicarr.tables import comics as t_comics

    comic = db.select_all(select(t_comics).where(t_comics.c.ComicID == comic_id))
    if not comic:
        return None

    img_data = None
    for url_key in ["ComicImageURL", "ComicImageALTURL"]:
        url = comic[0].get(url_key)
        if url:
            try:
                img_data = urllib.request.urlopen(url).read()
                break
            except Exception:
                continue

    if img_data:
        try:
            from io import BytesIO

            img = Image.open(BytesIO(img_data))
            if img.get_format_mimetype():
                with open(image_path, "wb") as f:
                    f.write(img_data)
                return image_path
        except Exception:
            pass

    return None


def manual_metatag(ctx, issue_id, comic_id=None):
    """Tag metadata for a single issue."""
    try:
        _do_manual_metatag(issue_id, comicid=comic_id)
        return {"success": True}
    except Exception as e:
        logger.error("[METADATA] Metatag error: %s" % e)
        return {"success": False, "error": str(e)}


def bulk_metatag(ctx, comic_id, issue_ids):
    """Tag metadata for multiple issues."""
    try:
        _do_bulk_metatag(comic_id, issue_ids)
        return {"success": True, "count": len(issue_ids)}
    except Exception as e:
        logger.error("[METADATA] Bulk metatag error: %s" % e)
        return {"success": False, "error": str(e)}


def group_metatag(ctx, comic_id):
    """Tag metadata for all issues in a series."""
    try:
        _do_group_metatag(comic_id)
        return {"success": True}
    except Exception as e:
        logger.error("[METADATA] Group metatag error: %s" % e)
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Metatag implementation (extracted from webserve.WebInterface)
# ---------------------------------------------------------------------------


def _do_manual_metatag(issueid, comicid=None, group=False):
    """Tag metadata for a single issue. Extracted from WebInterface.manual_metatag."""
    module = "[MANUAL META-TAGGING]"
    try:
        issuedata = db.raw_select_one(
            "SELECT a.ComicVersion, a.ComicLocation, a.ComicYear, a.AgeRating, b.* FROM comics a LEFT JOIN issues b ON a.ComicID=b.ComicID WHERE b.IssueID=?",
            [issueid],
        )
        if not issuedata:
            issuedata = db.raw_select_one(
                "SELECT a.ComicVersion, a.ComicLocation, a.ComicYear, a.AgeRating, b.* FROM comics a LEFT JOIN annuals b ON a.ComicID=b.ComicID WHERE b.IssueID=? AND b.Deleted != 1",
                [issueid],
            )
            if not issuedata:
                comicarr.GLOBAL_MESSAGES = {
                    "status": "failure",
                    "comicname": None,
                    "seriesyear": None,
                    "comicid": comicid,
                    "tables": "both",
                    "message": "Unable to locate corresponding issueid: %s" % issueid,
                }
                return

        comversion = issuedata["ComicVersion"]
        dirName = issuedata["ComicLocation"]
        filename = os.path.join(dirName, issuedata["Location"])
        if not os.path.exists(filename):
            file_check = list(Path(dirName).rglob("*" + issuedata["Location"]))
            if len(file_check) > 0:
                filename = str(file_check[0])
                dirName = str(Path(filename).parent.absolute())

        if not os.path.exists(filename):
            if all([comicarr.CONFIG.MULTIPLE_DEST_DIRS is not None, comicarr.CONFIG.MULTIPLE_DEST_DIRS != "None"]):
                if os.path.exists(os.path.join(comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(dirName))):
                    secondary_folder = os.path.join(comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(dirName))
                else:
                    ff = comicarr.filers.FileHandlers(ComicID=issuedata["ComicID"])
                    secondary_folder = ff.secondary_folders(dirName)

                if os.path.join(secondary_folder, os.path.basename(filename)):
                    dirName = secondary_folder
                    filename = os.path.join(secondary_folder, os.path.basename(filename))
                    if not os.path.exists(filename):
                        file_check = list(Path(dirName).rglob("*" + issuedata["Location"]))
                        if len(file_check) > 0:
                            filename = str(file_check[0])
                            dirName = str(Path(filename).parent.absolute())

        if not os.path.exists(filename):
            logger.warn(
                "%s %s does not exist in the given location. Cannot metatag this filename due to this."
                % (module, filename)
            )
            comicarr.GLOBAL_MESSAGES = {
                "status": "failure",
                "comicname": None,
                "seriesyear": None,
                "comicid": comicid,
                "tables": "both",
                "message": "Unable to locate corresponding filename: %s" % filename,
            }
            return

        comicid = issuedata["ComicID"]
        seriesyear = issuedata["ComicYear"]
        agerating = issuedata["AgeRating"]
        comicname = issuedata["ComicName"]

        from comicarr import cmtag

        if comicarr.CONFIG.CMTAG_START_YEAR_AS_VOLUME:
            if all([seriesyear is not None, seriesyear != "None"]):
                vol_label = seriesyear
            else:
                logger.warn(
                    "Cannot populate the year for the series for some reason. Dropping down to numeric volume label."
                )
                vol_label = comversion
        else:
            vol_label = comversion

        readingorder = None
        if all([issueid is not None, comicid is not None]):
            roders = db.raw_select_all(
                "SELECT StoryArc, ReadingOrder from storyarcs WHERE ComicID=? AND IssueID=?", [comicid, issueid]
            )
            if roders is not None:
                readingorder = []
                for rd in roders:
                    readingorder.append((rd["StoryArc"], rd["ReadingOrder"]))
                logger.fdebug("readingorder: %s" % (readingorder))

        metaresponse = cmtag.run(
            dirName,
            issueid=issueid,
            filename=filename,
            comversion=vol_label,
            manualmeta=True,
            readingorder=readingorder,
            agerating=agerating,
        )
    except ImportError:
        logger.warn(
            module
            + " comictaggerlib not found on system. Ensure the ENTIRE lib directory is located within comicarr/lib/comictaggerlib/ directory."
        )
        metaresponse = "fail"

    dst_filename = None
    if metaresponse == "fail":
        logger.fdebug(module + " Unable to write metadata successfully - check comicarr.log file.")
        comicarr.GLOBAL_MESSAGES = {
            "status": "failure",
            "comicname": comicname,
            "seriesyear": seriesyear,
            "comicid": comicid,
            "tables": "both",
            "message": "Unable to write metadata - there were errors. Check the log files",
        }
        return
    elif metaresponse == "unrar error":
        logger.error(
            module
            + " This is a corrupt archive - whether CRC errors or it is incomplete. Marking as BAD, and retrying a different copy."
        )
        comicarr.GLOBAL_MESSAGES = {
            "status": "failure",
            "comicname": comicname,
            "seriesyear": seriesyear,
            "comicid": comicid,
            "tables": "both",
            "message": "%s is a corrupt archive." % filename,
        }
        return
    else:
        dst_filename = os.path.split(metaresponse)[1]
        dst = os.path.join(dirName, dst_filename)
        fail = False
        try:
            shutil.copy(metaresponse, dst)
            logger.info("%s Sucessfully wrote metadata to .cbz (%s) - Continuing.." % (module, dst_filename))
        except Exception as e:
            if str(e.errno) == "2":
                try:
                    if all(
                        [
                            comicarr.CONFIG.MULTIPLE_DEST_DIRS is not None,
                            comicarr.CONFIG.MULTIPLE_DEST_DIRS != "None",
                        ]
                    ):
                        if os.path.exists(os.path.join(comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(dirName))):
                            secondary_folder = os.path.join(
                                comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(dirName)
                            )
                        else:
                            ff = comicarr.filers.FileHandlers(ComicID=comicid)
                            secondary_folder = ff.secondary_folders(dirName)

                        shutil.copy(metaresponse, secondary_folder)
                        logger.info(
                            "%s Sucessfully wrote metadata to .cbz (%s) - Continuing.." % (module, dst_filename)
                        )
                except Exception as e:
                    logger.warn(
                        "%s [%s] Unable to complete metatagging : %s [%s]" % (module, secondary_folder, e, e.errno)
                    )
                    fail = True
            else:
                logger.warn("%s [%s] Unable to complete metatagging : %s [%s]" % (module, dst, e, e.errno))
                fail = True
        if not fail:
            cache_dir = os.path.split(metaresponse)[0]
            if os.path.isfile(metaresponse):
                try:
                    os.remove(metaresponse)
                except OSError:
                    pass

            if not os.listdir(cache_dir):
                logger.fdebug("%s Tidying up. Deleting temporary cache directory: %s" % (module, cache_dir))
                try:
                    shutil.rmtree(cache_dir)
                except Exception:
                    logger.warn(module + " Unable to remove temporary directory: %s" % cache_dir)
            else:
                logger.fdebug("Failed to remove temporary directory: %s" % cache_dir)

            if filename is not None:
                if os.path.isfile(filename) and os.path.split(filename)[1].lower() != dst_filename.lower():
                    try:
                        logger.fdebug("%s Removing original filename: %s" % (module, filename))
                        os.remove(filename)
                    except OSError:
                        pass

    if all([group is False, fail is False]):
        updater.forceRescan(comicid)
        if group is False:
            comicarr.GLOBAL_MESSAGES = {
                "status": "success",
                "comicname": comicname,
                "seriesyear": seriesyear,
                "comicid": comicid,
                "tables": "both",
                "message": "Successfully meta-tagged %s" % dst_filename,
            }
    elif all([group is False, fail is True]):
        comicarr.GLOBAL_MESSAGES = {
            "status": "failure",
            "comicname": comicname,
            "seriesyear": seriesyear,
            "comicid": comicid,
            "tables": "both",
            "message": "Metatagging was not successful for %s" % dst_filename,
        }


def _thread_bulk_meta(comicinfo, issueinfo):
    """Worker thread for bulk metatag. Extracted from WebInterface.thread_that_bulk_meta."""
    for ginfo in issueinfo:
        _do_manual_metatag(ginfo["IssueID"], group=True)
    updater.forceRescan(comicinfo["ComicID"])
    logger.info(
        "[SERIES-METATAGGER][%s (%s)] Finished (re)tagging of metadata for selected issues."
        % (comicinfo["ComicName"], comicinfo["ComicYear"])
    )
    issueline = "%s issues" % len(issueinfo)
    if len(issueinfo) == 1:
        issueline = "1 issue"
    comicarr.GLOBAL_MESSAGES = {
        "status": "success",
        "comicname": comicinfo["ComicName"],
        "seriesyear": comicinfo["ComicYear"],
        "comicid": comicinfo["ComicID"],
        "tables": "both",
        "message": "Finished (re)tagging of %s of %s (%s)"
        % (issueline, comicinfo["ComicName"], comicinfo["ComicYear"]),
    }


def _do_bulk_metatag(ComicID, IssueIDs, threaded=False):
    """Tag metadata for selected issues. Extracted from WebInterface.bulk_metatag."""
    cinfo = db.raw_select_one(
        "SELECT ComicLocation, ComicVersion, ComicYear, ComicName, AgeRating FROM comics WHERE ComicID=?", [ComicID]
    )

    comicinfo = {
        "ComicID": ComicID,
        "ComicName": cinfo["ComicName"],
        "ComicYear": cinfo["ComicYear"],
        "ComicVersion": cinfo["ComicVersion"],
        "AgeRating": cinfo["AgeRating"],
        "meta_dir": cinfo["ComicLocation"],
    }

    if not isinstance(IssueIDs, list):
        IssueIDs = [IssueIDs]

    placeholders = ",".join(["?" for _ in IssueIDs])
    query_params = [ComicID] + IssueIDs
    groupinfo = db.raw_select_all(
        "SELECT IssueID, Location FROM issues WHERE ComicID=? and IssueID IN (%s) and Location IS NOT NULL"
        % placeholders,
        query_params,
    )
    if comicarr.CONFIG.ANNUALS_ON:
        groupinfo += db.raw_select_all(
            "SELECT IssueID, Location FROM annuals WHERE ComicID=? and IssueID IN (%s) and Location IS NOT NULL"
            % placeholders,
            query_params,
        )

    if len(groupinfo) == 0:
        logger.warn("No issues physically exist for me to (re)-tag.")
        return

    if comicarr.CONFIG.CV_BATCH_LIMIT_PROTECTION and len(groupinfo) > comicarr.CONFIG.CV_BATCH_LIMIT_THRESHOLD:
        warningMessage = (
            "CV Batch Limit Protection (%s) has been triggered trying to tag %s issues.  This will likely breach ComicVine API Limits."
            % (comicarr.CONFIG.CV_BATCH_LIMIT_THRESHOLD, len(groupinfo))
        )
        logger.warn(
            "[SERIES-METATAGGER][%s (%s)] %s" % (comicinfo["ComicName"], comicinfo["ComicYear"], warningMessage)
        )
        comicarr.GLOBAL_MESSAGES = {
            "status": "failure",
            "comicname": cinfo["ComicName"],
            "seriesyear": cinfo["ComicYear"],
            "comicid": ComicID,
            "tables": "both",
            "message": warningMessage,
        }
        return

    issueinfo = []
    for ginfo in groupinfo:
        issueinfo.append({"IssueID": ginfo["IssueID"], "Location": ginfo["Location"]})

    if threaded is False:
        threading.Thread(target=_thread_bulk_meta, args=[comicinfo, issueinfo]).start()
        return json.dumps({"status": "success"})
    else:
        _thread_bulk_meta(comicinfo, issueinfo)
        return json.dumps({"status": "success"})


def _thread_group_meta(comicinfo, issueinfo):
    """Worker thread for group metatag. Extracted from WebInterface.thread_that_meta."""
    for ginfo in issueinfo:
        _do_manual_metatag(ginfo["IssueID"], group=True)
    updater.forceRescan(comicinfo["ComicID"])
    logger.info(
        "[SERIES-METATAGGER][%s (%s)] Finished complete series (re)tagging of metadata."
        % (comicinfo["ComicName"], comicinfo["ComicYear"])
    )
    issueline = "%s issues" % len(issueinfo)
    if len(issueinfo) == 1:
        issueline = "1 issue"
    comicarr.GLOBAL_MESSAGES = {
        "status": "success",
        "comicname": comicinfo["ComicName"],
        "seriesyear": comicinfo["ComicYear"],
        "comicid": comicinfo["ComicID"],
        "tables": "both",
        "message": "Finished complete series (re)tagging of %s of %s (%s)"
        % (issueline, comicinfo["ComicName"], comicinfo["ComicYear"]),
    }


def _do_group_metatag(ComicID, threaded=False):
    """Tag metadata for all issues in a series. Extracted from WebInterface.group_metatag."""
    cinfo = db.raw_select_one(
        "SELECT ComicLocation, ComicVersion, ComicYear, ComicName, AgeRating FROM comics WHERE ComicID=?", [ComicID]
    )

    comicinfo = {
        "ComicID": ComicID,
        "ComicName": cinfo["ComicName"],
        "ComicYear": cinfo["ComicYear"],
        "ComicVersion": cinfo["ComicVersion"],
        "AgeRating": cinfo["AgeRating"],
        "meta_dir": cinfo["ComicLocation"],
    }

    groupinfo = db.raw_select_all(
        "SELECT IssueID, Location FROM issues WHERE ComicID=? and Location IS NOT NULL", [ComicID]
    )
    if comicarr.CONFIG.ANNUALS_ON:
        groupinfo += db.raw_select_all(
            "SELECT IssueID, Location FROM annuals WHERE ComicID=? and Location IS NOT NULL", [ComicID]
        )

    if len(groupinfo) == 0:
        logger.warn("No issues physically exist within the series directory for me to (re)-tag.")
        return

    if comicarr.CONFIG.CV_BATCH_LIMIT_PROTECTION and len(groupinfo) > comicarr.CONFIG.CV_BATCH_LIMIT_THRESHOLD:
        warningMessage = (
            "CV Batch Limit Protection (%s) has been triggered trying to tag %s issues.  This will likely breach ComicVine API Limits."
            % (comicarr.CONFIG.CV_BATCH_LIMIT_THRESHOLD, len(groupinfo))
        )
        logger.warn(
            "[SERIES-METATAGGER][%s (%s)] %s" % (comicinfo["ComicName"], comicinfo["ComicYear"], warningMessage)
        )
        comicarr.GLOBAL_MESSAGES = {
            "status": "failure",
            "comicname": cinfo["ComicName"],
            "seriesyear": cinfo["ComicYear"],
            "comicid": ComicID,
            "tables": "both",
            "message": warningMessage,
        }
        return

    issueinfo = []
    for ginfo in groupinfo:
        issueinfo.append({"IssueID": ginfo["IssueID"], "Location": ginfo["Location"]})

    if threaded is False:
        threading.Thread(target=_thread_group_meta, args=[comicinfo, issueinfo]).start()
        return json.dumps({"status": "success"})
    else:
        _thread_group_meta(comicinfo, issueinfo)
        return json.dumps({"status": "success"})


# --- Extracted from helpers.py ---


def IssueDetails(filelocation, IssueID=None, justinfo=False, comicname=None):
    from xml.dom.minidom import parseString

    issuetag = None
    if any([filelocation == "None", filelocation is None]):
        issue_data = comicarr.cv.getComic(None, "single_issue", IssueID)
        IssueImage = getimage.retrieve_image(issue_data["image"])
        metadata_info = {"metadata_source": "ComicVine", "metadata_type": None}
        return {
            "metadata": issue_data,
            "datamode": "single_issue",
            "IssueImage": IssueImage,
            "metadata_source": metadata_info,
        }
    if justinfo is False:
        file_info = getimage.extract_image(filelocation, single=True, imquality="issue", comicname=comicname)
        IssueImage = file_info["ComicImage"]
        data = file_info["metadata"]
        if data:
            issuetag = "xml"
    else:
        IssueImage = "None"
        try:
            with zipfile.ZipFile(filelocation, "r") as inzipfile:
                for infile in sorted(inzipfile.namelist()):
                    if infile == "ComicInfo.xml":
                        logger.fdebug("Found ComicInfo.xml - now retrieving information.")
                        data = inzipfile.read(infile)
                        issuetag = "xml"
                        break
        except Exception:
            metadata_info = {"metadata_source": None, "metadata_type": None}
            logger.info(
                "ERROR. Unable to properly retrieve the cover for displaying. It's probably best to re-tag this file."
            )
            return {"IssueImage": IssueImage, "datamode": "file", "metadata": None, "metadata_source": metadata_info}

    if issuetag is None:
        data = None
        try:
            dz = zipfile.ZipFile(filelocation, "r")
            data = dz.comment
        except Exception:
            metadata_info = {"metadata_source": "ComicVine", "metadata_type": None}
            logger.warn("Unable to extract any metadata from within file.")
            return {"IssueImage": IssueImage, "datamode": "file", "metadata": None, "metadata_source": metadata_info}
        else:
            if data:
                issuetag = "comment"
                metadata_info = {"metadata_source": "ComicVine", "metadata_type": "comicbooklover"}
            else:
                metadata_info = {"metadata_source": None, "metadata_type": None}
                logger.warn("No metadata available in zipfile comment field.")
                return {
                    "IssueImage": IssueImage,
                    "datamode": "file",
                    "metadata": None,
                    "metadata_source": metadata_info,
                }

    logger.info("Tag returned as being: " + str(issuetag))

    if issuetag == "xml":
        dom = parseString(data)
        results = dom.getElementsByTagName("ComicInfo")
        metadata_info = {"metadata_source": None, "metadata_type": "comicinfo.xml"}

        for result in results:
            try:
                issue_title = result.getElementsByTagName("Title")[0].firstChild.wholeText
            except Exception:
                issue_title = "None"
            try:
                series_title = result.getElementsByTagName("Series")[0].firstChild.wholeText
            except Exception:
                series_title = "None"
            try:
                series_volume = result.getElementsByTagName("Volume")[0].firstChild.wholeText
            except Exception:
                series_volume = "None"
            try:
                issue_number = result.getElementsByTagName("Number")[0].firstChild.wholeText
            except Exception:
                issue_number = "None"
            try:
                summary = result.getElementsByTagName("Summary")[0].firstChild.wholeText
            except Exception:
                summary = "None"
            if "*List" in summary:
                summary_cut = summary.find("*List")
                summary = summary[:summary_cut]
            try:
                notes = result.getElementsByTagName("Notes")[0].firstChild.wholeText
            except Exception:
                notes = "None"
            else:
                if "CMXID" in notes:
                    mtype = "Comixology"
                elif any(["cvdb" in notes.lower(), "issue id" in notes.lower(), "comic vine" in notes.lower()]):
                    mtype = "ComicVine"
                else:
                    mtype = None
                metadata_info = {"metadata_source": mtype, "metadata_type": "comicinfo.xml"}
            try:
                year = result.getElementsByTagName("Year")[0].firstChild.wholeText
            except Exception:
                year = "None"
            try:
                month = result.getElementsByTagName("Month")[0].firstChild.wholeText
            except Exception:
                month = "None"
            try:
                day = result.getElementsByTagName("Day")[0].firstChild.wholeText
            except Exception:
                day = "None"
            try:
                writer = result.getElementsByTagName("Writer")[0].firstChild.wholeText
            except Exception:
                writer = None
            try:
                penciller = result.getElementsByTagName("Penciller")[0].firstChild.wholeText
            except Exception:
                penciller = None
            try:
                inker = result.getElementsByTagName("Inker")[0].firstChild.wholeText
            except Exception:
                inker = None
            try:
                colorist = result.getElementsByTagName("Colorist")[0].firstChild.wholeText
            except Exception:
                colorist = None
            try:
                letterer = result.getElementsByTagName("Letterer")[0].firstChild.wholeText
            except Exception:
                letterer = None
            try:
                cover_artist = result.getElementsByTagName("CoverArtist")[0].firstChild.wholeText
            except Exception:
                cover_artist = None
            try:
                editor = result.getElementsByTagName("Editor")[0].firstChild.wholeText
            except Exception:
                editor = None
            try:
                publisher = result.getElementsByTagName("Publisher")[0].firstChild.wholeText
            except Exception:
                publisher = "None"
            try:
                webpage = result.getElementsByTagName("Web")[0].firstChild.wholeText
            except Exception:
                webpage = "None"
            try:
                pagecount = result.getElementsByTagName("PageCount")[0].firstChild.wholeText
            except Exception:
                pagecount = 0

    elif issuetag == "comment":
        logger.info("CBL Tagging.")
        stripline = "Archive:  " + filelocation
        data = re.sub(stripline, "", data.decode("utf-8"))
        if data is None or data == "":
            return {"IssueImage": IssueImage}
        import ast

        ast_data = ast.literal_eval(str(data))
        ast_data["lastModified"]
        dt = ast_data["ComicBookInfo/1.0"]
        try:
            publisher = dt["publisher"]
        except Exception:
            publisher = None
        try:
            year = dt["publicationYear"]
        except Exception:
            year = None
        try:
            month = dt["publicationMonth"]
        except Exception:
            month = None
        try:
            day = dt["publicationDay"]
        except Exception:
            day = None
        try:
            issue_title = dt["title"]
        except Exception:
            issue_title = None
        try:
            series_title = dt["series"]
        except Exception:
            series_title = None
        try:
            issue_number = dt["issue"]
        except Exception:
            issue_number = None
        try:
            summary = dt["comments"]
        except Exception:
            summary = "None"
        editor = None
        colorist = None
        artist = None
        writer = None
        letterer = None
        cover_artist = None
        penciller = None
        inker = None
        try:
            series_volume = dt["volume"]
        except Exception:
            series_volume = None
        try:
            dt["credits"]
        except Exception:
            pass
        else:
            for cl in dt["credits"]:
                if cl["role"] == "Editor":
                    if editor == "None":
                        editor = cl["person"]
                    else:
                        editor += ", " + cl["person"]
                elif cl["role"] == "Colorist":
                    if colorist == "None":
                        colorist = cl["person"]
                    else:
                        colorist += ", " + cl["person"]
                elif cl["role"] == "Artist":
                    if artist == "None":
                        artist = cl["person"]
                    else:
                        artist += ", " + cl["person"]
                elif cl["role"] == "Writer":
                    if writer == "None":
                        writer = cl["person"]
                    else:
                        writer += ", " + cl["person"]
                elif cl["role"] == "Letterer":
                    if letterer == "None":
                        letterer = cl["person"]
                    else:
                        letterer += ", " + cl["person"]
                elif cl["role"] == "Cover":
                    if cover_artist == "None":
                        cover_artist = cl["person"]
                    else:
                        cover_artist += ", " + cl["person"]
                elif cl["role"] == "Penciller":
                    if penciller == "None":
                        penciller = cl["person"]
                    else:
                        penciller += ", " + cl["person"]
                elif cl["role"] == "Inker":
                    if inker == "None":
                        inker = cl["person"]
                    else:
                        inker += ", " + cl["person"]
        try:
            notes = dt["notes"]
        except Exception:
            notes = "None"
        try:
            webpage = dt["web"]
        except Exception:
            webpage = "None"
        try:
            pagecount = dt["pagecount"]
        except Exception:
            pagecount = "None"
    else:
        logger.warn("Unable to locate any metadata within cbz file. Tag this file and try again if necessary.")
        return

    return {
        "metadata": {
            "title": issue_title,
            "series": series_title,
            "volume": series_volume,
            "issue_number": issue_number,
            "summary": summary,
            "notes": notes,
            "year": year,
            "month": month,
            "day": day,
            "writer": writer,
            "penciller": penciller,
            "inker": inker,
            "colorist": colorist,
            "letterer": letterer,
            "cover_artist": cover_artist,
            "editor": editor,
            "publisher": publisher,
            "webpage": webpage,
            "pagecount": pagecount,
        },
        "IssueImage": IssueImage,
        "datamode": "file",
        "metadata_source": metadata_info,
    }


def getImage(comicid, url, issueid=None, thumbnail_path=None, apicall=False, overwrite=False):
    if thumbnail_path is None:
        if not os.path.exists(comicarr.CONFIG.CACHE_DIR):
            try:
                os.makedirs(str(comicarr.CONFIG.CACHE_DIR))
                if apicall is False:
                    logger.info("Cache Directory successfully created at: %s" % comicarr.CONFIG.CACHE_DIR)
            except OSError:
                if apicall is False:
                    logger.error(
                        "Could not create cache dir. Check permissions of cache dir: %s" % comicarr.CONFIG.CACHE_DIR
                    )
        coverfile = os.path.join(comicarr.CONFIG.CACHE_DIR, str(comicid) + ".jpg")
    else:
        coverfile = thumbnail_path

    if comicarr.CONFIG.CVAPI_RATE is None or comicarr.CONFIG.CVAPI_RATE < 2:
        time.sleep(2)
    else:
        time.sleep(comicarr.CONFIG.CVAPI_RATE)

    if apicall is False:
        logger.info("Attempting to retrieve the comic image for series")
    try:
        r = requests.get(url, params=None, stream=True, verify=comicarr.CONFIG.CV_VERIFY, headers=comicarr.CV_HEADERS)
    except Exception as e:
        if apicall is False:
            logger.warn("[ERROR: %s] Unable to download image from CV URL link: %s" % (e, url))
        coversize = 0
        statuscode = "400"
    else:
        statuscode = str(r.status_code)
        if apicall is False:
            logger.fdebug("comic image retrieval status code: %s" % statuscode)
        if statuscode != "200":
            if apicall is False:
                logger.warn(
                    "Unable to download image from CV URL link: %s [Status Code returned: %s]" % (url, statuscode)
                )
            coversize = 0
        else:
            if os.path.exists(coverfile) and overwrite:
                try:
                    os.remove(coverfile)
                except Exception:
                    pass
            with open(coverfile, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
                        f.flush()
            statinfo = os.stat(coverfile)
            coversize = statinfo.st_size

        try:
            Image.open(coverfile)
        except OSError:
            logger.warn("Truncated image retrieved - trying alternate image file.")
            return {"coversize": coversize, "status": "retry"}
        return {"coversize": coversize, "status": "success"}

    if any([int(coversize) < 10000, statuscode != "200"]) and thumbnail_path is None:
        if apicall is False:
            logger.fdebug("invalid image link is here: %s" % url)
        if os.path.exists(coverfile):
            os.remove(coverfile)
        return {"coversize": coversize, "status": "retry"}
    else:
        return {"coversize": coversize, "status": "failed"}


def publisherImages(publisher):
    comicpublisher = None
    if comicarr.CONFIG.INTERFACE == "default":
        if any([publisher == "Image", publisher == "Image Comics"]):
            comicpublisher = {
                "publisher_image": "images/publisherlogos/logo-imagecomics.png",
                "publisher_image_alt": "Image",
                "publisher_imageH": "125",
                "publisher_imageW": "75",
            }
        elif publisher == "IDW Publishing":
            comicpublisher = {
                "publisher_image": "images/publisherlogos/logo-idwpublish.png",
                "publisher_image_alt": "IDW",
                "publisher_imageH": "50",
                "publisher_imageW": "100",
            }
        elif publisher == "Boom! Studios":
            comicpublisher = {
                "publisher_image": "images/publisherlogos/logo-boom.jpg",
                "publisher_image_alt": "Boom!",
                "publisher_imageH": "50",
                "publisher_imageW": "100",
            }
    else:
        if any([publisher == "Image", publisher == "Image Comics"]):
            comicpublisher = {
                "publisher_image": "images/publisherlogos/logo-imagecomics_carbon.png",
                "publisher_image_alt": "Image",
                "publisher_imageH": "125",
                "publisher_imageW": "75",
            }
        elif publisher == "IDW Publishing":
            comicpublisher = {
                "publisher_image": "images/publisherlogos/logo-idwpublish_carbon.png",
                "publisher_image_alt": "IDW",
                "publisher_imageH": "50",
                "publisher_imageW": "100",
            }
        elif publisher == "Boom! Studios":
            comicpublisher = {
                "publisher_image": "images/publisherlogos/logo-boom_carbon.png",
                "publisher_image_alt": "Boom!",
                "publisher_imageH": "50",
                "publisher_imageW": "100",
            }

    if comicpublisher is not None:
        return comicpublisher

    if comicpublisher is None:
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-blank_publisher.png",
            "publisher_image_alt": None,
            "publisher_imageH": "0",
            "publisher_imageW": "0",
        }
    return comicpublisher
