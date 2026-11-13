#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Restart-safe stages used by the legacy post-processing facade."""

import datetime
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, or_, select, update

from comicarr import db, helpers, logger, series_kind
from comicarr.app.common.numbers import zero_suppression_prefix
from comicarr.app.common.placement import OnExisting, Outcome, Purpose
from comicarr.app.common.redaction import redacted_traceback
from comicarr.app.downloads import journal
from comicarr.app.downloads.pp_commands import safe_walk
from comicarr.app.manga.ledger import normalize_volume_number
from comicarr.tables import annuals, comics, issues, snatched, storyarcs, weekly


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
    cache_dir: str | None = None


_TAGGER_CACHE_PREFIXES = ("comicarr_", "mylar_")


def _tagger_cache_folder(cache_dir, odir):
    """``odir`` resolved, if it is a tagger folder directly under ``cache_dir``.

    The tagger only ever makes ``CACHE_DIR/comicarr_*`` (``mylar_*`` before
    the rename), so anything else is never emptied, whatever it is named.
    """
    if not cache_dir or not odir:
        return None
    root = os.path.realpath(cache_dir)
    target = os.path.realpath(odir)
    if not target.startswith(root + os.sep):
        return None
    if os.path.dirname(target) != root:
        return None
    if not os.path.basename(target).startswith(_TAGGER_CACHE_PREFIXES):
        return None
    return target


class PostProcessCleanupStage:
    """Remove the download leftovers that ``FILE_OPTS`` says may go.

    Runs after the ``moved`` journal transition, so the placed file is already
    durable: a failure here is logged and narrated and never touches the
    journal or the library. Only ``move`` removes download files or folders;
    the metadata cache folder goes whenever tagging made one, and only when it
    is a tagger folder inside ``CACHE_DIR``.
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
        if not context.enable_meta:
            return
        odir = _tagger_cache_folder(context.cache_dir, odir)
        if odir is None or not os.path.isdir(odir):
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


# ---------------------------------------------------------------------------
# Per-item processing: one matched comic issue, or one manga download.
# ---------------------------------------------------------------------------

COMPLETED = "completed"
STOPPED = "stopped"
RETRY = "retry"
ABORTED = "aborted"

DEFAULT_EXTENSIONS = (".cbr", ".cbz", ".pdf", ".cb7")


@dataclass(frozen=True)
class PostProcessItemDeps:
    """The legacy collaborators a per-item run calls, passed in by the facade.

    ADR-0005 keeps the Deferred legacy modules (``cmtag``, ``filechecker``,
    ``getimage``, ``weeklypull``) and ``updater`` out of ``comicarr/app/``, so
    the facade hands over the functions themselves. ``settle`` waits while a
    file is still being written; ``refresh_series`` refreshes series for the
    folder matcher.
    """

    place: Callable
    tag_file: Callable
    validate_directory: Callable
    set_permissions: Callable
    weekly_check: Callable
    totals: Callable
    foundsearch: Callable
    extract_cover: Callable
    manga_destination: Callable
    settle: Callable = lambda _path: None
    refresh_series: Callable = lambda _comic_ids: None


@dataclass(frozen=True)
class PostProcessComicMatch:
    """One library issue (or annual) a downloaded file was matched to.

    ``manual`` is the folder matcher's row for the file when one was matched
    from a folder scan; without it the file is found in ``nzb_folder``.
    """

    comic_id: str
    issue_id: str
    issue_number: str | None
    manual: dict | None = None
    position: str | None = None


@dataclass(frozen=True)
class PostProcessItemResult:
    """How a per-item run ended.

    ``queued`` says whether the run's messages go to the caller's queue; a few
    legacy failure paths return without signalling it, and still do.
    """

    outcome: str
    queued: bool
    issue_id: str | None = None
    placed_path: str | None = None


@dataclass
class PostProcessRun:
    """The state one post-processing request carries across its items.

    ``log`` and ``messages`` are the legacy narration string and the list the
    queue consumer reads (``{"self.log": ..., "mode": ...}`` entries).
    """

    context: PostProcessContext
    nzb_name: str
    nzb_folder: str
    module: str = "[POST-PROCESSING]"
    extensions: tuple = DEFAULT_EXTENSIONS
    log: str = ""
    failed_files: int = 0
    messages: list = field(default_factory=list)

    def narrate(self, message):
        self.log += message + "\n"

    def finish(self, mode, outcome=None, **extra):
        entry = {"self.log": self.log, "mode": mode}
        entry.update(extra)
        self.messages.append(entry)
        if outcome is None:
            outcome = {"stop": STOPPED, "fail": RETRY}.get(mode, STOPPED)
        return PostProcessItemResult(outcome, True, issue_id=extra.get("issueid"))

    def abort(self):
        return PostProcessItemResult(ABORTED, False)

    def journal(self, stage, *, issue_id=None, issue_arc_id=None, payload=None):
        return _JOURNAL.transition(self.context, stage, issue_id=issue_id, issue_arc_id=issue_arc_id, payload=payload)

    def tidy(self, odir=None, del_nzbdir=False, sub_path=None, cacheonly=False, filename=None):
        import comicarr

        config = comicarr.CONFIG
        PostProcessCleanupStage(narrate=self.narrate).tidy(
            PostProcessCleanupContext(
                nzb_folder=self.nzb_folder,
                nzb_name=self.nzb_name,
                issue_id=self.context.issue_id,
                file_opts=config.FILE_OPTS,
                enable_meta=config.ENABLE_META,
                ddl_location=getattr(config, "DDL_LOCATION", None),
                log_module=self.module,
                cache_dir=getattr(config, "CACHE_DIR", None),
            ),
            odir,
            del_nzbdir=del_nzbdir,
            sub_path=sub_path,
            cacheonly=cacheonly,
            filename=filename,
        )

    def log_placement_failure(self, operation, src, dst, error, *, module=None):
        logger.error(
            "%s Failed to %s %s to %s (release=%s, issue=%s)\n%s"
            % (
                module or self.module,
                operation,
                src,
                dst,
                self.context.canonical_release_key,
                self.context.issue_id,
                redacted_traceback(error),
            )
        )


_JOURNAL = PostProcessJournalStage()


def run_script(kind, run, nzb_name, nzb_folder, filename, path, seriesmetadata):
    """Run the configured pre (``kind="pre"``) or extra script for one file."""
    import comicarr

    config = comicarr.CONFIG
    if kind == "pre":
        script, shell_location, label, text = config.PRE_SCRIPTS, config.PRE_SHELL_LOCATION, "pre", False
    else:
        script, shell_location, label, text = config.EXTRA_SCRIPTS, config.ES_SHELL_LOCATION, "extra", True
    name = "PRE_SCRIPTS" if kind == "pre" else "EXTRA_SCRIPTS"
    logger.fdebug("initiating %s script detection." % label)
    run.narrate("initiating %s script detection." % label)
    logger.fdebug("comicarr.%s : %s" % (name, script))
    run.narrate("comicarr.%s : %s" % (name, script))
    with open(script, "r") as f:
        first_line = f.readline()

    if script.endswith(".sh"):
        shell_cmd = re.sub("#!", "", first_line).strip()
        if shell_cmd == "" or shell_cmd is None:
            shell_cmd = "/bin/bash"
    elif shell_location is not None:
        if "powershell" in os.path.basename(shell_location.lower()):
            shell_cmd = "%s -%s" % (shell_location, "File")
        else:
            shell_cmd = shell_location
    else:
        shell_cmd = sys.executable

    script_name = shell_cmd + " " + str(script)
    logger.fdebug("%s script detected...enabling: %s" % (label, script_name))
    script_cmd = shlex.split(script_name, posix=False) + [
        str(nzb_name),
        str(nzb_folder),
        str(filename),
        str(path),
        json.dumps(seriesmetadata),
    ]
    logger.fdebug("cmd to be executed: %s" % (script_cmd,))
    run.narrate("cmd to be executed: %s" % (script_cmd,))

    logger.fdebug("Executing command %s" % (script_cmd,))
    logger.fdebug("Absolute path to script: %s" % (script_cmd[0],))
    try:
        p = subprocess.Popen(
            script_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=comicarr.PROG_DIR, text=text
        )
        out, _err = p.communicate()
        logger.fdebug("Script result: %s" % (out,))
        run.narrate("Script result: %s" % (out,))
    except OSError:
        logger.warn("Unable to run %s_script: %s" % (label, script_cmd))
        run.narrate("Unable to run %s_script: %s" % (label, script_cmd))


def _notify(run, deps, completion, *, series, issue_year, issue_number, placed_path, issue_id):
    # No completion attempt on this path means legacy behaviour: notify.
    completed = True if completion is None else bool(completion.recorded)
    PostProcessNotifyStage(extract_cover=deps.extract_cover).notify(
        PostProcessNotification(
            series=series,
            issue_year=issue_year,
            issue_number=issue_number,
            placed_path=placed_path,
            issue_id=issue_id,
            log_module=run.module,
        ),
        completed=completed,
    )


_ISSUE_SUFFIXES = (
    ("au", " AU"),
    ("ai", " AI"),
    ("inh", ".INH"),
    ("now", ".NOW"),
    ("bey", ".BEY"),
    ("mu", ".MU"),
    ("hu", ".HU"),
    ("deaths", ".DEATHS"),
)


def _split_issue_suffix(issuenum):
    """Strip a known issue-number suffix: ``"5AU"`` -> ``("5", " AU")``."""
    import comicarr

    lowered = issuenum.lower()
    for marker, suffix in _ISSUE_SUFFIXES:
        if marker in lowered and issuenum[:1].isdigit():
            if marker == "now" and "!" in issuenum:
                issuenum = re.sub(r"\!", "", issuenum)
            return re.sub("[^0-9]", "", issuenum), suffix
    for symbol, value in (("\xbd", "0.5"), ("\xbc", "0.25"), ("\xbe", "0.75"), ("∞", "infinity")):
        if symbol in issuenum:
            return value, "None"
    issue_except = "None"
    exceptionmatch = [x for x in comicarr.ISSUE_EXCEPTIONS if x.lower() in issuenum.lower()]
    if exceptionmatch:
        logger.fdebug("[FILECHECKER] We matched on : " + str(exceptionmatch))
        for x in exceptionmatch:
            issuenum = re.sub("[^0-9]", "", issuenum)
            issue_except = x
    return issuenum, issue_except


def _pretty_issue_number(run, issuenum, issue_except):
    """The zero-padded issue number for the filename, or None if unusable.

    Returns ``(prettycomiss, issueno)``; ``prettycomiss`` is ``False`` when the
    number cannot be read at all, which ends the item without a queue signal.
    """
    import comicarr

    module = run.module
    iss_decval = None
    if "." in issuenum:
        iss_find = issuenum.find(".")
        iss_b4dec = issuenum[:iss_find]
        if iss_b4dec == "":
            iss_b4dec = "0"
        iss_decval = issuenum[iss_find + 1 :]
        if iss_decval.endswith("."):
            iss_decval = iss_decval[:-1]
        if int(iss_decval) == 0:
            iss = iss_b4dec
            issueno = str(iss)
            run.narrate("Issue Number: %s" % issueno)
            logger.fdebug("%s Issue Number: %s" % (module, issueno))
        else:
            if len(iss_decval) == 1:
                iss = iss_b4dec + "." + iss_decval
            else:
                iss = iss_b4dec + "." + iss_decval.rstrip("0")
            issueno = iss_b4dec
            run.narrate("Issue Number: %s" % iss)
            logger.fdebug("%s Issue Number: %s" % (module, iss))
    else:
        iss = issuenum
        issueno = iss

    zeroadd = zero_suppression_prefix(comicarr.CONFIG.ZERO_LEVEL, comicarr.CONFIG.ZERO_LEVEL_N)
    logger.fdebug("%s Zero Suppression set to : %s" % (module, comicarr.CONFIG.ZERO_LEVEL_N))

    prettycomiss = None
    if issueno.isalpha():
        logger.fdebug("issue detected as an alpha.")
        prettycomiss = str(issueno)
    else:
        try:
            x = float(issueno)
            if x < 0:
                logger.info("%s I've encountered a negative issue #: %s. Trying to accomodate" % (module, issueno))
                prettycomiss = "-%s%s" % (zeroadd, issueno[1:])
            elif x >= 0:
                pass
            else:
                raise ValueError
        except ValueError:
            logger.warn(
                "Unable to properly determine issue number [%s] - you should probably log this on github for help."
                % issueno
            )
            return False, issueno

    if all([prettycomiss is None, len(str(issueno)) > 0]):
        if int(issueno) < 10:
            logger.fdebug("issue detected less than 10")
            prettycomiss = _padded(zeroadd, iss, issueno, iss_decval)
        elif int(issueno) >= 10 and int(issueno) < 100:
            logger.fdebug("issue detected greater than 10, but less than 100")
            if zeroadd == "00":
                zeroadd = "0"
            prettycomiss = _padded(zeroadd, iss, issueno, iss_decval)
        else:
            logger.fdebug("issue detected greater than 100")
            if "." in iss and int(iss_decval) > 0:
                issueno = str(iss)
            prettycomiss = str(issueno)
        if issue_except != "None":
            prettycomiss = str(prettycomiss) + issue_except
        logger.fdebug(
            "%s Zero level supplement set to %s. Issue will be set as : %s"
            % (module, comicarr.CONFIG.ZERO_LEVEL_N, prettycomiss)
        )
    elif len(str(issueno)) == 0:
        prettycomiss = str(issueno)
        logger.fdebug("issue length error - cannot determine length. Defaulting to None: %s " % prettycomiss)
    return prettycomiss, issueno


def _padded(zeroadd, iss, issueno, iss_decval):
    if "." in iss:
        if int(iss_decval) > 0:
            return str(zeroadd) + str(iss)
        return str(zeroadd) + str(int(issueno))
    return str(zeroadd) + str(iss)


def _names_an_arc(ml):
    """Whether the match row carries an ``IssueArcID`` key at all.

    The legacy test was a bare ``ml["IssueArcID"]`` lookup, so a row with the
    key set to None still looked its issue up in the watched arcs.
    """
    try:
        ml["IssueArcID"]
    except Exception:
        return False
    return True


def _arc_memberships(ml):
    """The watched-arc rows the matched issue belongs to (legacy lookup)."""
    arcsforever = db.select_all(
        select(storyarcs).where(and_(storyarcs.c.ComicID == ml["ComicID"], storyarcs.c.IssueID == ml["IssueID"]))
    )
    if not arcsforever:
        id_arcsforever = db.select_one(
            select(storyarcs.c.IssueID).where(
                and_(storyarcs.c.IssueArcID == ml["IssueArcID"], storyarcs.c.ComicID == ml["ComicID"])
            )
        )
        if not id_arcsforever:
            logger.warn(
                "Unable to locate IssueID within givin Story Arc. Ensure everything is up-to-date (refreshed) for the Arc."
            )
        else:
            arcsforever = db.select_all(select(storyarcs).where(storyarcs.c.IssueID == id_arcsforever["IssueID"]))
    return arcsforever or []


def _arc_payload(run, membership, library_file):
    return {
        "mode": "story_arc",
        "arc_copy": True,
        "issueid": membership.issue_arc_id,
        "issuearcid": membership.issue_arc_id,
        "comicid": run.context.comic_id,
        "nzb_name": run.nzb_name,
        "library_file": library_file,
        "story_arc": membership.story_arc,
        "story_arc_id": membership.story_arc_id,
        "reading_order": membership.reading_order,
        "publisher": membership.publisher,
    }


def _arc_context(context, issue_arc_id):
    """The journal context for one arc copy: its own arc-scoped key."""
    key = _JOURNAL.release_key(context, issue_arc_id=issue_arc_id)
    return PostProcessContext(
        issue_id=None,
        issue_arc_id=issue_arc_id,
        comic_id=context.comic_id,
        nzb_name=context.nzb_name,
        nzb_folder=context.nzb_folder,
        api_call=context.api_call,
        ddl=context.ddl,
        canonical_release_key=key,
        log_module=context.log_module,
    )


def _claim_arc_copies(run, ml, library_file):
    """Record each arc copy as owed before the library issue completes.

    The claim carries what recovery needs to make the copy from the library
    file, so a restart after the library placement finishes the copy without
    placing the issue again.
    """
    from comicarr.app.storyarcs import ArcMembership

    claims = []
    for row in _arc_memberships(ml):
        membership = ArcMembership.from_row(row)
        arc_context = _arc_context(run.context, membership.issue_arc_id)
        _JOURNAL.transition(
            arc_context,
            journal.POST_PROCESSING,
            issue_arc_id=membership.issue_arc_id,
            payload=_arc_payload(run, membership, library_file),
        )
        claims.append((membership, arc_context))
    return claims


def finish_arc_copy(context, membership, library_file, *, config=None, place=None, destination=None, log=logger):
    """Make (or, after ``moved``, just record) one arc copy and complete it.

    ``destination`` is given when recovery finds the copy already made. Raises
    ``ArcCopyError`` when the copy fails; the arc row is then left owed.
    """
    from comicarr.app.downloads._postprocess_completion import complete
    from comicarr.app.storyarcs import copy_issue_to_arc

    payload = None
    if destination is None:
        result = copy_issue_to_arc(library_file, membership, config=config, place=place)
        destination = result.destination
        if result.operation is not None:
            payload = {
                "mode": "story_arc",
                "arc_copy": True,
                "issueid": membership.issue_arc_id,
                "issuearcid": membership.issue_arc_id,
                "library_file": library_file,
                "arc_destination": destination,
            }
            _JOURNAL.transition(context, journal.MOVED, issue_arc_id=membership.issue_arc_id, payload=payload)
    completion = complete(
        context,
        issue_arc_id=membership.issue_arc_id,
        anchor_ids=("S" + str(membership.issue_arc_id),),
        arc_scope=membership.story_arc,
        database=db,
    )
    ctrl = {"IssueArcID": membership.issue_arc_id}
    values = {"Status": "Downloaded", "Location": destination}
    log.fdebug("writing: %s -- %s" % (values, ctrl))
    db.upsert("storyarcs", values, ctrl)
    log.fdebug("%s [%s] Post-Processing completed for: %s" % (context.log_module, membership.story_arc, destination))
    return completion


def recover_arc_copy(release_key, row, payload, *, config=None):
    """Finish an owed arc copy from the journal row alone.

    The library issue is already placed, so this never touches the download:
    at ``post_processing`` it makes the copy from ``library_file``, at
    ``moved`` it only records the copy ``arc_destination`` names.
    """
    from comicarr.app.storyarcs import ArcMembership

    payload = payload or {}
    issue_arc_id = payload.get("issuearcid") or row.get("issueid")
    membership = ArcMembership(
        story_arc=payload.get("story_arc"),
        story_arc_id=payload.get("story_arc_id"),
        issue_arc_id=issue_arc_id,
        reading_order=payload.get("reading_order"),
        publisher=payload.get("publisher"),
    )
    if membership.story_arc is None:
        arc_row = db.select_one(select(storyarcs).where(storyarcs.c.IssueArcID == str(issue_arc_id)))
        if arc_row is not None:
            membership = ArcMembership.from_row(arc_row)
    context = PostProcessContext(
        issue_id=None,
        issue_arc_id=issue_arc_id,
        comic_id=payload.get("comicid"),
        nzb_name=payload.get("nzb_name") or "",
        nzb_folder=payload.get("nzb_folder") or "",
        api_call=False,
        ddl=False,
        canonical_release_key=release_key,
        log_module="[POST-PROCESSING][RECOVERY]",
    )
    destination = payload.get("arc_destination") if row.get("stage") == journal.MOVED else None
    return finish_arc_copy(context, membership, payload.get("library_file"), config=config, destination=destination)


def _copy_to_arcs(run, deps, ml, claims, dst):
    """The legacy arc branch, now through ``copy_issue_to_arc``.

    Returns a result when the item must end here, else None. A folder that
    cannot be made stops the item; a failed copy returns without signalling
    the queue, as it always has.
    """
    import comicarr
    from comicarr.app.storyarcs import ArcCopyError, ArcFolderError

    module = run.module
    try:
        logger.info("Watchlist Story Arc match detected.")
        logger.info(ml)
        for membership, arc_context in claims:
            if comicarr.CONFIG.COPY2ARCDIR is True:
                logger.info(
                    "%s[%s] %s into the arc folder for %s"
                    % (module, comicarr.CONFIG.ARC_FILEOPS.upper(), dst, membership.story_arc)
                )
            try:
                finish_arc_copy(arc_context, membership, dst, place=deps.place)
            except ArcFolderError as e:
                logger.warn(
                    "%s Error trying to validate/create directory. Aborting this process at this time." % module
                )
                logger.fdebug("%s %s" % (module, e))
                return run.finish("stop")
            except ArcCopyError as e:
                run.log_placement_failure(
                    comicarr.CONFIG.ARC_FILEOPS, dst, "the %s arc folder" % membership.story_arc, e
                )
                return run.abort()
            logger.fdebug("%s IssueArcID: %s" % (module, ml["IssueArcID"]))
    except Exception as e:
        logger.error("error encountered: %s" % e)
    return None


def process_comic_issue(match: PostProcessComicMatch, run: PostProcessRun, deps: PostProcessItemDeps):
    """Post-process one file matched to a library issue or annual.

    Runs the stages in their legacy order: journal claim, tagging, placement
    (``moved``), cleanup, completion, reconciliation, the owed arc copies,
    weekly/extra-script hooks and the notification. A restart re-enters
    through the journal: see the post-processing migration map.
    """
    import comicarr

    comicid = match.comic_id
    issueid = match.issue_id
    issuenumOG = match.issue_number
    ml = match.manual
    stat = match.position if match.position is not None else " [1/1]"
    module = run.module
    config = comicarr.CONFIG

    annchk = "no"
    comicnzb = db.select_one(select(comics).where(comics.c.ComicID == comicid))
    issuenzb = db.select_one(
        select(issues).where(
            and_(issues.c.IssueID == issueid, issues.c.ComicID == comicid, issues.c.ComicName.isnot(None))
        )
    )
    if ml is not None and config.SNATCHEDTORRENT_NOTIFY:
        snatchnzb = db.select_one(
            select(snatched).where(
                and_(
                    snatched.c.IssueID == issueid,
                    snatched.c.ComicID == comicid,
                    or_(
                        snatched.c.Provider == "TPSE",
                        snatched.c.Provider == "DEM",
                        snatched.c.Provider == "WWT",
                        snatched.c.Provider == "32P",
                    ),
                    snatched.c.Status == "Snatched",
                )
            )
        )
        if snatchnzb is None:
            logger.fdebug("%s Was not snatched as a torrent. Using manual post-processing." % module)
        else:
            logger.fdebug(
                "%s Was downloaded from %s. Enabling torrent manual post-processing completion notification."
                % (module, snatchnzb["Provider"])
            )
    if issuenzb is None:
        issuenzb = db.select_one(
            select(annuals).where(
                and_(annuals.c.IssueID == issueid, annuals.c.ComicID == comicid, annuals.c.Deleted != 1)
            )
        )
        annchk = "yes"
    display_name = issuenzb["ComicName"] if annchk == "no" else issuenzb["ReleaseComicName"]
    logger.info(
        "%s %s Starting Post-Processing for %s issue: %s" % (module, stat, display_name, issuenzb["Issue_Number"])
    )
    logger.fdebug("%s issueid: %s" % (module, issueid))
    logger.fdebug("%s issuenumOG: %s" % (module, issuenumOG))
    issuenum, issue_except = _split_issue_suffix(issuenzb["Issue_Number"])

    prettycomiss, _issueno = _pretty_issue_number(run, issuenum, issue_except)
    if prettycomiss is False:
        return run.abort()

    if annchk == "yes":
        run.narrate("Annual detected.")
    logger.fdebug("%s Pretty Comic Issue is : %s" % (module, prettycomiss))
    issueyear = issuenzb["IssueDate"][:4]
    run.narrate("Issue Year: %s" % issueyear)
    logger.fdebug("%s Issue Year : %s" % (module, issueyear))
    month = issuenzb["IssueDate"][5:7].replace("-", "").strip()
    month_name = helpers.fullmonth(month)
    if month_name is None:
        month_name = "None"
    publisher = comicnzb["ComicPublisher"]
    run.narrate("Publisher: %s" % publisher)
    logger.fdebug("%s Publisher: %s" % (module, publisher))
    agerating = comicnzb["AgeRating"]
    series = comicnzb["ComicName"]
    if annchk == "yes":
        series = issuenzb["ReleaseComicName"]
    run.narrate("Series: %s" % series)
    logger.fdebug("%s Series: %s" % (module, series))
    if comicnzb["AlternateFileName"] is None or comicnzb["AlternateFileName"] == "None":
        seriesfilename = series
    else:
        seriesfilename = comicnzb["AlternateFileName"]
        logger.fdebug(
            "%s Alternate File Naming has been enabled for this series. Will rename series to : %s"
            % (module, seriesfilename)
        )
    seriesyear = comicnzb["ComicYear"]
    run.narrate("Year: %s" % seriesyear)
    logger.fdebug("%s Year: %s" % (module, seriesyear))
    comlocation = comicnzb["ComicLocation"]
    run.narrate("Comic Location: %s" % comlocation)
    logger.fdebug("%s Comic Location: %s" % (module, comlocation))
    comversion = comicnzb["ComicVersion"]
    run.narrate("Comic Version: %s" % comversion)
    logger.fdebug("%s Comic Version: %s" % (module, comversion))
    if comversion is None:
        comversion = "None"
    if comversion == "None":
        chunk_f_f = re.sub(r"\$VolumeN", "", config.FILE_FORMAT)
        chunk_file_format = re.compile(r"\s+").sub(" ", chunk_f_f)
        run.narrate("No version # found for series - tag will not be available for renaming.")
        logger.fdebug("%s No version # found for series, removing from filename" % module)
        logger.fdebug("%s New format is now: %s" % (module, chunk_file_format))
    else:
        chunk_file_format = config.FILE_FORMAT

    if annchk == "no":
        chunk_f_f = re.sub(r"\$Annual", "", chunk_file_format)
        chunk_file_format = re.compile(r"\s+").sub(" ", chunk_f_f)
        logger.fdebug("%s Not an annual - removing from filename parameters" % module)
        logger.fdebug("%s New format: %s" % (module, chunk_file_format))
    else:
        logger.fdebug("%s Chunk_file_format is: %s" % (module, chunk_file_format))
        if "$Annual" not in chunk_file_format:
            prettycomiss = "Annual %s" % prettycomiss
            logger.fdebug("%s prettycomiss: %s" % (module, prettycomiss))

    ofilename = None
    odir = None
    ext = None

    if ml is None:
        found_root = False
        for root, _dirnames, filenames in safe_walk(run.nzb_folder):
            for filename in filenames:
                if filename.lower().endswith(run.extensions):
                    odir = root
                    found_root = True
                    logger.fdebug("%s odir (root): %s" % (module, odir))
                    ofilename = filename
                    logger.fdebug("%s ofilename: %s" % (module, ofilename))
                    _path, ext = os.path.splitext(ofilename)
        if not found_root:
            # The legacy body read an unbound ``odir`` here and recovered in
            # its exception handler; this is that recovery.
            logger.error(
                "%s unable to set root folder. Forcing it due to some error above most likely: no file found in %s"
                % (module, run.nzb_folder)
            )
            if os.path.isfile(run.nzb_folder) and run.nzb_folder.lower().endswith(run.extensions):
                import ntpath

                odir, ofilename = ntpath.split(run.nzb_folder)
                _path, ext = os.path.splitext(ofilename)
            else:
                odir = run.nzb_folder
        elif odir is None:
            logger.fdebug("%s No root folder set." % module)
            odir = run.nzb_folder

        if ofilename is None:
            run.narrate("Unable to locate a valid cbr/cbz file. Aborting post-processing for this filename.")
            logger.error(
                "%s unable to locate a valid cbr/cbz file. Aborting post-processing for this filename." % module
            )
            run.failed_files += 1
            return run.finish("stop")
        logger.fdebug("%s odir: %s" % (module, odir))
        logger.fdebug("%s ofilename: %s" % (module, ofilename))

    pcheck = "fail"

    if ml is None:
        subpath = odir
        orig_filename = ofilename
        crcvalue = helpers.crc(os.path.join(odir, ofilename))
    else:
        subpath, orig_filename = os.path.split(ml["ComicLocation"])
        crcvalue = helpers.crc(ml["ComicLocation"])

    if config.ENABLE_PRE_SCRIPTS:
        seriesmetadata = {
            "name": series,
            "comicyear": seriesyear,
            "comicid": comicid,
            "issueid": issueid,
            "issueyear": issueyear,
            "issue": issuenum,
            "publisher": publisher,
        }
        run_script("pre", run, run.nzb_name, run.nzb_folder, orig_filename, subpath, seriesmetadata)

    if any([config.ENABLE_META, config.CBR2CBZ_ONLY]):
        run.narrate("Metatagging enabled - proceeding...")
        logger.fdebug("%s Metatagging enabled - proceeding..." % module)
        pcheck = "pass"
        vol_label = seriesyear if config.CMTAG_START_YEAR_AS_VOLUME else comversion

        pre_cmtag_info = None
        try:
            from comicarr.app.ai.enrichment import _read_comicinfo

            if ml is None:
                pre_cmtag_info = _read_comicinfo(os.path.join(odir, ofilename))
            else:
                pre_cmtag_info = _read_comicinfo(ml["ComicLocation"])
        except Exception as e:
            logger.fdebug("[POST-PROCESS] Could not read pre-cmtag ComicInfo.xml: %s" % e)

        try:
            order_the_read = db.select_all(
                select(storyarcs.c.StoryArc, storyarcs.c.ReadingOrder).where(
                    and_(storyarcs.c.IssueID == issueid, storyarcs.c.ComicID == comicid)
                )
            )
            readingorder = None
            if order_the_read is not None:
                readingorder = [(rd["StoryArc"], rd["ReadingOrder"]) for rd in order_the_read]
            logger.fdebug("readingorder: %s" % (readingorder))

            if ml is None:
                pcheck = deps.tag_file(
                    run.nzb_folder,
                    issueid=issueid,
                    comversion=vol_label,
                    filename=os.path.join(odir, ofilename),
                    readingorder=readingorder,
                    agerating=agerating,
                )
            else:
                pcheck = deps.tag_file(
                    run.nzb_folder,
                    issueid=issueid,
                    comversion=vol_label,
                    manual="yes",
                    filename=ml["ComicLocation"],
                    readingorder=readingorder,
                    agerating=agerating,
                )
        except ImportError:
            logger.fdebug(
                "%s comictaggerlib not found on system. Ensure the bundled vendor package is available at comicarr/_vendor/comictaggerlib/"
                % module
            )
            logger.fdebug("%s continuing with PostProcessing, but I am not using metadata." % module)
            pcheck = "fail"

        if pcheck == "fail":
            run.narrate(
                "Unable to write metadata successfully - check comicarr.log file. Attempting to continue without tagging..."
            )
            logger.fdebug(
                "%s Unable to write metadata successfully - check comicarr.log file. Attempting to continue without tagging..."
                % module
            )
            run.failed_files += 1
        elif any([pcheck == "unrar error", pcheck == "corrupt"]):
            if ml is not None:
                run.narrate(
                    "This is a corrupt archive - whether CRC errors or it's incomplete. Marking as BAD, and not post-processing."
                )
                logger.error(
                    "%s This is a corrupt archive - whether CRC errors or it is incomplete. Marking as BAD, and not post-processing."
                    % module
                )
                run.failed_files += 1
                return run.finish("stop")
            run.narrate(
                "This is a corrupt archive - whether CRC errors or it's incomplete. Marking as BAD, and retrying a different copy."
            )
            logger.error(
                "%s This is a corrupt archive - whether CRC errors or it is incomplete. Marking as BAD, and retrying a different copy."
                % module
            )
            return run.finish(
                "fail",
                issueid=issueid,
                comicid=comicid,
                comicname=comicnzb["ComicName"],
                issuenumber=issuenzb["Issue_Number"],
                annchk=annchk,
            )
        elif pcheck.startswith("file not found"):
            filename_in_error = pcheck.split("||")[1]
            run.narrate(
                "The file cannot be found in the location provided [%s]. Please verify it exists, and re-run if necessary. Aborting."
                % filename_in_error
            )
            logger.error(
                "%s The file cannot be found in the location provided [%s]. Please verify it exists, and re-run if necessary. Aborting"
                % (module, filename_in_error)
            )
            run.failed_files += 1
            return run.finish("stop")
        else:
            odir = os.path.split(pcheck)[0]
            ofilename = os.path.split(pcheck)[1]
            ext = os.path.splitext(ofilename)[1]
            run.narrate("Sucessfully wrote metadata to .cbz - Continuing..")
            logger.info("%s Sucessfully wrote metadata to .cbz (%s) - Continuing.." % (module, ofilename))
            _enrich(pcheck, issueid, pre_cmtag_info)

    file_values = {
        "$Series": seriesfilename,
        "$Issue": prettycomiss,
        "$Year": issueyear,
        "$series": series.lower(),
        "$Publisher": publisher,
        "$publisher": publisher.lower(),
        "$VolumeY": "V" + str(seriesyear),
        "$VolumeN": comversion,
        "$monthname": month_name,
        "$month": month,
        "$Annual": "Annual",
    }

    if ml:
        if pcheck == "fail":
            odir, ofilename = os.path.split(ml["ComicLocation"])
            orig_filename = ofilename
        elif pcheck:
            pass
        else:
            odir, orig_filename = os.path.split(ml["ComicLocation"])
        logger.fdebug("%s ofilename: %s" % (module, ofilename))
        if any([ofilename == odir, ofilename == odir[:-1], ofilename == ""]):
            run.narrate(
                "There was a problem deciphering the filename/directory - please verify that the filename : [%s] exists in location [%s]. Aborting."
                % (ofilename, odir)
            )
            logger.error(
                module
                + " There was a problem deciphering the filename/directory - please verify that the filename : [%s] exists in location [%s]. Aborting."
                % (ofilename, odir)
            )
            run.failed_files += 1
            return run.finish("stop")
        logger.fdebug("%s odir: %s" % (module, odir))
        logger.fdebug("%s ofilename: %s" % (module, ofilename))
        ext = os.path.splitext(ofilename)[1]
        logger.fdebug("%s ext: %s" % (module, ext))

    if ofilename is None or ofilename == "":
        logger.error(
            "%s Aborting PostProcessing - the filename does not exist in the location given. Make sure that %s exists and is the correct location."
            % (module, run.nzb_folder)
        )
        run.failed_files += 1
        return run.finish("stop")

    run.narrate("Original Filename: %s [%s]" % (orig_filename, ext))
    logger.fdebug("%s Original Filename: %s [%s]" % (module, orig_filename, ext))

    if config.FILE_FORMAT == "" or not config.RENAME_FILES:
        run.narrate("Rename Files isn't enabled...keeping original filename.")
        logger.fdebug("%s Rename Files is not enabled - keeping original filename." % module)
        if ofilename.lower().endswith(run.extensions):
            nfilename = ofilename[:-4]
        else:
            nfilename = ofilename
    else:
        nfilename = helpers.replace_all(chunk_file_format, file_values)
        if config.REPLACE_SPACES:
            nfilename = nfilename.replace(" ", config.REPLACE_CHAR)
    nfilename = re.sub("[\\,\\:\\?\"']", "", nfilename)
    nfilename = re.sub(r"[\/\*]", "-", nfilename)
    if ml is not None and ml["ForcedMatch"] is True:
        nfilename = _strip_forced_issueid(nfilename)

    run.narrate("New Filename: %s" % nfilename)
    logger.fdebug("%s New Filename: %s" % (module, nfilename))

    src = os.path.join(odir, ofilename)
    if not deps.validate_directory(comlocation, True, module=module):
        logger.warn("%s Error trying to validate/create directory. Aborting this process at this time." % module)
        run.failed_files += 1
        return run.finish("stop")

    if config.LOWERCASE_FILENAMES:
        dst = os.path.join(comlocation, (nfilename + ext).lower())
    else:
        dst = os.path.join(comlocation, (nfilename + ext.lower()))
    run.narrate("Source: %s" % src)
    run.narrate("Destination: %s" % dst)
    logger.fdebug("%s Source: %s" % (module, src))
    logger.fdebug("%s Destination: %s" % (module, dst))

    run.journal(journal.POST_PROCESSING, issue_id=issueid)

    if ml is None:
        downtype = "True"
        logger.fdebug("%s self.nzb_folder: %s" % (module, run.nzb_folder))
        logger.fdebug("%s odir: %s" % (module, odir))
        logger.fdebug("%s ofilename: %s" % (module, ofilename))
        logger.fdebug("%s nfilename: %s" % (module, nfilename + ext))
        _log_rename(module, config, odir, ofilename, nfilename + ext, os.path.join(odir, nfilename + ext))
        try:
            run.narrate("[%s] %s - to - %s" % (config.FILE_OPTS, src, dst))
            if helpers.get_free_space(comlocation) is False:
                if all([pcheck is not None, pcheck != "fail"]):
                    run.tidy(odir, True, cacheonly=True)
                raise OSError
            deps.place(src, dst, Purpose.SERIES, on_existing=OnExisting.UNGUARDED)
        except Exception as e:
            run.narrate("Failed to %s %s - check log for exact error." % (config.FILE_OPTS, src))
            run.narrate("Post-Processing ABORTED.")
            run.log_placement_failure(config.FILE_OPTS, src, dst, e)
            logger.error("%s Post-Processing ABORTED" % module)
            return run.finish("stop")

        run.journal(journal.MOVED, issue_id=issueid)

        if any([config.FILE_OPTS == "move", config.FILE_OPTS == "copy"]):
            run.tidy(odir, True, filename=os.path.basename(orig_filename))
    else:
        downtype = "PP"
        _log_rename(
            module,
            config,
            odir,
            ofilename,
            nfilename + ext,
            os.path.join(odir, run.nzb_folder, str(nfilename + ext)),
        )
        logger.fdebug("%s odir src : %s" % (module, src))
        logger.fdebug("%s[%s] %s ... to ... %s" % (module, config.FILE_OPTS, src, dst))
        try:
            if helpers.get_free_space(comlocation) is False:
                if all([pcheck != "fail", pcheck is not None]):
                    run.tidy(odir, True, cacheonly=True)
                raise OSError
            deps.place(src, dst, Purpose.SERIES, on_existing=OnExisting.UNGUARDED)
        except Exception as e:
            run.log_placement_failure(config.FILE_OPTS, src, dst, e)
            logger.error("%s Post-Processing ABORTED." % module)
            run.failed_files += 1
            return run.finish("stop")
        logger.info("%s %s successful to : %s" % (module, config.FILE_OPTS, dst))

        run.journal(journal.MOVED, issue_id=issueid)

        if any([config.FILE_OPTS == "move", config.FILE_OPTS == "copy"]):
            run.tidy(odir, True, subpath, filename=os.path.basename(orig_filename))

    _enforce_permissions(module, config, deps, dst)

    arc_claims = []
    if _names_an_arc(ml):
        try:
            arc_claims = _claim_arc_copies(run, ml, dst)
        except Exception as e:
            logger.error("error encountered: %s" % e)

    from comicarr.app.downloads._postprocess_completion import complete

    completion = complete(run.context, issue_id=issueid, anchor_ids=(issueid,), database=db)

    PostProcessReconcileStage(totals=deps.totals, foundsearch=deps.foundsearch).reconcile(
        PostProcessPlacedItem(
            comic_id=comicid,
            issue_id=issueid,
            kind=ISSUE if annchk == "no" else ANNUAL,
            placed_path=dst,
            download_type=downtype,
            crc=crcvalue,
            log_module=module,
        )
    )

    dispiss = "#%s" % issuenumOG
    if annchk != "no" and any(word in issuenzb["ReleaseComicName"].lower() for word in ("annual", "special")):
        series = issuenzb["ReleaseComicName"]
    logger.fdebug("[%s][annchk:%s] issue to update: %s" % (series, annchk, dispiss))

    if arc_claims:
        ended = _copy_to_arcs(run, deps, ml, arc_claims, dst)
        if ended is not None:
            return ended

    if config.WEEKFOLDER or config.SEND2READ:
        deps.weekly_check(comicid, issuenum, file=(nfilename + ext), path=dst, module=module, issueid=issueid)

    if config.ENABLE_EXTRA_SCRIPTS:
        seriesmetadata = {
            "seriesmeta": [
                {
                    "name": series,
                    "comicyear": seriesyear,
                    "comicid": comicid,
                    "issueid": issueid,
                    "issueyear": issueyear,
                    "issue": issuenum,
                    "publisher": publisher,
                }
            ]
        }
        run_script("extra", run, run.nzb_name, run.nzb_folder, nfilename + ext, dst, seriesmetadata)

    _notify(
        run,
        deps,
        completion,
        series=series,
        issue_year=issueyear,
        issue_number=dispiss,
        placed_path=dst,
        issue_id=issueid,
    )

    logger.info("%s Post-Processing completed for: %s %s" % (module, series, dispiss))
    run.narrate("Post Processing SUCCESSFUL! ")

    run.journal(journal.POST_PROCESSED, issue_id=issueid)

    run.finish("stop", COMPLETED, issueid=issueid, comicid=comicid)
    return PostProcessItemResult(COMPLETED, True, issue_id=issueid, placed_path=dst)


def _enrich(pcheck, issueid, pre_cmtag_info):
    try:
        from comicarr.app.ai.enrichment import enrich_metadata

        enriched_count = enrich_metadata(cbz_path=pcheck, issue_id=issueid)
        if enriched_count > 0:
            logger.fdebug("[POST-PROCESS] AI enriched %d metadata fields" % enriched_count)
    except Exception as e:
        logger.error("[POST-PROCESS] AI enrichment error: %s" % e)

    try:
        from comicarr.app.ai.enrichment import _read_comicinfo
        from comicarr.app.ai.reconciliation import reconcile_metadata

        post_cmtag_info = _read_comicinfo(pcheck)
        reconciled_count = reconcile_metadata(
            cbz_path=pcheck,
            issue_id=issueid,
            pre_cmtag_info=pre_cmtag_info,
            post_cmtag_info=post_cmtag_info,
        )
        if reconciled_count > 0:
            logger.fdebug("[POST-PROCESS] AI reconciled %d metadata fields" % reconciled_count)
    except Exception as e:
        logger.error("[POST-PROCESS] AI reconciliation error: %s" % e)


def _strip_forced_issueid(nfilename):
    xyb = nfilename.find("[__")
    if xyb != -1:
        yyb = nfilename.find("__]", xyb)
        if yyb != -1:
            rem_issueid = nfilename[xyb + 3 : yyb]
            logger.fdebug("issueid: %s" % rem_issueid)
            two_add = re.sub(r"\s+", "", nfilename[yyb + 3 :]).strip()
            if any([two_add == "", two_add == " "]):
                nfilename = "%s" % nfilename[:xyb].strip()
            else:
                nfilename = "%s %s" % (nfilename[:xyb].strip(), two_add)
            logger.fdebug("issueid information [%s] removed successfully: %s" % (rem_issueid, nfilename))
    return nfilename


def _log_rename(module, config, odir, ofilename, new_name, shown_target):
    if not config.RENAME_FILES:
        return
    if ofilename != new_name:
        logger.fdebug("%s Renaming %s ..to.. %s" % (module, os.path.join(odir, ofilename), shown_target))
    else:
        logger.fdebug("%s Filename is identical as original, not renaming." % module)


def _enforce_permissions(module, config, deps, dst):
    import comicarr

    if not config.ENFORCE_PERMS:
        return
    if comicarr.OS_DETECT != "windows":
        deps.set_permissions(dst.rstrip())
        return
    try:
        permission = int(config.CHMOD_FILE, 8)
        os.umask(0)
        os.chmod(dst.rstrip(), permission)
    except OSError:
        logger.error(
            "%s Failed to change file permissions. Ensure that the user running Comicarr has proper permissions to change permissions in : %s"
            % (module, dst)
        )
        logger.fdebug("%s Continuing post-processing but unable to change file permissions in %s" % (module, dst))


def match_manga_issue(comic_id, parsed):
    """Return the ledger row a parsed manga file belongs to, or None.

    A pure lookup over ``parsed`` and this series' issue rows: it reads the
    database and nothing else, so it can be answered before the file is
    placed. That ordering matters -- tagging needs the IssueID, and tagging
    has to happen while the file is still at its download location.

    Chapter first, then volume: a chapter number is the more specific claim,
    and a volume-numbered file has no chapter number to offer.
    """
    if parsed is None:
        return None

    matching = None

    if parsed.get("chapter_number") is not None:
        ch_num = parsed["chapter_number"]
        ch_str = "%g" % ch_num
        matching = db.select_one(
            select(issues).where(and_(issues.c.ComicID == comic_id, issues.c.ChapterNumber == ch_str))
        )
        if matching is None:
            matching = db.select_one(
                select(issues).where(and_(issues.c.ComicID == comic_id, issues.c.Issue_Number == ch_str))
            )
            if matching is None and ch_str != str(ch_num):
                matching = db.select_one(
                    select(issues).where(and_(issues.c.ComicID == comic_id, issues.c.Issue_Number == str(ch_num)))
                )

    if matching is None and parsed.get("volume_number") is not None:
        vol_str = str(parsed["volume_number"])
        matching = db.select_one(
            select(issues).where(and_(issues.c.ComicID == comic_id, issues.c.VolumeNumber == vol_str))
        )
        if matching is None:
            # The equality above is a string comparison between two sources
            # that write the same volume differently: the parser turns `v01`
            # into int 1, so it asks for '1', while MangaDex stores
            # str(chapter.volume) and can hold '01'. Compare through the ledger
            # rule, which already owns what a volume number means.
            for row in db.select_all(
                select(issues).where(and_(issues.c.ComicID == comic_id, issues.c.VolumeNumber.isnot(None)))
            ):
                wanted = normalize_volume_number(vol_str)
                if wanted is not None and normalize_volume_number(row.get("VolumeNumber")) == wanted:
                    matching = row
                    break

    return matching


def metatag_manga_file(run, deps, filepath, issueid):
    """Write metadata into a manga file before it is placed.

    Tagging can rename the file (a .cbr is rebuilt as a .cbz), so the caller
    places whatever this returns: the tagged file on success, the original
    path otherwise. Tagging is best effort; a metadata failure must not cost
    the import, exactly as it does not on the comic path.
    """
    import comicarr

    module = run.module

    # Same condition the comic path uses (ENABLE_META or CBR2CBZ_ONLY), read
    # defensively: a process without configuration loaded places the file
    # untagged rather than failing the import over it.
    config = comicarr.CONFIG
    if config is None:
        return filepath
    if not (getattr(config, "ENABLE_META", False) or getattr(config, "CBR2CBZ_ONLY", False)):
        return filepath

    try:
        pcheck = deps.tag_file(run.nzb_folder, issueid=issueid, filename=filepath)
    except ImportError:
        logger.fdebug(
            "%s comictaggerlib not found on system. Ensure the bundled vendor package is available at comicarr/_vendor/comictaggerlib/"
            % module
        )
        return filepath
    except Exception as e:
        logger.error("%s [MANGA] Metatagging raised for %s [%s]" % (module, filepath, e))
        return filepath

    # The tagger returns a path on success and a sentinel string otherwise
    # ("fail", "corrupt", "unrar error", "file not found||<path>"). Requiring
    # an existing file rather than enumerating the sentinels means a new
    # sentinel degrades to "not tagged" instead of placing a bogus path.
    if not isinstance(pcheck, str) or not os.path.isfile(pcheck):
        logger.warn(
            "%s [MANGA] Unable to write metadata to %s [%s] - placing it untagged."
            % (module, os.path.basename(filepath), pcheck)
        )
        return filepath

    if pcheck != filepath:
        logger.info(
            "%s [MANGA] Wrote metadata: %s -> %s" % (module, os.path.basename(filepath), os.path.basename(pcheck))
        )
    else:
        logger.info("%s [MANGA] Wrote metadata to %s" % (module, os.path.basename(pcheck)))
    return pcheck


def tidy_manga_folder(run, nzb_dir):
    """Remove a download folder that ``move`` has emptied.

    The ``move`` / ``Manual Run`` guards keep manga from asking cleanup to
    touch an operator-chosen folder, and cleanup still refuses to delete a
    directory that is not empty. The config is read through ``getattr``: this
    is the last thing a manga import does, and it must never turn a successful
    import into an exception.
    """
    import comicarr

    if getattr(comicarr.CONFIG, "FILE_OPTS", None) != "move" or run.nzb_name == "Manual Run":
        return
    run.tidy(nzb_dir, True)


def process_manga_download(run: PostProcessRun, deps: PostProcessItemDeps):
    """Post-process a downloaded manga release for ``run.context.comic_id``.

    Routes the files to the series folder under the manga destination,
    matches each to a chapter or volume through the manga filename parser,
    and marks the matched rows Downloaded.
    """
    import comicarr

    module = run.module
    comic_id = run.context.comic_id

    comicnzb = db.select_one(select(comics).where(comics.c.ComicID == comic_id))
    if not comicnzb:
        run.narrate("Cannot find manga series in database: %s" % comic_id)
        logger.error("%s Cannot find manga series: %s" % (module, comic_id))
        return run.finish("stop")

    series_name = comicnzb["ComicName"]
    logger.info("%s Processing manga download for: %s" % (module, series_name))

    nzb_dir = run.nzb_folder
    if not nzb_dir or not os.path.isdir(nzb_dir):
        if run.nzb_name and os.path.isdir(run.nzb_name):
            nzb_dir = run.nzb_name
        else:
            run.narrate("Download directory not found")
            logger.error("%s Download directory not found: %s" % (module, nzb_dir))
            return run.finish("stop")

    manga_files = []
    for root, _dirs, files in safe_walk(nzb_dir):
        for f in files:
            if any(f.lower().endswith(ext) for ext in run.extensions):
                manga_files.append(os.path.join(root, f))

    manga_files.sort()

    if not manga_files:
        run.narrate("No manga files found in download directory")
        logger.warn("%s No manga files in: %s" % (module, nzb_dir))
        return run.finish("stop")

    manga_dest = deps.manga_destination()
    if not manga_dest:
        run.narrate("No manga destination directory configured")
        logger.error("%s No manga destination configured" % module)
        return run.finish("stop")

    from comicarr.app.series.service import persist_manga_location_if_needed

    series_folder, _repointed = persist_manga_location_if_needed(comicnzb, manga_dest)
    if not series_folder:
        series_folder = comicnzb.get("ComicLocation") or os.path.join(manga_dest, helpers.filesafe(series_name))
    if comicnzb.get("ComicLocation") != series_folder:
        comicnzb = dict(comicnzb)
        comicnzb["ComicLocation"] = series_folder

    from comicarr.app.common.library_roots import is_strict_library_descendant
    from comicarr.app.series.location import is_location_override

    if is_location_override(comicnzb):
        if not is_strict_library_descendant(series_folder, comicarr.CONFIG):
            run.narrate("Chosen series folder is outside the allowed library roots — refusing to write")
            logger.error("%s Chosen series folder %s is outside the allowed library roots" % (module, series_folder))
            return run.finish("stop")
    elif not os.path.realpath(series_folder).startswith(os.path.realpath(manga_dest)):
        run.narrate("Series folder is outside manga destination — refusing to write")
        logger.error("%s Series folder %s is outside manga destination %s" % (module, series_folder, manga_dest))
        return run.finish("stop")

    if not os.path.isdir(series_folder):
        try:
            os.makedirs(series_folder, exist_ok=True)
            logger.fdebug("%s Created manga series directory: %s" % (module, series_folder))
        except OSError as e:
            logger.warn("%s Failed to create directory %s: %s" % (module, series_folder, e))
            run.narrate("Failed to create manga series directory")
            return run.finish("stop")

    run.journal(journal.POST_PROCESSING)

    processed = 0
    last_matched_issueid = None
    matched_issueids = []
    from comicarr.app.manga.parse import parse_in_series_context

    sibling_names = [os.path.basename(path) for path in manga_files]
    series_issues = db.select_all(select(issues).where(issues.c.ComicID == comic_id))
    reconcile = PostProcessReconcileStage(totals=deps.totals, foundsearch=deps.foundsearch)
    for filepath in manga_files:
        filename = os.path.basename(filepath)
        parsed = parse_in_series_context(
            filename,
            series=comicnzb,
            filenames=sibling_names,
            series_name=series_name,
            issues=series_issues,
        )
        run.narrate("Found manga file: %s" % filename)

        if not os.path.realpath(filepath).startswith(os.path.realpath(nzb_dir)):
            logger.warning("%s Skipping file outside download directory: %s" % (module, filepath))
            continue

        # Resolve the ledger row first: the tagger needs the IssueID, and
        # tagging happens here, at the download location, because it can
        # rename the file -- so the name that gets placed is the tagged one.
        matching = match_manga_issue(comic_id, parsed)

        # Kept so the download original can be tidied after placement: the
        # tagger copies into CACHE_DIR and returns the CACHE path, so what
        # placement consumes is the copy, not the download.
        pre_tag_path = filepath

        if matching is not None:
            # Best effort: a row without an IssueID cannot be tagged, but it
            # can still be placed and marked, so this must not raise.
            try:
                tag_issueid = matching["IssueID"]
            except (KeyError, TypeError, IndexError):
                tag_issueid = None
            if tag_issueid is not None:
                filepath = metatag_manga_file(run, deps, filepath, tag_issueid)
                filename = os.path.basename(filepath)

        dst = os.path.join(series_folder, filename)

        try:
            placement = deps.place(filepath, dst, Purpose.SERIES, on_existing=OnExisting.DISPLACE)
        except Exception as e:
            run.log_placement_failure("place", filepath, dst, e)
            run.narrate("Failed to move/copy manga file: %s" % filename)
            continue

        if placement.outcome is Outcome.ALREADY_PLACED:
            logger.fdebug("%s Manga file already placed, skipping placement: %s" % (module, filename))
        else:
            logger.info("%s Placed manga file: %s -> %s" % (module, filename, series_folder))

        # Under FILE_OPTS = move, placement consumed the TAGGED copy out of the
        # cache, so the download original is still there and the next pass
        # picks it up again. Remove it per file rather than through cleanup,
        # which works on the whole folder and would take files this run has
        # not placed yet. Skipped when tagging produced no new path, and when
        # the series folder is the download folder and tagging kept the name:
        # the file at pre_tag_path is then the one just placed. realpath rather
        # than samefile, because dst need not exist here.
        if (
            filepath != pre_tag_path
            and getattr(comicarr.CONFIG, "FILE_OPTS", None) == "move"
            and os.path.realpath(pre_tag_path) != os.path.realpath(dst)
            and os.path.isfile(pre_tag_path)
        ):
            try:
                os.remove(pre_tag_path)
                logger.fdebug("%s Removed the pre-tag download original: %s" % (module, pre_tag_path))
            except OSError as e:
                logger.warn(
                    "%s Unable to remove the pre-tag download original %s [%s] -- it will be re-processed"
                    % (module, pre_tag_path, e)
                )

        run.journal(journal.POST_PROCESSING)

        if matching:
            issueid = matching["IssueID"]
            reconcile.reconcile(
                PostProcessPlacedItem(
                    comic_id=comic_id,
                    issue_id=issueid,
                    kind=MANGA,
                    placed_path=dst,
                    log_module=module,
                )
            )
            logger.info("%s Matched and marked downloaded: %s (IssueID: %s)" % (module, filename, issueid))
            run.narrate("Matched to chapter IssueID: %s" % issueid)

            matched_issueids.append(issueid)

            last_matched_issueid = issueid
            processed += 1
        else:
            logger.warn("%s Unable to match %s to any chapter for %s" % (module, filename, series_name))

    if processed > 0:
        reconcile.recount_series(comic_id)

    if processed > 0:
        run.narrate("Post Processing SUCCESSFUL! %d file(s) processed" % processed)
    else:
        run.narrate("Manga post-processing complete: 0 files matched to chapters")
    logger.info("%s Manga post-processing complete for %s: %d files" % (module, series_name, processed))

    if processed > 0:
        from comicarr.app.downloads._postprocess_completion import complete

        run.journal(journal.MOVED, issue_id=last_matched_issueid)
        complete(run.context, issue_id=last_matched_issueid, anchor_ids=tuple(matched_issueids), database=db)
        tidy_manga_folder(run, nzb_dir)

    extra = {"comicid": comic_id}
    if last_matched_issueid:
        extra["issueid"] = last_matched_issueid
    run.finish("stop", COMPLETED if processed > 0 else STOPPED, **extra)
    return PostProcessItemResult(
        COMPLETED if processed > 0 else STOPPED, True, issue_id=last_matched_issueid, placed_path=None
    )


# ---------------------------------------------------------------------------
# A whole post-processing request: resolve the folder, match it, process it.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PostProcessRequest:
    """One post-processing request, as a downloader or a folder scan makes it.

    ``nzb_name`` is ``"Manual Run"`` for a folder scan. ``journal_release_key``
    is the journal row the caller claimed, so every marker advances it.
    """

    nzb_name: str
    nzb_folder: str
    issue_id: str | None = None
    comic_id: str | None = None
    api_call: bool = False
    ddl: bool = False
    module: str | None = None
    journal_release_key: str | None = None


_INPUT = PostProcessInputStage()


def _rename(src, dst):
    return pathlib.Path(src).replace(dst)


def process_download(request: PostProcessRequest, *, match: Callable, deps: PostProcessItemDeps):
    """Run one request; return the messages it posted, or None for none.

    ``match`` is the folder matcher (``comicarr.postprocessor.match_folder``),
    passed in by the facade like the other legacy collaborators.
    """
    import comicarr

    config = comicarr.CONFIG
    module = request.module + "[POST-PROCESSING]" if request.module is not None else "[POST-PROCESSING]"
    extensions = tuple(x for x in DEFAULT_EXTENSIONS if x not in config.IGNORE_SEARCH_WORDS)
    api_call = request.api_call is True
    ddl = request.ddl is True

    def new_run(nzb_folder, issue_id, issue_arc_id, comic_id, log):
        return PostProcessRun(
            context=PostProcessContext(
                issue_id=issue_id,
                issue_arc_id=issue_arc_id,
                comic_id=comic_id,
                nzb_name=request.nzb_name,
                nzb_folder=nzb_folder,
                api_call=api_call,
                ddl=ddl,
                canonical_release_key=request.journal_release_key,
                log_module=module,
            ),
            nzb_name=request.nzb_name,
            nzb_folder=nzb_folder,
            module=module,
            extensions=extensions,
            log=log,
        )

    log = "nzb name: %s\nnzb folder: %s\n" % (request.nzb_name, request.nzb_folder)
    logger.fdebug("%s nzb name: %s" % (module, request.nzb_name))
    logger.fdebug("%s nzb folder: %s" % (module, request.nzb_folder))
    use_sabnzbd = comicarr.USE_SABNZBD == 1
    use_nzbget = comicarr.USE_NZBGET == 1
    input_result = _INPUT.resolve(
        PostProcessInputContext(
            nzb_name=request.nzb_name,
            nzb_folder=request.nzb_folder,
            module=module,
            ddl=ddl,
            use_sabnzbd=use_sabnzbd,
            use_nzbget=use_nzbget,
            sab_direct_unpack=(config.SAB_DIRECT_UNPACK if use_sabnzbd else False),
            sab_directory=(config.SAB_DIRECTORY if use_sabnzbd else None),
            nzbget_directory=(config.NZBGET_DIRECTORY if use_nzbget else None),
            nzbget_category=(config.NZBGET_CATEGORY if use_nzbget else None),
        )
    )
    nzb_folder = input_result.folder
    if input_result.error is not None:
        run = new_run(nzb_folder, request.issue_id, None, request.comic_id, log)
        run.finish("stop")
        return run.messages

    if request.comic_id is not None:
        series = db.select_one(
            select(comics.c.ComicID, comics.c.ContentType, comics.c.ContentKindSetBy).where(
                comics.c.ComicID == request.comic_id
            )
        )
        if series_kind.is_manga(series if series is not None else request.comic_id):
            logger.fdebug(
                "%s Manga series detected (ComicID: %s) - branching to manga post-processing"
                % (module, request.comic_id)
            )
            run = new_run(nzb_folder, request.issue_id, None, request.comic_id, log)
            run.narrate("Manga series detected - using manga post-processing path")
            process_manga_download(run, deps)
            return run.messages or None

    matches = match(
        request.nzb_name,
        nzb_folder,
        issueid=request.issue_id,
        comicid=request.comic_id,
        apicall=api_call,
        module=module,
        extensions=extensions,
        log=log,
        refresh_series=deps.refresh_series,
        rename=_rename,
    )
    run = new_run(matches.nzb_folder, matches.issue_id, matches.issue_arc_id, matches.comic_id, matches.log)
    process_folder_matches(run, deps, matches)
    return run.messages or None


def process_folder_matches(run: PostProcessRun, deps: PostProcessItemDeps, matches):
    """Place what a folder scan matched, in the order the legacy rules did.

    Arc-only files go first, then the snatch lookup the matcher handed back
    runs. A scan the rules ended stops there; otherwise each snatched
    download is processed, then the library matches.
    """
    library = [m.values for m in matches.library]
    arc_only = [m.values for m in matches.arc_only]
    if matches.exit is None:
        if place_arc_only_matches(run, deps, arc_only) is not None:
            return
        if matches.find_snatched is not None:
            matches = matches.find_snatched(run.log)
            run.log = matches.log
    if matches.exit == "abort":
        return
    if matches.exit is not None:
        run.finish(matches.exit)
        return
    for pp in matches.snatched:
        logger.info("[PPINFO-POST-PROCESSING-ATTEMPT] %s" % pp)
        process_snatched_match(run, deps, tinfo=pp)
    dispatch_library_matches(run, deps, library, arc_only)


def _process_library_issue(run, deps, comicid, issueid, issuenumOG, ml=None, stat=None):
    match = PostProcessComicMatch(comicid, issueid, issuenumOG, manual=ml, position=stat)
    return process_comic_issue(match, run, deps)


def mark_pull_row_downloaded(issueid):
    """Mark a one-off's existing pull-list row as Downloaded.

    An update rather than an upsert: weekly's upsert target is (ComicID,
    IssueID), and a one-off only knows its IssueID.
    """
    with db.get_engine().begin() as conn:
        conn.execute(update(weekly).where(weekly.c.IssueID == issueid).values(STATUS="Downloaded"))


def place_arc_only_matches(run: PostProcessRun, deps: PostProcessItemDeps, manual_arclist):
    """Place files that belong to a watched arc and no watched series.

    Returns None to go on, or how the request ended.
    """
    import comicarr
    from comicarr.app.downloads._postprocess_completion import complete

    module = run.module

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
                grdst = helpers.arcformat(ml["StoryArc"], helpers.spantheyears(ml["StoryArcID"]), ml["Publisher"])
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
                            metaresponse = deps.tag_file(
                                run.nzb_folder,
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
                            run.narrate(
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
                            logger.info(
                                "%s Sucessfully wrote metadata to .cbz (%s) - Continuing.." % (module, ofilename)
                            )
                            run.narrate("Sucessfully wrote metadata to .cbz (%s) - proceeding..." % ofilename)

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
                    else:
                        dfilename = ml["Filename"]

                    if metaresponse:
                        src_location = odir
                        grab_src = os.path.join(src_location, ofilename)
                    else:
                        src_location = ofilename
                        grab_src = ofilename

                    logger.fdebug("%s Source Path : %s" % (module, grab_src))

                checkdirectory = deps.validate_directory(grdst, True, module=module)
                if not checkdirectory:
                    logger.warn(
                        "%s Error trying to validate/create directory. Aborting this process at this time." % module
                    )
                    return run.finish("stop")

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

                run.journal("post_processing", issue_arc_id=ml["IssueArcID"])

                try:
                    checkspace = helpers.get_free_space(grdst)
                    if checkspace is False:
                        if all([metaresponse is not None, metaresponse != "fail"]):
                            run.tidy(src_location, True, cacheonly=True)
                        raise OSError
                    mult_count = False
                    if ml_cnt != multiple_arcs:
                        mult_count = True
                    logger.fdebug(
                        "ml_cnt: %s / multiple_arcs: %s --- multiple arc entry: %s"
                        % (ml_cnt, multiple_arcs, mult_count)
                    )
                    deps.place(
                        grab_src,
                        grab_dst,
                        Purpose.ONE_OFF,
                        on_existing=OnExisting.UNGUARDED,
                        multiple=mult_count,
                    )
                except Exception as e:
                    run.log_placement_failure(
                        comicarr.CONFIG.ARC_FILEOPS, grab_src, grab_dst, e, module="%s [ONE-OFF MODE]" % module
                    )
                    return run.abort()

                run.journal("moved", issue_arc_id=ml["IssueArcID"])

                if any([comicarr.CONFIG.FILE_OPTS == "move", comicarr.CONFIG.FILE_OPTS == "copy"]):
                    if mult_count is False:
                        run.tidy(src_location, True, filename=os.path.basename(orig_filename))
                    else:
                        logger.fdebug(
                            "Not deleting %s due to belonging to multiple arcs - will delete in subsequent pass(es)"
                            % os.path.basename(orig_filename)
                        )
                completion = complete(
                    run.context,
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
            deps.foundsearch(
                ComicID=ml["ComicID"],
                mode="story_arc",
                IssueID=ml["IssueID"],
                IssueArcID=ml["IssueArcID"],
                down="PP",
            )
            if all([comicarr.CONFIG.STORYARCDIR is True, comicarr.CONFIG.COPY2ARCDIR is True]):
                logger.fdebug("%s [%s] Post-Processing completed for: %s" % (module, ml["StoryArc"], grab_dst))
            else:
                logger.fdebug(
                    "%s [%s] Post-Processing completed for: %s" % (module, ml["StoryArc"], ml["ComicLocation"])
                )

            _notify(
                run,
                deps,
                completion,
                series=ml["ComicName"],
                issue_year=ml["IssueYear"],
                issue_number=ml["IssueNumber"],
                placed_path=grab_dst,
                issue_id=issueid,
            )

            run.journal("post_processed", issue_arc_id=ml["IssueArcID"])
    return None


def dispatch_library_matches(run: PostProcessRun, deps: PostProcessItemDeps, manual_list, manual_arclist):
    """Process each library match, then post the request's summary."""
    import comicarr

    module = run.module
    # The legacy loop read the last arc-only row for a one-arc summary.
    ml = manual_arclist[-1] if manual_arclist else None

    if any(
        [
            run.nzb_name == "Manual Run",
            run.context.issue_id is not None,
            run.context.comic_id is not None,
            run.context.api_call is True,
        ]
    ):
        annualtype = None
        issuenumOG = None
        if len(manual_list) == 0 and len(manual_arclist) == 0:
            if run.nzb_name == "Manual Run":
                logger.info("%s No matches for Manual Run ... exiting." % module)
            return run.finish("stop")
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
            deps.settle(ml["ComicLocation"])

            dupthis = helpers.duplicate_filecheck(ml["ComicLocation"], ComicID=comicid, IssueID=issueid)
            if dupthis["action"] == "dupe_src" or dupthis["action"] == "dupe_file":
                if comicarr.CONFIG.DDUMP and not all(
                    [comicarr.CONFIG.DUPLICATE_DUMP is None, comicarr.CONFIG.DUPLICATE_DUMP == ""]
                ):
                    dupchkit = _move_duplicate(deps, dupthis)
                    if not dupchkit:
                        logger.warn("Unable to move duplicate file - skipping post-processing of this file.")
                        continue

            if any([dupthis["action"] == "write", dupthis["action"] == "dupe_src"]):
                stat = " [%s/%s]" % (i, len(manual_list))
                _process_library_issue(run, deps, comicid, issueid, issuenumOG, ml, stat)
                dupthis = None

        if run.failed_files == 0:
            if all([run.context.comic_id is not None, run.context.issue_id is None]):
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

            elif run.context.issue_id is not None:
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
            if run.context.comic_id is not None:
                logger.info(
                    "%s post-processing of pack completed for %s issues [FAILED: %s]" % (module, i, run.failed_files)
                )
                global_line = "Successfully post-processing of pack completed for %s issues [FAILED: %s]" % (
                    i,
                    run.failed_files,
                )
            else:
                logger.info(
                    "%s Manual post-processing completed for %s issues [FAILED: %s]" % (module, i, run.failed_files)
                )
                global_line = "Successfully post-processed %s issues [FAILED: %s]" % (i, run.failed_files)

        logger.fdebug("%s %s" % (module, global_line))

        return run.finish("stop")
    else:
        pass


def process_snatched_match(run: PostProcessRun, deps: PostProcessItemDeps, tinfo=None, manual=None):
    """Process a download identified from what was snatched, not its filename."""
    import comicarr
    from comicarr.app.downloads._postprocess_completion import complete

    module = run.module
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
            location = run.nzb_folder
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
                    run.narrate(
                        "Unable to locate downloaded file within items I have snatched. Attempting to parse the filename directly and process."
                    )
                    return run.finish("outside")
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
                    run.narrate("One-off STORYARC mode enabled for Post-Processing for %s" % sarc)
                    logger.info("%s One-off STORYARC mode enabled for Post-Processing for %s" % (module, sarc))
                else:
                    run.narrate(
                        "One-off mode enabled for Post-Processing. All I'm doing is moving the file untouched into the Grab-bag directory."
                    )
                    if comicarr.CONFIG.GRABBAG_DIR is None:
                        comicarr.CONFIG.GRABBAG_DIR = os.path.join(comicarr.CONFIG.DESTINATION_DIR, "Grabbag")
                    logger.info(
                        "%s One-off mode enabled for Post-Processing. Will move into Grab-bag directory: %s"
                        % (module, comicarr.CONFIG.GRABBAG_DIR)
                    )
                    run.narrate("Grab-Bag Directory set to : %s" % comicarr.CONFIG.GRABBAG_DIR)
                    grdst = comicarr.CONFIG.GRABBAG_DIR

                odir = location

                if odir is None:
                    odir = run.nzb_folder

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
                                if filename.lower().endswith(run.extensions):
                                    ofilename = orig_filename = filename
                                    logger.fdebug("%s Valid filename located as : %s" % (module, ofilename))
                                    path, ext = os.path.splitext(ofilename)
                                    break

                if ofilename is None:
                    logger.error(
                        "%s Unable to post-process file as it is not in a valid cbr/cbz format or cannot be located in path. PostProcessing aborted."
                        % module
                    )
                    run.narrate("Unable to locate downloaded file to rename. PostProcessing aborted.")
                    return run.finish("stop")

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
                        run.narrate(
                            "Unable to locate issue within Story Arcs in orde to properly assign metadata. PostProcessing aborted."
                        )
                        return run.finish("stop")

                    if arcdata["Publisher"] is None:
                        arcpub = arcdata["IssuePublisher"]
                    else:
                        arcpub = arcdata["Publisher"]

                    grdst = helpers.arcformat(arcdata["StoryArc"], helpers.spantheyears(arcdata["StoryArcID"]), arcpub)

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
                    run.narrate("Metatagging enabled - proceeding...")

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
                        if os.path.isfile(odir):
                            tmp_ppdir = odir
                        else:
                            tmp_ppdir = os.path.join(odir, ofilename)
                        metaresponse = deps.tag_file(
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
                        run.narrate(
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
                        logger.info("%s Sucessfully wrote metadata to .cbz (%s) - Continuing.." % (module, ofilename))
                        run.narrate("Sucessfully wrote metadata to .cbz (%s) - proceeding..." % ofilename)

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
                run.narrate("Source Path : %s" % grab_src)
                logger.info("%s Source Path : %s" % (module, grab_src))

                checkdirectory = deps.validate_directory(grdst, True, module=module)
                if not checkdirectory:
                    logger.warn(
                        "%s Error trying to validate/create directory. Aborting this process at this time." % module
                    )
                    return run.finish("stop")

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

                run.narrate("Destination Path : %s" % grab_dst)

                logger.info("%s Destination Path : %s" % (module, grab_dst))
                logger.info("%s[%s] %s into directory : %s" % (module, comicarr.CONFIG.FILE_OPTS, ofilename, grab_dst))

                run.journal("post_processing", issue_id=issueid, issue_arc_id=issuearcid)

                try:
                    checkspace = helpers.get_free_space(grdst)
                    if checkspace is False:
                        if all([metaresponse != "fail", metaresponse is not None]):
                            run.tidy(src_location, True, cacheonly=True)
                        raise OSError
                    deps.place(grab_src, grab_dst, Purpose.SERIES, on_existing=OnExisting.UNGUARDED)
                except Exception as e:
                    run.log_placement_failure(comicarr.CONFIG.FILE_OPTS, grab_src, grab_dst, e)
                    run.narrate("Failed to %s %s: %s" % (comicarr.CONFIG.FILE_OPTS, grab_src, e))
                    return run.finish("stop")

                run.journal("moved", issue_id=issueid, issue_arc_id=issuearcid)

                if any([comicarr.CONFIG.FILE_OPTS == "move", comicarr.CONFIG.FILE_OPTS == "copy"]):
                    run.tidy(src_location, True, filename=os.path.basename(orig_filename))

                completion = complete(
                    run.context,
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
                    deps.foundsearch(
                        ComicID=comicid,
                        mode="story_arc",
                        IssueID=issueid,
                        IssueArcID=issuearcid,
                        down="PP",
                    )
                    logger.info("%s Updated status to Downloaded" % module)

                    logger.info("%s Post-Processing completed for: [%s] %s" % (module, sarc, grab_dst))
                    run.narrate("Post Processing SUCCESSFUL! ")
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
                        "%s Post-Processing completed for: [ %s #%s ] %s" % (module, comicname, issuenumber, grab_dst)
                    )
                    run.narrate("Post Processing SUCCESSFUL! ")

                _notify(
                    run,
                    deps,
                    completion,
                    series=comicname,
                    issue_year=None,
                    issue_number=issuenumber,
                    placed_path=grab_dst,
                    issue_id=issueid,
                )

                run.journal("post_processed", issue_id=issueid, issue_arc_id=issuearcid)

                return run.finish("stop")

            else:
                try:
                    len(manual_arclist)
                except (TypeError, NameError):
                    manual_arclist = []

                if tinfo["comiclocation"] is None:
                    cloc = run.nzb_folder
                else:
                    cloc = tinfo["comiclocation"]

                clocation = cloc
                if os.path.isdir(cloc):
                    for root, _dirnames, filenames in safe_walk(cloc):
                        for filename in filenames:
                            if filename.lower().endswith(run.extensions):
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

    if run.nzb_name == "Manual Run":
        if len(manual_list) == 0 and len(manual_arclist) == 0:
            logger.info("%s No matches for Manual Run ... exiting." % module)
            return run.finish("stop")
        elif len(manual_arclist) > 0 and len(manual_list) == 0:
            logger.info("%s Manual post-processing completed for %s story-arc issues." % (module, len(manual_arclist)))
            return run.finish("stop")
        elif len(manual_arclist) > 0:
            logger.info("%s Manual post-processing completed for %s story-arc issues." % (module, len(manual_arclist)))
        i = 0

        for ml in manual_list:
            i += 1
            comicid = ml["ComicID"]
            issueid = ml["IssueID"]
            issuenumOG = ml["IssueNumber"]
            deps.settle(ml["ComicLocation"])

            dupthis = helpers.duplicate_filecheck(ml["ComicLocation"], ComicID=comicid, IssueID=issueid)
            if dupthis["action"] == "dupe_src" or dupthis["action"] == "dupe_file":
                if comicarr.CONFIG.DDUMP and not all(
                    [comicarr.CONFIG.DUPLICATE_DUMP is None, comicarr.CONFIG.DUPLICATE_DUMP == ""]
                ):
                    dupchkit = _move_duplicate(deps, dupthis)
                    if not dupchkit:
                        logger.warn("Unable to move duplicate file - skipping post-processing of this file.")
                        continue

            if any([dupthis["action"] == "write", dupthis["action"] == "dupe_src"]):
                stat = " [%s/%s]" % (i, len(manual_list))
                _process_library_issue(run, deps, comicid, issueid, issuenumOG, ml, stat)
                dupthis = None

        if run.failed_files == 0:
            logger.info("%s Manual post-processing completed for %s issues." % (module, i))
        else:
            logger.info(
                "%s Manual post-processing completed for %s issues [FAILED: %s]" % (module, i, run.failed_files)
            )
        return run.finish("stop")

    else:
        comicid = issuenzb["ComicID"]
        issuenumOG = issuenzb["Issue_Number"]
        dupthis = helpers.duplicate_filecheck(run.nzb_folder, ComicID=comicid, IssueID=issueid)
        if dupthis["action"] == "dupe_src" or dupthis["action"] == "dupe_file":
            if comicarr.CONFIG.DUPLICATE_DUMP:
                if comicarr.CONFIG.DDUMP and not all(
                    [comicarr.CONFIG.DUPLICATE_DUMP is None, comicarr.CONFIG.DUPLICATE_DUMP == ""]
                ):
                    dupchkit = _move_duplicate(deps, dupthis)
                    if not dupchkit:
                        logger.warn("Unable to move duplicate file - skipping post-processing of this file.")
                        return run.finish("stop", issueid=issueid, comicid=comicid)

        if dupthis["action"] == "write" or dupthis["action"] == "dupe_src":
            if manual_list is None:
                return _process_library_issue(run, deps, comicid, issueid, issuenumOG)
            else:
                logger.info("Post-processing issue is found in more than one destination - let us do this!")
                return _process_library_issue(run, deps, comicid, issueid, issuenumOG, manual_list)
        else:
            return run.finish("stop", issueid=issueid, comicid=comicid)


def _move_duplicate(deps, dupeinfo):
    import comicarr

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
        deps.validate_directory(comicarr.CONFIG.DUPLICATE_DUMP, True, module="[DUPLICATE-CLEANUP]")

        if comicarr.CONFIG.DUPLICATE_DATED_FOLDERS is True:
            todaydate = datetime.datetime.now().strftime("%Y-%m-%d")
            dump_folder = os.path.join(comicarr.CONFIG.DUPLICATE_DUMP, todaydate)
            deps.validate_directory(dump_folder, True, module="[DUPLICATE-DATED CLEANUP]")
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
