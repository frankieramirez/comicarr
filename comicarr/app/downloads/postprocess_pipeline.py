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


def _legacy_totals(*args, **kwargs):
    from comicarr import updater

    return updater.totals(*args, **kwargs)


def _legacy_foundsearch(*args, **kwargs):
    from comicarr import updater

    return updater.foundsearch(*args, **kwargs)


class PostProcessReconcileStage:
    """Write the database facts that follow a placed file.

    Every write is keyed on the issue and converges, so re-running the stage
    after a restart leaves the rows as the first run left them. Callers run it
    after the ``moved`` journal transition for comics and before it for manga,
    exactly where the inline writes used to sit.
    """

    def __init__(
        self,
        *,
        totals=_legacy_totals,
        foundsearch=_legacy_foundsearch,
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
