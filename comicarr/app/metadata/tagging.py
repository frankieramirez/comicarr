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

"""Tag a placed comic with ComicInfo.xml and ComicBookLover data.

The archive work lives in ``comicarr.app.metadata.comicinfo``; this module
decides what to write: the archive's own tags, then Comicarr's values, then
ComicVine's for a ComicVine issue.
"""

import os
import re
import shutil
import sys
import tempfile

from comicarr.app.core import logger, runtime
from comicarr.app.library import directories
from comicarr.app.metadata import comicinfo
from comicarr.app.notifications import service as notifiers


def current_file_mode(path):
    """Return path's permission bits, or None if they cannot be read.

    Captured before tagging starts, because the original file may be gone by
    the time tagging finishes: a .cbr is converted to .cbz and, under
    FILE_OPTS = move, the rar is deleted.
    """
    try:
        return os.stat(path).st_mode & 0o7777
    except OSError:
        return None


def restore_tagged_file_mode(path, original_mode, module=""):
    """Give a freshly tagged file the accessibility it had before tagging.

    Tagging is a round trip, and a round trip must not change how readable a
    file is. A zip cannot be edited in place, so tagging builds a NEW file
    (converting .cbr -> .cbz along the way) with tempfile semantics -- 0600 --
    instead of inheriting the library file's mode. Moving that back
    into place leaves a tagged issue less readable than every untagged issue
    beside it, and nothing logs the change.

    ENFORCE_PERMS is the configured owner of file modes, so when it is on this
    defers to directories.setperms() exactly as the six other placement sites
    do. When it is off the user has asked for modes to be left alone -- which
    means left alone, not quietly reduced -- so the pre-tag mode is restored.

    Returns True when the mode was applied, False when there was nothing to do.
    """
    if runtime.current().config.ENFORCE_PERMS:
        # Wrapped like the chmod branch below, and not left bare: setperms
        # catches only OSError, while its own `int(CONFIG.CHMOD_FILE, 8)`
        # raises ValueError for a mode the config accepts but Python cannot
        # parse ('888'). That escaped run(), whose caller catches only
        # ImportError, and killed post-processing AFTER the tag had already
        # succeeded -- losing the rest of the job to a cosmetic step.
        try:
            applied = directories.setperms(path)
        except Exception as e:
            logger.warn("%s Unable to enforce permissions on %s [%s]" % (module, path, e))
            return False
        # setperms reports its own failure by returning False; answering True
        # regardless would claim a mode that was never applied.
        return bool(applied)

    if original_mode is None:
        return False
    current = current_file_mode(path)
    if current is None or current == original_mode:
        return False
    try:
        os.chmod(path, original_mode)
    except OSError as e:
        logger.warn("%s Unable to restore permissions %s on %s [%s]" % (module, oct(original_mode), path, e))
        return False
    logger.fdebug(
        "%s Restored pre-tagging permissions %s on %s (tagging left it %s)"
        % (module, oct(original_mode), path, oct(current))
    )
    return True


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

    from comicarr.app.common import series_kind
    from comicarr.app.core import db
    from comicarr.app.core.tables import comics, issues
    from comicarr.app.manga import ledger

    try:
        row = db.select_one(
            select(issues.c.ComicID, issues.c.VolumeNumber, issues.c.ChapterNumber, issues.c.Issue_Number).where(
                issues.c.IssueID == issueid
            )
        )
        if row is None or "VolumeNumber" not in set(row.keys()):
            return None
        comic = db.select_one(select(comics).where(comics.c.ComicID == row["ComicID"]))
        if comic is None or not series_kind.is_manga(comic):
            return None
        # A chapter is not a book, so it keeps its number. MangaDex chapter
        # rows also store the CONTAINING volume in VolumeNumber, so reading
        # VolumeNumber alone tagged Chainsaw Man 165 as volume 18 with its
        # number stripped -- the chapter became unidentifiable.
        if ledger.normalize_volume_number(row.get("ChapterNumber")) is not None:
            return None
        # ComicVine catalogues a licensed manga's English volumes as the
        # series' issues: the volume lands in Issue_Number and VolumeNumber is
        # never written. Reading VolumeNumber alone meant One-Punch Man v7
        # never reached this branch at all and kept <Number>7</Number>, which
        # is the periodical shape this exists to correct.
        volume = ledger.normalize_volume_number(row.get("VolumeNumber"))
        if volume is None:
            volume = ledger.normalize_volume_number(row.get("Issue_Number"))
        if volume is None:
            return None
    except Exception as e:
        logger.fdebug("[META-TAGGER] Could not resolve a manga volume for issue %s: %s" % (issueid, e))
        return None
    return volume


def volume_value(comversion, manga_volume, module=""):
    """The <Volume> to write; "" removes the element.

    A manga volume is a book, not an instalment of one: the file IS volume N
    and has no issue number, so it overrides the series-level volume label a
    periodical would carry. Written that way, a reader groups the files as the
    volumes they were published as rather than as chapters of one volume named
    for the series. Its issue number is removed in run(), after the ComicVine
    values that would put it back.
    """
    volume = ""
    if runtime.current().config.CMTAG_VOLUME:
        if not runtime.current().config.CMTAG_START_YEAR_AS_VOLUME:
            if runtime.current().config.SETDEFAULTVOLUME:
                if any([comversion is None, comversion == "", comversion == "None"]):
                    comversion = "1"
                comversion = re.sub("[^0-9]", "", comversion).strip()
            else:
                if any([comversion is None, comversion == "", comversion == "None"]):
                    comversion = None
                else:
                    comversion = re.sub("[^0-9]", "", comversion).strip()
        if comversion is not None:
            volume = str(comversion)

    if manga_volume is not None:
        logger.fdebug(
            "%s [MANGA] tagging as volume %s with no issue number (was volume label: %s)"
            % (module, manga_volume, comversion)
        )
        volume = str(manga_volume)
    return volume


def story_arc_values(readingorder):
    """StoryArc and StoryArcNumber from ``[(arc, order), ...]``; empty values remove them."""
    if readingorder is None:
        return {"StoryArcNumber": ""}
    if isinstance(readingorder, list):
        return {
            "StoryArcNumber": ",".join(str(order) for _, order in readingorder),
            "StoryArc": ",".join(str(arc) for arc, _ in readingorder),
        }
    return {"StoryArcNumber": str(readingorder)}


def local_values(comversion, manga_volume, readingorder, agerating, module=""):
    """The values Comicarr itself knows, laid over the archive's own tags."""
    values = {"Volume": volume_value(comversion, manga_volume, module)}
    values.update(story_arc_values(readingorder))
    values["AgeRating"] = agerating if all([agerating is not None, agerating != "None"]) else ""
    return values


def is_comicvine_id(issueid):
    """A ComicVine issue id is numeric; MangaDex ids such as ``md-csm-ch165`` are not.

    Only a ComicVine id is looked up online. Any other issue is tagged from
    Comicarr's own data, because asking ComicVine for a MangaDex id fails the
    whole tag and leaves the file untagged.
    """
    return issueid is not None and str(issueid).strip().isdigit()


def comicvine_issue(issueid):
    """The ComicVine issue record and its series' publisher, or (None, None)."""
    from sqlalchemy import select

    from comicarr.app.core import db
    from comicarr.app.core.tables import comics
    from comicarr.app.metadata import cv

    dom = cv.pulldetails(None, "single_issue", issueid=issueid)
    if not isinstance(dom, dict):
        return None, None
    issue = dom.get("results")
    if not isinstance(issue, dict) or not issue:
        return None, None
    publisher = None
    series_id = (issue.get("volume") or {}).get("id")
    if series_id is not None:
        try:
            row = db.select_one(select(comics.c.ComicPublisher).where(comics.c.ComicID == str(series_id)))
            if row is not None and row["ComicPublisher"] not in (None, "", "None"):
                publisher = row["ComicPublisher"]
        except Exception as e:
            logger.fdebug("[META-TAGGER] Could not read the publisher for series %s: %s" % (series_id, e))
    return issue, publisher


def build_tags(existing, values, cv_values=None, cv_credits=(), manga_volume=None):
    """Tags to write: the archive's own, then Comicarr's values, then ComicVine's.

    A manga volume loses its issue number last, after ComicVine, which
    catalogues an English volume as an issue and would number it again.
    """
    tags = existing or comicinfo.Tags()
    tags.overlay(values)
    if cv_values is not None:
        tags.overlay(cv_values)
        tags.add_credits(cv_credits)
    if manga_volume is not None:
        tags.overlay({"Number": ""})
    return tags


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
    """Tag a copy of ``filename`` and return the tagged copy's path.

    Otherwise returns "fail" (not tagged, the original is untouched),
    "corrupt" (the archive cannot be read) or "file not found||<name>" (the
    file is not a comic archive). A .cbr comes back as a .cbz.
    """
    if module is None:
        module = ""
    module += "[META-TAGGER]"

    logger.fdebug(module + " dirName:" + dirName)
    logger.fdebug(module + " Filename is : " + filename)

    filepath = filename
    og_filepath = filepath
    # Capture before anything is copied or converted: under FILE_OPTS = move a
    # .cbr is deleted once it becomes a .cbz, so this is the last point the
    # library file's own mode can still be read.
    og_file_mode = current_file_mode(og_filepath)
    try:
        filename = os.path.split(filename)[1]
    except Exception:
        logger.warn(
            "Unable to detect filename within directory - I am aborting the tagging. You best check things out."
        )
        sendnotify("Error - Unable to detect filename within directory. Tagging aborted.", filename, module)
        return "fail"

    new_filepath = None
    new_folder = None
    try:
        new_folder = tempfile.mkdtemp(prefix="comicarr_", dir=runtime.current().config.CACHE_DIR)
        os.chmod(new_folder, 0o755)
        new_filepath = os.path.join(new_folder, filename)
        logger.fdebug("New_Filepath: %s" % new_filepath)
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

    styles = []
    if runtime.current().config.CBR2CBZ_ONLY:
        logger.fdebug(module + " CBR2CBZ Conversion only.")
    else:
        if runtime.current().config.CT_TAG_CR:
            styles.append("cr")
        if runtime.current().config.CT_TAG_CBL:
            styles.append("cbl")
        if not styles:
            logger.warn(
                module
                + " You have metatagging enabled, but you have not selected the type(s) of metadata to write. Please fix and re-run manually"
            )
            tidyup(filepath, new_filepath, new_folder, manualmeta)
            return "fail"

    kind = comicinfo.archive_kind(filepath)
    if kind is None:
        logger.warn("%s Unable to read %s as a comic archive." % (module, filename))
        return "file not found||%s" % filename
    if kind == "rar":
        try:
            filepath = comicinfo.rar_to_cbz(filepath)
        except comicinfo.NotAComicArchive:
            logger.warn("%s %s holds no images." % (module, filename))
            return "file not found||%s" % filename
        except comicinfo.CorruptArchive as e:
            logger.warn("%s[CBR-TO-CBZ] %s could not be read: %s" % (module, filename, e))
            tidyup(og_filepath, new_filepath, new_folder, manualmeta)
            return "corrupt"
        logger.fdebug("%s[CBR-TO-CBZ] New filename: %s" % (module, filepath))
    elif filename.lower().endswith(".cbr"):
        logger.warn("%s file is not in a RAR format: %s" % (module, filename))

    if runtime.current().config.CBR2CBZ_ONLY:
        restore_tagged_file_mode(filepath, og_file_mode, module)
        return filepath

    try:
        comicinfo.check_archive(filepath)
    except comicinfo.NotAComicArchive:
        logger.warn("%s Unable to read %s as a comic archive." % (module, filename))
        return "file not found||%s" % filename

    try:
        cv_values = None
        cv_credits = ()
        if is_comicvine_id(issueid):
            issue, publisher = comicvine_issue(issueid)
            if issue is None:
                message = "No ComicVine details could be fetched for issue %s" % issueid
                logger.warn("%s %s" % (module, message))
                sendnotify("Error - %s" % message, filename, module)
                tidyup(og_filepath, new_filepath, new_folder, manualmeta)
                return "fail"
            cv_values, cv_credits = comicinfo.comicvine_values(
                issue, publisher=publisher, notes_format=runtime.current().config.CT_NOTES_FORMAT
            )
        elif issueid is not None:
            logger.fdebug("%s %s is not a ComicVine issue id -- tagging from local metadata." % (module, issueid))

        manga_volume = manga_volume_for_issue(issueid)
        values = local_values(comversion, manga_volume, readingorder, agerating, module)
        existing = comicinfo.read_tags(filepath)
        # An existing .cbz keeps its tags unless overwriting is on. A converted
        # .cbr has no tags of its own worth keeping.
        overwrite = runtime.current().config.CT_CBZ_OVERWRITE or not filename.endswith(".cbz")
        pages = comicinfo.page_count(filepath)

        xml = comment = None
        for style in styles:
            if existing[style] is not None and not overwrite:
                logger.fdebug("%s Already has %s tags. Not overwriting." % (module, style))
                continue
            tags = build_tags(existing[style], values, cv_values, cv_credits, manga_volume)
            if style == "cr":
                xml = comicinfo.comicinfo_xml(tags, pages)
            else:
                comment = comicinfo.cbl_comment(tags)
        if xml is not None or comment is not None:
            comicinfo.write_tags(filepath, comicinfo=xml, comment=comment)
            logger.info("%s Successfully wrote %s tags [%s]" % (module, "+".join(styles), filepath))
    except Exception as e:
        logger.warn("%s Error : %s" % (module, e))
        sendnotify("Error - %s" % e, filename, module)
        tidyup(og_filepath, new_filepath, new_folder, manualmeta)
        return "fail"

    restore_tagged_file_mode(filepath, og_file_mode, module)
    return filepath


def tidyup(filepath, new_filepath, new_folder, manualmeta):
    if all([new_filepath is not None, new_folder is not None]):
        if runtime.current().config.FILE_OPTS == "copy" and not manualmeta:
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
        if runtime.current().config.PROWL_ENABLED:
            pushmessage = prline
            prowl = notifiers.PROWL()
            prowl.notify(pushmessage, "Comicarr metatagging error: ", module=module)

        if runtime.current().config.PUSHOVER_ENABLED:
            pushover = notifiers.PUSHOVER()
            pushover.notify(prline, prline2, module=module)

        if runtime.current().config.BOXCAR_ENABLED:
            boxcar = notifiers.BOXCAR()
            boxcar.notify(prline=prline, prline2=prline2, module=module)

        if runtime.current().config.PUSHBULLET_ENABLED:
            pushbullet = notifiers.PUSHBULLET()
            pushbullet.notify(prline=prline, prline2=prline2, module=module)

        if runtime.current().config.TELEGRAM_ENABLED:
            telegram = notifiers.TELEGRAM()
            telegram.notify(prline2)

        if runtime.current().config.SLACK_ENABLED:
            slack = notifiers.SLACK()
            slack.notify("Comicarr metatagging error: ", prline2, module=module)

        if runtime.current().config.MATTERMOST_ENABLED:
            mattermost = notifiers.MATTERMOST()
            mattermost.notify("Comicarr metatagging error: ", prline2, module=module)

        if runtime.current().config.DISCORD_ENABLED:
            discord = notifiers.DISCORD()
            discord.notify(filename, message, module=module)

        if runtime.current().config.EMAIL_ENABLED and runtime.current().config.EMAIL_ONPOST:
            logger.info("Sending email notification")
            email = notifiers.EMAIL()
            email.notify(prline2, "Comicarr metatagging error: ", module=module)

        if runtime.current().config.GOTIFY_ENABLED:
            gotify = notifiers.GOTIFY()
            gotify.notify("Comicarr metatagging error: ", prline2, module=module)

        if runtime.current().config.MATRIX_ENABLED:
            matrix = notifiers.MATRIX()
            matrix.notify("Comicarr metatagging error: ", prline2, module=module)
    except Exception as e:
        logger.warn("[NOTIFICATION] Unable to send notification: %s" % e)

    return
