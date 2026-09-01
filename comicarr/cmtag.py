import os
import re
import shutil
import subprocess
import sys

from packaging.version import parse as parse_version

import comicarr
from comicarr import logger, notifiers


def manga_volume_for_issue(issueid):
    """Return the volume number this file *is*, or None for a periodical issue.

    A licensed manga is catalogued by ComicVine as a Series whose "issues" are
    the English volumes, so an untouched tag reads ``<Number>7</Number>`` with
    ``<Volume>`` set to the series-level label. A reader consuming ComicInfo
    then files every volume as a chapter of one volume named after the series,
    losing the volume structure the files were published in. A manga volume is a
    book: the file *is* volume 7 and carries no issue number.

    Both facts are looked up from their existing owners rather than restated
    here -- ``series_kind.is_manga`` decides the Series, and
    ``ledger.normalize_volume_number`` decides what the number means.

    Best-effort: a missing row, a ledger without volume numbers, or a Series
    that is not manga all return None, leaving the periodical tag shape exactly
    as it was.
    """
    if issueid is None:
        return None
    # Imported here rather than at module scope: cmtag is itself imported lazily
    # from the post-processor, and keeping the DB/table chain out of import time
    # preserves that ordering.
    from sqlalchemy import select

    from comicarr import db, series_kind
    from comicarr.app.manga import ledger
    from comicarr.tables import comics, issues

    try:
        row = db.select_one(select(issues.c.ComicID, issues.c.VolumeNumber).where(issues.c.IssueID == issueid))
        if row is None or "VolumeNumber" not in set(row.keys()):
            return None
        volume = ledger.normalize_volume_number(row["VolumeNumber"])
        if volume is None:
            return None
        comic = db.select_one(select(comics).where(comics.c.ComicID == row["ComicID"]))
        if comic is None or not series_kind.is_manga(comic):
            return None
    except Exception as e:
        logger.fdebug("[META-TAGGER] Could not resolve a manga volume for issue %s: %s" % (issueid, e))
        return None
    return volume


def run(
    dirName,
    nzbName=None,
    issueid=None,
    comversion=None,
    manual=None,
    filename=None,
    module=None,
    manualmeta=False,
    readingorder=None,
    agerating=None,
):
    if module is None:
        module = ""
    module += "[META-TAGGER]"

    logger.fdebug(module + " dirName:" + dirName)

    comictagger_cmd = os.path.join(comicarr.CMTAGGER_PATH, "comictagger.py")
    logger.fdebug("ComicTagger Path location for internal comictagger.py set to : " + comictagger_cmd)

    logger.fdebug(module + " Filename is : " + filename)

    filepath = filename
    og_filepath = filepath
    try:
        filename = os.path.split(filename)[1]
    except:
        logger.warn(
            "Unable to detect filename within directory - I am aborting the tagging. You best check things out."
        )
        sendnotify("Error - Unable to detect filename within directory. Tagging aborted.", filename, module)
        return "fail"

    new_filepath = None
    new_folder = None
    try:
        import tempfile

        logger.fdebug("Filepath: %s" % filepath)
        logger.fdebug("Filename: %s" % filename)
        new_folder = tempfile.mkdtemp(prefix="comicarr_", dir=comicarr.CONFIG.CACHE_DIR)
        os.chmod(new_folder, 0o755)
        logger.fdebug("New_Folder: %s" % new_folder)
        new_filepath = os.path.join(new_folder, filename)
        logger.fdebug("New_Filepath: %s" % new_filepath)
        if comicarr.CONFIG.FILE_OPTS == "copy" and not manualmeta:
            shutil.copy(filepath, new_filepath)
        else:
            shutil.copy(filepath, new_filepath)
        filepath = new_filepath
    except Exception as e:
        logger.warn("%s Unexpected Error: %s [%s]" % (module, sys.exc_info()[0], e))
        logger.warn(
            module + " Unable to create temporary directory to perform meta-tagging. Processing without metatagging."
        )
        sendnotify(
            "Error - Unable to create temporary directory to perform meta-tagging. Processing without metatagging.",
            filename,
            module,
        )
        tidyup(og_filepath, new_filepath, new_folder, manualmeta)
        return "fail"

    scriptname = os.path.basename(sys.argv[0])
    downloadpath = os.path.abspath(dirName)
    sabnzbdscriptpath = os.path.dirname(sys.argv[0])
    comicpath = new_folder

    logger.fdebug(module + " Paths / Locations:")
    logger.fdebug(module + " scriptname : " + scriptname)
    logger.fdebug(module + " downloadpath : " + downloadpath)
    logger.fdebug(module + " sabnzbdscriptpath : " + sabnzbdscriptpath)
    logger.fdebug(module + " comicpath : " + comicpath)
    logger.fdebug(module + " Running the ComicTagger Add-on for Comicarr")

    if comicarr.CONFIG.FILE_OPTS == "move":
        cbr2cbzoptions = ["--configfolder", comicarr.CONFIG.CT_SETTINGSPATH, "-e", "--delete-rar"]
    else:
        cbr2cbzoptions = ["--configfolder", comicarr.CONFIG.CT_SETTINGSPATH, "-e"]

    tagoptions = ["-s"]

    cvers = "volume="
    if comicarr.CONFIG.CMTAG_VOLUME:
        if comicarr.CONFIG.CMTAG_START_YEAR_AS_VOLUME:
            pass
        else:
            if comicarr.CONFIG.SETDEFAULTVOLUME:
                if any([comversion is None, comversion == "", comversion == "None"]):
                    comversion = "1"
                comversion = re.sub("[^0-9]", "", comversion).strip()
            else:
                if any([comversion is None, comversion == "", comversion == "None"]):
                    comversion = None
                else:
                    comversion = re.sub("[^0-9]", "", comversion).strip()
        if comversion is not None:
            cvers = "volume=%s" % comversion

    # A manga volume is a book, not an instalment of one: the file is volume N
    # and has no issue number. Write that shape instead of the series-level
    # volume label, so a reader groups the files as the volumes they were
    # published as rather than as chapters of a single volume.
    #
    # An empty value clears the field on overlay -- the same mechanism the
    # ``cvers = "volume="`` default above already relies on -- so ``issue=``
    # removes the number ComicVine supplies for the catalogued issue.
    manga_volume = manga_volume_for_issue(issueid)
    if manga_volume is not None:
        logger.fdebug(
            "%s [MANGA] tagging as volume %s with no issue number (was volume label: %s)"
            % (module, manga_volume, comversion)
        )
        cvers = "volume=%s" % manga_volume
        iline = "issue="
    else:
        iline = None

    if readingorder is not None:
        if type(readingorder) == list:
            orderseq = []
            arcseq = []
            for osq in readingorder:
                orderseq.append(str(osq[1]))
                arcseq.append(osq[0])
            arcseqn = ",".join(arcseq).strip()
            arcseqname = re.sub(r",", "^,", arcseqn).strip()
            ordersn = ",".join(orderseq).strip()
            orders = re.sub(r",", "^,", ordersn).strip()
            rorder = "storyArcNumber=%s, storyArc=%s" % (orders, arcseqname)
        else:
            "storyArcNumber=%s" % readingorder
    else:
        rorder = "storyArcNumber="

    if all([agerating is not None, agerating != "None"]):
        arating = "ageRating=%s" % (agerating)
    else:
        arating = "ageRating="

    tline = ", ".join(part for part in (cvers, rorder, arating, iline) if part is not None)
    tagoptions.extend(["-m", tline])

    try:
        ct_check = subprocess.check_output([sys.executable, comictagger_cmd, "--version"], stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError:
        logger.warn(module + "[WARNING] Make sure that you are using the comictagger included with Comicarr.")
        tidyup(filepath, new_filepath, new_folder, manualmeta)
        return "fail"

    logger.info("ct_check: %s" % ct_check)
    ctend = str(ct_check).find("[")
    ct_version = re.sub("[^0-9]", "", str(ct_check)[:ctend])
    if parse_version(ct_version) >= parse_version("1.3.1"):
        if any([comicarr.CONFIG.COMICVINE_API == "None", comicarr.CONFIG.COMICVINE_API is None]):
            logger.fdebug(
                "%s ComicTagger v.%s being used - no personal ComicVine API Key supplied. Take your chances."
                % (module, ct_version)
            )
        else:
            logger.fdebug(
                "%s ComicTagger v.%s being used - using personal ComicVine API key supplied via comicarr."
                % (module, ct_version)
            )
            tagoptions.extend(
                [
                    "--cv-api-key",
                    comicarr.CONFIG.COMICVINE_API,
                    "--configfolder",
                    comicarr.CONFIG.CT_SETTINGSPATH,
                    "--notes_format",
                    comicarr.CONFIG.CT_NOTES_FORMAT,
                ]
            )
    else:
        logger.fdebug(
            "%s ComicTagger v.ct_version being used - personal ComicVine API key not supported in this version. Good luck."
            % (module, ct_version)
        )

    i = 1
    tagcnt = 0

    if comicarr.CONFIG.CBR2CBZ_ONLY:
        logger.fdebug(module + " CBR2CBZ Conversion only.")
    else:
        if comicarr.CONFIG.CT_TAG_CR:
            tagcnt = 1
            logger.fdebug(module + " CR Tagging enabled.")

        if comicarr.CONFIG.CT_TAG_CBL:
            if not comicarr.CONFIG.CT_TAG_CR:
                i = 2
            tagcnt = 2
            logger.fdebug(module + " CBL Tagging enabled.")

    if tagcnt == 0 and not comicarr.CONFIG.CBR2CBZ_ONLY:
        logger.warn(
            module
            + " You have metatagging enabled, but you have not selected the type(s) of metadata to write. Please fix and re-run manually"
        )
        tidyup(filepath, new_filepath, new_folder, manualmeta)
        return "fail"

    if filename.endswith(".cbz"):
        if comicarr.CONFIG.CT_CBZ_OVERWRITE:
            logger.fdebug(module + " Will modify existing tag blocks even if it exists.")
        else:
            logger.fdebug(module + " Will NOT modify existing tag blocks even if they exist already.")
            tagoptions.extend(["--nooverwrite"])

    if issueid is None:
        tagoptions.extend(["-f", "-o"])
    else:
        tagoptions.extend(["-o", "--id", issueid])

    original_tagoptions = tagoptions
    og_tagtype = None
    initial_ctrun = True

    while i <= tagcnt:
        if initial_ctrun:
            f_tagoptions = cbr2cbzoptions
            f_tagoptions.extend([filepath])
        else:
            if i == 1:
                tagtype = "cr"
                tagdisp = "ComicRack tagging"
            elif i == 2:
                tagtype = "cbl"
                tagdisp = "Comicbooklover tagging"

            f_tagoptions = original_tagoptions

            if og_tagtype is not None:
                for index, item in enumerate(f_tagoptions):
                    if item == og_tagtype:
                        f_tagoptions[index] = tagtype
            else:
                f_tagoptions.extend(["--type", tagtype, filepath])

            og_tagtype = tagtype

            logger.info(module + " " + tagdisp + " meta-tagging processing started.")

        currentScriptName = [sys.executable, comictagger_cmd]
        script_cmd = currentScriptName + f_tagoptions

        if initial_ctrun:
            logger.fdebug("%s Enabling ComicTagger script with options: %s" % (module, f_tagoptions))
            script_cmdlog = script_cmd

        else:
            logger.fdebug(
                "%s Enabling ComicTagger script with options: %s"
                % (
                    module,
                    re.sub(
                        f_tagoptions[f_tagoptions.index(comicarr.CONFIG.COMICVINE_API)], "REDACTED", str(f_tagoptions)
                    ),
                )
            )
            script_cmdlog = re.sub(
                f_tagoptions[f_tagoptions.index(comicarr.CONFIG.COMICVINE_API)], "REDACTED", str(script_cmd)
            )

        logger.fdebug(module + " Executing command: " + str(script_cmdlog))
        logger.fdebug(module + " Absolute path to script: " + script_cmd[0])
        try:
            p = subprocess.Popen(script_cmd, stdout=subprocess.PIPE, text=True, stderr=subprocess.STDOUT)
            out, err = p.communicate()
            if all([err is not None, err != ""]):
                logger.warn("[ERROR RETURNED FROM COMIC-TAGGER] %s" % (err,))
            if initial_ctrun and "exported successfully" in out:
                logger.fdebug("%s[COMIC-TAGGER] : %s" % (module, out))
                if "Error deleting" in filepath:
                    tf1 = out.find("exported successfully to: ")
                    tmpfilename = out[tf1 + len("exported successfully to: ") :].strip()
                else:
                    tmpfilename = re.sub("Archive exported successfully to: ", "", out.rstrip())
                if comicarr.CONFIG.FILE_OPTS == "move":
                    tmpfilename = re.sub(r"\(Original deleted\)", "", tmpfilename).strip()
                tmpf = tmpfilename
                filepath = os.path.join(comicpath, tmpf)
                if filename.lower() != tmpf.lower() and tmpf.endswith("(1).cbz"):
                    logger.fdebug(
                        "New filename [%s] is named incorrectly due to duplication during metatagging - Making sure it's named correctly [%s]."
                        % (tmpf, filename)
                    )
                    tmpfilename = filename
                    filepath_new = os.path.join(comicpath, tmpfilename)
                    try:
                        os.rename(filepath, filepath_new)
                        filepath = filepath_new
                    except:
                        logger.warn(
                            "%s unable to rename file to accomodate metatagging cbz to the same filename" % module
                        )
                if not os.path.isfile(filepath):
                    logger.fdebug("%s Trying utf-8 conversion." % module)
                    tmpf = tmpfilename.encode("utf-8")
                    filepath = os.path.join(comicpath, tmpf)
                    if not os.path.isfile(filepath):
                        logger.fdebug("%s Trying latin-1 conversion." % module)
                        tmpf = tmpfilename.encode("Latin-1")
                        filepath = os.path.join(comicpath, tmpf)

                logger.fdebug("%s[COMIC-TAGGER][CBR-TO-CBZ] New filename: %s" % (module, filepath))
                initial_ctrun = False
            elif initial_ctrun and "Archive is not a RAR" in out:
                logger.fdebug("%s Output: %s" % (module, out))
                logger.warn("%s[COMIC-TAGGER] file is not in a RAR format: %s" % (module, filename))
                initial_ctrun = False
            elif initial_ctrun:
                initial_ctrun = False
                if any(["file is not expected size" in out, "Failed the read" in out]):
                    logger.fdebug("%s Output: %s" % (module, out))
                    tidyup(og_filepath, new_filepath, new_folder, manualmeta)
                    return "corrupt"
                else:
                    logger.fdebug("out: %s" % (out,))
                    logger.fdebug("filename: %s" % (filename,))
                    cbz_message = (
                        "Failed to convert cbr to cbz - check permissions on folder %s and/or the location where Comicarr is trying to tag the files from."
                        % comicarr.CONFIG.CACHE_DIR
                    )
                    logger.warn("%s[COMIC-TAGGER][CBR-TO-CBZ]%s" % (module, cbz_message))
                    sendnotify("Error - %s" % (cbz_message), filename, module)
                    tidyup(og_filepath, new_filepath, new_folder, manualmeta)
                    return "fail"
            elif "Cannot find" in out:
                logger.fdebug("%s Output: %s" % (module, out))
                logger.warn("%s[COMIC-TAGGER] Unable to locate file: %s" % (module, filename))
                file_error = "file not found||" + filename
                return file_error
            elif "not a comic archive!" in out:
                logger.fdebug("%s Output: %s" % (module, out))
                logger.warn("%s[COMIC-TAGGER] Unable to locate file: %s" % (module, filename))
                file_error = "file not found||%s" % filename
                return file_error
            else:
                if "Save complete" not in out:
                    unknown_message = out
                    logger.warn("%s[COMIC-TAGGER][UNKNOWN-ERROR-DURING-METATAGGING] %s" % (module, unknown_message))
                    sendnotify("Error - %s" % (unknown_message), filename, module)
                    tidyup(og_filepath, new_filepath, new_folder, manualmeta)
                    return "fail"
                else:
                    logger.info("%s[COMIC-TAGGER] Successfully wrote %s [%s]" % (module, tagdisp, filepath))
                i += 1
        except OSError:
            logger.warn(
                "%s[COMIC-TAGGER] Unable to run comictagger with the options provided: %s"
                % (
                    module,
                    re.sub(
                        f_tagoptions[f_tagoptions.index(comicarr.CONFIG.COMICVINE_API)], "REDACTED", str(script_cmd)
                    ),
                )
            )
            tidyup(filepath, new_filepath, new_folder, manualmeta)
            return "fail"
        except Exception as e:
            logger.warn("%s[COMIC-TAGGER] Error : %s" % (module, e))
            tidyup(filepath, new_filepath, new_folder, manualmeta)
            return "fail"
        if comicarr.CONFIG.CBR2CBZ_ONLY and not initial_ctrun:
            break

    return filepath


def tidyup(filepath, new_filepath, new_folder, manualmeta):
    if all([new_filepath is not None, new_folder is not None]):
        if comicarr.CONFIG.FILE_OPTS == "copy" and not manualmeta:
            if all([os.path.exists(new_folder), os.path.isfile(filepath)]):
                shutil.rmtree(new_folder)
            elif os.path.exists(new_filepath) and not os.path.exists(filepath):
                shutil.move(new_filepath, filepath + ".BAD")
        else:
            if os.path.exists(new_filepath) and not os.path.exists(filepath):
                shutil.move(new_filepath, filepath + ".BAD")
            if all([os.path.exists(new_folder), os.path.isfile(filepath)]):
                shutil.rmtree(new_folder)


def sendnotify(message, filename, module):

    prline = filename

    prline2 = "Comicarr metatagging error: " + message + " File: " + prline

    try:
        if comicarr.CONFIG.PROWL_ENABLED:
            pushmessage = prline
            prowl = notifiers.PROWL()
            prowl.notify(pushmessage, "Comicarr metatagging error: ", module=module)

        if comicarr.CONFIG.PUSHOVER_ENABLED:
            pushover = notifiers.PUSHOVER()
            pushover.notify(prline, prline2, module=module)

        if comicarr.CONFIG.BOXCAR_ENABLED:
            boxcar = notifiers.BOXCAR()
            boxcar.notify(prline=prline, prline2=prline2, module=module)

        if comicarr.CONFIG.PUSHBULLET_ENABLED:
            pushbullet = notifiers.PUSHBULLET()
            pushbullet.notify(prline=prline, prline2=prline2, module=module)

        if comicarr.CONFIG.TELEGRAM_ENABLED:
            telegram = notifiers.TELEGRAM()
            telegram.notify(prline2)

        if comicarr.CONFIG.SLACK_ENABLED:
            slack = notifiers.SLACK()
            slack.notify("Comicarr metatagging error: ", prline2, module=module)

        if comicarr.CONFIG.MATTERMOST_ENABLED:
            mattermost = notifiers.MATTERMOST()
            mattermost.notify("Comicarr metatagging error: ", prline2, module=module)

        if comicarr.CONFIG.DISCORD_ENABLED:
            discord = notifiers.DISCORD()
            discord.notify(filename, message, module=module)

        if comicarr.CONFIG.EMAIL_ENABLED and comicarr.CONFIG.EMAIL_ONPOST:
            logger.info("Sending email notification")
            email = notifiers.EMAIL()
            email.notify(prline2, "Comicarr metatagging error: ", module=module)

        if comicarr.CONFIG.GOTIFY_ENABLED:
            gotify = notifiers.GOTIFY()
            gotify.notify("Comicarr metatagging error: ", prline2, module=module)

        if comicarr.CONFIG.MATRIX_ENABLED:
            matrix = notifiers.MATRIX()
            matrix.notify("Comicarr metatagging error: ", prline2, module=module)
    except Exception as e:
        logger.warn("[NOTIFICATION] Unable to send notification: %s" % e)

    return
