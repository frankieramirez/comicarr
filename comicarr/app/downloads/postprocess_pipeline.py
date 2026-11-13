#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Restart-safe stages used by the legacy post-processing facade."""

import os
import shutil
from dataclasses import dataclass
from typing import Any

from comicarr import logger
from comicarr.app.downloads import journal


@dataclass(frozen=True)
class PostProcessContext:
    """Explicit state required to advance post-processing recovery."""

    issue_id: str | None
    issue_arc_id: str | None
    comic_id: str | None
    nzb_name: str
    nzb_folder: str
    api_call: bool
    ddl: bool
    canonical_release_key: str | None
    log_module: str


@dataclass(frozen=True)
class PostProcessTransitionResult:
    """Observable outcome of an attempted journal transition."""

    release_key: str | None
    stage: str
    recorded: bool
    error: str | None = None


@dataclass(frozen=True)
class PostProcessInputContext:
    """Downloader inputs needed to resolve the folder presented to PP."""

    nzb_name: str
    nzb_folder: str
    module: str
    ddl: bool
    use_sabnzbd: bool
    use_nzbget: bool
    sab_direct_unpack: bool
    sab_directory: str | None
    nzbget_directory: str | None
    nzbget_category: str | None = None


@dataclass(frozen=True)
class PostProcessInputResult:
    """Resolved input folder or a stop reason for the compatibility facade."""

    folder: str
    error: str | None = None


class PostProcessInputStage:
    """Resolve downloader-specific paths without mutating facade state."""

    def __init__(self, path_exists=os.path.exists, log=logger):
        self._path_exists = path_exists
        self._log = log

    def resolve(self, context: PostProcessInputContext) -> PostProcessInputResult:
        folder = context.nzb_folder
        if context.ddl:
            self._log.fdebug(f"{context.module} Now performing post-processing of {context.nzb_name} sent from DDL")
            return PostProcessInputResult(folder)

        if context.use_sabnzbd:
            if context.nzb_name != "Manual Run":
                self._log.fdebug(f"{context.module} Using SABnzbd")
                self._log.fdebug(f"{context.module} NZB name as passed from SABnzbd: {context.nzb_name}")

            if context.nzb_name == "Manual Run":
                self._log.fdebug(f"{context.module} Manual Run Post-Processing enabled.")
            elif context.sab_direct_unpack and context.sab_directory not in (None, "None"):
                if self._path_exists(os.path.join(folder, context.nzb_name)):
                    self._log.fdebug(
                        f"{context.module} SABnzbd Download folder option enabled. Using directory of : {folder}"
                    )
                else:
                    job_folder = os.path.join(context.sab_directory, context.nzb_name)
                    basename_folder = os.path.join(context.sab_directory, os.path.basename(folder))
                    if self._path_exists(job_folder):
                        folder = job_folder
                        self._log.fdebug(
                            f"{context.module} SABnzbd Download folder option enabled. Directory set to : {folder}"
                        )
                    elif self._path_exists(basename_folder):
                        folder = basename_folder
                        self._log.fdebug(
                            f"{context.module} SABnzbd Download folder option enabled. Directory set to : {folder}"
                        )
                    else:
                        error = (
                            f"Unable to locate directory within {context.sab_directory} location. "
                            "I have unsucessfully attempted to locate the following paths: "
                            f"{job_folder} & {basename_folder}"
                        )
                        self._log.warn(error)
                        return PostProcessInputResult(folder, error)

        if context.use_nzbget:
            if context.nzb_name != "Manual Run":
                self._log.fdebug(f"{context.module} Using NZBGET")
                self._log.fdebug(f"{context.module} NZB name as passed from NZBGet: {context.nzb_name}")

            if context.nzb_name == "Manual Run":
                self._log.fdebug(f"{context.module} Manual Run Post-Processing enabled.")
            elif context.nzbget_directory not in (None, "None"):
                self._log.fdebug(f"{context.module} NZB name as passed from NZBGet: {context.nzb_name}")
                folder = os.path.join(context.nzbget_directory, context.nzb_name)
                if not self._path_exists(folder) and context.nzbget_category not in (None, "", "None"):
                    categorised = os.path.join(context.nzbget_directory, context.nzbget_category, context.nzb_name)
                    if self._path_exists(categorised):
                        folder = categorised
                        self._log.fdebug(
                            f"{context.module} NZBGet category subdirectory in use. Directory set to : {folder}"
                        )
                self._log.fdebug(f"{context.module} NZBGET Download folder option enabled. Directory set to : {folder}")

        return PostProcessInputResult(folder)


class PostProcessJournalStage:
    """Advance the durable journal around irreversible post-processing work.

    The injected collaborators make failure and idempotency behavior testable
    without a database. The default journal module remains patchable by the
    facade's existing integration tests.
    """

    def __init__(self, journal=journal, log=logger):
        self._journal = journal
        self._log = log

    def release_key(
        self,
        context: PostProcessContext,
        *,
        issue_id: str | None = None,
        issue_arc_id: str | None = None,
    ) -> str:
        explicit_arc_override = issue_arc_id is not None and issue_arc_id != context.issue_arc_id
        if context.canonical_release_key and not explicit_arc_override:
            return context.canonical_release_key

        if explicit_arc_override:
            identity = {
                "issueid": issue_arc_id,
                "IssueArcID": issue_arc_id,
                "comicid": context.comic_id,
                "nzbname": context.nzb_name,
                "ddl": context.ddl,
            }
            return self._journal.derive_release_key(identity)

        identity = {
            "issueid": issue_id if issue_id is not None else context.issue_id,
            "IssueArcID": issue_arc_id if issue_arc_id is not None else context.issue_arc_id,
            "comicid": context.comic_id,
            "nzbname": context.nzb_name,
            "ddl": context.ddl,
        }
        return self._journal.derive_release_key(identity)

    def transition(
        self,
        context: PostProcessContext,
        stage: str,
        *,
        issue_id: str | None = None,
        issue_arc_id: str | None = None,
        payload: dict[str, Any] | None = None,
        conn=None,
    ) -> PostProcessTransitionResult:
        release_key = None
        try:
            release_key = self.release_key(context, issue_id=issue_id, issue_arc_id=issue_arc_id)
            if payload is None:
                payload = {
                    "issueid": issue_id if issue_id is not None else context.issue_id,
                    "issuearcid": issue_arc_id if issue_arc_id is not None else context.issue_arc_id,
                    "comicid": context.comic_id,
                    "nzb_name": context.nzb_name,
                    "nzb_folder": context.nzb_folder,
                    "apicall": context.api_call,
                    "ddl": context.ddl,
                }
            recorded = self._journal.record_transition(
                release_key,
                stage,
                payload=payload,
                conn=conn,
                issueid=issue_id if issue_id is not None else context.issue_id,
            )
            self._log.fdebug(f"{context.log_module} [JOURNAL] {stage} for {release_key}")
            return PostProcessTransitionResult(release_key, stage, bool(recorded))
        except Exception as e:
            if conn is not None:
                raise
            self._log.error(f"{context.log_module} [JOURNAL] {stage} transition failed (inert, continuing): {e}")
            return PostProcessTransitionResult(release_key, stage, False, str(e))


ISSUE = "issue"
ANNUAL = "annual"
MANGA = "manga"


@dataclass(frozen=True)
class PostProcessPlacedItem:
    """A file the placement stage has put in the library, and what it is for."""

    comic_id: str
    issue_id: str
    kind: str
    placed_path: str
    download_type: str | None = None
    crc: str | None = None
    log_module: str = "[POST-PROCESSING]"


@dataclass(frozen=True)
class PostProcessReconcileResult:
    """Which row the reconciliation marked Downloaded, if any."""

    issue_id: str
    table: str
    marked_downloaded: bool
    already_reconciled: bool = False


class PostProcessReconcileStage:
    """Write the database facts that follow a placed file.

    Every write is keyed on the issue and converges, so re-running the stage
    after a restart leaves the rows as the first run left them. Callers run it
    after the ``moved`` journal transition for comics and before it for manga,
    exactly where the inline writes used to sit.

    ``totals`` and ``foundsearch`` are the legacy ``updater`` functions. The
    facade passes them in, so this module never imports a legacy root module
    (ADR-0005); the series seams replace them later.
    """

    def __init__(
        self,
        *,
        totals,
        foundsearch,
        series_queries=None,
        downloads_queries=None,
        is_file=os.path.isfile,
        log=logger,
    ):
        if series_queries is None:
            from comicarr.app.series import queries as series_queries
        if downloads_queries is None:
            from comicarr.app.downloads import queries as downloads_queries
        self._totals = totals
        self._foundsearch = foundsearch
        self._series = series_queries
        self._downloads = downloads_queries
        self._is_file = is_file
        self._log = log

    def reconcile(self, item: PostProcessPlacedItem) -> PostProcessReconcileResult:
        location = os.path.basename(item.placed_path)
        annual = item.kind == ANNUAL
        table = "annuals" if annual else "issues"
        if self._already_reconciled(item, location, annual):
            self._log.fdebug(f"{item.log_module} {table} row {item.issue_id} already records {location}; skipping")
            return PostProcessReconcileResult(item.issue_id, table, True, already_reconciled=True)

        if item.kind == MANGA:
            self._series.mark_issue_downloaded(item.issue_id, location)
            self._downloads.mark_snatched_post_processed(item.issue_id)
            return PostProcessReconcileResult(item.issue_id, "issues", True)

        self._totals(item.comic_id, havefiles="+1", issueid=item.issue_id, file=item.placed_path)
        if annual:
            self._foundsearch(
                item.comic_id,
                item.issue_id,
                mode="want_ann",
                down=item.download_type,
                module=item.log_module,
                crc=item.crc,
            )
        else:
            self._foundsearch(
                item.comic_id, item.issue_id, down=item.download_type, module=item.log_module, crc=item.crc
            )

        if not self._is_file(item.placed_path):
            return PostProcessReconcileResult(item.issue_id, table, False)
        self._log.fdebug(f"{item.log_module} Marking {table} row {item.issue_id} Downloaded: {location}")
        self._series.mark_issue_downloaded(item.issue_id, location, annual=annual)
        return PostProcessReconcileResult(item.issue_id, table, True)

    def _already_reconciled(self, item: PostProcessPlacedItem, location: str, annual: bool) -> bool:
        # The history writes underneath are not keyed tightly enough to
        # converge (a NULL Provider never conflicts), so a re-run is detected
        # from the row the first run leaves behind instead.
        row = self._series.get_issue_file_state(item.issue_id, annual=annual)
        if not row or row.get("Status") != "Downloaded" or row.get("Location") != location:
            return False
        if item.kind == MANGA:
            return True
        try:
            size = os.path.getsize(item.placed_path)
        except OSError:
            return False
        return str(row.get("ComicSize")) == str(size)

    def recount_series(self, comic_id: str):
        """Refresh a manga series' Have count after its chapters were marked."""
        return self._series.recount_have(comic_id)


@dataclass(frozen=True)
class PostProcessCleanupContext:
    """What the cleanup stage may remove once a file is durably placed."""

    nzb_folder: str
    nzb_name: str
    issue_id: str | None
    file_opts: str
    enable_meta: bool
    ddl_location: str | None
    log_module: str = "[POST-PROCESSING]"


class PostProcessCleanupStage:
    """Remove the download leftovers that ``FILE_OPTS`` says may go.

    Runs after the ``moved`` journal transition, so the placed file is already
    durable: a failure here is logged and narrated and never touches the
    journal or the library. Only ``move`` removes download files or folders;
    the metadata cache folder goes whenever tagging made one.
    """

    def __init__(self, *, narrate=lambda _message: None, log=logger):
        self._narrate = narrate
        self._log = log

    def tidy(self, context, odir=None, del_nzbdir=False, sub_path=None, cacheonly=False, filename=None):
        try:
            if cacheonly is False:
                self._tidy_download(context, del_nzbdir, sub_path, filename)
            self._tidy_cache(context, odir)
        except OSError as e:
            self._log.fdebug(
                "%s[%s] Failed to remove directory - Processing will continue, but manual removal is necessary"
                % (context.log_module, e)
            )
            self._narrate("Failed to remove temporary directory")

    def _tidy_download(self, context, del_nzbdir, sub_path, filename):
        module = context.log_module
        nzb_folder = context.nzb_folder
        manual = context.nzb_name == "Manual Run"
        move = context.file_opts == "move"
        self._log.fdebug("File Option: %s [META-ENABLED: %s]" % (context.file_opts, context.enable_meta))
        self._log.fdebug("filename: %s [nzb_folder: %s]" % (filename, nzb_folder))
        self._log.fdebug("sub_path: %s [del_nzbdir: %s]" % (sub_path, del_nzbdir))

        orig_folder = nzb_folder
        if sub_path is not None and sub_path not in (nzb_folder, os.path.join(nzb_folder, "mega")):
            if context.issue_id is None:
                self._log.fdebug(
                    "Sub-directory detected during cleanup. Will attempt to remove if empty: %s" % sub_path
                )
                orig_folder = sub_path
            else:
                self._log.fdebug(
                    "Direct post-processing was performed against specific issueid. "
                    "Using supplied filepath for deletion."
                )

        tmp_folder = orig_folder[:-1] if orig_folder.endswith(("/", "\\")) else orig_folder
        if os.path.split(tmp_folder)[1] == filename and not os.path.isdir(tmp_folder):
            self._log.fdebug(
                "%s item to be deleted is file, not folder due to direct submission: %s" % (module, tmp_folder)
            )
            tmp_folder = os.path.split(tmp_folder)[0]

        if move and manual and tmp_folder != nzb_folder:
            self._remove_folder_or_file(context, tmp_folder, filename, keep_mega=False)
        elif move and manual and filename is not None:
            target = os.path.join(tmp_folder, filename)
            if os.path.isfile(target):
                self._log.fdebug("%s Attempting to remove original file: %s" % (module, target))
                self._remove_file(module, target)
        elif move and del_nzbdir is True and not manual:
            self._remove_folder_or_file(context, tmp_folder, filename, keep_mega=True)

    def _remove_folder_or_file(self, context, tmp_folder, filename, *, keep_mega):
        module = context.log_module
        if not os.listdir(tmp_folder):
            self._log.fdebug("%s Tidying up. Deleting original folder location : %s" % (module, tmp_folder))
            shutil.rmtree(tmp_folder)
            self._narrate("Removed temporary directory : %s" % tmp_folder)
            return
        target = os.path.join(tmp_folder, filename) if filename is not None else None
        if target is None:
            self._not_empty(module, tmp_folder)
            return
        if not os.path.isfile(target):
            return
        self._log.fdebug("%s Attempting to remove file: %s" % (module, target))
        if not self._remove_file(module, target):
            return
        if os.listdir(tmp_folder):
            self._not_empty(module, tmp_folder)
            return
        if keep_mega and context.ddl_location and os.path.join(context.ddl_location, "mega") == tmp_folder:
            self._log.fdebug(
                "%s Tidying up. %s sub-directory not being removed as is required for mega ddl" % (module, tmp_folder)
            )
            return
        self._log.fdebug("%s Tidying up. Deleting original folder location : %s" % (module, tmp_folder))
        try:
            shutil.rmtree(tmp_folder)
        except Exception as e:
            self._log.warn("%s [%s] Unable to delete original folder location: %s" % (module, e, tmp_folder))
        else:
            self._log.fdebug("%s Removed original folder location: %s" % (module, tmp_folder))
            self._narrate("Removed temporary directory : %s" % tmp_folder)

    def _remove_file(self, module, target):
        try:
            os.remove(target)
        except Exception as e:
            self._log.warn("%s [%s] Unable to remove file : %s" % (module, e, target))
            return False
        return True

    def _not_empty(self, module, folder):
        self._narrate("Failed to remove temporary directory: %s" % folder)
        self._log.error(
            "%s %s not empty. Skipping removal of directory - this will either be caught in further "
            "post-processing or it will have to be manually deleted." % (module, folder)
        )

    def _tidy_cache(self, context, odir):
        if not (context.enable_meta and odir and os.path.isdir(odir)):
            return
        if "mylar_" not in odir and "comicarr_" not in odir:
            return
        for name in os.listdir(odir):
            try:
                os.remove(os.path.join(odir, name))
            except OSError:
                pass
        if not os.listdir(odir):
            self._log.fdebug("%s Tidying up. Deleting temporary cache directory : %s" % (context.log_module, odir))
            shutil.rmtree(odir)
            self._narrate("Removed temporary directory : %s" % odir)
        else:
            self._narrate("Failed to remove temporary directory: %s" % odir)
            self._log.error(
                "%s %s not empty. Skipping removal of temporary cache directory - this will either be caught in "
                "further post-processing or have to be manually deleted." % (context.log_module, odir)
            )


@dataclass(frozen=True)
class PostProcessNotification:
    """The completed release a notification describes."""

    series: str
    issue_year: str | None
    issue_number: str | None
    placed_path: str
    issue_id: str | None
    log_module: str = "[POST-PROCESSING]"


def _completion_lines(item: PostProcessNotification) -> tuple[str, str]:
    number = item.issue_number
    if number is not None and "#" not in number:
        number = "#%s" % number
    parts = [item.series]
    if item.issue_year is not None:
        parts.append("(%s)" % item.issue_year)
    if number is not None:
        parts.append(number)
    prline = " ".join(parts)
    return prline, "Comicarr has downloaded and post-processed: " + prline


class PostProcessNotifyStage:
    """Tell the enabled notifiers that a release finished post-processing.

    Sends only when ``completed`` is true: the caller passes whether its own
    call wrote ``post_processed``, so a re-run after a restart, which finds the
    release already completed, sends nothing. ``extract_cover`` is the legacy
    cover reader, passed in by the facade.
    """

    def __init__(self, *, extract_cover, notifiers=None, config=None, log=logger):
        if notifiers is None:
            from comicarr.app.notifications import service as notifiers
        self._extract_cover = extract_cover
        self._notifiers = notifiers
        self._config = config
        self._log = log

    def notify(self, item: PostProcessNotification, *, completed: bool) -> bool:
        if not completed:
            self._log.fdebug(f"{item.log_module} [NOTIFICATION] release already completed; not notifying again")
            return False
        config = self._config
        if config is None:
            import comicarr

            config = comicarr.CONFIG
        try:
            self._send(item, config, self._cover(item, config))
        except Exception as e:
            self._log.warn("[NOTIFICATION] Unable to send notification: %s" % e)
            return False
        return True

    def _cover(self, item, config):
        wants_image = (
            (config.PUSHOVER_IMAGE and config.PUSHOVER_ENABLED)
            or (config.TELEGRAM_IMAGE and config.TELEGRAM_ENABLED)
            or config.DISCORD_ENABLED
            or config.GOTIFY_ENABLED
            or config.MATTERMOST_ENABLED
        )
        if not wants_image:
            return None
        try:
            return self._extract_cover(item.placed_path, single=True, imquality="notif")["ComicImage"]
        except Exception:
            self._log.info("[WARNING] Could not extract image from download in order to send notification")
            return None

    def _send(self, item, config, image):
        n = self._notifiers
        module = item.log_module
        prline, prline2 = _completion_lines(item)
        number = item.issue_number
        if number is not None and "#" not in number:
            number = "#%s" % number
        title = "Download and Postprocessing completed"
        if config.PROWL_ENABLED:
            n.PROWL().notify(prline, title, module=module)
        if config.PUSHOVER_ENABLED:
            n.PUSHOVER().notify(prline, prline2, module=module, imageFile=image)
        if config.BOXCAR_ENABLED:
            n.BOXCAR().notify(prline=prline, prline2=prline2, module=module)
        if config.PUSHBULLET_ENABLED:
            n.PUSHBULLET().notify(prline=prline, prline2=prline2, module=module)
        if config.TELEGRAM_ENABLED:
            n.TELEGRAM().notify(prline2, image)
        if config.SLACK_ENABLED:
            n.SLACK().notify(title, prline2, module=module)
        if config.MATTERMOST_ENABLED:
            n.MATTERMOST().notify(
                "Downloading and Postprocessing completed",
                prline2,
                metadata={"series": item.series, "issue": number, "year": item.issue_year},
                imageFile=image,
                module=module,
            )
        if config.DISCORD_ENABLED:
            n.DISCORD().notify(title, prline2, module=module, imageFile=image)
        if config.EMAIL_ENABLED and config.EMAIL_ONPOST:
            self._log.info("Sending email notification")
            n.EMAIL().notify(prline2, "Comicarr notification - Processed", module=module)
        if config.GOTIFY_ENABLED:
            n.GOTIFY().notify(
                title,
                prline2,
                module=module,
                imageFile=image,
                metadata={"series": item.series, "issue": number, "year": item.issue_year, "issueid": item.issue_id},
            )
        if config.MATRIX_ENABLED:
            n.MATRIX().notify(title, prline2, module=module)
