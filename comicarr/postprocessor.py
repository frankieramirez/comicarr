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
import os
import pathlib
import re
import shutil
import time

from sqlalchemy import Integer, and_, func, inspect, or_, select, update

import comicarr
from comicarr import db, filechecker, getimage, helpers, logger, series_kind, updater, weeklypull
from comicarr.app.common.placement import OnExisting, Purpose, place
from comicarr.app.common.redaction import redacted_traceback
from comicarr.app.downloads._postprocess_completion import complete as _complete_postprocess
from comicarr.app.downloads.postprocess_pipeline import (
    PostProcessCleanupContext,
    PostProcessCleanupStage,
    PostProcessComicMatch,
    PostProcessContext,
    PostProcessInputContext,
    PostProcessInputStage,
    PostProcessItemDeps,
    PostProcessJournalStage,
    PostProcessNotification,
    PostProcessNotifyStage,
    PostProcessRun,
    process_comic_issue,
    process_manga_download,
)
from comicarr.app.downloads.pp_commands import safe_walk
from comicarr.app.manga.ledger import normalize_volume_number
from comicarr.config import get_manga_destination
from comicarr.tables import (
    annuals,
    comics,
    issues,
    nzblog,
    oneoffhistory,
    snatched,
    storyarcs,
    weekly,
)

_POSTPROCESS_JOURNAL_STAGE = PostProcessJournalStage()
_POSTPROCESS_INPUT_STAGE = PostProcessInputStage()


def mark_pull_row_downloaded(issueid):
    """Mark a one-off's existing pull-list row as Downloaded.

    An update rather than an upsert: weekly's upsert target is (ComicID,
    IssueID), and a one-off only knows its IssueID.
    """
    with db.get_engine().begin() as conn:
        conn.execute(update(weekly).where(weekly.c.IssueID == issueid).values(STATUS="Downloaded"))


def format_scan_summary(filename, candidate_count, selected_items, annual_count, story_arc):
    """Format the bounded Debug summary emitted once for each scanned file."""
    selected = (
        ", ".join("%s/%s" % (item.get("ComicID", "?"), item.get("ComicName", "?")) for item in selected_items) or "none"
    )
    return "[SCAN SUMMARY] %s: candidates=%s, selected=%s, annual_or_special=%s, story_arc=%s" % (
        filename,
        candidate_count,
        selected,
        annual_count,
        story_arc,
    )


def log_scan_summary(module, filename, candidate_count, selected_items, annual_count, story_arc):
    logger.fdebug(
        "%s%s" % (module, format_scan_summary(filename, candidate_count, selected_items, annual_count, story_arc))
    )


_COLLECTED_TYPES = ("TPB", "HC", "GN")


def numbered_by_volume(watch_values):
    """Return whether this series names its files by volume rather than issue.

    Collected editions and One-Shots have always been named this way, which is
    why the scan exempts them from every check that assumes a file carries an
    issue number: the weekly-pull cross-check, the "no issue number" rejection,
    and the fallback that defaults a missing number to 1.

    Manga belongs with them. In a periodical ``vNN`` names *which run* of the
    series a release belongs to; in manga it names *which book*. A manga volume
    file therefore carries no issue number at all, so applying the periodical
    checks to it rejects a perfectly good file.

    Rows built without the manga flag -- story arcs and one-offs assembled from
    tables that do not carry it -- read as comics, which is the prior behaviour.
    """
    if watch_values.get("IsManga"):
        return True
    return watch_values["Type"] in _COLLECTED_TYPES + ("One-Shot",)


def volume_match_settles_year(watch_values, volume_matched):
    """Return whether a matched volume makes the filename's year irrelevant.

    The year check exists because periodical issue numbers repeat across runs,
    so ``Batman 1`` needs a year to say *which* Batman 1. A manga volume number
    does not repeat -- there is one volume 1 -- so once it matches, the year
    cannot be evidence of a wrong file.

    It is routinely a mismatch, too: a provider dates the licensed English
    printing while the release is labelled with the volume's original year. For
    One-Punch Man v01 those are 2015 and 2014, and the file was rejected for it.

    Deliberately manga-only. A collected edition's year mismatch can still mean
    the wrong edition, so periodical and TPB behaviour is untouched.
    """
    return bool(volume_matched) and bool(watch_values.get("IsManga"))


def volume_settles_year_for_match(watch_values, match):
    """Return whether a volume match lets this file through a year mismatch.

    Deliberately NOT keyed off ``lonevol``. That flag means "the filename's
    volume digits equal ComicVersion", and manga has no ComicVersion -- the
    scan defaults it to 1. So v01 slipped through by coincidence while v20
    died on ``20 != 1``, which is the opposite of the intended rule.

    The only question that matters here is whether the file was located by its
    own volume: a real volume, not the "v1" FileChecker defaults onto a
    chapter file.
    """
    volume_located = (
        volume_identifies_file(watch_values)
        and not chapter_named_file(match)
        and (match or {}).get("series_volume") is not None
    )
    return volume_match_settles_year(watch_values, volume_located)


def chapter_named_file(match):
    """Return whether a scanned file is named by CHAPTER rather than volume.

    FileChecker sets ``booktype`` to "manga" only when it actually found a
    c/ch/chapter token, and then defaults a *missing* volume to "v1". So a
    chapter file arrives carrying a volume it never stated, and locating it by
    that volume files "Chainsaw Man c181 (2023).cbz" as issue 1.

    A volume-named file keeps ``booktype`` "issue", so this reads the
    distinction FileChecker already drew rather than re-deriving it.
    """
    return str((match or {}).get("booktype") or "").strip().lower() == "manga"


def manga_volume_rows(comicid, series_volume):
    """Resolve a manga VOLUME file to its rows via VolumeNumber.

    MangaDex and MyAnimeList series store the CHAPTER in ``Int_IssueNumber``,
    so looking a volume up in that column files "v20" against chapter 20 --
    ticking Have on a row the file has nothing to do with. Volume rows carry
    the volume in its own column, which is where rescan already matches them.

    Returns ``None`` when the series has no volume rows at all -- the
    ComicVine volumes-as-issues case, where ``Int_IssueNumber`` *is* the
    volume and the caller's existing query is already correct.
    """
    digits = re.sub("[^0-9.]", "", str(series_volume or "")).strip()
    wanted = normalize_volume_number(digits) if digits else None
    if wanted is None:
        return None
    rows = db.select_all(
        select(issues).where(
            and_(
                issues.c.ComicID == comicid,
                issues.c.VolumeNumber.isnot(None),
                issues.c.VolumeNumber != "",
            )
        )
    )
    if not rows:
        return None
    return [row for row in rows if normalize_volume_number(row.get("VolumeNumber")) == wanted]


def volume_identifies_file(watch_values):
    """Return whether a scanned file is located by volume rather than issue.

    This is :func:`numbered_by_volume` qualified by the run length, because a
    collected edition only numbers *files* by volume when the run actually has
    volumes to distinguish: TPB/HC/GN spanning more than one entry, or a
    One-Shot standing alone.

    Manga is not qualified that way. Volume 1 of a one-volume manga is still
    identified by its volume, so the run length says nothing useful here.
    """
    if watch_values.get("IsManga"):
        return True
    series_type = watch_values["Type"]
    total = watch_values["Total"]
    return (series_type in _COLLECTED_TYPES and total > 1) or (series_type == "One-Shot" and total == 1)


def summarize_scan_matches(normal_items, arc_items):
    """Build summary fields from the matches selected for one input file."""
    selected_items = normal_items + arc_items
    annual_count = sum(1 for item in selected_items if item.get("AnnualType"))
    story_arc = bool(arc_items or any(item.get("IssueArcID") for item in normal_items))
    return selected_items, annual_count, story_arc


class PostProcessor(object):
    """File matching and placement behind downloads.postprocessing.run/recover.

    The post-processing module owns the lock across this work and any retries.
    """

    EXISTS_LARGER = 1
    EXISTS_SAME = 2
    EXISTS_SMALLER = 3
    DOESNT_EXIST = 4

    NZB_NAME = 1
    FOLDER_NAME = 2
    FILE_NAME = 3

    def __init__(
        self,
        nzb_name,
        nzb_folder,
        issueid=None,
        module=None,
        queue=None,
        comicid=None,
        apicall=False,
        ddl=False,
        journal_release_key=None,
    ):
        """
        Creates a new post processor with the given file path and optionally an NZB name.

        file_path: The path to the file to be processed
        nzb_name: The name of the NZB which resulted in this file being downloaded (optional)
        """
        self.nzb_name = nzb_name
        self.nzb_folder = nzb_folder
        if module is not None:
            self.module = module + "[POST-PROCESSING]"
        else:
            self.module = "[POST-PROCESSING]"

        if queue:
            self.queue = queue

        self.apicall = apicall is True

        if ddl is True:
            self.ddl = True
        else:
            self.ddl = False

        self.valreturn = []
        self.extensions = (".cbr", ".cbz", ".pdf", ".cb7")

        self.extensions = tuple(x for x in self.extensions if x not in comicarr.CONFIG.IGNORE_SEARCH_WORDS)

        self.failed_files = 0
        self.log = ""
        if issueid is not None:
            self.issueid = issueid
        else:
            self.issueid = None

        if comicid is not None:
            self.comicid = comicid
        else:
            self.comicid = None
        self.issuearcid = None

        self.journal_release_key = journal_release_key

    def _journal_release_key(self, issueid=None, issuearcid=None):
        """Derive the journal release_key for this PP item.

        A canonical release_key threaded from postprocessing.run's atomic claim
        (self.journal_release_key) is PREFERRED over re-derivation so these
        markers advance the SAME journal row the PP-consumer claim advanced
        (single-derivation invariant). The PostProcessor does not receive
        provider/hash (only nzb_name, nzb_folder, issueid, comicid are threaded
        in), so a re-derived key could diverge from the claimed row; the
        threaded key closes that. Re-derive ONLY when no canonical key was
        threaded (manual/API/ComicRN PP with no journal row) — a divergent key
        in that case is a safe, behavior-neutral monotonic no-op worst case.

        EXCEPTION — explicit story-arc override: the secondary COPY2ARCDIR
        writes pass an explicit `issuearcid` and are supposed to terminalize
        the ARC row whose own `nzblog` ("S<IssueArcID>") entry is being
        deleted, NOT the primary claimed ISSUE row. Returning the threaded
        primary key for those would advance the wrong row and break the
        delete-and-terminalize-the-same-item invariant on COPY2ARCDIR
        recovery. So when an explicit `issuearcid` override is supplied we
        RE-DERIVE the key for the arc row. The primary path (no explicit
        issuearcid/issueid override) still returns the single threaded key, so
        the U4 single-derivation invariant — claim/markers/snatch all share
        the one key — is preserved unchanged.
        """
        return _POSTPROCESS_JOURNAL_STAGE.release_key(
            self._journal_context(),
            issue_id=issueid,
            issue_arc_id=issuearcid,
        )

    def _journal_context(self):
        return PostProcessContext(
            issue_id=self.issueid,
            issue_arc_id=self.issuearcid,
            comic_id=self.comicid,
            nzb_name=self.nzb_name,
            nzb_folder=self.nzb_folder,
            api_call=getattr(self, "apicall", False),
            ddl=getattr(self, "ddl", False),
            canonical_release_key=self.journal_release_key,
            log_module=self.module,
        )

    def _log_placement_failure(self, module, operation, src, dst, error):
        logger.error(
            "%s Failed to %s %s to %s (release=%s, issue=%s)\n%s"
            % (module, operation, src, dst, self.journal_release_key, self.issueid, redacted_traceback(error))
        )

    def _journal_pp(self, stage, issueid=None, issuearcid=None, payload=None, conn=None):
        """Record a PP-marker journal transition.

        The façade is monotonic (a late/duplicate/regressing write is a logged
        no-op). The `post_processing` (pre-move) and `moved` (post-move-pre-
        tidyup) markers are additive — a journal failure there must never abort
        post-processing, so it is logged and swallowed.

        CONTRACT: when `conn` is supplied this write JOINS the caller's
        explicit begin() block so the journal `post_processed` transition
        CO-COMMITS atomically with the `nzblog`-delete in that block. In that
        mode a failure MUST propagate so the whole block rolls back — nzblog
        must never be deleted while the journal still says
        post_processing/moved. The swallow-and-continue contract applies ONLY
        to the own-transaction (conn is None) additive markers.
        """
        _POSTPROCESS_JOURNAL_STAGE.transition(
            self._journal_context(),
            stage,
            issue_id=issueid,
            issue_arc_id=issuearcid,
            payload=payload,
            conn=conn,
        )

    def _log(self, message, level=logger):
        """
        A wrapper for the internal logger which also keeps track of messages and saves them to a string for sabnzbd post-processing logging functions.

        message: The string to log (unicode)
        level: The log level to use (optional)
        """
        self.log += message + "\n"

    def duplicate_process(self, dupeinfo):
        path_to_move = dupeinfo["to_dupe"]
        file_to_move = os.path.split(path_to_move)[1]

        if dupeinfo["action"] == "dupe_src" and comicarr.CONFIG.FILE_OPTS == "move":
            logger.info(
                "[DUPLICATE-CLEANUP] New File will be post-processed. Moving duplicate [%s] to Duplicate Dump Folder for manual intervention."
                % path_to_move
            )
        else:
            if comicarr.CONFIG.FILE_OPTS == "move":
                logger.info(
                    "[DUPLICATE-CLEANUP][MOVE-MODE] New File will not be post-processed. Moving duplicate [%s] to Duplicate Dump Folder for manual intervention."
                    % path_to_move
                )
            else:
                logger.info(
                    "[DUPLICATE-CLEANUP][COPY-MODE] NEW File will not be post-processed. Retaining file in original location [%s]"
                    % path_to_move
                )
                return True

        if comicarr.CONFIG.FILE_OPTS == "move":
            filechecker.validateAndCreateDirectory(comicarr.CONFIG.DUPLICATE_DUMP, True, module="[DUPLICATE-CLEANUP]")

            if comicarr.CONFIG.DUPLICATE_DATED_FOLDERS is True:
                todaydate = datetime.datetime.now().strftime("%Y-%m-%d")
                dump_folder = os.path.join(comicarr.CONFIG.DUPLICATE_DUMP, todaydate)
                filechecker.validateAndCreateDirectory(dump_folder, True, module="[DUPLICATE-DATED CLEANUP]")
            else:
                dump_folder = comicarr.CONFIG.DUPLICATE_DUMP

            try:
                shutil.move(path_to_move, os.path.join(dump_folder, file_to_move))
            except (OSError, IOError):
                logger.warn(
                    "[DUPLICATE-CLEANUP] Failed to move %s ... to ... %s"
                    % (path_to_move, os.path.join(dump_folder, file_to_move))
                )
                return False

            logger.warn(
                "[DUPLICATE-CLEANUP] Successfully moved %s ... to ... %s"
                % (path_to_move, os.path.join(dump_folder, file_to_move))
            )
            return True

    def tidyup(self, odir=None, del_nzbdir=False, sub_path=None, cacheonly=False, filename=None):
        PostProcessCleanupStage(narrate=self._log).tidy(
            PostProcessCleanupContext(
                nzb_folder=self.nzb_folder,
                nzb_name=self.nzb_name,
                issue_id=self.issueid,
                file_opts=comicarr.CONFIG.FILE_OPTS,
                enable_meta=comicarr.CONFIG.ENABLE_META,
                ddl_location=getattr(comicarr.CONFIG, "DDL_LOCATION", None),
                log_module=self.module,
                cache_dir=getattr(comicarr.CONFIG, "CACHE_DIR", None),
            ),
            odir,
            del_nzbdir=del_nzbdir,
            sub_path=sub_path,
            cacheonly=cacheonly,
            filename=filename,
        )

    def _notify_completed(self, completion, *, series, issue_year, issue_number, placed_path, issue_id, module):
        # No completion attempt on this path means legacy behaviour: notify.
        completed = True if completion is None else bool(completion.recorded)
        PostProcessNotifyStage(extract_cover=getimage.extract_image).notify(
            PostProcessNotification(
                series=series,
                issue_year=issue_year,
                issue_number=issue_number,
                placed_path=placed_path,
                issue_id=issue_id,
                log_module=module,
            ),
            completed=completed,
        )

    def Process(self):
        module = self.module
        self._log("nzb name: %s" % self.nzb_name)
        self._log("nzb folder: %s" % self.nzb_folder)
        logger.fdebug("%s nzb name: %s" % (module, self.nzb_name))
        logger.fdebug("%s nzb folder: %s" % (module, self.nzb_folder))
        use_sabnzbd = comicarr.USE_SABNZBD == 1
        use_nzbget = comicarr.USE_NZBGET == 1
        input_result = _POSTPROCESS_INPUT_STAGE.resolve(
            PostProcessInputContext(
                nzb_name=self.nzb_name,
                nzb_folder=self.nzb_folder,
                module=module,
                ddl=self.ddl,
                use_sabnzbd=use_sabnzbd,
                use_nzbget=use_nzbget,
                sab_direct_unpack=(comicarr.CONFIG.SAB_DIRECT_UNPACK if use_sabnzbd else False),
                sab_directory=(comicarr.CONFIG.SAB_DIRECTORY if use_sabnzbd else None),
                nzbget_directory=(comicarr.CONFIG.NZBGET_DIRECTORY if use_nzbget else None),
                nzbget_category=(comicarr.CONFIG.NZBGET_CATEGORY if use_nzbget else None),
            )
        )
        self.nzb_folder = input_result.folder
        if input_result.error is not None:
            self.valreturn.append({"self.log": self.log, "mode": "stop"})
            return self.queue.put(self.valreturn)

        self.oneoffinlist = False

        series = None
        if self.comicid is not None:
            series = db.select_one(
                select(comics.c.ComicID, comics.c.ContentType, comics.c.ContentKindSetBy).where(
                    comics.c.ComicID == self.comicid
                )
            )
        kind_source = series if series is not None else self.comicid
        if self.comicid is not None and series_kind.is_manga(kind_source):
            logger.fdebug(
                "%s Manga series detected (ComicID: %s) - branching to manga post-processing" % (module, self.comicid)
            )
            self._log("Manga series detected - using manga post-processing path")
            return self._process_manga()

        if any(
            [self.nzb_name == "Manual Run", self.issueid is not None, self.comicid is not None, self.apicall is True]
        ):
            if (
                all([self.issueid is None, self.comicid is not None, self.apicall is True])
                or self.nzb_name == "Manual Run"
                or all(
                    [
                        self.apicall is True,
                        self.comicid is None,
                        self.issueid is None,
                        self.nzb_name.startswith("0-Day"),
                    ]
                )
            ):
                if self.comicid is not None:
                    logger.fdebug("%s Now post-processing pack directly against ComicID: %s" % (module, self.comicid))
                elif all(
                    [
                        self.apicall is True,
                        self.issueid is None,
                        self.comicid is None,
                        self.nzb_name.startswith("0-Day"),
                    ]
                ):
                    logger.fdebug("%s Now post-processing 0-day pack: %s" % (module, self.nzb_name))
                else:
                    logger.fdebug("%s Manual Run initiated" % module)
                flc = filechecker.FileChecker(self.nzb_folder, justparse=True, pp_mode=True)
                filelist = flc.listFiles()
                if filelist["comiccount"] == 0:
                    logger.warn("There were no files located - check the debugging logs if you think this is in error.")
                    self.valreturn.append({"self.log": self.log, "mode": "stop"})
                    return self.queue.put(self.valreturn)
                logger.info(
                    "I have located %s files that I should be able to post-process. Continuing..."
                    % filelist["comiccount"]
                )
            else:
                if all([self.comicid is None, "_" not in self.issueid]):
                    cid = db.select_one(select(issues.c.ComicID).where(issues.c.IssueID == str(self.issueid)))
                    self.comicid = cid["ComicID"]
                else:
                    if "_" in self.issueid:
                        self.issuearcid = self.issueid
                        self.issueid = None
                        logger.fdebug(
                            "%s Now post-processing directly against StoryArcs -  ComicID: %s / IssueArcID: %s"
                            % (module, self.comicid, self.issuearcid)
                        )
                if self.issueid is not None:
                    logger.fdebug(
                        "%s Now post-processing directly against ComicID: %s / IssueID: %s"
                        % (module, self.comicid, self.issueid)
                    )
                if self.issuearcid is None:
                    if self.nzb_name.lower().endswith(self.extensions):
                        flc = filechecker.FileChecker(self.nzb_folder, file=self.nzb_name, pp_mode=True)
                        fl = flc.listFiles()
                        filelist = {}
                        filelist["comiclist"] = [fl]
                        filelist["comiccount"] = len(filelist["comiclist"])
                    else:
                        flc = filechecker.FileChecker(self.nzb_folder, justparse=True, pp_mode=True)
                        filelist = flc.listFiles()
                else:
                    filelist = {}
                    filelist["comiclist"] = []
                    filelist["comiccount"] = 0
            alt_list = []
            alt_db = db.select_all(select(comics).where(comics.c.AlternateSearch != "None"))
            if alt_db is not None:
                for aldb in alt_db:
                    as_d = filechecker.FileChecker(AlternateSearch=aldb["AlternateSearch"])
                    as_dinfo = as_d.altcheck()
                    alt_list.append(
                        {
                            "AS_Alt": as_dinfo["AS_Alt"],
                            "AS_Tuple": as_dinfo["AS_Tuple"],
                            "AS_DyComicName": aldb["DynamicComicName"],
                        }
                    )

            manual_arclist = []
            oneoff_issuelist = []
            manual_list = []
            for fl in filelist["comiclist"]:
                manual_list_start = len(manual_list)
                manual_arclist_start = len(manual_arclist)
                if (
                    all([fl["series_name"] is not None, fl["series_name"] != ""])
                    and comicarr.CONFIG.IGNORE_COVERS is True
                ):
                    cvchk = re.sub(r"[\s\s+\_\.]", "", fl["series_name"]).lower()
                    if any(["coveronly" in cvchk, "coversonly" in cvchk]):
                        logger.fdebug("Cover only detected. Ignoring result.")
                        continue

                if os.path.isfile(fl["comiclocation"]):
                    full_filename = fl["comiclocation"]
                else:
                    if fl["sub"] is not None:
                        full_filename = os.path.join(fl["comiclocation"], fl["sub"], fl["comicfilename"])
                    else:
                        full_filename = os.path.join(fl["comiclocation"], fl["comicfilename"])

                if os.path.isfile(full_filename):
                    condition_check = helpers.check_file_condition(full_filename)
                    if condition_check["status"] is False:
                        logger.warn(
                            f"CRC Check: File {full_filename} failed condition check ({condition_check['quality']}).  Ignoring file."
                        )
                        continue
                else:
                    logger.warn(f"Could not find file {full_filename}.  Skipping condition check.")

                self.matched = False
                as_d = filechecker.FileChecker()
                as_dinfo = as_d.dynamic_replace(fl["series_name"])
                orig_seriesname = as_dinfo["mod_seriesname"]
                mod_seriesname = as_dinfo["mod_seriesname"]
                loopchk = []
                if fl["alt_series"] is not None:
                    logger.fdebug("%s Alternate series naming detected: %s" % (module, fl["alt_series"]))
                    as_sinfo = as_d.dynamic_replace(fl["alt_series"])
                    mod_altseriesname = as_sinfo["mod_seriesname"]
                    if all([comicarr.CONFIG.ANNUALS_ON, "annual" in mod_altseriesname.lower()]) or all(
                        [comicarr.CONFIG.ANNUALS_ON, "special" in mod_altseriesname.lower()]
                    ):
                        mod_altseriesname = re.sub("2021annual", "", mod_altseriesname, flags=re.I).strip()
                        mod_altseriesname = re.sub("annual", "", mod_altseriesname, flags=re.I).strip()
                        mod_altseriesname = re.sub("special", "", mod_altseriesname, flags=re.I).strip()
                    if not any(re.sub(r"[\|\s]", "", mod_altseriesname).lower() == x for x in loopchk):
                        loopchk.append(re.sub(r"[\|\s]", "", mod_altseriesname.lower()))

                for x in alt_list:
                    cname = x["AS_DyComicName"]
                    for ab in x["AS_Alt"]:
                        tmp_ab = re.sub(" ", "", ab)
                        tmp_mod_seriesname = re.sub(" ", "", mod_seriesname)
                        if (
                            re.sub(r"\|", "", tmp_mod_seriesname.lower()).strip()
                            == re.sub(r"\|", "", tmp_ab.lower()).strip()
                        ):
                            if not any(re.sub(r"[\|\s]", "", cname.lower()) == x for x in loopchk):
                                loopchk.append(re.sub(r"[\|\s]", "", cname.lower()))

                if all([comicarr.CONFIG.ANNUALS_ON, "annual" in mod_seriesname.lower()]) or all(
                    [comicarr.CONFIG.ANNUALS_ON, "special" in mod_seriesname.lower()]
                ):
                    mod_seriesname = re.sub("2021annual", "", mod_seriesname, flags=re.I).strip()
                    mod_seriesname = re.sub("annual", "", mod_seriesname, flags=re.I).strip()
                    mod_seriesname = re.sub("special", "", mod_seriesname, flags=re.I).strip()

                if not any(re.sub(r"[\|\s]", "", mod_seriesname).lower() == x for x in loopchk):
                    loopchk.append(re.sub(r"[\|\s]", "", mod_seriesname.lower()))

                if any([self.issueid is not None, self.comicid is not None]) and fl["issueid"] is None:
                    comicseries = db.select_all(select(comics).where(comics.c.ComicID == self.comicid))
                else:
                    if fl["issueid"] is not None:
                        story_the_arcs = False
                        annchk = "no"
                        tmp_the_arc = {}
                        tmp_manual_list = {}
                        tmp_oneoff = {}
                        logger.info("issueid detected in filename: %s" % fl["issueid"])
                        ssi = db.select_one(
                            select(
                                storyarcs.c.ComicID,
                                storyarcs.c.IssueID,
                                storyarcs.c.IssueArcID,
                                storyarcs.c.IssueNumber,
                                storyarcs.c.ComicName,
                                storyarcs.c.SeriesYear,
                                storyarcs.c.StoryArc,
                                storyarcs.c.StoryArcID,
                                storyarcs.c.Publisher,
                                storyarcs.c.Volume,
                                storyarcs.c.ReadingOrder,
                            ).where(storyarcs.c.IssueID == fl["issueid"])
                        )
                        if ssi is not None:
                            annualtype = None
                            annualseries = None
                            if comicarr.CONFIG.ANNUALS_ON:
                                if "Annual" in ssi["ComicName"]:
                                    annualtype = "Annual"
                                elif "Special" in ssi["ComicName"]:
                                    annualtype = "Special"
                                annualseries = ssi["ComicName"]
                            story_the_arcs = True
                            tmp_the_arc = {
                                "ComicID": ssi["ComicID"],
                                "IssueID": ssi["IssueID"],
                                "IssueNumber": ssi["IssueNumber"],
                                "AnnualType": annualtype,
                                "AnnualSeries": annualseries,
                                "StoryArc": ssi["StoryArc"],
                                "StoryArcID": ssi["StoryArcID"],
                                "IssueArcID": ssi["IssueArcID"],
                                "SeriesYear": ssi["SeriesYear"],
                                "Publisher": ssi["Publisher"],
                                "ReadingOrder": ssi["ReadingOrder"],
                                "Volume": ssi["Volume"],
                                "ComicName": ssi["ComicName"],
                            }

                        csi = db.select_one(
                            select(
                                issues.c.ComicID,
                                issues.c.IssueID,
                                issues.c.Issue_Number,
                                comics.c.ComicName,
                                comics.c.ComicYear,
                                comics.c.AgeRating,
                            )
                            .select_from(comics.join(issues, comics.c.ComicID == issues.c.ComicID))
                            .where(issues.c.IssueID == fl["issueid"])
                        )
                        if csi is None:
                            csi = db.select_one(
                                select(
                                    annuals.c.ComicID,
                                    annuals.c.IssueID,
                                    annuals.c.Issue_Number,
                                    annuals.c.ReleaseComicName,
                                    comics.c.ComicName,
                                    comics.c.ComicYear,
                                    comics.c.AgeRating,
                                )
                                .select_from(comics.join(annuals, comics.c.ComicID == annuals.c.ComicID))
                                .where(and_(annuals.c.IssueID == fl["issueid"], annuals.c.Deleted != 1))
                            )
                            if csi is not None:
                                annchk = "yes"

                        osi = None
                        if all([csi is None, ssi is None]):
                            osi = db.select_one(
                                select(
                                    snatched.c.Issue_Number,
                                    snatched.c.ComicName,
                                    snatched.c.IssueID,
                                    snatched.c.ComicID,
                                    weekly.c.seriesyear,
                                )
                                .select_from(
                                    snatched.join(nzblog, snatched.c.IssueID == nzblog.c.IssueID).join(
                                        weekly, snatched.c.IssueID == weekly.c.IssueID
                                    )
                                )
                                .where(
                                    and_(
                                        snatched.c.IssueID == fl["issueid"],
                                        nzblog.c.OneOff == "1",
                                        snatched.c.ComicName.isnot(None),
                                    )
                                )
                            )
                            if osi is not None:
                                tmp_oneoff = {
                                    "ComicID": osi["ComicID"],
                                    "IssueID": osi["IssueID"],
                                    "IssueNumber": osi["Issue_Number"],
                                    "ComicName": osi["ComicName"],
                                    "SeriesYear": osi["seriesyear"],
                                    "One-Off": True,
                                }
                                self.oneoffinlist = True

                        if any([csi is not None, ssi is not None, osi is not None]):
                            if self.nzb_name == "Manual Run":
                                tname = str(pathlib.Path(fl["comicfilename"]))
                            else:
                                if os.path.isfile(fl["comiclocation"]):
                                    t_mp = pathlib.Path(fl["comiclocation"])
                                    tpath = str(t_mp.parents[0])
                                    tname = str(pathlib.Path(fl["comiclocation"]).name)
                                else:
                                    tname = str(pathlib.Path(fl["comiclocation"]).name)
                                    tpath = fl["comiclocation"]
                            xyb = tname.find("[__")
                            if xyb != -1:
                                yyb = tname.find("__]", xyb)
                                if yyb != -1:
                                    rem_issueid = tname[xyb + 3 : yyb]
                                    two_add = re.sub(r"\s+", "", tname[yyb + 3 :]).strip()
                                    if any([two_add == "", two_add == " "]):
                                        nfilename = "%s" % tname[:xyb].strip()
                                    else:
                                        nfilename = "%s%s" % (tname[:xyb].strip(), two_add)
                                    logger.fdebug(
                                        "issueid information [%s] removed successfully: %s" % (rem_issueid, nfilename)
                                    )

                                path_failure = False
                                if self.nzb_name == "Manual Run":
                                    if fl["sub"] is None:
                                        tpath = os.path.join(self.nzb_folder, fl["comicfilename"])
                                    else:
                                        tpath = os.path.join(self.nzb_folder, fl["sub"], fl["comicfilename"])
                                    if pathlib.Path(tpath).is_file():
                                        try:
                                            cloct = pathlib.Path(tpath).with_name(nfilename)
                                            clocation = str(pathlib.Path(tpath).replace(cloct))
                                            if any([clocation is None, clocation == "None"]):
                                                raise ValueError("clocation returned None value")
                                        except (ValueError, Exception):
                                            try:
                                                tt = str(pathlib.Path(tpath))
                                                clocation = str(pathlib.Path(tpath).with_name(nfilename))
                                                if any([clocation is None, clocation == "None"]):
                                                    raise ValueError("clocation returned None value")
                                            except (ValueError, Exception) as e:
                                                logger.warn(
                                                    "[%s] Skipping this file due to path conversion error [path: %s]/[name: %s]"
                                                    % (e, tpath, tname)
                                                )
                                                path_failure = True
                                            else:
                                                os.replace(tt, clocation)
                                    else:
                                        logger.warn(
                                            "Skipping this file due to path conversion error [path: %s]/[name: %s]"
                                            % (tpath, tname)
                                        )
                                        path_failure = True
                                else:
                                    logger.fdebug("tpath: %s" % (tpath))
                                    logger.fdebug("tname: %s" % (tname))
                                    if pathlib.Path(tpath).joinpath(tname).is_file():
                                        try:
                                            cloct = pathlib.Path(tpath).joinpath(tname).with_name(nfilename)
                                            logger.fdebug("cloct: %s" % (str(cloct)))
                                            clocation = str(pathlib.Path(tpath).joinpath(tname).replace(cloct))
                                            logger.fdebug("clocation: %s" % (clocation))
                                            if any([clocation is None, clocation == "None"]):
                                                raise ValueError("clocation returned None value")
                                        except (ValueError, Exception) as err:
                                            logger.fdebug(
                                                "[%s]error converting/copying path via pathlib - reverting to old method"
                                                % (err,)
                                            )
                                            try:
                                                tt = str(pathlib.Path(tpath).joinpath(tname))
                                                logger.fdebug("tt: %s" % (tt))
                                                clocation = str(
                                                    pathlib.Path(tpath).joinpath(tname).with_name(nfilename)
                                                )
                                                logger.fdebug("clocation: %s" % (clocation))
                                                if any([clocation is None, clocation == "None"]):
                                                    raise ValueError("clocation returned None value")
                                            except (ValueError, Exception) as e:
                                                logger.warn(
                                                    "[%s] Skipping this file due to path conversion error [path: %s]/[name: %s]"
                                                    % (e, tpath, tname)
                                                )
                                                path_failure = True
                                            else:
                                                os.replace(tt, clocation)
                                                self.nzb_folder = clocation
                                        else:
                                            self.nzb_folder = clocation
                                    else:
                                        try:
                                            if all(
                                                [
                                                    pathlib.Path(tpath) != pathlib.Path(comicarr.CACHE_DIR),
                                                    pathlib.Path(tpath) != pathlib.Path(comicarr.CONFIG.DDL_LOCATION),
                                                    pathlib.Path(tpath)
                                                    != pathlib.Path(comicarr.CONFIG.DDL_LOCATION).joinpath("mega"),
                                                ]
                                            ):
                                                if pathlib.Path(tpath).is_file():
                                                    try:
                                                        cloct = pathlib.Path(tpath).with_name(nfilename)
                                                        logger.fdebug("cloct: %s" % (str(cloct)))
                                                        clocation = str(pathlib.Path(tpath).replace(cloct))
                                                        logger.fdebug("clocation: %s" % (clocation))
                                                        if any([clocation is None, clocation == "None"]):
                                                            raise ValueError("clocation returned None value")
                                                    except (ValueError, Exception) as err:
                                                        logger.fdebug(
                                                            "[%s]error converting/copying path via pathlib - reverting to old method"
                                                            % (err,)
                                                        )
                                                        try:
                                                            tt = str(pathlib.Path(tpath).joinpath(tname))
                                                            logger.fdebug("tt: %s" % (tt))
                                                            clocation = str(
                                                                pathlib.Path(tpath).joinpath(tname).with_name(nfilename)
                                                            )
                                                            logger.fdebug("clocation: %s" % (clocation))
                                                            if any([clocation is None, clocation == "None"]):
                                                                raise ValueError("clocation returned None value")
                                                        except Exception as e:
                                                            logger.warn(
                                                                "[%s] Skipping this file due to path conversion error [path: %s]/[name: %s]"
                                                                % (e, tpath, tname)
                                                            )
                                                            path_failure = True
                                                        else:
                                                            os.replace(tt, clocation)
                                                            self.nzb_folder = clocation
                                                    else:
                                                        self.nzb_folder = clocation
                                                else:
                                                    logger.warn(
                                                        "Skipping this file due to path conversion error [path: %s]/[name: %s]"
                                                        % (tpath, tname)
                                                    )
                                                    path_failure = True
                                            else:
                                                logger.warn(
                                                    "Skipping this file due to path conversion error [path: %s]/[name: %s]"
                                                    % (tpath, tname)
                                                )
                                                path_failure = True
                                        except Exception as e:
                                            logger.warn(
                                                "[%s] Skipping this file due to path conversion error [path: %s]/[name: %s]"
                                                % (e, tpath, tname)
                                            )
                                            path_failure = True

                                if path_failure is True:
                                    continue

                                logger.fdebug("path with the issueid removed: %s" % clocation)

                                if csi is not None:
                                    annualtype = None
                                    annualseries = None
                                    if annchk == "yes":
                                        if "Annual" in csi["ReleaseComicName"]:
                                            annualtype = "Annual"
                                        elif "Special" in csi["ReleaseComicName"]:
                                            annualtype = "Special"
                                        annualseries = csi["ReleaseComicName"]
                                    else:
                                        if "Annual" in csi["ComicName"]:
                                            annualtype = "Annual"
                                        elif "Special" in csi["ComicName"]:
                                            annualtype = "Special"

                                    tmp_manual_list = {
                                        "ComicLocation": clocation,
                                        "ComicID": csi["ComicID"],
                                        "IssueID": csi["IssueID"],
                                        "IssueNumber": csi["Issue_Number"],
                                        "AnnualType": annualtype,
                                        "AnnualSeries": annualseries,
                                        "ComicName": csi["ComicName"],
                                        "AgeRating": csi["AgeRating"],
                                        "Series": fl["series_name"],
                                        "SeriesYear": csi["ComicYear"],
                                        "AltSeries": fl["alt_series"],
                                        "One-Off": False,
                                        "ForcedMatch": True,
                                    }

                                if story_the_arcs is True:
                                    if tmp_manual_list:
                                        if tmp_manual_list["IssueID"] == tmp_the_arc["IssueID"]:
                                            tmp_manual_list["IssueArcID"] = ssi["IssueArcID"]
                                    else:
                                        tmp_the_arc["ComicLocation"] = clocation
                                        tmp_the_arc["Filename"] = nfilename
                                if tmp_oneoff is not None:
                                    tmp_oneoff["ComicLocation"] = clocation

                        if tmp_manual_list:
                            manual_list.append(tmp_manual_list)
                        elif tmp_the_arc:
                            manual_arclist.append(tmp_the_arc)
                        elif tmp_oneoff:
                            oneoff_issuelist.append(tmp_oneoff)
                        continue

                    comicseries = db.select_all(
                        select(comics).where(func.lower(comics.c.DynamicComicName).in_([x.lower() for x in loopchk]))
                    )

                if not comicseries or orig_seriesname != mod_seriesname:
                    if any(["special" in orig_seriesname.lower(), "annual" in orig_seriesname.lower()]) and all(
                        [comicarr.CONFIG.ANNUALS_ON, orig_seriesname != mod_seriesname]
                    ):
                        if not any(re.sub(r"[\|\s]", "", orig_seriesname).lower() == x for x in loopchk):
                            loopchk.append(re.sub(r"[\|\s]", "", orig_seriesname.lower()))
                            comicseries = db.select_all(
                                select(comics).where(
                                    func.lower(comics.c.DynamicComicName).in_([x.lower() for x in loopchk])
                                )
                            )
                watchvals = []
                for wv in comicseries:
                    try:
                        tmp_iss = helpers.issuedigits(fl["issue_number"])
                    except Exception as e:
                        logger.warn("Unable to determine issue number. This is a no-go, Captain [%s]" % (e,))

                    if wv["ComicPublished"] is None:
                        logger.fdebug(
                            "Publication Run cannot be generated - probably due to an incomplete Refresh. Manually refresh the following series and try again: %s (%s)"
                            % (wv["ComicName"], wv["ComicYear"])
                        )
                        continue
                    if (
                        wv["Status"] == "Paused" and any([wv["cv_removed"] == 2, bool(wv["ForceContinuing"]) is True])
                    ) or (
                        wv["Have"] == wv["Total"]
                        and not any(["Present" in wv["ComicPublished"], helpers.now()[:4] in wv["ComicPublished"]])
                    ):
                        dbcheck = db.select_one(
                            select(issues.c.Status).where(
                                and_(issues.c.ComicID == wv["ComicID"], issues.c.Int_IssueNumber == tmp_iss)
                            )
                        )
                        if not dbcheck and comicarr.CONFIG.ANNUALS_ON:
                            dbcheck = db.select_one(
                                select(annuals.c.Status).where(
                                    and_(annuals.c.ComicID == wv["ComicID"], annuals.c.Int_IssueNumber == tmp_iss)
                                )
                            )
                        if dbcheck:
                            if any([dbcheck["Status"] == "Wanted", dbcheck["Status"] == "Snatched"]):
                                logger.fdebug(
                                    "Series is 100%s complete, but specific issue %s matched up to a %s status. Let's Go!"
                                    % ("%", tmp_iss, dbcheck["Status"])
                                )
                            else:
                                logger.fdebug(
                                    "Series is 100%s complete, however status is not Wanted (or Snatched), but %s. Set to Wanted for this to post-process on the next run."
                                    % ("%", dbcheck["Status"])
                                )
                                continue
                        else:
                            logger.warn(
                                "%s [%s] is either Paused or in an Ended status with 100%s completion. Ignoring for match."
                                % (wv["ComicName"], wv["ComicYear"], "%")
                            )
                            continue
                    wv_comicname = wv["ComicName"]
                    wv_dynamicname = wv["DynamicComicName"]
                    wv_comicpublisher = wv["ComicPublisher"]
                    wv_comicpublished = wv["ComicPublished"]
                    wv_alternatesearch = wv["AlternateSearch"]
                    wv_comicid = wv["ComicID"]
                    if wv["Corrected_Type"] is None:
                        wv_type = wv["Type"]
                    else:
                        wv_type = wv["Corrected_Type"]
                    wv_seriesyear = wv["ComicYear"]
                    wv_comicversion = wv["ComicVersion"]
                    wv_publisher = wv["ComicPublisher"]
                    wv_is_manga = series_kind.is_manga(wv)
                    wv_total = int(wv["Total"])
                    wv_agerating = wv["AgeRating"]
                    wv_latestissue = wv["LatestIssue"]
                    wv_intlatestissue = wv["intLatestIssue"]
                    wv_forcecontinuing = bool(wv["ForceContinuing"])
                    ld_check = db.select_one(
                        select(issues.c.ReleaseDate, issues.c.Issue_Number, issues.c.Int_IssueNumber)
                        .where(issues.c.ComicID == wv["ComicID"])
                        .order_by(issues.c.ReleaseDate.desc())
                    )
                    highest_issue_check = db.select_one(
                        select(issues.c.Issue_Number, issues.c.Int_IssueNumber)
                        .where(issues.c.ComicID == wv["ComicID"])
                        .order_by(issues.c.Int_IssueNumber.desc())
                    )
                    if ld_check:
                        if comicarr.CONFIG.ANNUALS_ON:
                            ld_check_ann = db.select_one(
                                select(annuals.c.ReleaseDate, annuals.c.Issue_Number, annuals.c.Int_IssueNumber)
                                .where(annuals.c.ComicID == wv["ComicID"])
                                .order_by(annuals.c.ReleaseDate.desc())
                            )
                            highest_issue_check_ann = db.select_one(
                                select(annuals.c.Issue_Number, annuals.c.Int_IssueNumber)
                                .where(annuals.c.ComicID == wv["ComicID"])
                                .order_by(annuals.c.Int_IssueNumber.desc())
                            )
                            if ld_check_ann:
                                if all(
                                    [
                                        ld_check_ann["ReleaseDate"] != "0000-00-00",
                                        ld_check_ann["ReleaseDate"] is not None,
                                    ]
                                ):
                                    if int(re.sub("-", "", ld_check_ann["ReleaseDate"]).strip()) > int(
                                        re.sub("-", "", ld_check["ReleaseDate"]).strip()
                                    ):
                                        logger.fdebug(
                                            "Annual date newer than latest issue date - re-assigning latestdate as an annual"
                                        )
                                        ld_check = ld_check_ann
                            if highest_issue_check_ann:
                                if highest_issue_check_ann["Int_IssueNumber"] > highest_issue_check["Int_IssueNumber"]:
                                    logger.fdebug(
                                        "Largest annual issue # higher than issues - re-assigning latestissue as an annual"
                                    )
                                    highest_issue_check = highest_issue_check_ann
                        if ld_check["ReleaseDate"][:4] != wv["LatestDate"][:4]:
                            if ld_check["ReleaseDate"][:4] > wv["LatestDate"][:4]:
                                latestdate = ld_check["ReleaseDate"]
                            else:
                                latestdate = wv["LatestDate"]
                        else:
                            latestdate = ld_check["ReleaseDate"]
                        tmplatestissue = highest_issue_check["Issue_Number"]
                        tmplatestissueint = highest_issue_check["Int_IssueNumber"]
                        logger.fdebug("tmplatestissue: %s" % (tmplatestissue))
                        logger.fdebug("tmplatestissueint: %s" % (tmplatestissueint))
                        try:
                            if tmplatestissueint >= wv_intlatestissue:
                                latestissue_int = tmplatestissueint
                                latestissue = tmplatestissue
                            else:
                                latestissue_int = wv_intlatestissue
                                latestissue = wv_latestissue
                        except Exception:
                            latestissue_int = tmplatestissueint
                            latestissue = tmplatestissue
                    else:
                        latestdate = wv["LatestDate"]
                        latestissue = wv_latestissue
                        latestissue_int = wv_intlatestissue

                    if latestdate == "0000-00-00" or latestdate == "None" or latestdate is None:
                        logger.fdebug(
                            "Forcing a refresh of series: %s as it appears to have incomplete issue dates."
                            % wv_comicname
                        )
                        updater.dbUpdate([wv_comicid])
                        logger.fdebug("Refresh complete for %s. Rechecking issue dates for completion." % wv_comicname)
                        ld_check = db.select_one(
                            select(issues.c.ReleaseDate, issues.c.Issue_Number, issues.c.Int_IssueNumber)
                            .where(issues.c.ComicID == wv["ComicID"])
                            .order_by(issues.c.ReleaseDate.desc())
                        )
                        if ld_check:
                            try:
                                if ld_check["ReleaseDate"][:4] != wv["LatestDate"][:4]:
                                    if ld_check["ReleaseDate"][:4] > wv["LatestDate"][:4]:
                                        latestdate = ld_check["ReleaseDate"]
                                    else:
                                        latestdate = wv["LatestDate"]
                                else:
                                    latestdate = ld_check["ReleaseDate"]
                            except Exception:
                                logger.fdebug(
                                    "Unable to properly attain the Latest Date for series: %s. Cannot check against this series for post-processing."
                                    % wv_comicname
                                )
                                continue
                            tmplatestissue = ld_check["Issue_Number"]
                            tmplatestissueint = ld_check["Int_IssueNumber"]
                            logger.fdebug("tmplatestissue: %s" % (tmplatestissue))
                            logger.fdebug("tmplatestissueint: %s" % (tmplatestissueint))
                            try:
                                if tmplatestissueint >= wv_intlatestissue:
                                    latestissue_int = tmplatestissueint
                                    latestissue = tmplatestissue
                                else:
                                    latestissue_int = wv_intlatestissue
                                    latestissue = wv_latestissue
                            except Exception:
                                latestissue_int = tmplatestissueint
                                latestissue = tmplatestissue
                        else:
                            latestdate = wv["LatestDate"]
                            latestissue = wv_latestissue
                            latestissue_int = wv_intlatestissue

                        logger.fdebug("Latest Date (after forced refresh) set to :" + str(latestdate))

                        if latestdate == "0000-00-00" or latestdate == "None" or latestdate is None:
                            logger.fdebug(
                                "Unable to properly attain the Latest Date for series: %s. Cannot check against this series for post-processing."
                                % wv_comicname
                            )
                            continue

                    watchvals.append(
                        {
                            "ComicName": wv_comicname,
                            "DynamicName": wv_dynamicname,
                            "ComicPublisher": wv_comicpublisher,
                            "ComicPublished": wv_comicpublished,
                            "AlternateSearch": wv_alternatesearch,
                            "ComicID": wv_comicid,
                            "LastUpdated": wv["LastUpdated"],
                            "WatchValues": {
                                "SeriesYear": wv_seriesyear,
                                "LatestDate": latestdate,
                                "ForceContinuing": wv_forcecontinuing,
                                "LatestIssue": latestissue,
                                "LatestIssueInt": latestissue_int,
                                "ComicVersion": wv_comicversion,
                                "AgeRating": wv_agerating,
                                "Type": wv_type,
                                "Publisher": wv_publisher,
                                "Total": wv_total,
                                "ComicID": wv_comicid,
                                "IsManga": wv_is_manga,
                                "IsArc": False,
                            },
                        }
                    )

                nm = 0
                for cs in watchvals:
                    wm = filechecker.FileChecker(
                        watchcomic=cs["ComicName"],
                        Publisher=cs["ComicPublisher"],
                        AlternateSearch=cs["AlternateSearch"],
                        manual=cs["WatchValues"],
                    )
                    watchmatch = wm.matchIT(fl)
                    if watchmatch["process_status"] == "fail":
                        nm += 1
                        continue
                    else:
                        try:
                            # A chapter-named file is excluded even for manga:
                            # FileChecker handed it a defaulted "v1" it never
                            # stated, and locating by that files c181 as issue 1.
                            if volume_identifies_file(cs["WatchValues"]) and not chapter_named_file(watchmatch):
                                if watchmatch["series_volume"] is not None:
                                    just_the_digits = re.sub("[^0-9]", "", watchmatch["series_volume"]).strip()
                                else:
                                    just_the_digits = re.sub("[^0-9.-]", "", watchmatch["justthedigits"]).strip()
                            else:
                                just_the_digits = watchmatch["justthedigits"]
                        except Exception as e:
                            logger.warn(
                                "[Exception: %s] Unable to properly match up/retrieve issue number (or volume) for this [CS: %s] [WATCHMATCH: %s]"
                                % (e, cs, watchmatch)
                            )
                            nm += 1
                            continue

                        if just_the_digits is not None:
                            temploc = just_the_digits.replace("_", " ")
                            temploc = re.sub("[\\#']", "", temploc)
                        else:
                            if numbered_by_volume(cs["WatchValues"]):
                                temploc = "1"
                            else:
                                temploc = None
                        datematch = "False"

                        if temploc is None and not numbered_by_volume(cs["WatchValues"]):
                            logger.info(
                                "this should have an issue number to match to this particular series: %s"
                                % cs["ComicID"]
                            )
                            continue

                        if temploc is not None and (
                            any(["annual" in temploc.lower(), "special" in temploc.lower()])
                            and comicarr.CONFIG.ANNUALS_ON is True
                        ):
                            biannchk = re.sub("-", "", temploc.lower()).strip()
                            if "biannual" in biannchk:
                                logger.fdebug("%s Bi-Annual detected." % module)
                                fcdigit = helpers.issuedigits(re.sub("biannual", "", str(biannchk)).strip())
                            else:
                                if "annual" in temploc.lower():
                                    year_check = re.findall(r"(\d{4})(?=[\s]|annual\b|$)", temploc, flags=re.I)
                                    if year_check:
                                        ann_line = "%s annual" % year_check[0]
                                        fcdigit = helpers.issuedigits(
                                            re.sub(ann_line, "", str(temploc.lower())).strip()
                                        )
                                    fcdigit = helpers.issuedigits(re.sub("annual", "", str(temploc.lower())).strip())
                                else:
                                    fcdigit = helpers.issuedigits(re.sub("special", "", str(temploc.lower())).strip())
                                logger.fdebug(
                                    "%s Annual/Special detected [%s]. ComicID assigned as %s"
                                    % (module, fcdigit, cs["ComicID"])
                                )
                            annchk = "yes"
                            issuechk = db.select_all(
                                select(annuals).where(
                                    and_(
                                        annuals.c.ComicID == cs["ComicID"],
                                        annuals.c.Int_IssueNumber == fcdigit,
                                        annuals.c.Deleted != 1,
                                    )
                                )
                            )
                        else:
                            annchk = "no"
                            if temploc is not None:
                                fcdigit = helpers.issuedigits(temploc)
                                issuechk = None
                                # A manga VOLUME resolves on VolumeNumber. On
                                # MangaDex/MAL Int_IssueNumber holds the
                                # chapter, so querying it here would file v20
                                # against chapter 20. Returns None when the
                                # series has no volume rows (ComicVine stores
                                # volumes AS issues), and the query below is
                                # then already the right one.
                                if cs["WatchValues"].get("IsManga") and not chapter_named_file(watchmatch):
                                    issuechk = manga_volume_rows(cs["ComicID"], watchmatch["series_volume"])
                                if issuechk is None:
                                    issuechk = db.select_all(
                                        select(issues).where(
                                            and_(
                                                issues.c.ComicID == cs["ComicID"],
                                                issues.c.Int_IssueNumber == fcdigit,
                                            )
                                        )
                                    )
                            else:
                                fcdigit = None
                                issuechk = db.select_all(select(issues).where(issues.c.ComicID == cs["ComicID"]))

                        if not issuechk:
                            try:
                                logger.fdebug(
                                    "%s No corresponding issue #%s found for %s" % (module, temploc, cs["ComicID"])
                                )
                            except Exception as e:
                                logger.fdebug("[PP] Error logging issue info: %s" % e)
                                continue
                            c_date = cs["LastUpdated"]
                            if c_date is None:
                                logger.error(
                                    "%s %s failed during a previous add /refresh as it has no Last Update timestamp. Forcing refresh now."
                                    % (module, cs["ComicName"])
                                )
                            else:
                                c_obj_date = datetime.datetime.strptime(c_date, "%Y-%m-%d %H:%M:%S")
                                n_date = datetime.datetime.now()
                                absdiff = abs(n_date - c_obj_date)
                                hours = (absdiff.days * 24 * 60 * 60 + absdiff.seconds) / 3600.0
                                if hours < 1:
                                    logger.fdebug(
                                        "%s %s [%s] Was refreshed less than 1 hours ago. Skipping Refresh at this time so we don't hammer things unnecessarily."
                                        % (module, cs["ComicName"], cs["ComicID"])
                                    )
                                    continue

                            try:
                                updater.dbUpdate([cs["ComicID"]])
                                logger.fdebug(
                                    "%s Succssfully refreshed series - now re-querying against new data for issue #%s."
                                    % (module, temploc)
                                )
                            except Exception as e:
                                logger.error("%s %s failed to update comic: %s" % (module, cs["ComicName"], e))
                                continue

                            if annchk == "yes":
                                issuechk = db.select_all(
                                    select(annuals).where(
                                        and_(
                                            annuals.c.ComicID == cs["ComicID"],
                                            annuals.c.Int_IssueNumber == fcdigit,
                                            annuals.c.Deleted != 1,
                                        )
                                    )
                                )
                            else:
                                issuechk = None
                                # The refresh is often exactly what added the
                                # volume rows, so re-apply the volume lookup
                                # here too. Retrying Int_IssueNumber alone
                                # would file the v20 we just fetched against
                                # chapter 20.
                                if cs["WatchValues"].get("IsManga") and not chapter_named_file(watchmatch):
                                    issuechk = manga_volume_rows(cs["ComicID"], watchmatch["series_volume"])
                                if issuechk is None:
                                    issuechk = db.select_all(
                                        select(issues).where(
                                            and_(issues.c.ComicID == cs["ComicID"], issues.c.Int_IssueNumber == fcdigit)
                                        )
                                    )
                            if not issuechk:
                                logger.fdebug(
                                    "%s No corresponding issue #%s found for %s even after refreshing. It might not have the information available as of yet..."
                                    % (module, temploc, cs["ComicID"])
                                )
                                continue

                        for isc in issuechk:
                            if (
                                any([temploc is not None, temploc != 999999999999999])
                                and all(
                                    [
                                        annchk == "no",
                                        helpers.issuedigits(temploc) != helpers.issuedigits(isc["Issue_Number"]),
                                    ]
                                )
                                or all(
                                    [
                                        annchk == "yes",
                                        helpers.issuedigits(re.sub("annual", "", temploc.lower()).strip())
                                        != helpers.issuedigits(isc["Issue_Number"]),
                                    ]
                                )
                            ):
                                logger.fdebug("issues dont match. Skipping")
                                continue

                            datematch = "True"
                            datechkit = False
                            if isc["ReleaseDate"] is not None and isc["ReleaseDate"] != "0000-00-00":
                                try:
                                    if isc["DigitalDate"] != "0000-00-00" and int(
                                        re.sub("-", "", isc["DigitalDate"]).strip()
                                    ) <= int(re.sub("-", "", isc["ReleaseDate"]).strip()):
                                        monthval = isc["DigitalDate"]
                                        watch_issueyear = isc["DigitalDate"][:4]
                                    else:
                                        monthval = isc["ReleaseDate"]
                                        watch_issueyear = isc["ReleaseDate"][:4]
                                except (ValueError, TypeError, KeyError):
                                    monthval = isc["ReleaseDate"]
                                    watch_issueyear = isc["ReleaseDate"][:4]

                            else:
                                try:
                                    if isc["DigitalDate"] != "0000-00-00" and int(
                                        re.sub("-", "", isc["DigitalDate"]).strip()
                                    ) <= int(re.sub("-", "", isc["ReleaseDate"]).strip()):
                                        monthval = isc["DigitalDate"]
                                        watch_issueyear = isc["DigitalDate"][:4]
                                    else:
                                        monthval = isc["IssueDate"]
                                        watch_issueyear = isc["IssueDate"][:4]
                                except (ValueError, TypeError, KeyError):
                                    monthval = isc["IssueDate"]
                                    watch_issueyear = isc["IssueDate"][:4]

                            if len(watchmatch) >= 1 and watchmatch["issue_year"] is not None:
                                logger.fdebug(
                                    "%s[ISSUE-VERIFY] Now checking against %s - %s"
                                    % (module, cs["ComicName"], cs["ComicID"])
                                )
                                issyr = None

                                if isc["DigitalDate"] is not None and isc["DigitalDate"] != "0000-00-00":
                                    if int(isc["DigitalDate"][:4]) < int(watchmatch["issue_year"]):
                                        logger.fdebug(
                                            "%s[ISSUE-VERIFY] %s is before the issue year of %s that was discovered in the filename"
                                            % (module, isc["DigitalDate"], watchmatch["issue_year"])
                                        )
                                        datematch = "False"

                                elif isc["ReleaseDate"] is not None and isc["ReleaseDate"] != "0000-00-00":
                                    if int(isc["ReleaseDate"][:4]) < int(watchmatch["issue_year"]):
                                        logger.fdebug(
                                            "%s[ISSUE-VERIFY] %s is before the issue year of %s that was discovered in the filename"
                                            % (module, isc["ReleaseDate"], watchmatch["issue_year"])
                                        )
                                        datematch = "False"
                                else:
                                    if int(isc["IssueDate"][:4]) < int(watchmatch["issue_year"]):
                                        logger.fdebug(
                                            "%s[ISSUE-VERIFY] %s is before the issue year %s that was discovered in the filename"
                                            % (module, isc["IssueDate"], watchmatch["issue_year"])
                                        )
                                        datematch = "False"

                                if int(watch_issueyear) != int(watchmatch["issue_year"]):
                                    if int(monthval[5:7]) == 11 or int(monthval[5:7]) == 12:
                                        issyr = int(monthval[:4]) + 1
                                        logger.fdebug("%s[ISSUE-VERIFY] IssueYear (issyr) is %s" % (module, issyr))
                                        datechkit = True
                                    elif int(monthval[5:7]) == 1 or int(monthval[5:7]) == 2 or int(monthval[5:7]) == 3:
                                        issyr = int(monthval[:4]) - 1
                                        datechkit = True

                                    if datechkit is True and issyr is not None:
                                        logger.fdebug(
                                            "%s[ISSUE-VERIFY] %s comparing to %s : rechecking by month-check versus year."
                                            % (module, issyr, watchmatch["issue_year"])
                                        )
                                        datematch = "True"
                                        if int(issyr) != int(watchmatch["issue_year"]):
                                            logger.fdebug(
                                                "%s[ISSUE-VERIFY][.:FAIL:.] Issue is before the modified issue year of %s"
                                                % (module, issyr)
                                            )
                                            datematch = "False"

                            else:
                                if fcdigit is None:
                                    logger.info(
                                        "%s[ISSUE-VERIFY] Found matching issue for ComicID: %s / IssueID: %s"
                                        % (module, cs["ComicID"], isc["IssueID"])
                                    )
                                else:
                                    logger.info(
                                        "%s[ISSUE-VERIFY] Found matching issue # %s for ComicID: %s / IssueID: %s"
                                        % (module, fcdigit, cs["ComicID"], isc["IssueID"])
                                    )

                            if datematch == "True":
                                datematch = "False"
                                lonevol = False
                                watch_values = cs["WatchValues"]
                                second_check = False
                                if watch_values["LatestIssueInt"] >= fcdigit:
                                    logger.fdebug(
                                        "possible match - issue in dB (%s) is greater than issue in file (%s)"
                                        % (watch_values["LatestIssueInt"], fcdigit)
                                    )

                                    as_d = filechecker.FileChecker(watchcomic=watchmatch["series_name"])
                                    as_dinfo = as_d.dynamic_replace(watchmatch["series_name"])
                                    tmpseriesname = as_dinfo["mod_seriesname"]
                                    if all(
                                        [
                                            comicarr.CONFIG.ANNUALS_ON,
                                            "annual" in tmpseriesname.lower(),
                                            "annual" not in cs["DynamicName"],
                                        ]
                                    ) or all([comicarr.CONFIG.ANNUALS_ON, "special" in tmpseriesname.lower()]):
                                        tmpseriesname = re.sub("2021annual", "", tmpseriesname, flags=re.I).strip()
                                        tmpseriesname = re.sub("annual", "", tmpseriesname, flags=re.I).strip()
                                        tmpseriesname = re.sub("special", "", tmpseriesname, flags=re.I).strip()
                                    dynamic_seriesname = re.sub(r"[\|\s]", "", tmpseriesname.lower()).strip()

                                    alts = []
                                    for x in alt_list:
                                        if x["AS_DyComicName"] == cs["DynamicName"]:
                                            alts = x["AS_Alt"]
                                    alt_listing = [True if x.lower() == dynamic_seriesname else False for x in alts]

                                    if any(
                                        [cs["DynamicName"] == dynamic_seriesname, alt_listing]
                                    ) and not numbered_by_volume(cs["WatchValues"]):
                                        logger.fdebug(
                                            "name match exact : %s - %s" % (cs["DynamicName"], dynamic_seriesname)
                                        )
                                        test = db.select_one(
                                            select(
                                                weekly.c.COMIC,
                                                weekly.c.DynamicName,
                                                weekly.c.ISSUE,
                                                weekly.c.weeknumber,
                                                weekly.c.year,
                                            )
                                            .where(weekly.c.ComicID == cs["ComicID"])
                                            .order_by(
                                                weekly.c.year.desc(), func.cast(weekly.c.weeknumber, Integer).desc()
                                            )
                                        )
                                        if test:
                                            logger.fdebug("test matched to ComicID: %s" % (cs["ComicID"]))
                                            week_comic = test["COMIC"]
                                            week_dynamicname = test["DynamicName"]
                                            if all(
                                                [
                                                    comicarr.CONFIG.ANNUALS_ON,
                                                    "annual" in week_dynamicname.lower(),
                                                    "annual" not in dynamic_seriesname,
                                                ]
                                            ) or all(
                                                [comicarr.CONFIG.ANNUALS_ON, "special" in week_dynamicname.lower()]
                                            ):
                                                week_dynamicname = re.sub(
                                                    "2021annual", "", week_dynamicname, flags=re.I
                                                ).strip()
                                                week_dynamicname = re.sub(
                                                    "annual", "", week_dynamicname, flags=re.I
                                                ).strip()
                                                week_dynamicname = re.sub(
                                                    "special", "", week_dynamicname, flags=re.I
                                                ).strip()
                                            week_issue = test["ISSUE"]
                                            week_intissue = helpers.issuedigits(week_issue)
                                            logger.fdebug(
                                                "week_dynamicname: %s / dynamic_seriesname: %s"
                                                % (week_dynamicname, dynamic_seriesname)
                                            )
                                            logger.fdebug("week_intissue: %s / fcdigit: %s" % (week_intissue, fcdigit))
                                            logger.fdebug(
                                                "last issue for series listed as #%s in week %s, %s"
                                                % (week_issue, test["weeknumber"], test["year"])
                                            )
                                            if any([week_dynamicname == dynamic_seriesname, alt_listing]):
                                                if any(
                                                    [
                                                        "Present" in cs["ComicPublished"],
                                                        watch_values["ForceContinuing"] is True,
                                                    ]
                                                ):
                                                    if week_intissue == fcdigit:
                                                        logger.fdebug(
                                                            "Matched exactly on Series Title, IssueNumber, present on the pull."
                                                        )
                                                        second_check = True
                                                    else:
                                                        logger.fdebug(
                                                            "Matched to Series Title - but Issue Number is not on pull and series is ongoing. Bypassing this check to let the dates verify."
                                                        )
                                                        second_check = True
                                                else:
                                                    tmp_weeknumber = int(test["weeknumber"])
                                                    tmp_weekyear = int(test["year"])
                                                    if (
                                                        tmp_weekyear == int(comicarr.CURRENT_YEAR)
                                                    ) and tmp_weeknumber + 2 >= int(comicarr.CURRENT_WEEKNUMBER):
                                                        logger.fdebug(
                                                            "%s %s should have current weekly data if this was an ongoing publication."
                                                            % (watchmatch["series_name"], watchmatch["justthedigits"])
                                                        )
                                                        second_check = False
                                                    else:
                                                        second_check = True
                                            else:
                                                logger.fdebug(
                                                    "%s %s in filename don't match up to what's in the dB %s %s [%s]"
                                                    % (
                                                        watchmatch["series_name"],
                                                        watchmatch["justthedigits"],
                                                        week_comic,
                                                        week_issue,
                                                        cs["ComicID"],
                                                    )
                                                )
                                        else:
                                            if any(
                                                [
                                                    "Present" not in cs["ComicPublished"],
                                                    watch_values["ForceContinuing"] is True,
                                                    helpers.now()[:4] not in cs["ComicPublished"],
                                                ]
                                            ):
                                                logger.fdebug(
                                                    "%s %s is not part of an ongoing publication. Bypassing this check and letting the dates verify below"
                                                    % (watchmatch["series_name"], watchmatch["justthedigits"])
                                                )
                                                second_check = True
                                            else:
                                                ischk = isc["ReleaseDate"]
                                                if ischk:
                                                    rls_the_date = datetime.datetime.strptime(
                                                        isc["ReleaseDate"], "%Y-%m-%d"
                                                    )
                                                    rls_weeknumber = rls_the_date.isocalendar()[1]
                                                    rls_weekyear = rls_the_date.isocalendar()[0]
                                                    popit = inspect(db.get_engine()).has_table("weekly")
                                                    if popit:
                                                        w_results = db.select_all(
                                                            select(weekly).where(
                                                                and_(
                                                                    weekly.c.weeknumber == str(rls_weeknumber),
                                                                    weekly.c.year == str(rls_weekyear),
                                                                )
                                                            )
                                                        )
                                                        if len(w_results) == 0:
                                                            second_check = True
                                    else:
                                        pass
                                else:
                                    logger.fdebug("not a match")

                                if second_check is False and not numbered_by_volume(cs["WatchValues"]):
                                    logger.fdebug(
                                        "%s %s in filename don't match up to what's in the dB for %s [%s]. This is a wrong match. Continuing..."
                                        % (
                                            watchmatch["series_name"],
                                            watchmatch["justthedigits"],
                                            cs["ComicName"],
                                            cs["ComicID"],
                                        )
                                    )
                                    continue

                                if any([watch_values["ComicVersion"] is None, watch_values["ComicVersion"] == "None"]):
                                    tmp_watchlist_vol = "1"
                                else:
                                    tmp_watchlist_vol = re.sub("[^0-9]", "", watch_values["ComicVersion"]).strip()
                                if all(
                                    [watchmatch["series_volume"] != "None", watchmatch["series_volume"] is not None]
                                ):
                                    tmp_watchmatch_vol = re.sub("[^0-9]", "", watchmatch["series_volume"]).strip()
                                    if len(tmp_watchmatch_vol) == 4:
                                        if int(tmp_watchmatch_vol) == int(watch_values["SeriesYear"]):
                                            logger.fdebug(
                                                "%s[ISSUE-VERIFY][SeriesYear-Volume MATCH] Series Year of %s matched to volume/year label of %s"
                                                % (module, watch_values["SeriesYear"], tmp_watchmatch_vol)
                                            )
                                            if len(watchvals) == 1:
                                                logger.fdebug(
                                                    "%s[ISSUE-VERIFY][Lone Volume MATCH] Series Volume Year of %s indicates only volume for this series on your watchlist."
                                                    % (module, watch_values["SeriesYear"])
                                                )
                                                lonevol = True
                                        else:
                                            logger.fdebug(
                                                "%s[ISSUE-VERIFY][SeriesYear-Volume FAILURE] Series Year of %s DID NOT match to volume/year label of %s"
                                                % (module, watch_values["SeriesYear"], tmp_watchmatch_vol)
                                            )
                                            datematch = "False"
                                    elif len(watchvals) > 1 and int(tmp_watchmatch_vol) >= 1:
                                        if int(tmp_watchmatch_vol) == int(tmp_watchlist_vol):
                                            logger.fdebug(
                                                "%s[ISSUE-VERIFY][SeriesYear-Volume MATCH] Volume label of series Year of %s matched to volume label of %s"
                                                % (module, watch_values["ComicVersion"], watchmatch["series_volume"])
                                            )
                                            lonevol = True
                                        else:
                                            logger.fdebug(
                                                "%s[ISSUE-VERIFY][SeriesYear-Volume FAILURE] Volume label of Series Year of %s DID NOT match to volume label of %s"
                                                % (module, watch_values["ComicVersion"], watchmatch["series_volume"])
                                            )
                                            datematch = "False"
                                    elif len(watchvals) == 1 and int(tmp_watchmatch_vol) == int(tmp_watchlist_vol):
                                        logger.fdebug(
                                            "%s[ISSUE-VERIFY][SeriesYear-Volume MATCH] Volume label of series Year of %s matched to volume label of %s"
                                            % (module, watch_values["ComicVersion"], watchmatch["series_volume"])
                                        )
                                        lonevol = True
                                else:
                                    if any(
                                        [
                                            tmp_watchlist_vol is None,
                                            tmp_watchlist_vol == "None",
                                            tmp_watchlist_vol == "",
                                        ]
                                    ):
                                        logger.fdebug(
                                            "%s[ISSUE-VERIFY][NO VOLUME PRESENT] No Volume label present for series. Dropping down to Issue Year matching."
                                            % module
                                        )
                                        datematch = "False"
                                    elif len(watchvals) == 1 and int(tmp_watchlist_vol) == 1:
                                        logger.fdebug(
                                            "%s[ISSUE-VERIFY][Lone Volume MATCH] Volume label of %s indicates only volume for this series on your watchlist."
                                            % (module, watch_values["ComicVersion"])
                                        )
                                        lonevol = True
                                    elif int(tmp_watchlist_vol) > 1:
                                        logger.fdebug(
                                            "%s[ISSUE-VERIFY][Lone Volume FAILURE] Volume label of %s indicates that there is more than one volume for this series, but the one on your watchlist has no volume label set."
                                            % (module, watch_values["ComicVersion"])
                                        )
                                        datematch = "False"

                                if datematch == "False" and all(
                                    [
                                        watchmatch["issue_year"] is not None,
                                        watchmatch["issue_year"] != "None",
                                        watch_issueyear is not None,
                                    ]
                                ):
                                    if int(watch_issueyear) == int(watchmatch["issue_year"]):
                                        logger.fdebug(
                                            "%s[ISSUE-VERIFY][Issue Year MATCH] Issue Year of %s is a match to the year found in the filename of : %s"
                                            % (module, watch_issueyear, watchmatch["issue_year"])
                                        )
                                        datematch = "True"
                                    else:
                                        logger.fdebug(
                                            "%s[ISSUE-VERIFY][Issue Year FAILURE] Issue Year of %s does NOT match the year found in the filename of : %s"
                                            % (module, watch_issueyear, watchmatch["issue_year"])
                                        )
                                        logger.fdebug(
                                            "%s[ISSUE-VERIFY] Checking against complete date to see if month published could allow for different publication year."
                                            % module
                                        )
                                        if issyr is not None:
                                            if int(issyr) != int(watchmatch["issue_year"]):
                                                logger.fdebug(
                                                    "%s[ISSUE-VERIFY][Issue Year FAILURE] Modified Issue year of %s is before the modified issue year of %s"
                                                    % (module, issyr, watchmatch["issue_year"])
                                                )
                                            else:
                                                logger.fdebug(
                                                    "%s[ISSUE-VERIFY][Issue Year MATCH] Modified Issue Year of %s is a match to the year found in the filename of : %s"
                                                    % (module, issyr, watchmatch["issue_year"])
                                                )
                                                datematch = "True"
                                elif datematch == "False" and watchmatch["issue_year"] is None and lonevol is True:
                                    logger.fdebug(
                                        "%s[LONE-VOLUME/NO YEAR][MATCH] Only Volume on watchlist matches, no year present in filename. Assuming match based on volume and title."
                                        % module
                                    )
                                    datematch = "True"

                                if datematch == "False" and volume_settles_year_for_match(
                                    cs["WatchValues"], watchmatch
                                ):
                                    logger.fdebug(
                                        "%s[MANGA][VOLUME MATCH] Volume %s matched, so the year in the filename (%s) does not decide this file. Assuming match based on volume and title."
                                        % (module, watchmatch["series_volume"], watchmatch["issue_year"])
                                    )
                                    datematch = "True"

                                if datematch == "True":
                                    if watchmatch["sub"]:
                                        logger.fdebug(
                                            "%s[SUB: %s][CLOCATION: %s]"
                                            % (module, watchmatch["sub"], watchmatch["comiclocation"])
                                        )
                                        clocation = os.path.join(
                                            watchmatch["comiclocation"], watchmatch["sub"], watchmatch["comicfilename"]
                                        )
                                        if not os.path.exists(clocation):
                                            scrubs = re.sub(watchmatch["comiclocation"], "", watchmatch["sub"]).strip()
                                            if scrubs[:2] == "//" or scrubs[:2] == "\\":
                                                scrubs = scrubs[1:]
                                                if os.path.exists(scrubs):
                                                    logger.fdebug("[MODIFIED CLOCATION] %s" % scrubs)
                                                    clocation = scrubs
                                    else:
                                        logger.fdebug("%s[CLOCATION] %s" % (module, watchmatch["comiclocation"]))
                                        if self.issueid is not None and os.path.isfile(watchmatch["comiclocation"]):
                                            clocation = watchmatch["comiclocation"]
                                        else:
                                            clocation = os.path.join(
                                                watchmatch["comiclocation"], watchmatch["comicfilename"]
                                            )
                                    annualtype = None
                                    if annchk == "yes":
                                        if "Annual" in isc["ReleaseComicName"]:
                                            annualtype = "Annual"
                                        elif "Special" in isc["ReleaseComicName"]:
                                            annualtype = "Special"
                                    else:
                                        if "Annual" in isc["ComicName"]:
                                            annualtype = "Annual"
                                        elif "Special" in isc["ComicName"]:
                                            annualtype = "Special"

                                    manual_list.append(
                                        {
                                            "ComicLocation": clocation,
                                            "ComicID": cs["ComicID"],
                                            "IssueID": isc["IssueID"],
                                            "IssueNumber": isc["Issue_Number"],
                                            "AnnualType": annualtype,
                                            "ComicName": cs["ComicName"],
                                            "AgeRating": cs["WatchValues"]["AgeRating"],
                                            "Series": watchmatch["series_name"],
                                            "SeriesYear": cs["WatchValues"]["SeriesYear"],
                                            "AltSeries": watchmatch["alt_series"],
                                            "One-Off": False,
                                            "ForcedMatch": False,
                                        }
                                    )
                                    break
                                else:
                                    logger.fdebug(
                                        "%s[NON-MATCH: %s-%s] Incorrect series - not populating..continuing post-processing"
                                        % (module, cs["ComicName"], cs["ComicID"])
                                    )
                                    continue
                            else:
                                logger.fdebug(
                                    "%s[NON-MATCH: %s-%s] Incorrect series - not populating..continuing post-processing"
                                    % (module, cs["ComicName"], cs["ComicID"])
                                )
                                continue

                    if datematch == "True":
                        xmld = filechecker.FileChecker()
                        xmld1 = xmld.dynamic_replace(cs["ComicName"])
                        xseries = xmld1["mod_seriesname"].lower()
                        xmld2 = xmld.dynamic_replace(watchmatch["series_name"])
                        xfile = xmld2["mod_seriesname"].lower()

                        if re.sub(r"\|", "", xseries) == re.sub(r"\|", "", xfile):
                            logger.fdebug(
                                "%s[DEFINITIVE-NAME MATCH] Definitive name match exactly to : %s [%s]"
                                % (module, watchmatch["series_name"], cs["ComicID"])
                            )
                            if len(manual_list) > 1:
                                manual_list = [
                                    item
                                    for item in manual_list
                                    if all([item["IssueID"] == isc["IssueID"], item["AnnualType"] is not None])
                                    or all([item["IssueID"] == isc["IssueID"], item["ComicLocation"] == clocation])
                                    or all([item["IssueID"] != isc["IssueID"], item["ComicLocation"] != clocation])
                                ]
                            self.matched = True
                        else:
                            continue

                    if datematch == "True":
                        logger.fdebug(
                            "%s[SUCCESSFUL MATCH: %s-%s] Match verified for %s"
                            % (module, cs["ComicName"], cs["ComicID"], fl["comicfilename"])
                        )
                        break
                    elif self.matched is True:
                        logger.warn(
                            "%s[MATCH: %s - %s] We matched by name for this series, but cannot find a corresponding issue number in the series list."
                            % (module, cs["ComicName"], cs["ComicID"])
                        )

                if self.issuearcid is None:
                    arc_series = db.select_all(
                        select(storyarcs).where(
                            func.lower(storyarcs.c.DynamicComicName).in_([x.lower() for x in loopchk])
                        )
                    )
                else:
                    if self.issuearcid[0] == "S":
                        self.issuearcid = self.issuearcid[1:]
                    arc_series = db.select_all(select(storyarcs).where(storyarcs.c.IssueArcID == self.issuearcid))

                if arc_series is None:
                    logger.error(
                        "%s No Story Arcs in Watchlist that contain that particular series - aborting Manual Post Processing. Maybe you should be running Import?"
                        % module
                    )
                    return
                else:
                    tmp_arclist = []
                    arcvals = []
                    for av in arc_series:
                        arcvals.append(
                            {
                                "ComicName": av["ComicName"],
                                "ArcValues": {
                                    "StoryArc": av["StoryArc"],
                                    "StoryArcID": av["StoryArcID"],
                                    "IssueArcID": av["IssueArcID"],
                                    "ComicName": av["ComicName"],
                                    "DynamicComicName": av["DynamicComicName"],
                                    "ComicPublisher": av["IssuePublisher"],
                                    "Publisher": av["Publisher"],
                                    "IssueID": av["IssueID"],
                                    "IssueNumber": av["IssueNumber"],
                                    "IssueYear": av["IssueYEAR"],
                                    "ReadingOrder": av["ReadingOrder"],
                                    "IssueDate": av["IssueDate"],
                                    "Status": av["Status"],
                                    "Location": av["Location"],
                                },
                                "WatchValues": {
                                    "SeriesYear": av["SeriesYear"],
                                    "LatestDate": av["IssueDate"],
                                    "ComicVersion": av["Volume"],
                                    "ComicID": av["ComicID"],
                                    "Publisher": av["IssuePublisher"],
                                    "Total": int(av["TotalIssues"]),
                                    "Type": av["Type"],
                                    "IsManga": series_kind.is_manga(av),
                                    "IsArc": True,
                                },
                            }
                        )

                    nm = 0
                    from collections import defaultdict

                    res = defaultdict(list)
                    for acv in arcvals:
                        if len(manual_list) == 0:
                            res[acv["ComicName"]].append(
                                {"ArcValues": acv["ArcValues"], "WatchValues": acv["WatchValues"]}
                            )
                        else:
                            acv_check = [x for x in manual_list if x["ComicID"] == acv["WatchValues"]["ComicID"]]
                            if acv_check:
                                res[acv["ComicName"]].append(
                                    {"ArcValues": acv["ArcValues"], "WatchValues": acv["WatchValues"]}
                                )
                if len(res) > 0:
                    logger.fdebug(
                        "%s Now Checking if this issue(s) may also reside in one of %s storyarc's that I am watching."
                        % (module, len(res))
                    )
                for k, v in list(res.items()):
                    i = 0
                    while i < len(v):
                        if k is None or k == "None":
                            pass
                        else:
                            arcm = filechecker.FileChecker(
                                watchcomic=k, Publisher=v[i]["ArcValues"]["ComicPublisher"], manual=v[i]["WatchValues"]
                            )
                            arcmatch = arcm.matchIT(fl)
                            if arcmatch["process_status"] == "fail":
                                nm += 1
                            else:
                                try:
                                    # Same exclusion as the watchlist scan above: a
                                    # chapter-named file carries a defaulted "v1" it
                                    # never stated, and would file c181 as issue 1.
                                    if volume_identifies_file(v[i]["WatchValues"]) and not chapter_named_file(arcmatch):
                                        if arcmatch["series_volume"] is not None:
                                            just_the_digits = re.sub("[^0-9]", "", arcmatch["series_volume"]).strip()
                                        else:
                                            just_the_digits = re.sub("[^0-9.]", "", arcmatch["justthedigits"]).strip()
                                    else:
                                        just_the_digits = arcmatch["justthedigits"]
                                except Exception as e:
                                    logger.warn(
                                        "[Exception: %s] Unable to properly match up/retrieve issue number (or volume) for this [CS: %s] [WATCHMATCH: %s]"
                                        % (e, v[i]["ArcValues"], v[i]["WatchValues"])
                                    )
                                    nm += 1
                                    continue

                                if just_the_digits is not None:
                                    temploc = just_the_digits.replace("_", " ")
                                    temploc = re.sub("[\\#']", "", temploc)
                                else:
                                    if numbered_by_volume(v[i]["WatchValues"]):
                                        temploc = "1"
                                    else:
                                        temploc = None

                                if any([temploc is not None, temploc != 999999999999999]) and helpers.issuedigits(
                                    temploc
                                ) != helpers.issuedigits(v[i]["ArcValues"]["IssueNumber"]):
                                    i += 1
                                    continue
                                else:
                                    annualtype = None
                                    if temploc is not None and (
                                        any(["annual" in temploc.lower(), "special" in temploc.lower()])
                                        and comicarr.CONFIG.ANNUALS_ON is True
                                    ):
                                        biannchk = re.sub("-", "", temploc.lower()).strip()
                                        if "biannual" in biannchk:
                                            logger.fdebug("%s Bi-Annual detected." % module)
                                            fcdigit = helpers.issuedigits(re.sub("biannual", "", str(biannchk)).strip())
                                            annualtype = "BiAnnual"
                                        else:
                                            if "annual" in temploc.lower():
                                                year_check = re.findall(
                                                    r"(\d{4})(?=[\s]|annual\b|$)", temploc, flags=re.I
                                                )
                                                if year_check:
                                                    ann_line = "%s annual" % year_check[0]
                                                    fcdigit = helpers.issuedigits(
                                                        re.sub(ann_line, "", str(temploc.lower())).strip()
                                                    )
                                                fcdigit = helpers.issuedigits(
                                                    re.sub("annual", "", str(temploc.lower())).strip()
                                                )
                                                annualtype = "Annual"
                                            else:
                                                fcdigit = helpers.issuedigits(
                                                    re.sub("special", "", str(temploc.lower())).strip()
                                                )
                                                annualtype = "Special"
                                            logger.fdebug(
                                                "%s %s detected [%s]. ComicID assigned as %s"
                                                % (module, annualtype, fcdigit, v[i]["WatchValues"]["ComicID"])
                                            )
                                        annchk = "yes"
                                        issuechk_row = db.select_one(
                                            select(storyarcs).where(
                                                and_(
                                                    storyarcs.c.ComicID == v[i]["WatchValues"]["ComicID"],
                                                    storyarcs.c.Int_IssueNumber == fcdigit,
                                                )
                                            )
                                        )
                                        issuechk = [issuechk_row] if issuechk_row else []
                                    else:
                                        annchk = "no"
                                        if temploc is not None:
                                            fcdigit = helpers.issuedigits(temploc)
                                            issuechk = db.select_all(
                                                select(storyarcs).where(
                                                    and_(
                                                        storyarcs.c.ComicID == v[i]["WatchValues"]["ComicID"],
                                                        storyarcs.c.Int_IssueNumber == fcdigit,
                                                    )
                                                )
                                            )
                                        else:
                                            fcdigit = None
                                            issuechk = db.select_all(
                                                select(storyarcs).where(
                                                    storyarcs.c.ComicID == v[i]["WatchValues"]["ComicID"]
                                                )
                                            )

                                if issuechk is None:
                                    try:
                                        logger.fdebug(
                                            "%s No corresponding issue # found for %s"
                                            % (module, v[i]["WatchValues"]["ComicID"])
                                        )
                                    except Exception as e:
                                        logger.fdebug("[PP] Error logging arc issue info: %s" % e)
                                        continue
                                else:
                                    for isc in issuechk:
                                        datematch = "True"
                                        datechkit = False
                                        if isc["ReleaseDate"] is not None and isc["ReleaseDate"] != "0000-00-00":
                                            try:
                                                if isc["DigitalDate"] != "0000-00-00" and int(
                                                    re.sub("-", "", isc["DigitalDate"]).strip()
                                                ) <= int(re.sub("-", "", isc["ReleaseDate"]).strip()):
                                                    monthval = isc["DigitalDate"]
                                                    arc_issueyear = isc["DigitalDate"][:4]
                                                else:
                                                    monthval = isc["ReleaseDate"]
                                                    arc_issueyear = isc["ReleaseDate"][:4]
                                            except (ValueError, TypeError, KeyError):
                                                monthval = isc["ReleaseDate"]
                                                arc_issueyear = isc["ReleaseDate"][:4]

                                        else:
                                            try:
                                                if isc["DigitalDate"] != "0000-00-00" and int(
                                                    re.sub("-", "", isc["DigitalDate"]).strip()
                                                ) <= int(re.sub("-", "", isc["ReleaseDate"]).strip()):
                                                    monthval = isc["DigitalDate"]
                                                    arc_issueyear = isc["DigitalDate"][:4]
                                                else:
                                                    monthval = isc["IssueDate"]
                                                    arc_issueyear = isc["IssueDate"][:4]
                                            except (ValueError, TypeError, KeyError):
                                                monthval = isc["IssueDate"]
                                                arc_issueyear = isc["IssueDate"][:4]

                                        if len(arcmatch) >= 1 and arcmatch["issue_year"] is not None:
                                            logger.fdebug(
                                                "%s[ARC ISSUE-VERIFY] Now checking against %s - %s"
                                                % (module, k, v[i]["WatchValues"]["ComicID"])
                                            )
                                            issyr = None
                                            if isc["DigitalDate"] is not None and isc["DigitalDate"] != "0000-00-00":
                                                if int(isc["DigitalDate"][:4]) < int(arcmatch["issue_year"]):
                                                    logger.fdebug(
                                                        "%s[ARC ISSUE-VERIFY] %s is before the issue year of %s that was discovered in the filename"
                                                        % (module, isc["DigitalDate"], arcmatch["issue_year"])
                                                    )
                                                    datematch = "False"

                                            elif all(
                                                [isc["ReleaseDate"] is not None, isc["ReleaseDate"] != "0000-00-00"]
                                            ):
                                                if isc["ReleaseDate"] == "0000-00-00":
                                                    datevalue = isc["IssueDate"]
                                                else:
                                                    datevalue = isc["ReleaseDate"]
                                                if int(datevalue[:4]) < int(arcmatch["issue_year"]):
                                                    logger.fdebug(
                                                        "%s[ARC ISSUE-VERIFY] %s is before the issue year %s that was discovered in the filename"
                                                        % (module, datevalue[:4], arcmatch["issue_year"])
                                                    )
                                                    datematch = "False"
                                            elif all([isc["IssueDate"] is not None, isc["IssueDate"] != "0000-00-00"]):
                                                if isc["IssueDate"] == "0000-00-00":
                                                    datevalue = isc["ReleaseDate"]
                                                else:
                                                    datevalue = isc["IssueDate"]
                                                if int(datevalue[:4]) < int(arcmatch["issue_year"]):
                                                    logger.fdebug(
                                                        "%s[ARC ISSUE-VERIFY] %s is before the issue year of %s that was discovered in the filename"
                                                        % (module, datevalue[:4], arcmatch["issue_year"])
                                                    )
                                                    datematch = "False"
                                            else:
                                                if int(isc["IssueDate"][:4]) < int(arcmatch["issue_year"]):
                                                    logger.fdebug(
                                                        "%s[ARC ISSUE-VERIFY] %s is before the issue year %s that was discovered in the filename"
                                                        % (module, isc["IssueDate"], arcmatch["issue_year"])
                                                    )
                                                    datematch = "False"

                                            if int(arc_issueyear) != int(arcmatch["issue_year"]):
                                                if int(monthval[5:7]) == 11 or int(monthval[5:7]) == 12:
                                                    issyr = int(monthval[:4]) + 1
                                                    datechkit = True
                                                    logger.fdebug(
                                                        "%s[ARC ISSUE-VERIFY] IssueYear (issyr) is %s" % (module, issyr)
                                                    )
                                                elif (
                                                    int(monthval[5:7]) == 1
                                                    or int(monthval[5:7]) == 2
                                                    or int(monthval[5:7]) == 3
                                                ):
                                                    issyr = int(monthval[:4]) - 1
                                                    datechkit = True

                                                if datechkit is True and issyr is not None:
                                                    logger.fdebug(
                                                        "%s[ARC ISSUE-VERIFY] %s comparing to %s : rechecking by month-check versus year."
                                                        % (module, issyr, arcmatch["issue_year"])
                                                    )
                                                    datematch = "True"
                                                    if int(issyr) != int(arcmatch["issue_year"]):
                                                        logger.fdebug(
                                                            "%s[.:FAIL:.] Issue is before the modified issue year of %s"
                                                            % (module, issyr)
                                                        )
                                                        datematch = "False"

                                        else:
                                            if fcdigit is None:
                                                logger.info(
                                                    "%s Found matching issue for ComicID: %s / IssueID: %s"
                                                    % (module, v[i]["WatchValues"]["ComicID"], isc["IssueID"])
                                                )
                                            else:
                                                logger.info(
                                                    "%s Found matching issue # %s for ComicID: %s / IssueID: %s"
                                                    % (module, fcdigit, v[i]["WatchValues"]["ComicID"], isc["IssueID"])
                                                )

                                        if datematch == "True":
                                            datematch = "False"
                                            lonevol = False
                                            arc_values = v[i]["WatchValues"]
                                            if any(
                                                [
                                                    arc_values["ComicVersion"] is None,
                                                    arc_values["ComicVersion"] == "None",
                                                ]
                                            ):
                                                tmp_arclist_vol = "1"
                                            else:
                                                tmp_arclist_vol = re.sub(
                                                    "[^0-9]", "", arc_values["ComicVersion"]
                                                ).strip()
                                            if all(
                                                [
                                                    arcmatch["series_volume"] != "None",
                                                    arcmatch["series_volume"] is not None,
                                                ]
                                            ):
                                                tmp_arcmatch_vol = re.sub(
                                                    "[^0-9]", "", arcmatch["series_volume"]
                                                ).strip()
                                                if len(tmp_arcmatch_vol) == 4:
                                                    if int(tmp_arcmatch_vol) == int(arc_values["SeriesYear"]):
                                                        logger.fdebug(
                                                            "%s[ARC ISSUE-VERIFY][SeriesYear-Volume MATCH] Series Year of %s matched to volume/year label of %s"
                                                            % (module, arc_values["SeriesYear"], tmp_arcmatch_vol)
                                                        )
                                                    else:
                                                        logger.fdebug(
                                                            "%s[ARC ISSUE-VERIFY][SeriesYear-Volume FAILURE] Series Year of %s DID NOT match to volume/year label of %s"
                                                            % (module, arc_values["SeriesYear"], tmp_arcmatch_vol)
                                                        )
                                                        datematch = "False"
                                                elif len(arcvals) > 1 and int(tmp_arcmatch_vol) >= 1:
                                                    if int(tmp_arcmatch_vol) == int(tmp_arclist_vol):
                                                        logger.fdebug(
                                                            "%s[ARC ISSUE-VERIFY][SeriesYear-Volume MATCH] Volume label of series Year of %s matched to volume label of %s"
                                                            % (
                                                                module,
                                                                arc_values["ComicVersion"],
                                                                arcmatch["series_volume"],
                                                            )
                                                        )
                                                        lonevol = True
                                                    else:
                                                        logger.fdebug(
                                                            "%s[ARC ISSUE-VERIFY][SeriesYear-Volume FAILURE] Volume label of Series Year of %s DID NOT match to volume label of %s"
                                                            % (
                                                                module,
                                                                arc_values["ComicVersion"],
                                                                arcmatch["series_volume"],
                                                            )
                                                        )
                                                        datematch = "False"
                                                elif len(arcvals) == 1 and int(tmp_arcmatch_vol) == int(
                                                    tmp_arclist_vol
                                                ):
                                                    logger.fdebug(
                                                        "%s[ARC ISSUE-VERIFY][SeriesYear-Volume MATCH] Volume label of series Year of %s matched to volume label of %s"
                                                        % (
                                                            module,
                                                            arc_values["ComicVersion"],
                                                            arcmatch["series_volume"],
                                                        )
                                                    )
                                                    lonevol = True
                                            else:
                                                if any(
                                                    [
                                                        tmp_arclist_vol is None,
                                                        tmp_arclist_vol == "None",
                                                        tmp_arclist_vol == "",
                                                    ]
                                                ):
                                                    logger.fdebug(
                                                        "%s[ARC ISSUE-VERIFY][NO VOLUME PRESENT] No Volume label present for series. Dropping down to Issue Year matching."
                                                        % module
                                                    )
                                                    datematch = "False"
                                                elif len(arcvals) == 1 and int(tmp_arclist_vol) == 1:
                                                    logger.fdebug(
                                                        "%s[ARC ISSUE-VERIFY][Lone Volume MATCH] Volume label of %s indicates only volume for this series on your watchlist."
                                                        % (module, arc_values["ComicVersion"])
                                                    )
                                                    lonevol = True
                                                elif int(tmp_arclist_vol) > 1:
                                                    logger.fdebug(
                                                        "%s[ARC ISSUE-VERIFY][Lone Volume FAILURE] Volume label of %s indicates that there is more than one volume for this series, but the one on your watchlist has no volume label set."
                                                        % (module, arc_values["ComicVersion"])
                                                    )
                                                    datematch = "False"

                                            if datematch == "False" and all(
                                                [
                                                    arcmatch["issue_year"] is not None,
                                                    arcmatch["issue_year"] != "None",
                                                    arc_issueyear is not None,
                                                ]
                                            ):
                                                if int(arc_issueyear) == int(arcmatch["issue_year"]):
                                                    logger.fdebug(
                                                        "%s[ARC ISSUE-VERIFY][Issue Year MATCH] Issue Year of %s is a match to the year found in the filename of : %s"
                                                        % (module, arc_issueyear, arcmatch["issue_year"])
                                                    )
                                                    datematch = "True"
                                                else:
                                                    logger.fdebug(
                                                        "%s[ARC ISSUE-VERIFY][Issue Year FAILURE] Issue Year of %s does NOT match the year found in the filename of : %s"
                                                        % (module, arc_issueyear, arcmatch["issue_year"])
                                                    )
                                                    logger.fdebug(
                                                        "%s[ARC ISSUE-VERIFY] Checking against complete date to see if month published could allow for different publication year."
                                                        % module
                                                    )
                                                    if issyr is not None:
                                                        if int(issyr) != int(arcmatch["issue_year"]):
                                                            logger.fdebug(
                                                                "%s[ARC ISSUE-VERIFY][Issue Year FAILURE] Modified Issue year of %s is before the modified issue year of %s"
                                                                % (module, issyr, arcmatch["issue_year"])
                                                            )
                                                        else:
                                                            logger.fdebug(
                                                                "%s[ARC ISSUE-VERIFY][Issue Year MATCH] Modified Issue Year of %s is a match to the year found in the filename of : %s"
                                                                % (module, issyr, arcmatch["issue_year"])
                                                            )
                                                            datematch = "True"

                                            elif (
                                                datematch == "False"
                                                and arcmatch["issue_year"] is None
                                                and lonevol is True
                                            ):
                                                logger.fdebug(
                                                    "%s[LONE-VOLUME/NO YEAR][MATCH] Only Volume on arc watchlist matches, no year present in filename. Assuming match based on volume and title."
                                                    % module
                                                )
                                                datematch = "True"

                                            # The year-settle was added to the watchlist
                                            # path and never copied here, so the same
                                            # manga whose 2014-labelled file matched a
                                            # 2015 ledger year was accepted on the
                                            # watchlist and rejected when it arrived as
                                            # part of a story arc.
                                            if datematch == "False" and volume_settles_year_for_match(
                                                arc_values, arcmatch
                                            ):
                                                logger.fdebug(
                                                    "%s[ARC][MANGA][VOLUME MATCH] Volume %s matched, so the year in the filename (%s) does not decide this file."
                                                    % (module, arcmatch["series_volume"], arcmatch["issue_year"])
                                                )
                                                datematch = "True"

                                            if datematch == "True":
                                                passit = False
                                                if len(manual_list) > 0:
                                                    if any(
                                                        v[i]["ArcValues"]["IssueID"] == x["IssueID"]
                                                        for x in manual_list
                                                    ):
                                                        logger.info(
                                                            "[STORY-ARC POST-PROCESSING] IssueID %s exists in your watchlist. Bypassing Story-Arc post-processing performed later."
                                                            % v[i]["ArcValues"]["IssueID"]
                                                        )
                                                        for a in manual_list:
                                                            if a["IssueID"] == v[i]["ArcValues"]["IssueID"]:
                                                                a["IssueArcID"] = v[i]["ArcValues"]["IssueArcID"]
                                                                break
                                                        passit = True

                                                if not passit:
                                                    tmpfilename = arcmatch["comicfilename"]
                                                    if arcmatch["sub"]:
                                                        clocation = os.path.join(
                                                            arcmatch["comiclocation"], arcmatch["sub"], tmpfilename
                                                        )
                                                        if not os.path.exists(clocation):
                                                            scrubs = re.sub(
                                                                watchmatch["comiclocation"], "", watchmatch["sub"]
                                                            ).strip()
                                                            if scrubs[:2] == "//" or scrubs[:2] == "\\":
                                                                scrubs = scrubs[1:]
                                                                if os.path.exists(scrubs):
                                                                    logger.fdebug("[MODIFIED CLOCATION] %s" % scrubs)
                                                                    clocation = scrubs
                                                    else:
                                                        logger.fdebug(
                                                            "%s[CLOCATION] %s" % (module, arcmatch["comiclocation"])
                                                        )
                                                        if os.path.isfile(arcmatch["comiclocation"]):
                                                            clocation = arcmatch["comiclocation"]
                                                        else:
                                                            clocation = os.path.join(
                                                                arcmatch["comiclocation"], tmpfilename
                                                            )

                                                    logger.info(
                                                        "[%s #%s] MATCH: %s / %s / %s"
                                                        % (
                                                            k,
                                                            isc["IssueNumber"],
                                                            clocation,
                                                            isc["IssueID"],
                                                            v[i]["ArcValues"]["IssueID"],
                                                        )
                                                    )
                                                    if v[i]["ArcValues"]["Publisher"] is None:
                                                        arcpublisher = v[i]["ArcValues"]["ComicPublisher"]
                                                    else:
                                                        arcpublisher = v[i]["ArcValues"]["Publisher"]

                                                    manual_arclist.append(
                                                        {
                                                            "ComicLocation": clocation,
                                                            "Filename": tmpfilename,
                                                            "ComicID": v[i]["WatchValues"]["ComicID"],
                                                            "IssueID": v[i]["ArcValues"]["IssueID"],
                                                            "IssueNumber": v[i]["ArcValues"]["IssueNumber"],
                                                            "IssueYear": arc_issueyear,
                                                            "StoryArc": v[i]["ArcValues"]["StoryArc"],
                                                            "StoryArcID": v[i]["ArcValues"]["StoryArcID"],
                                                            "IssueArcID": v[i]["ArcValues"]["IssueArcID"],
                                                            "SeriesYear": v[i]["WatchValues"]["SeriesYear"],
                                                            "Publisher": arcpublisher,
                                                            "AnnualType": annualtype,
                                                            "ReadingOrder": v[i]["ArcValues"]["ReadingOrder"],
                                                            "Volume": v[i]["WatchValues"]["ComicVersion"],
                                                            "ComicName": k,
                                                        }
                                                    )
                                                    tmp_arclist.append(
                                                        {
                                                            "ComicName": k,
                                                            "ComicID": v[i]["WatchValues"]["ComicID"],
                                                            "IssueID": v[i]["ArcValues"]["IssueID"],
                                                        }
                                                    )

                                                    logger.info(
                                                        "%s[SUCCESSFUL MATCH: %s-%s] Match verified for %s"
                                                        % (
                                                            module,
                                                            k,
                                                            v[i]["WatchValues"]["ComicID"],
                                                            arcmatch["comicfilename"],
                                                        )
                                                    )
                                                    self.matched = True
                                                    break
                                            else:
                                                logger.fdebug(
                                                    "%s[NON-MATCH: %s-%s] Incorrect series - not populating..continuing post-processing"
                                                    % (module, k, v[i]["WatchValues"]["ComicID"])
                                                )

                        i += 1
                    if len(tmp_arclist) > 1:
                        logger.info(
                            "[STORY-ARC VERIFICATION] %s matches to storyarcs - probably due to invalid name matching above. Let's try to correct this."
                            % len(tmp_arclist)
                        )
                        keep_match = []
                        drop_match = []
                        for x in tmp_arclist:
                            xmld = filechecker.FileChecker()
                            xmld1 = xmld.dynamic_replace(x["ComicName"])
                            xseries = xmld1["mod_seriesname"].lower()
                            xmld2 = xmld.dynamic_replace(arcmatch["series_name"])
                            xfile = xmld2["mod_seriesname"].lower()
                            if re.sub(r"\|", "", xseries) == re.sub(r"\|", "", xfile):
                                logger.fdebug(
                                    "%s[DEFINITIVE-NAME MATCH] Definitive name match exactly to : %s [%s]"
                                    % (module, arcmatch["series_name"], x["ComicID"])
                                )
                                keep_match.append(x["IssueID"])
                                self.matched = True
                            else:
                                logger.fdebug("INVALID MATCH DETECTED: %s" % x["ComicName"])
                                drop_match.append(x["IssueID"])

                        tmp_list = []
                        for xy in manual_arclist:
                            if [True for dm in drop_match if xy["IssueID"] == dm]:
                                continue
                            else:
                                tmp_list.append(xy)
                        manual_arclist = tmp_list

                if self.matched is False:
                    if all(["0-Day Week" in self.nzb_name, comicarr.CONFIG.PACK_0DAY_WATCHLIST_ONLY is True]):
                        pass
                    else:
                        oneofflist = db.select_all(
                            select(
                                snatched.c.Issue_Number,
                                snatched.c.ComicName,
                                snatched.c.IssueID,
                                snatched.c.ComicID,
                                snatched.c.Provider,
                                weekly.c.format,
                                weekly.c.PUBLISHER,
                                weekly.c.weeknumber,
                                weekly.c.year,
                            )
                            .select_from(
                                snatched.join(nzblog, snatched.c.IssueID == nzblog.c.IssueID).join(
                                    weekly, snatched.c.IssueID == weekly.c.IssueID
                                )
                            )
                            .where(and_(nzblog.c.OneOff == "1", snatched.c.ComicName.isnot(None)))
                        )
                        if not oneofflist:
                            pass
                        else:
                            logger.fdebug("%s[ONEOFF-SELECTION][self.nzb_name: %s]" % (module, self.nzb_name))
                            oneoffvals = []
                            for ofl in oneofflist:
                                oneoffvals.append(
                                    {
                                        "ComicName": ofl["ComicName"],
                                        "ComicPublisher": ofl["PUBLISHER"],
                                        "Issue_Number": ofl["Issue_Number"],
                                        "AlternateSearch": None,
                                        "ComicID": ofl["ComicID"],
                                        "IssueID": ofl["IssueID"],
                                        "WatchValues": {
                                            "SeriesYear": ofl["year"],
                                            "LatestDate": None,
                                            "ComicVersion": None,
                                            "Publisher": ofl["PUBLISHER"],
                                            "Total": 0,
                                            "Type": ofl["format"],
                                            "ComicID": ofl["ComicID"],
                                            "IsManga": series_kind.is_manga(ofl),
                                            "IsArc": False,
                                        },
                                    }
                                )

                            for ofv in oneoffvals:
                                wm = filechecker.FileChecker(
                                    watchcomic=ofv["ComicName"],
                                    Publisher=ofv["ComicPublisher"],
                                    AlternateSearch=None,
                                    manual=ofv["WatchValues"],
                                )
                                watchmatch = wm.matchIT(fl)
                                if watchmatch["process_status"] == "fail":
                                    nm += 1
                                    continue
                                else:
                                    try:
                                        # Same exclusion as the watchlist scan above: a
                                        # chapter-named file carries a defaulted "v1" it
                                        # never stated, and would file c181 as issue 1.
                                        if volume_identifies_file(ofv["WatchValues"]) and not chapter_named_file(
                                            watchmatch
                                        ):
                                            if watchmatch["series_volume"] is not None:
                                                just_the_digits = re.sub(
                                                    "[^0-9]", "", watchmatch["series_volume"]
                                                ).strip()
                                            else:
                                                just_the_digits = re.sub(
                                                    "[^0-9]", "", watchmatch["justthedigits"]
                                                ).strip()
                                        else:
                                            just_the_digits = watchmatch["justthedigits"]
                                    except Exception as e:
                                        logger.warn(
                                            "[Exception: %s] Unable to properly match up/retrieve issue number (or volume) for this [CS: %s] [WATCHMATCH: %s]"
                                            % (e, cs, watchmatch)
                                        )
                                        nm += 1
                                        continue

                                    if just_the_digits is not None:
                                        temploc = just_the_digits.replace("_", " ")
                                        temploc = re.sub("[\\#']", "", temploc)
                                        logger.fdebug("temploc: %s" % temploc)
                                    else:
                                        temploc = None

                                logger.info("watchmatch: %s" % watchmatch)
                                if temploc is not None:
                                    if "annual" in temploc.lower():
                                        biannchk = re.sub("-", "", temploc.lower()).strip()
                                        if "biannual" in biannchk:
                                            logger.fdebug("%s Bi-Annual detected." % module)
                                            fcdigit = helpers.issuedigits(re.sub("biannual", "", str(biannchk)).strip())
                                        else:
                                            year_check = re.findall(r"(\d{4})(?=[\s]|annual\b|$)", temploc, flags=re.I)
                                            if year_check:
                                                ann_line = "%s annual" % year_check[0]
                                                fcdigit = helpers.issuedigits(
                                                    re.sub(ann_line, "", str(temploc.lower())).strip()
                                                )
                                            fcdigit = helpers.issuedigits(
                                                re.sub("annual", "", str(temploc.lower())).strip()
                                            )
                                            logger.fdebug(
                                                "%s Annual detected [%s]. ComicID assigned as %s"
                                                % (module, fcdigit, ofv["ComicID"])
                                            )
                                        annchk = "yes"
                                    else:
                                        fcdigit = helpers.issuedigits(temploc)

                                if (
                                    temploc is not None
                                    and fcdigit == helpers.issuedigits(ofv["Issue_Number"])
                                    or all([temploc is None, helpers.issuedigits(ofv["Issue_Number"]) == "1"])
                                ):
                                    if watchmatch["sub"]:
                                        clocation = os.path.join(
                                            watchmatch["comiclocation"], watchmatch["sub"], watchmatch["comicfilename"]
                                        )
                                        if not os.path.exists(clocation):
                                            scrubs = re.sub(watchmatch["comiclocation"], "", watchmatch["sub"]).strip()
                                            if scrubs[:2] == "//" or scrubs[:2] == "\\":
                                                scrubs = scrubs[1:]
                                                if os.path.exists(scrubs):
                                                    logger.fdebug("[MODIFIED CLOCATION] %s" % scrubs)
                                                    clocation = scrubs

                                    else:
                                        if self.issueid is not None and os.path.isfile(watchmatch["comiclocation"]):
                                            clocation = watchmatch["comiclocation"]
                                        else:
                                            clocation = os.path.join(
                                                watchmatch["comiclocation"], watchmatch["comicfilename"]
                                            )
                                    oneoff_issuelist.append(
                                        {
                                            "ComicLocation": clocation,
                                            "ComicID": ofv["ComicID"],
                                            "IssueID": ofv["IssueID"],
                                            "IssueNumber": ofv["Issue_Number"],
                                            "ComicName": ofv["ComicName"],
                                            "SeriesYear": ofv["WatchValues"]["SeriesYear"],
                                            "One-Off": True,
                                        }
                                    )
                                    self.oneoffinlist = True
                                else:
                                    logger.fdebug(
                                        "%s No corresponding issue # in dB found for %s # %s"
                                        % (module, ofv["ComicName"], ofv["Issue_Number"])
                                    )
                                    continue

                                logger.fdebug(
                                    "%s[SUCCESSFUL MATCH: %s-%s] Match Verified for %s"
                                    % (module, ofv["ComicName"], ofv["ComicID"], fl["comicfilename"])
                                )
                                self.matched = True
                                break

                selected_items, annual_count, story_arc_matched = summarize_scan_matches(
                    manual_list[manual_list_start:],
                    manual_arclist[manual_arclist_start:],
                )
                log_scan_summary(
                    module,
                    fl["comicfilename"],
                    len(watchvals),
                    selected_items,
                    annual_count,
                    story_arc_matched,
                )

            if filelist["comiccount"] > 0:
                logger.fdebug(
                    "%s There are %s files found that match on your watchlist, %s files are considered one-off's, and %s files do not match anything"
                    % (module, len(manual_list), len(oneoff_issuelist), int(filelist["comiccount"]) - len(manual_list))
                )

            if len(manual_arclist) > 0:
                logger.info(
                    "[STORY-ARC MANUAL POST-PROCESSING] I have found %s issues that belong to Story Arcs. Flinging them into the correct directories."
                    % len(manual_arclist)
                )
                multiple_arcs = None
                ml_cnt = 0
                for ml in manual_arclist:
                    ml_cnt += 1
                    issueid = ml["IssueID"]
                    ofilename = orig_filename = ml["ComicLocation"]
                    logger.info("[STORY-ARC POST-PROCESSING] Enabled for %s" % ml["StoryArc"])

                    # No copy into the arc folder means no completion write here,
                    # and so the legacy unconditional notification.
                    completion = None
                    if all([comicarr.CONFIG.STORYARCDIR is True, comicarr.CONFIG.COPY2ARCDIR is True]):
                        grdst = helpers.arcformat(
                            ml["StoryArc"], helpers.spantheyears(ml["StoryArcID"]), ml["Publisher"]
                        )
                        logger.info("grdst: %s" % grdst)

                        metaresponse = None

                        helpers.crc(ofilename)

                        if comicarr.CONFIG.CMTAG_START_YEAR_AS_VOLUME:
                            vol_label = ml["SeriesYear"]
                        else:
                            vol_label = ml["Volume"]

                        if not multiple_arcs:
                            roders = db.select_all(
                                select(storyarcs.c.StoryArc, storyarcs.c.ReadingOrder).where(
                                    and_(storyarcs.c.ComicID == ml["ComicID"], storyarcs.c.IssueID == issueid)
                                )
                            )
                            readingorder = None
                            if roders is not None:
                                readingorder = []
                                for rd in roders:
                                    readingorder.append((rd["StoryArc"], rd["ReadingOrder"]))
                                multiple_arcs = len(readingorder)

                            logger.fdebug("readingorder: %s" % (readingorder))

                            if any([comicarr.CONFIG.ENABLE_META, comicarr.CONFIG.CBR2CBZ_ONLY]):
                                logger.info("[STORY-ARC POST-PROCESSING] Metatagging enabled - proceeding...")

                                pre_cmtag_info = None
                                try:
                                    from comicarr.app.ai.enrichment import _read_comicinfo

                                    pre_cmtag_info = _read_comicinfo(ofilename)
                                except Exception as e:
                                    logger.fdebug("[POST-PROCESS] Could not read pre-cmtag ComicInfo.xml: %s" % e)

                                try:
                                    from . import cmtag

                                    metaresponse = cmtag.run(
                                        self.nzb_folder,
                                        issueid=issueid,
                                        comversion=vol_label,
                                        filename=ofilename,
                                        readingorder=readingorder,
                                        agerating=None,
                                    )
                                except ImportError:
                                    logger.warn(
                                        "%s comictaggerlib not found on system. Ensure the bundled vendor package is available at comicarr/_vendor/comictaggerlib/"
                                        % module
                                    )
                                    metaresponse = "fail"

                                if metaresponse == "fail":
                                    logger.fdebug(
                                        "%s Unable to write metadata successfully - check comicarr.log file. Attempting to continue without metatagging..."
                                        % module
                                    )
                                elif any([metaresponse == "unrar error", metaresponse == "corrupt"]):
                                    logger.error(
                                        "%s This is a corrupt archive - whether CRC errors or it is incomplete. Marking as BAD, and retrying it."
                                        % module
                                    )
                                    continue
                                elif metaresponse.startswith("file not found"):
                                    filename_in_error = metaresponse.split("||")[1]
                                    self._log(
                                        "The file cannot be found in the location provided for metatagging to be used [%s]. Please verify it exists, and re-run if necessary. Attempting to continue without metatagging..."
                                        % (filename_in_error)
                                    )
                                    logger.error(
                                        "%s The file cannot be found in the location provided for metatagging to be used [%s]. Please verify it exists, and re-run if necessary. Attempting to continue without metatagging..."
                                        % (module, filename_in_error)
                                    )
                                else:
                                    odir = os.path.split(metaresponse)[0]
                                    ofilename = os.path.split(metaresponse)[1]
                                    ext = os.path.splitext(metaresponse)[1]
                                    logger.info(
                                        "%s Sucessfully wrote metadata to .cbz (%s) - Continuing.."
                                        % (module, ofilename)
                                    )
                                    self._log("Sucessfully wrote metadata to .cbz (%s) - proceeding..." % ofilename)

                                    try:
                                        from comicarr.app.ai.enrichment import enrich_metadata

                                        enriched_count = enrich_metadata(
                                            cbz_path=metaresponse,
                                            issue_id=issueid,
                                        )
                                        if enriched_count > 0:
                                            logger.fdebug(
                                                "[POST-PROCESS] AI enriched %d metadata fields" % enriched_count
                                            )
                                    except Exception as e:
                                        logger.error("[POST-PROCESS] AI enrichment error: %s" % e)

                                    try:
                                        from comicarr.app.ai.reconciliation import reconcile_metadata

                                        post_cmtag_info = _read_comicinfo(metaresponse)
                                        reconciled_count = reconcile_metadata(
                                            cbz_path=metaresponse,
                                            issue_id=issueid,
                                            pre_cmtag_info=pre_cmtag_info,
                                            post_cmtag_info=post_cmtag_info,
                                        )
                                        if reconciled_count > 0:
                                            logger.fdebug(
                                                "[POST-PROCESS] AI reconciled %d metadata fields" % reconciled_count
                                            )
                                    except Exception as e:
                                        logger.error("[POST-PROCESS] AI reconciliation error: %s" % e)

                                dfilename = ofilename
                            else:
                                dfilename = ml["Filename"]

                            if metaresponse:
                                src_location = odir
                                grab_src = os.path.join(src_location, ofilename)
                            else:
                                src_location = ofilename
                                grab_src = ofilename

                            logger.fdebug("%s Source Path : %s" % (module, grab_src))

                        checkdirectory = filechecker.validateAndCreateDirectory(grdst, True, module=module)
                        if not checkdirectory:
                            logger.warn(
                                "%s Error trying to validate/create directory. Aborting this process at this time."
                                % module
                            )
                            self.valreturn.append({"self.log": self.log, "mode": "stop"})
                            return self.queue.put(self.valreturn)

                        if comicarr.CONFIG.RENAME_FILES:
                            renamed_file = helpers.rename_param(
                                ml["ComicID"],
                                ml["ComicName"],
                                ml["IssueNumber"],
                                dfilename,
                                issueid=ml["IssueID"],
                                arc=ml["StoryArc"],
                            )
                            if renamed_file:
                                dfilename = renamed_file["nfilename"]
                                logger.fdebug("%s Renaming file to conform to configuration: %s" % (module, ofilename))

                        if comicarr.CONFIG.READ2FILENAME:
                            if multiple_arcs > 1:
                                new_path_f = dfilename[dfilename.find("-") + 1 :].strip()
                            else:
                                new_path_f = os.path.split(dfilename)[1]
                            logger.fdebug("%s readingorder#: %s" % (module, ml["ReadingOrder"]))
                            if int(ml["ReadingOrder"]) < 10:
                                readord = "00" + str(ml["ReadingOrder"])
                            elif int(ml["ReadingOrder"]) >= 10 and int(ml["ReadingOrder"]) <= 99:
                                readord = "0" + str(ml["ReadingOrder"])
                            else:
                                readord = str(ml["ReadingOrder"])
                            dfilename = "%s-%s" % (readord, new_path_f)

                        grab_dst = os.path.join(grdst, dfilename)

                        logger.fdebug("%s Destination Path : %s" % (module, grab_dst))
                        logger.fdebug("%s Source Path : %s" % (module, grab_src))

                        logger.info(
                            "%s[ONE-OFF MODE][%s] %s into directory : %s"
                            % (module, comicarr.CONFIG.ARC_FILEOPS.upper(), grab_src, grab_dst)
                        )

                        self._journal_pp("post_processing", issuearcid=ml["IssueArcID"])

                        try:
                            checkspace = helpers.get_free_space(grdst)
                            if checkspace is False:
                                if all([metaresponse is not None, metaresponse != "fail"]):
                                    self.tidyup(src_location, True, cacheonly=True)
                                raise OSError
                            mult_count = False
                            if ml_cnt != multiple_arcs:
                                mult_count = True
                            logger.fdebug(
                                "ml_cnt: %s / multiple_arcs: %s --- multiple arc entry: %s"
                                % (ml_cnt, multiple_arcs, mult_count)
                            )
                            place(
                                grab_src,
                                grab_dst,
                                Purpose.ONE_OFF,
                                on_existing=OnExisting.UNGUARDED,
                                multiple=mult_count,
                            )
                        except Exception as e:
                            self._log_placement_failure(
                                "%s [ONE-OFF MODE]" % module, comicarr.CONFIG.ARC_FILEOPS, grab_src, grab_dst, e
                            )
                            return

                        self._journal_pp("moved", issuearcid=ml["IssueArcID"])

                        if any([comicarr.CONFIG.FILE_OPTS == "move", comicarr.CONFIG.FILE_OPTS == "copy"]):
                            if mult_count is False:
                                self.tidyup(src_location, True, filename=os.path.basename(orig_filename))
                            else:
                                logger.fdebug(
                                    "Not deleting %s due to belonging to multiple arcs - will delete in subsequent pass(es)"
                                    % os.path.basename(orig_filename)
                                )
                        completion = _complete_postprocess(
                            self._journal_context(),
                            issue_arc_id=ml["IssueArcID"],
                            anchor_ids=("S" + str(ml["IssueArcID"]), str(ml["IssueArcID"])),
                            arc_scope=ml["StoryArc"],
                            database=db,
                        )

                        logger.fdebug("%s IssueArcID: %s" % (module, ml["IssueArcID"]))
                        newVal = {"Status": "Downloaded", "Location": grab_dst}
                    else:
                        grab_dst = ml["ComicLocation"]
                        newVal = {"Status": "Downloaded", "Location": grab_dst}
                    ctrlVal = {"IssueArcID": ml["IssueArcID"]}
                    logger.fdebug("writing: %s -- %s" % (newVal, ctrlVal))
                    db.upsert("storyarcs", newVal, ctrlVal)
                    updater.foundsearch(
                        ComicID=ml["ComicID"],
                        mode="story_arc",
                        IssueID=ml["IssueID"],
                        IssueArcID=ml["IssueArcID"],
                        down="PP",
                        module=module,
                    )
                    if all([comicarr.CONFIG.STORYARCDIR is True, comicarr.CONFIG.COPY2ARCDIR is True]):
                        logger.fdebug("%s [%s] Post-Processing completed for: %s" % (module, ml["StoryArc"], grab_dst))
                    else:
                        logger.fdebug(
                            "%s [%s] Post-Processing completed for: %s" % (module, ml["StoryArc"], ml["ComicLocation"])
                        )

                    self._notify_completed(
                        completion,
                        series=ml["ComicName"],
                        issue_year=ml["IssueYear"],
                        issue_number=ml["IssueNumber"],
                        placed_path=grab_dst,
                        issue_id=issueid,
                        module=module,
                    )

                    self._journal_pp("post_processed", issuearcid=ml["IssueArcID"])

        if (
            all([self.nzb_name != "Manual Run", self.apicall is False])
            or (self.oneoffinlist is True or all([self.issuearcid is not None, self.issueid is None]))
        ) and not self.nzb_name.startswith("0-Day"):
            ppinfo = []
            if self.oneoffinlist is False:
                self.oneoff = False
                if any([self.issueid is not None, self.issuearcid is not None]):
                    if self.issuearcid is not None:
                        s_id = self.issuearcid
                    else:
                        s_id = self.issueid
                    nzbiss = db.select_one(select(nzblog).where(nzblog.c.IssueID == s_id))
                    if nzbiss is None and self.issuearcid is not None:
                        nzbiss = db.select_one(select(nzblog).where(nzblog.c.IssueID == "S" + s_id))

                else:
                    nzbname = self.nzb_name
                    if nzbname.lower().endswith(self.extensions):
                        fd, ext = os.path.splitext(nzbname)
                        self._log("Removed extension from nzb: " + ext)
                        nzbname = re.sub(str(ext), "", str(nzbname))

                    logger.fdebug("[NZBNAME]: " + nzbname)
                    nzbname = re.sub(r"\&", "and", nzbname)
                    nzbname = re.sub("[\\,\\:\\?'\\+]", "", nzbname)
                    nzbname = re.sub(r"[\(\)]", " ", nzbname)
                    logger.fdebug("[NZBNAME] nzbname (remove chars): " + nzbname)
                    nzbname = re.sub(".cbr", "", nzbname).strip()
                    nzbname = re.sub(".cbz", "", nzbname).strip()
                    nzbname = re.sub(r"[\.\_]", " ", nzbname).strip()
                    nzbname = re.sub(r"\s+", " ", nzbname)
                    logger.fdebug(
                        "[NZBNAME] nzbname (remove extensions, double spaces, convert underscores to spaces): "
                        + nzbname
                    )
                    nzbname = re.sub(r"\s", ".", nzbname)

                    logger.fdebug("%s After conversions, nzbname is : %s" % (module, nzbname))
                    self._log("nzbname: %s" % nzbname)

                    nzbiss = db.select_one(
                        select(nzblog).where(or_(nzblog.c.NZBName == nzbname, nzblog.c.AltNZBName == nzbname))
                    )

                    if nzbiss is None:
                        self._log("Failure - could not initially locate nzbfile in my database to rename.")
                        logger.fdebug("%s Failure - could not locate nzbfile initially" % module)
                        nzbname = re.sub(r"[\(\)]", "", str(nzbname))
                        self._log("trying again with this nzbname: %s" % nzbname)
                        logger.fdebug("%s Trying to locate nzbfile again with nzbname of : %s" % (module, nzbname))
                        nzbiss = db.select_one(
                            select(nzblog).where(or_(nzblog.c.NZBName == nzbname, nzblog.c.AltNZBName == nzbname))
                        )
                        if nzbiss is None:
                            logger.error(
                                "%s Unable to locate downloaded file within items I have snatched. Attempting to parse the filename directly and process."
                                % module
                            )
                            self._log(
                                "Unable to locate downloaded file within items I have snatched. Attempting to parse the filename directly and process."
                            )
                            self.valreturn.append({"self.log": self.log, "mode": "outside"})
                            return self.queue.put(self.valreturn)
                        else:
                            self._log("I corrected and found the nzb as : %s" % nzbname)
                            logger.fdebug("%s Auto-corrected and found the nzb as : %s" % (module, nzbname))

                issueid = nzbiss["IssueID"]
                logger.fdebug("%s Issueid: %s" % (module, issueid))
                sarc = nzbiss["SARC"]
                self.oneoff = nzbiss["OneOff"]
                logger.fdebug("sarc: %s / oneoff: %s" % (sarc, self.oneoff))
                tmpiss = db.select_one(
                    select(comics.c.ComicYear, comics.c.ComicVersion, issues)
                    .select_from(comics.join(issues, comics.c.ComicID == issues.c.ComicID, isouter=True))
                    .where(issues.c.IssueID == issueid)
                )
                if tmpiss is None:
                    tmpiss = db.select_one(
                        select(annuals).where(and_(annuals.c.IssueID == issueid, annuals.c.Deleted != 1))
                    )
                comicid = None
                if tmpiss is not None:
                    ppinfo.append(
                        {
                            "comicid": tmpiss["ComicID"],
                            "issueid": issueid,
                            "comicname": tmpiss["ComicName"],
                            "seriesyear": tmpiss["ComicYear"],
                            "seriesvolume": tmpiss["ComicVersion"],
                            "issuenumber": tmpiss["Issue_Number"],
                            "comiclocation": None,
                            "publisher": None,
                            "sarc": sarc,
                            "oneoff": self.oneoff,
                        }
                    )

                elif self.oneoff is not None and any([issueid[0] == "S", "_" in issueid]):
                    issuearcid = re.sub("S", "", issueid).strip()
                    oneinfo = db.select_one(select(storyarcs).where(storyarcs.c.IssueArcID == issuearcid))
                    if oneinfo is None:
                        logger.warn(
                            "Unable to locate issue as previously snatched arc issue - it might be something else..."
                        )
                        self._log(
                            "Unable to locate issue as previously snatched arc issue - it might be something else..."
                        )
                    else:
                        tmplookup = db.select_one(select(comics).where(comics.c.ComicID == oneinfo["ComicID"]))
                        if tmplookup is not None:
                            logger.fdebug(
                                "[WATCHLIST-DETECTION-%s] Processing as Arc, detected on watchlist - will PP for both."
                                % tmplookup["ComicName"]
                            )
                            self.oneoff = False
                        else:
                            self.oneoff = True
                        ppinfo.append(
                            {
                                "comicid": oneinfo["ComicID"],
                                "comicname": oneinfo["ComicName"],
                                "seriesyear": oneinfo["SeriesYear"],
                                "seriesvolume": oneinfo["Volume"],
                                "issuenumber": oneinfo["IssueNumber"],
                                "publisher": oneinfo["IssuePublisher"],
                                "comiclocation": None,
                                "issueid": issueid,
                                "sarc": sarc,
                                "oneoff": self.oneoff,
                            }
                        )

                if all([len(ppinfo) == 0, self.oneoff is not None, comicarr.CONFIG.ALT_PULL == 2]):
                    oneinfo = db.select_one(select(weekly).where(weekly.c.IssueID == issueid))
                    if oneinfo is None:
                        oneinfo = db.select_one(select(oneoffhistory).where(oneoffhistory.c.IssueID == issueid))
                        if oneinfo is None:
                            logger.warn("Unable to locate issue as previously snatched one-off")
                            self._log("Unable to locate issue as previously snatched one-off")
                            self.valreturn.append({"self.log": self.log, "mode": "stop"})
                            return self.queue.put(self.valreturn)
                        else:
                            OComicname = oneinfo["ComicName"]
                            OIssue = oneinfo["IssueNumber"]
                            OPublisher = None
                            OSeriesYear = oneinfo["year"]
                            OSeriesVolume = oneinfo["year"]
                    else:
                        OComicname = oneinfo["COMIC"]
                        OIssue = oneinfo["ISSUE"]
                        OPublisher = oneinfo["PUBLISHER"]
                        OSeriesYear = oneinfo["SHIPDATE"][:4]
                        OSeriesVolume = oneinfo["volume"]

                    ppinfo.append(
                        {
                            "comicid": oneinfo["ComicID"],
                            "comicname": OComicname,
                            "seriesyear": OSeriesYear,
                            "seriesvolume": OSeriesVolume,
                            "issuenumber": OIssue,
                            "publisher": OPublisher,
                            "comiclocation": None,
                            "issueid": issueid,
                            "sarc": None,
                            "oneoff": True,
                        }
                    )

                    self.oneoff = True
            else:
                for x in oneoff_issuelist:
                    if x["One-Off"] is True:
                        oneinfo = db.select_one(select(weekly).where(weekly.c.IssueID == x["IssueID"]))
                        if oneinfo is not None:
                            ppinfo.append(
                                {
                                    "comicid": oneinfo["ComicID"],
                                    "comicname": oneinfo["COMIC"],
                                    "seriesyear": oneinfo["SHIPDATE"][:4],
                                    "seriesvolume": oneinfo["volume"],
                                    "issuenumber": oneinfo["ISSUE"],
                                    "publisher": oneinfo["PUBLISHER"],
                                    "issueid": x["IssueID"],
                                    "comiclocation": x["ComicLocation"],
                                    "sarc": None,
                                    "oneoff": x["One-Off"],
                                }
                            )
                            self.oneoff = True

            if len(ppinfo) > 0:
                for pp in ppinfo:
                    logger.info("[PPINFO-POST-PROCESSING-ATTEMPT] %s" % pp)
                    self.nzb_or_oneoff_pp(tinfo=pp)

        if any(
            [self.nzb_name == "Manual Run", self.issueid is not None, self.comicid is not None, self.apicall is True]
        ):
            annualtype = None
            issuenumOG = None
            if len(manual_list) == 0 and len(manual_arclist) == 0:
                if self.nzb_name == "Manual Run":
                    logger.info("%s No matches for Manual Run ... exiting." % module)
                self.valreturn.append({"self.log": self.log, "mode": "stop"})
                return self.queue.put(self.valreturn)
            elif len(manual_arclist) > 0:
                if len(manual_arclist) > 1:
                    logger.info(
                        "%s Manual post-processing completed for %s story-arc issues." % (module, len(manual_arclist))
                    )
                try:
                    dspcname = None
                    dspcyear = None
                    if len(manual_arclist) == 1:
                        dspcname = ml["ComicName"]
                        dspcyear = ml["SeriesYear"]
                        annualtype = ml["AnnualType"]
                        issuenumOG = ml["IssueNumber"]
                        logger.info(
                            "%s[STORY-ARC] Manual post-processing completed for %s issue belonging to %s"
                            % (module, len(manual_arclist), ml["StoryArc"])
                        )
                except Exception:
                    dspcname = None
                    dspcyear = None
            i = 0

            for ml in manual_list:
                i += 1
                comicid = ml["ComicID"]
                issueid = ml["IssueID"]
                issuenumOG = ml["IssueNumber"]
                dspcname = ml["ComicName"]
                dspcyear = ml["SeriesYear"]
                waiting = True
                while waiting is True:
                    try:
                        ctime = max(os.path.getctime(ml["ComicLocation"]), os.path.getmtime(ml["ComicLocation"]))
                        if time.time() > ctime > time.time() - 10:
                            time.sleep(max(time.time() - ctime, 0))
                        else:
                            break
                    except (OSError, IOError) as e:
                        logger.fdebug("[PP] File no longer accessible: %s" % e)
                        break

                dupthis = helpers.duplicate_filecheck(ml["ComicLocation"], ComicID=comicid, IssueID=issueid)
                if dupthis["action"] == "dupe_src" or dupthis["action"] == "dupe_file":
                    if comicarr.CONFIG.DDUMP and not all(
                        [comicarr.CONFIG.DUPLICATE_DUMP is None, comicarr.CONFIG.DUPLICATE_DUMP == ""]
                    ):
                        dupchkit = self.duplicate_process(dupthis)
                        if not dupchkit:
                            logger.warn("Unable to move duplicate file - skipping post-processing of this file.")
                            continue

                if any([dupthis["action"] == "write", dupthis["action"] == "dupe_src"]):
                    stat = " [%s/%s]" % (i, len(manual_list))
                    self.Process_next(comicid, issueid, issuenumOG, ml, stat)
                    dupthis = None

            if self.failed_files == 0:
                if all([self.comicid is not None, self.issueid is None]):
                    try:
                        logger.info(
                            "%s post-processing of pack completed for %s issues of %s (%s)."
                            % (module, i, dspcname, dspcyear)
                        )
                        global_line = "Successfully post-processed pack for %s issues of %s (%s)" % (
                            i,
                            dspcname,
                            dspcyear,
                        )
                    except Exception:
                        logger.info("%s post-processing of pack completed for %s issues." % (module, i))
                        global_line = "Successfully post-processed pack for %s issues." % (i)

                elif self.issueid is not None:
                    if ml:
                        t_comicname = ml["ComicName"]
                        t_annualtype = ml["AnnualType"]
                        if t_annualtype is not None:
                            try:
                                t_comicname = ml["AnnualSeries"]
                            except Exception:
                                pass
                            else:
                                if t_annualtype == "Annual":
                                    t_annualtype = None
                        t_issuenumber = ml["IssueNumber"]
                    else:
                        t_comicname = dspcname
                        t_annualtype = annualtype
                        t_issuenumber = issuenumOG
                    if t_annualtype is not None:
                        logger.info(
                            "%s direct post-processing of issue completed for %s %s #%s."
                            % (module, t_comicname, t_annualtype, t_issuenumber)
                        )
                        global_line = "Successfully post-processed</br> %s %s %s" % (
                            t_comicname,
                            t_annualtype,
                            t_issuenumber,
                        )
                    else:
                        if t_issuenumber is not None:
                            logger.info(
                                "%s direct post-processing of issue completed for %s #%s."
                                % (module, t_comicname, t_issuenumber)
                            )
                            global_line = "Successfully post-processed</br> %s #%s" % (t_comicname, t_issuenumber)
                        else:
                            logger.info("%s direct post-processing of issue completed for %s." % (module, t_comicname))
                            global_line = "Successfully post-processed</br> %s" % (t_comicname)
                else:
                    if i == 0 and len(manual_arclist) >= 1:
                        global_line = "Successfully post-processed</br> %s storyarc issues" % len(manual_arclist)
                    else:
                        logger.info("%s Manual post-processing completed for %s issues." % (module, i))
                        global_line = "Manual post-processing completed for %s issues" % (i)
            else:
                if self.comicid is not None:
                    logger.info(
                        "%s post-processing of pack completed for %s issues [FAILED: %s]"
                        % (module, i, self.failed_files)
                    )
                    global_line = "Successfully post-processing of pack completed for %s issues [FAILED: %s]" % (
                        i,
                        self.failed_files,
                    )
                else:
                    logger.info(
                        "%s Manual post-processing completed for %s issues [FAILED: %s]"
                        % (module, i, self.failed_files)
                    )
                    global_line = "Successfully post-processed %s issues [FAILED: %s]" % (i, self.failed_files)

            logger.fdebug("%s %s" % (module, global_line))

            self.valreturn.append({"self.log": self.log, "mode": "stop"})
            return self.queue.put(self.valreturn)
        else:
            pass

    def nzb_or_oneoff_pp(self, tinfo=None, manual=None):
        module = self.module
        manual_list = None
        if tinfo is not None:
            sandwich = None
            issueid = tinfo["issueid"]
            comicid = tinfo["comicid"]
            comicname = tinfo["comicname"]
            seriesyear = tinfo["seriesyear"]
            seriesvolume = tinfo["seriesvolume"]
            issuearcid = None
            issuenumber = tinfo["issuenumber"]
            tinfo["publisher"]
            sarc = tinfo["sarc"]
            oneoff = tinfo["oneoff"]
            if all([oneoff is True, tinfo["comiclocation"] is not None]):
                location = os.path.abspath(os.path.join(tinfo["comiclocation"], os.pardir))
            else:
                location = self.nzb_folder
            issuenzb = db.select_one(
                select(issues).where(and_(issues.c.IssueID == issueid, issues.c.ComicName.isnot(None)))
            )
            if issuenzb is None:
                logger.info("%s Could not detect as a standard issue - checking against annuals." % module)
                issuenzb = db.select_one(
                    select(annuals).where(
                        and_(annuals.c.IssueID == issueid, annuals.c.ComicName.isnot(None), annuals.c.Deleted != 1)
                    )
                )
                if issuenzb is None:
                    logger.info("%s issuenzb not found." % module)
                    if "S" in issueid:
                        sandwich = issueid
                        if oneoff is False:
                            onechk = db.select_one(
                                select(storyarcs).where(storyarcs.c.IssueArcID == re.sub("S", "", issueid).strip())
                            )
                            if onechk is not None:
                                issuearcid = onechk["IssueArcID"]
                                issuenzb = db.select_one(
                                    select(issues).where(
                                        and_(issues.c.IssueID == onechk["IssueID"], issues.c.ComicName.isnot(None))
                                    )
                                )
                                if issuenzb is None:
                                    issuenzb = db.select_one(
                                        select(annuals).where(
                                            and_(
                                                annuals.c.IssueID == onechk["IssueID"],
                                                annuals.c.ComicName.isnot(None),
                                                annuals.c.Deleted != 1,
                                            )
                                        )
                                    )
                            if issuenzb is not None:
                                issueid = issuenzb["IssueID"]
                                logger.fdebug(
                                    "Reverse lookup discovered watchlisted series [issueid: %s] - adjusting so we can PP both properly."
                                    % issueid
                                )
                    elif "G" in issueid or "-" in issueid:
                        sandwich = 1
                    elif any([oneoff is True, issueid >= "900000", issueid == "1"]):
                        logger.info(
                            "%s [ONE-OFF POST-PROCESSING] One-off download detected. Post-processing as a non-watchlist item."
                            % module
                        )
                        sandwich = None
                    else:
                        logger.error(
                            "%s Unable to locate downloaded file as being initiated via Comicarr. Attempting to parse the filename directly and process."
                            % module
                        )
                        self._log(
                            "Unable to locate downloaded file within items I have snatched. Attempting to parse the filename directly and process."
                        )
                        self.valreturn.append({"self.log": self.log, "mode": "outside"})
                        return self.queue.put(self.valreturn)
                else:
                    logger.info("%s Successfully located issue as an annual. Continuing." % module)

            if issuenzb is not None:
                logger.info("%s issuenzb found." % module)
                if helpers.is_number(issueid):
                    sandwich = int(issuenzb["IssueID"])
            if all([sandwich is not None, helpers.is_number(sandwich), sarc is None]):
                if sandwich < 900000:
                    pass
            else:
                if (
                    any([oneoff is True, issuenzb is None])
                    or all([sandwich is not None, "S" in str(sandwich), oneoff is True])
                    or int(sandwich) >= 900000
                ):
                    if sandwich is not None and "S" in sandwich:
                        self._log("One-off STORYARC mode enabled for Post-Processing for %s" % sarc)
                        logger.info("%s One-off STORYARC mode enabled for Post-Processing for %s" % (module, sarc))
                    else:
                        self._log(
                            "One-off mode enabled for Post-Processing. All I'm doing is moving the file untouched into the Grab-bag directory."
                        )
                        if comicarr.CONFIG.GRABBAG_DIR is None:
                            comicarr.CONFIG.GRABBAG_DIR = os.path.join(comicarr.CONFIG.DESTINATION_DIR, "Grabbag")
                        logger.info(
                            "%s One-off mode enabled for Post-Processing. Will move into Grab-bag directory: %s"
                            % (module, comicarr.CONFIG.GRABBAG_DIR)
                        )
                        self._log("Grab-Bag Directory set to : %s" % comicarr.CONFIG.GRABBAG_DIR)
                        grdst = comicarr.CONFIG.GRABBAG_DIR

                    odir = location

                    if odir is None:
                        odir = self.nzb_folder

                    ofilename = orig_filename = tinfo["comiclocation"]
                    if ofilename is not None:
                        path, ext = os.path.splitext(ofilename)
                    else:
                        if os.path.isfile(odir):
                            logger.fdebug(
                                "%s Assumed directory location (%s) is actually file location. Correcting..."
                                % (module, odir)
                            )
                            ofilename = orig_filename = os.path.basename(odir)
                            _, ext = os.path.splitext(ofilename)
                        else:
                            for root, _dirnames, filenames in safe_walk(odir):
                                for filename in filenames:
                                    if filename.lower().endswith(self.extensions):
                                        ofilename = orig_filename = filename
                                        logger.fdebug("%s Valid filename located as : %s" % (module, ofilename))
                                        path, ext = os.path.splitext(ofilename)
                                        break

                    if ofilename is None:
                        logger.error(
                            "%s Unable to post-process file as it is not in a valid cbr/cbz format or cannot be located in path. PostProcessing aborted."
                            % module
                        )
                        self._log("Unable to locate downloaded file to rename. PostProcessing aborted.")
                        self.valreturn.append({"self.log": self.log, "mode": "stop"})
                        return self.queue.put(self.valreturn)

                    rdorder = None
                    arcdata = None
                    if sandwich is not None and "S" in sandwich:
                        issuearcid = re.sub("S", "", issueid)
                        logger.fdebug("%s issuearcid:%s" % (module, issuearcid))
                        arcdata = db.select_one(select(storyarcs).where(storyarcs.c.IssueArcID == issuearcid))
                        if arcdata is None:
                            logger.warn(
                                "%s Unable to locate issue within Story Arcs. Cannot post-process at this time - try to Refresh the Arc and manual post-process if necessary."
                                % module
                            )
                            self._log(
                                "Unable to locate issue within Story Arcs in orde to properly assign metadata. PostProcessing aborted."
                            )
                            self.valreturn.append({"self.log": self.log, "mode": "stop"})
                            return self.queue.put(self.valreturn)

                        if arcdata["Publisher"] is None:
                            arcpub = arcdata["IssuePublisher"]
                        else:
                            arcpub = arcdata["Publisher"]

                        grdst = helpers.arcformat(
                            arcdata["StoryArc"], helpers.spantheyears(arcdata["StoryArcID"]), arcpub
                        )

                        if comicid is None:
                            comicid = arcdata["ComicID"]
                        if comicname is None:
                            comicname = arcdata["ComicName"]
                        if issuenumber is None:
                            issuenumber = arcdata["IssueNumber"]
                        issueid = arcdata["IssueID"]
                        rdorder = arcdata["ReadingOrder"]

                    if comicarr.CONFIG.CMTAG_START_YEAR_AS_VOLUME:
                        if arcdata:
                            vol_label = arcdata["SeriesYear"]
                        else:
                            vol_label = seriesyear
                    else:
                        if arcdata:
                            vol_label = arcdata["ComicVersion"]
                        else:
                            vol_label = seriesvolume

                    if rdorder is not None:
                        roders = db.select_all(
                            select(storyarcs.c.StoryArc, storyarcs.c.ReadingOrder).where(
                                and_(storyarcs.c.ComicID == comicid, storyarcs.c.IssueID == issueid)
                            )
                        )
                        readingorder = None
                        if roders is not None:
                            readingorder = []
                            for rd in roders:
                                readingorder.append((rd["StoryArc"], rd["ReadingOrder"]))
                    else:
                        readingorder = rdorder
                    logger.fdebug("readingorder: %s" % (readingorder))

                    metaresponse = None
                    helpers.crc(os.path.join(location, ofilename))

                    if all([comicarr.CONFIG.ENABLE_META, issueid is not None]) or comicarr.CONFIG.CBR2CBZ_ONLY:
                        self._log("Metatagging enabled - proceeding...")

                        pre_cmtag_info = None
                        try:
                            from comicarr.app.ai.enrichment import _read_comicinfo

                            if os.path.isfile(odir):
                                pre_cmtag_info = _read_comicinfo(odir)
                            else:
                                pre_cmtag_info = _read_comicinfo(os.path.join(odir, ofilename))
                        except Exception as e:
                            logger.fdebug("[POST-PROCESS] Could not read pre-cmtag ComicInfo.xml: %s" % e)

                        try:
                            from . import cmtag

                            if os.path.isfile(odir):
                                tmp_ppdir = odir
                            else:
                                tmp_ppdir = os.path.join(odir, ofilename)
                            metaresponse = cmtag.run(
                                location,
                                issueid=issueid,
                                comversion=vol_label,
                                filename=tmp_ppdir,
                                readingorder=readingorder,
                                agerating=None,
                            )
                        except ImportError:
                            logger.warn(
                                "%s comictaggerlib not found on system. Ensure the bundled vendor package is available at comicarr/_vendor/comictaggerlib/"
                                % module
                            )
                            metaresponse = "fail"

                        if metaresponse == "fail":
                            logger.fdebug(
                                "%s Unable to write metadata successfully - check comicarr.log file. Attempting to continue without metatagging..."
                                % module
                            )
                        elif any([metaresponse == "unrar error", metaresponse == "corrupt"]):
                            logger.error(
                                "%s This is a corrupt archive - whether CRC errors or it is incomplete. Marking as BAD, and retrying it."
                                % module
                            )
                        elif metaresponse.startswith("file not found"):
                            filename_in_error = metaresponse.split("||")[1]
                            self._log(
                                "The file cannot be found in the location provided for metatagging [%s]. Please verify it exists, and re-run if necessary."
                                % filename_in_error
                            )
                            logger.error(
                                "%s The file cannot be found in the location provided for metagging [%s]. Please verify it exists, and re-run if necessary."
                                % (module, filename_in_error)
                            )
                        else:
                            odir = os.path.split(metaresponse)[0]
                            ofilename = os.path.split(metaresponse)[1]
                            os.path.splitext(metaresponse)[1]
                            logger.info(
                                "%s Sucessfully wrote metadata to .cbz (%s) - Continuing.." % (module, ofilename)
                            )
                            self._log("Sucessfully wrote metadata to .cbz (%s) - proceeding..." % ofilename)

                            try:
                                from comicarr.app.ai.enrichment import enrich_metadata

                                enriched_count = enrich_metadata(
                                    cbz_path=metaresponse,
                                    issue_id=issueid,
                                )
                                if enriched_count > 0:
                                    logger.fdebug("[POST-PROCESS] AI enriched %d metadata fields" % enriched_count)
                            except Exception as e:
                                logger.error("[POST-PROCESS] AI enrichment error: %s" % e)

                            try:
                                from comicarr.app.ai.reconciliation import reconcile_metadata

                                post_cmtag_info = _read_comicinfo(metaresponse)
                                reconciled_count = reconcile_metadata(
                                    cbz_path=metaresponse,
                                    issue_id=issueid,
                                    pre_cmtag_info=pre_cmtag_info,
                                    post_cmtag_info=post_cmtag_info,
                                )
                                if reconciled_count > 0:
                                    logger.fdebug("[POST-PROCESS] AI reconciled %d metadata fields" % reconciled_count)
                            except Exception as e:
                                logger.error("[POST-PROCESS] AI reconciliation error: %s" % e)

                    dfilename = ofilename
                    if metaresponse:
                        src_location = odir
                    else:
                        src_location = location

                    grab_src = os.path.join(src_location, ofilename)
                    self._log("Source Path : %s" % grab_src)
                    logger.info("%s Source Path : %s" % (module, grab_src))

                    checkdirectory = filechecker.validateAndCreateDirectory(grdst, True, module=module)
                    if not checkdirectory:
                        logger.warn(
                            "%s Error trying to validate/create directory. Aborting this process at this time." % module
                        )
                        self.valreturn.append({"self.log": self.log, "mode": "stop"})
                        return self.queue.put(self.valreturn)

                    if comicarr.CONFIG.RENAME_FILES:
                        renamed_file = helpers.rename_param(
                            comicid, comicname, issuenumber, dfilename, issueid=issueid, arc=sarc
                        )
                        if renamed_file:
                            dfilename = renamed_file["nfilename"]
                            logger.fdebug("%s Renaming file to conform to configuration: %s" % (module, dfilename))

                    if sandwich is not None and "S" in sandwich:
                        if comicarr.CONFIG.READ2FILENAME:
                            logger.fdebug("%s readingorder#: %s" % (module, arcdata["ReadingOrder"]))
                            if int(arcdata["ReadingOrder"]) < 10:
                                readord = "00" + str(arcdata["ReadingOrder"])
                            elif int(arcdata["ReadingOrder"]) >= 10 and int(arcdata["ReadingOrder"]) <= 99:
                                readord = "0" + str(arcdata["ReadingOrder"])
                            else:
                                readord = str(arcdata["ReadingOrder"])
                            dfilename = str(readord) + "-" + dfilename
                        else:
                            dfilename = ofilename
                        grab_dst = os.path.join(grdst, dfilename)
                    else:
                        grab_dst = os.path.join(grdst, dfilename)

                    if not os.path.exists(grab_dst) or grab_src == grab_dst:
                        grab_dst = os.path.join(grdst, os.path.split(dfilename)[1])

                    self._log("Destination Path : %s" % grab_dst)

                    logger.info("%s Destination Path : %s" % (module, grab_dst))
                    logger.info(
                        "%s[%s] %s into directory : %s" % (module, comicarr.CONFIG.FILE_OPTS, ofilename, grab_dst)
                    )

                    self._journal_pp("post_processing", issueid=issueid, issuearcid=issuearcid)

                    try:
                        checkspace = helpers.get_free_space(grdst)
                        if checkspace is False:
                            if all([metaresponse != "fail", metaresponse is not None]):
                                self.tidyup(src_location, True, cacheonly=True)
                            raise OSError
                        place(grab_src, grab_dst, Purpose.SERIES, on_existing=OnExisting.UNGUARDED)
                    except Exception as e:
                        self._log_placement_failure(module, comicarr.CONFIG.FILE_OPTS, grab_src, grab_dst, e)
                        self._log("Failed to %s %s: %s" % (comicarr.CONFIG.FILE_OPTS, grab_src, e))
                        self.valreturn.append({"self.log": self.log, "mode": "stop"})
                        return self.queue.put(self.valreturn)

                    self._journal_pp("moved", issueid=issueid, issuearcid=issuearcid)

                    if any([comicarr.CONFIG.FILE_OPTS == "move", comicarr.CONFIG.FILE_OPTS == "copy"]):
                        self.tidyup(src_location, True, filename=os.path.basename(orig_filename))

                    completion = _complete_postprocess(
                        self._journal_context(),
                        issue_id=issueid,
                        issue_arc_id=issuearcid,
                        anchor_ids=(issueid,),
                        database=db,
                    )

                    if (sandwich is not None and "S" in sandwich) or "_" in issueid:
                        logger.info("%s IssueArcID is : %s" % (module, issuearcid))
                        ctrlVal = {"IssueArcID": issuearcid}
                        newVal = {"Status": "Downloaded", "Location": grab_dst}
                        db.upsert("storyarcs", newVal, ctrlVal)
                        updater.foundsearch(
                            ComicID=comicid,
                            mode="story_arc",
                            IssueID=issueid,
                            IssueArcID=issuearcid,
                            down="PP",
                            module=module,
                        )
                        logger.info("%s Updated status to Downloaded" % module)

                        logger.info("%s Post-Processing completed for: [%s] %s" % (module, sarc, grab_dst))
                        self._log("Post Processing SUCCESSFUL! ")
                    elif oneoff is True:
                        logger.info("%s IssueID is : %s" % (module, issueid))
                        ctrlVal = {"IssueID": issueid}
                        newVal = {"Status": "Downloaded"}
                        logger.info("%s Writing to db: %s -- %s" % (module, newVal, ctrlVal))
                        mark_pull_row_downloaded(issueid)
                        logger.info("%s Updated status to Downloaded" % module)
                        db.upsert("oneoffhistory", newVal, ctrlVal)
                        logger.info("%s Updated history for one-off's for tracking purposes" % module)
                        logger.info(
                            "%s Post-Processing completed for: [ %s #%s ] %s"
                            % (module, comicname, issuenumber, grab_dst)
                        )
                        self._log("Post Processing SUCCESSFUL! ")

                    self._notify_completed(
                        completion,
                        series=comicname,
                        issue_year=None,
                        issue_number=issuenumber,
                        placed_path=grab_dst,
                        issue_id=issueid,
                        module=module,
                    )

                    self._journal_pp("post_processed", issueid=issueid, issuearcid=issuearcid)

                    self.valreturn.append({"self.log": self.log, "mode": "stop"})

                    return self.queue.put(self.valreturn)

                else:
                    try:
                        len(manual_arclist)
                    except (TypeError, NameError):
                        manual_arclist = []

                    if tinfo["comiclocation"] is None:
                        cloc = self.nzb_folder
                    else:
                        cloc = tinfo["comiclocation"]

                    clocation = cloc
                    if os.path.isdir(cloc):
                        for root, _dirnames, filenames in safe_walk(cloc):
                            for filename in filenames:
                                if filename.lower().endswith(self.extensions):
                                    clocation = os.path.join(root, filename)

                    manual_list = {
                        "ComicID": tinfo["comicid"],
                        "IssueID": tinfo["issueid"],
                        "ComicLocation": clocation,
                        "SARC": tinfo["sarc"],
                        "IssueArcID": issuearcid,
                        "ComicName": tinfo["comicname"],
                        "IssueNumber": tinfo["issuenumber"],
                        "Publisher": tinfo["publisher"],
                        "OneOff": tinfo["oneoff"],
                        "ForcedMatch": False,
                    }

        else:
            manual_list = manual

        if self.nzb_name == "Manual Run":
            if len(manual_list) == 0 and len(manual_arclist) == 0:
                logger.info("%s No matches for Manual Run ... exiting." % module)
                self.valreturn.append({"self.log": self.log, "mode": "stop"})
                return self.queue.put(self.valreturn)
            elif len(manual_arclist) > 0 and len(manual_list) == 0:
                logger.info(
                    "%s Manual post-processing completed for %s story-arc issues." % (module, len(manual_arclist))
                )
                self.valreturn.append({"self.log": self.log, "mode": "stop"})
                return self.queue.put(self.valreturn)
            elif len(manual_arclist) > 0:
                logger.info(
                    "%s Manual post-processing completed for %s story-arc issues." % (module, len(manual_arclist))
                )
            i = 0

            for ml in manual_list:
                i += 1
                comicid = ml["ComicID"]
                issueid = ml["IssueID"]
                issuenumOG = ml["IssueNumber"]
                while True:
                    try:
                        ctime = max(os.path.getctime(ml["ComicLocation"]), os.path.getmtime(ml["ComicLocation"]))
                        if time.time() > ctime > time.time() - 10:
                            time.sleep(max(time.time() - ctime, 0))
                        else:
                            break
                    except (OSError, IOError) as e:
                        logger.fdebug("[PP] File no longer accessible: %s" % e)
                        break

                dupthis = helpers.duplicate_filecheck(ml["ComicLocation"], ComicID=comicid, IssueID=issueid)
                if dupthis["action"] == "dupe_src" or dupthis["action"] == "dupe_file":
                    if comicarr.CONFIG.DDUMP and not all(
                        [comicarr.CONFIG.DUPLICATE_DUMP is None, comicarr.CONFIG.DUPLICATE_DUMP == ""]
                    ):
                        dupchkit = self.duplicate_process(dupthis)
                        if not dupchkit:
                            logger.warn("Unable to move duplicate file - skipping post-processing of this file.")
                            continue

                if any([dupthis["action"] == "write", dupthis["action"] == "dupe_src"]):
                    stat = " [%s/%s]" % (i, len(manual_list))
                    self.Process_next(comicid, issueid, issuenumOG, ml, stat)
                    dupthis = None

            if self.failed_files == 0:
                logger.info("%s Manual post-processing completed for %s issues." % (module, i))
            else:
                logger.info(
                    "%s Manual post-processing completed for %s issues [FAILED: %s]" % (module, i, self.failed_files)
                )
            self.valreturn.append({"self.log": self.log, "mode": "stop"})
            return self.queue.put(self.valreturn)

        else:
            comicid = issuenzb["ComicID"]
            issuenumOG = issuenzb["Issue_Number"]
            dupthis = helpers.duplicate_filecheck(self.nzb_folder, ComicID=comicid, IssueID=issueid)
            if dupthis["action"] == "dupe_src" or dupthis["action"] == "dupe_file":
                if comicarr.CONFIG.DUPLICATE_DUMP:
                    if comicarr.CONFIG.DDUMP and not all(
                        [comicarr.CONFIG.DUPLICATE_DUMP is None, comicarr.CONFIG.DUPLICATE_DUMP == ""]
                    ):
                        dupchkit = self.duplicate_process(dupthis)
                        if not dupchkit:
                            logger.warn("Unable to move duplicate file - skipping post-processing of this file.")
                            self.valreturn.append(
                                {"self.log": self.log, "mode": "stop", "issueid": issueid, "comicid": comicid}
                            )
                            return self.queue.put(self.valreturn)

            if dupthis["action"] == "write" or dupthis["action"] == "dupe_src":
                if manual_list is None:
                    return self.Process_next(comicid, issueid, issuenumOG)
                else:
                    logger.info("Post-processing issue is found in more than one destination - let us do this!")
                    return self.Process_next(comicid, issueid, issuenumOG, manual_list)
            else:
                self.valreturn.append({"self.log": self.log, "mode": "stop", "issueid": issueid, "comicid": comicid})
                return self.queue.put(self.valreturn)

    def _item_run(self):
        """This request's state, handed to the per-item pipeline functions."""
        return PostProcessRun(
            context=self._journal_context(),
            nzb_name=self.nzb_name,
            nzb_folder=self.nzb_folder,
            module=self.module,
            extensions=self.extensions,
            log=self.log,
            failed_files=self.failed_files,
            messages=self.valreturn,
        )

    def _item_deps(self):
        # Read at call time, so a patched module attribute is what runs.
        return PostProcessItemDeps(
            place=place,
            tag_file=_tag_file,
            validate_directory=filechecker.validateAndCreateDirectory,
            set_permissions=filechecker.setperms,
            weekly_check=weeklypull.weekly_check,
            totals=updater.totals,
            foundsearch=updater.foundsearch,
            extract_cover=getimage.extract_image,
            manga_destination=get_manga_destination,
        )

    def _finish_item(self, run, result):
        # The legacy methods returned ``queue.put(...)``, which is None.
        self.log = run.log
        self.failed_files = run.failed_files
        if result.queued:
            self.queue.put(self.valreturn)

    def _process_manga(self):
        run = self._item_run()
        self._finish_item(run, process_manga_download(run, self._item_deps()))

    def Process_next(self, comicid, issueid, issuenumOG, ml=None, stat=None):
        run = self._item_run()
        match = PostProcessComicMatch(comicid, issueid, issuenumOG, manual=ml, position=stat)
        self._finish_item(run, process_comic_issue(match, run, self._item_deps()))


def _tag_file(*args, **kwargs):
    from . import cmtag

    return cmtag.run(*args, **kwargs)


class FolderCheck:
    def __init__(self):
        import queue

        self.module = "[FOLDER-CHECK]"
        self.queue = queue.Queue()

    def run(self):
        if comicarr.IMPORTLOCK:
            logger.info(
                "There is an import currently running. In order to ensure successful import - deferring this until the import is finished."
            )
            return
        if comicarr.CONFIG.CHECK_FOLDER is None:
            logger.warn(
                "%s Unable to initialise folder monitor properly - you need to specify a folder to monitor first"
                % self.module
            )
            comicarr.SCHED.pause_job("monitor")
            comicarr.MONITOR_STATUS = "Paused"
            helpers.job_management(write=True)
        else:
            helpers.job_management(
                write=True, job="Folder Monitor", current_run=helpers.utctimestamp(), status="Running"
            )
            comicarr.MONITOR_STATUS = "Running"
            from comicarr.app.downloads import postprocessing
            from comicarr.app.downloads.pp_commands import monitored_folders

            for folder in monitored_folders(comicarr.CONFIG):
                if not os.path.isdir(folder) or not os.access(folder, os.R_OK | os.X_OK):
                    logger.warn("%s Skipping monitored folder %s: it is missing or unreadable" % (self.module, folder))
                    continue
                logger.info("%s Checking folder %s for newly snatched downloads" % (self.module, folder))
                outcome = postprocessing.run({"nzb_name": "Manual Run", "nzb_folder": folder, "source": "monitor"})
                if outcome.status == "busy":
                    comicarr.MONITOR_STATUS = "Waiting"
                    helpers.job_management(write=True, job="Folder Monitor", status="Waiting")
                    return {"status": "IN PROGRESS"}
            logger.info("%s Finished checking for newly snatched downloads" % self.module)
            helpers.job_management(
                write=True, job="Folder Monitor", last_run_completed=helpers.utctimestamp(), status="Waiting"
            )
