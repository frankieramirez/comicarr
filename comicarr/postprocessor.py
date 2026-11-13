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


"""Folder matching for post-processing.

``match_folder`` works out which watched issue, story-arc issue or snatched
download each file in a folder belongs to. It is the inherited Mylar3 rule
set, kept here on purpose (see ``docs/architecture/postprocessing-migration-map.md``):
it moves no files, writes no rows and sends nothing. The two things it used
to do itself, stripping a forced ``[__issueid__]`` tag from a filename and
refreshing a series whose dates are incomplete, it now asks its caller to do
through ``rename`` and ``refresh_series``.

``comicarr.app.downloads.postprocessing`` is the only module that imports
this one (ADR-0005). It also takes the legacy collaborators the pipeline
calls from ``pipeline_deps``.
"""

import datetime
import os
import pathlib
import re
import time
from dataclasses import dataclass

from sqlalchemy import Integer, and_, func, inspect, or_, select

import comicarr
from comicarr import db, filechecker, getimage, helpers, logger, series_kind, updater, weeklypull
from comicarr.app.common.placement import place
from comicarr.app.downloads.postprocess_pipeline import PostProcessItemDeps
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


@dataclass(frozen=True)
class LibraryIssueMatch:
    """A file matched to an issue or annual of a watched series.

    ``values`` is the matcher's row for the file, the dict the per-item stage
    reads as ``ml``.
    """

    comic_id: str
    issue_id: str
    issue_number: str | None
    location: str
    values: dict


@dataclass(frozen=True)
class ArcOnlyMatch:
    """A file that belongs to a watched story arc and to no watched series."""

    issue_arc_id: str
    location: str
    values: dict


@dataclass(frozen=True)
class FolderMatches:
    """What a folder scan found, and the request state the rules left behind.

    ``snatched`` holds the downloads identified from what was snatched (the
    ``nzblog`` row, a story-arc snatch or a pull-list one-off) rather than by
    filename. ``exit`` is ``"stop"`` or ``"outside"`` when the rules ended the
    request with that message, and ``"abort"`` when they ended it with none.
    """

    library: tuple
    arc_only: tuple
    snatched: tuple
    exit: str | None
    nzb_folder: str
    issue_id: str | None
    issue_arc_id: str | None
    comic_id: str | None
    log: str


class _Scan:
    """The attributes the inherited rules read and write while they match."""

    def __init__(self, nzb_name, nzb_folder, issueid, comicid, apicall, module, extensions, log):
        self.nzb_name = nzb_name
        self.nzb_folder = nzb_folder
        self.issueid = issueid
        self.comicid = comicid
        self.issuearcid = None
        self.apicall = apicall
        self.module = module
        self.extensions = extensions
        self.log = log
        self.oneoffinlist = False
        self.phase = "match"
        self.manual_list = []
        self.manual_arclist = []

    def _log(self, message):
        self.log += message + "\n"

    def matched_files(self, manual_list, manual_arclist):
        self.manual_list = manual_list
        self.manual_arclist = manual_arclist

    def result(self, exit, snatched=()):
        # Matching that ends early hands nothing on; the snatch lookup ends
        # after the arc-only files were placed, so those still go.
        library = self.manual_list if self.phase == "snatch" else []
        arc_only = self.manual_arclist if self.phase == "snatch" else []
        return FolderMatches(
            library=tuple(
                LibraryIssueMatch(ml["ComicID"], ml["IssueID"], ml["IssueNumber"], ml["ComicLocation"], ml)
                for ml in library
            ),
            arc_only=tuple(ArcOnlyMatch(ml["IssueArcID"], ml["ComicLocation"], ml) for ml in arc_only),
            snatched=tuple(snatched),
            exit=exit,
            nzb_folder=self.nzb_folder,
            issue_id=self.issueid,
            issue_arc_id=self.issuearcid,
            comic_id=self.comicid,
            log=self.log,
        )


def match_folder(
    nzb_name: str,
    nzb_folder: str,
    *,
    issueid: str | None = None,
    comicid: str | None = None,
    apicall: bool = False,
    module: str = "[POST-PROCESSING]",
    extensions: tuple = (".cbr", ".cbz", ".pdf", ".cb7"),
    log: str = "",
    refresh_series,
    rename,
) -> FolderMatches:
    """Match the files in ``nzb_folder`` (or the one named download).

    ``refresh_series(comic_ids)`` refreshes series whose issue dates are
    incomplete before the rules re-read them; ``rename(src, dst)`` moves a
    file whose forced ``[__issueid__]`` tag is stripped and returns its new
    path.
    """
    scan = _Scan(nzb_name, nzb_folder, issueid, comicid, apicall is True, module, extensions, log)
    module = scan.module
    manual_list = []
    manual_arclist = []
    oneoff_issuelist = []
    ppinfo = []
    if any([scan.nzb_name == "Manual Run", scan.issueid is not None, scan.comicid is not None, scan.apicall is True]):
        if (
            all([scan.issueid is None, scan.comicid is not None, scan.apicall is True])
            or scan.nzb_name == "Manual Run"
            or all(
                [
                    scan.apicall is True,
                    scan.comicid is None,
                    scan.issueid is None,
                    scan.nzb_name.startswith("0-Day"),
                ]
            )
        ):
            if scan.comicid is not None:
                logger.fdebug("%s Now post-processing pack directly against ComicID: %s" % (module, scan.comicid))
            elif all(
                [
                    scan.apicall is True,
                    scan.issueid is None,
                    scan.comicid is None,
                    scan.nzb_name.startswith("0-Day"),
                ]
            ):
                logger.fdebug("%s Now post-processing 0-day pack: %s" % (module, scan.nzb_name))
            else:
                logger.fdebug("%s Manual Run initiated" % module)
            flc = filechecker.FileChecker(scan.nzb_folder, justparse=True, pp_mode=True)
            filelist = flc.listFiles()
            if filelist["comiccount"] == 0:
                logger.warn("There were no files located - check the debugging logs if you think this is in error.")
                return scan.result("stop")
            logger.info(
                "I have located %s files that I should be able to post-process. Continuing..." % filelist["comiccount"]
            )
        else:
            if all([scan.comicid is None, "_" not in scan.issueid]):
                cid = db.select_one(select(issues.c.ComicID).where(issues.c.IssueID == str(scan.issueid)))
                scan.comicid = cid["ComicID"]
            else:
                if "_" in scan.issueid:
                    scan.issuearcid = scan.issueid
                    scan.issueid = None
                    logger.fdebug(
                        "%s Now post-processing directly against StoryArcs -  ComicID: %s / IssueArcID: %s"
                        % (module, scan.comicid, scan.issuearcid)
                    )
            if scan.issueid is not None:
                logger.fdebug(
                    "%s Now post-processing directly against ComicID: %s / IssueID: %s"
                    % (module, scan.comicid, scan.issueid)
                )
            if scan.issuearcid is None:
                if scan.nzb_name.lower().endswith(scan.extensions):
                    flc = filechecker.FileChecker(scan.nzb_folder, file=scan.nzb_name, pp_mode=True)
                    fl = flc.listFiles()
                    filelist = {}
                    filelist["comiclist"] = [fl]
                    filelist["comiccount"] = len(filelist["comiclist"])
                else:
                    flc = filechecker.FileChecker(scan.nzb_folder, justparse=True, pp_mode=True)
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
            if all([fl["series_name"] is not None, fl["series_name"] != ""]) and comicarr.CONFIG.IGNORE_COVERS is True:
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

            scan.matched = False
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

            if any([scan.issueid is not None, scan.comicid is not None]) and fl["issueid"] is None:
                comicseries = db.select_all(select(comics).where(comics.c.ComicID == scan.comicid))
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
                            scan.oneoffinlist = True

                    if any([csi is not None, ssi is not None, osi is not None]):
                        if scan.nzb_name == "Manual Run":
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
                            if scan.nzb_name == "Manual Run":
                                if fl["sub"] is None:
                                    tpath = os.path.join(scan.nzb_folder, fl["comicfilename"])
                                else:
                                    tpath = os.path.join(scan.nzb_folder, fl["sub"], fl["comicfilename"])
                                if pathlib.Path(tpath).is_file():
                                    try:
                                        cloct = pathlib.Path(tpath).with_name(nfilename)
                                        clocation = str(rename(pathlib.Path(tpath), cloct))
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
                                            rename(tt, clocation)
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
                                        clocation = str(rename(pathlib.Path(tpath).joinpath(tname), cloct))
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
                                            clocation = str(pathlib.Path(tpath).joinpath(tname).with_name(nfilename))
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
                                            rename(tt, clocation)
                                            scan.nzb_folder = clocation
                                    else:
                                        scan.nzb_folder = clocation
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
                                                    clocation = str(rename(pathlib.Path(tpath), cloct))
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
                                                        rename(tt, clocation)
                                                        scan.nzb_folder = clocation
                                                else:
                                                    scan.nzb_folder = clocation
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
                if (wv["Status"] == "Paused" and any([wv["cv_removed"] == 2, bool(wv["ForceContinuing"]) is True])) or (
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
                        "Forcing a refresh of series: %s as it appears to have incomplete issue dates." % wv_comicname
                    )
                    refresh_series([wv_comicid])
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
                            "this should have an issue number to match to this particular series: %s" % cs["ComicID"]
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
                                    fcdigit = helpers.issuedigits(re.sub(ann_line, "", str(temploc.lower())).strip())
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
                            refresh_series([cs["ComicID"]])
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
                                        .order_by(weekly.c.year.desc(), func.cast(weekly.c.weeknumber, Integer).desc())
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
                                        ) or all([comicarr.CONFIG.ANNUALS_ON, "special" in week_dynamicname.lower()]):
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
                            if all([watchmatch["series_volume"] != "None", watchmatch["series_volume"] is not None]):
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

                            if datematch == "False" and volume_settles_year_for_match(cs["WatchValues"], watchmatch):
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
                                    if scan.issueid is not None and os.path.isfile(watchmatch["comiclocation"]):
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
                        scan.matched = True
                    else:
                        continue

                if datematch == "True":
                    logger.fdebug(
                        "%s[SUCCESSFUL MATCH: %s-%s] Match verified for %s"
                        % (module, cs["ComicName"], cs["ComicID"], fl["comicfilename"])
                    )
                    break
                elif scan.matched is True:
                    logger.warn(
                        "%s[MATCH: %s - %s] We matched by name for this series, but cannot find a corresponding issue number in the series list."
                        % (module, cs["ComicName"], cs["ComicID"])
                    )

            if scan.issuearcid is None:
                arc_series = db.select_all(
                    select(storyarcs).where(func.lower(storyarcs.c.DynamicComicName).in_([x.lower() for x in loopchk]))
                )
            else:
                if scan.issuearcid[0] == "S":
                    scan.issuearcid = scan.issuearcid[1:]
                arc_series = db.select_all(select(storyarcs).where(storyarcs.c.IssueArcID == scan.issuearcid))

            if arc_series is None:
                logger.error(
                    "%s No Story Arcs in Watchlist that contain that particular series - aborting Manual Post Processing. Maybe you should be running Import?"
                    % module
                )
                return scan.result("abort")
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
                        res[acv["ComicName"]].append({"ArcValues": acv["ArcValues"], "WatchValues": acv["WatchValues"]})
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
                                            year_check = re.findall(r"(\d{4})(?=[\s]|annual\b|$)", temploc, flags=re.I)
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

                                        elif all([isc["ReleaseDate"] is not None, isc["ReleaseDate"] != "0000-00-00"]):
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
                                            tmp_arclist_vol = re.sub("[^0-9]", "", arc_values["ComicVersion"]).strip()
                                        if all(
                                            [
                                                arcmatch["series_volume"] != "None",
                                                arcmatch["series_volume"] is not None,
                                            ]
                                        ):
                                            tmp_arcmatch_vol = re.sub("[^0-9]", "", arcmatch["series_volume"]).strip()
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
                                            elif len(arcvals) == 1 and int(tmp_arcmatch_vol) == int(tmp_arclist_vol):
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
                                            datematch == "False" and arcmatch["issue_year"] is None and lonevol is True
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
                                        if datematch == "False" and volume_settles_year_for_match(arc_values, arcmatch):
                                            logger.fdebug(
                                                "%s[ARC][MANGA][VOLUME MATCH] Volume %s matched, so the year in the filename (%s) does not decide this file."
                                                % (module, arcmatch["series_volume"], arcmatch["issue_year"])
                                            )
                                            datematch = "True"

                                        if datematch == "True":
                                            passit = False
                                            if len(manual_list) > 0:
                                                if any(
                                                    v[i]["ArcValues"]["IssueID"] == x["IssueID"] for x in manual_list
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
                                                        clocation = os.path.join(arcmatch["comiclocation"], tmpfilename)

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
                                                scan.matched = True
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
                            scan.matched = True
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

            if scan.matched is False:
                if all(["0-Day Week" in scan.nzb_name, comicarr.CONFIG.PACK_0DAY_WATCHLIST_ONLY is True]):
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
                        logger.fdebug("%s[ONEOFF-SELECTION][scan.nzb_name: %s]" % (module, scan.nzb_name))
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
                                            just_the_digits = re.sub("[^0-9]", "", watchmatch["series_volume"]).strip()
                                        else:
                                            just_the_digits = re.sub("[^0-9]", "", watchmatch["justthedigits"]).strip()
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
                                    if scan.issueid is not None and os.path.isfile(watchmatch["comiclocation"]):
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
                                scan.oneoffinlist = True
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
                            scan.matched = True
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

    scan.matched_files(manual_list, manual_arclist)
    scan.phase = "snatch"
    if (
        all([scan.nzb_name != "Manual Run", scan.apicall is False])
        or (scan.oneoffinlist is True or all([scan.issuearcid is not None, scan.issueid is None]))
    ) and not scan.nzb_name.startswith("0-Day"):
        ppinfo = []
        if scan.oneoffinlist is False:
            scan.oneoff = False
            if any([scan.issueid is not None, scan.issuearcid is not None]):
                if scan.issuearcid is not None:
                    s_id = scan.issuearcid
                else:
                    s_id = scan.issueid
                nzbiss = db.select_one(select(nzblog).where(nzblog.c.IssueID == s_id))
                if nzbiss is None and scan.issuearcid is not None:
                    nzbiss = db.select_one(select(nzblog).where(nzblog.c.IssueID == "S" + s_id))

            else:
                nzbname = scan.nzb_name
                if nzbname.lower().endswith(scan.extensions):
                    fd, ext = os.path.splitext(nzbname)
                    scan._log("Removed extension from nzb: " + ext)
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
                    "[NZBNAME] nzbname (remove extensions, double spaces, convert underscores to spaces): " + nzbname
                )
                nzbname = re.sub(r"\s", ".", nzbname)

                logger.fdebug("%s After conversions, nzbname is : %s" % (module, nzbname))
                scan._log("nzbname: %s" % nzbname)

                nzbiss = db.select_one(
                    select(nzblog).where(or_(nzblog.c.NZBName == nzbname, nzblog.c.AltNZBName == nzbname))
                )

                if nzbiss is None:
                    scan._log("Failure - could not initially locate nzbfile in my database to rename.")
                    logger.fdebug("%s Failure - could not locate nzbfile initially" % module)
                    nzbname = re.sub(r"[\(\)]", "", str(nzbname))
                    scan._log("trying again with this nzbname: %s" % nzbname)
                    logger.fdebug("%s Trying to locate nzbfile again with nzbname of : %s" % (module, nzbname))
                    nzbiss = db.select_one(
                        select(nzblog).where(or_(nzblog.c.NZBName == nzbname, nzblog.c.AltNZBName == nzbname))
                    )
                    if nzbiss is None:
                        logger.error(
                            "%s Unable to locate downloaded file within items I have snatched. Attempting to parse the filename directly and process."
                            % module
                        )
                        scan._log(
                            "Unable to locate downloaded file within items I have snatched. Attempting to parse the filename directly and process."
                        )
                        return scan.result("outside")
                    else:
                        scan._log("I corrected and found the nzb as : %s" % nzbname)
                        logger.fdebug("%s Auto-corrected and found the nzb as : %s" % (module, nzbname))

            issueid = nzbiss["IssueID"]
            logger.fdebug("%s Issueid: %s" % (module, issueid))
            sarc = nzbiss["SARC"]
            scan.oneoff = nzbiss["OneOff"]
            logger.fdebug("sarc: %s / oneoff: %s" % (sarc, scan.oneoff))
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
                        "oneoff": scan.oneoff,
                    }
                )

            elif scan.oneoff is not None and any([issueid[0] == "S", "_" in issueid]):
                issuearcid = re.sub("S", "", issueid).strip()
                oneinfo = db.select_one(select(storyarcs).where(storyarcs.c.IssueArcID == issuearcid))
                if oneinfo is None:
                    logger.warn(
                        "Unable to locate issue as previously snatched arc issue - it might be something else..."
                    )
                    scan._log("Unable to locate issue as previously snatched arc issue - it might be something else...")
                else:
                    tmplookup = db.select_one(select(comics).where(comics.c.ComicID == oneinfo["ComicID"]))
                    if tmplookup is not None:
                        logger.fdebug(
                            "[WATCHLIST-DETECTION-%s] Processing as Arc, detected on watchlist - will PP for both."
                            % tmplookup["ComicName"]
                        )
                        scan.oneoff = False
                    else:
                        scan.oneoff = True
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
                            "oneoff": scan.oneoff,
                        }
                    )

            if all([len(ppinfo) == 0, scan.oneoff is not None, comicarr.CONFIG.ALT_PULL == 2]):
                oneinfo = db.select_one(select(weekly).where(weekly.c.IssueID == issueid))
                if oneinfo is None:
                    oneinfo = db.select_one(select(oneoffhistory).where(oneoffhistory.c.IssueID == issueid))
                    if oneinfo is None:
                        logger.warn("Unable to locate issue as previously snatched one-off")
                        scan._log("Unable to locate issue as previously snatched one-off")
                        return scan.result("stop")
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

                scan.oneoff = True
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
                        scan.oneoff = True
    return scan.result(None, ppinfo)


def wait_until_settled(path):
    """Wait while a file was written in the last ten seconds."""
    while True:
        try:
            ctime = max(os.path.getctime(path), os.path.getmtime(path))
            if time.time() > ctime > time.time() - 10:
                time.sleep(max(time.time() - ctime, 0))
            else:
                break
        except (OSError, IOError) as e:
            logger.fdebug("[PP] File no longer accessible: %s" % e)
            break


def pipeline_deps():
    """The legacy collaborators the post-processing pipeline calls.

    Read at call time, so a patched module attribute is what runs.
    """
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
        settle=wait_until_settled,
        refresh_series=updater.dbUpdate,
    )


def _tag_file(*args, **kwargs):
    from . import cmtag

    return cmtag.run(*args, **kwargs)
