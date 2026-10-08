#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Deep module for operator-confirmed Import Inbox finalization."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import dataclass

import comicarr
from comicarr import logger, series_kind
from comicarr.app.common import placement
from comicarr.app.core.context import AppContext
from comicarr.app.imports import queries as import_queries
from comicarr.app.series import queries as series_queries

_FINALIZATION_LOCK = threading.Lock()


@dataclass(frozen=True)
class ImportFinalizationResult:
    """Successful outcome returned through the finalization seam."""

    matched: int
    series_id: str
    series_name: str
    moved: int
    archived: int


class ImportFinalizationError(RuntimeError):
    """Manual import finalization failed at a named implementation phase."""

    def __init__(self, message: str, *, phase: str, rollback_failed: bool = False):
        super().__init__(message)
        self.phase = phase
        self.rollback_failed = rollback_failed


def _fail(message: str, *, phase: str, rollback_failed: bool = False) -> ImportFinalizationError:
    return ImportFinalizationError(message, phase=phase, rollback_failed=rollback_failed)


def _normalize_import_ids(import_ids: Sequence[str]) -> list[str]:
    normalized = []
    seen = set()
    raw_import_ids = [import_ids] if isinstance(import_ids, str) else import_ids or ()
    for raw_import_id in raw_import_ids:
        if raw_import_id is None:
            continue
        import_id = str(raw_import_id).strip()
        if import_id and import_id not in seen:
            normalized.append(import_id)
            seen.add(import_id)
    if not normalized:
        raise _fail("Missing import record IDs", phase="preflight")
    return normalized


def _load_and_validate_rows(import_ids: Sequence[str]) -> list[dict]:
    rows_by_id = {row["impID"]: row for row in import_queries.get_import_rows(import_ids)}
    missing = [import_id for import_id in import_ids if import_id not in rows_by_id]
    if missing:
        raise _fail("Missing import record(s): %s" % ", ".join(missing), phase="preflight")

    rows = [rows_by_id[import_id] for import_id in import_ids]
    for row in rows:
        import_id = row["impID"]
        if str(row.get("Status") or "").strip().casefold() == "imported":
            raise _fail("Import record is no longer pending: %s" % import_id, phase="preflight")
        source_path = row.get("ComicLocation")
        if not source_path:
            raise _fail("Import record %s has no source path" % import_id, phase="preflight")
        if not os.path.isfile(source_path):
            raise _fail("Import source file does not exist: %s" % source_path, phase="preflight")
    return rows


def _ensure_series(series_id: str, requested_name: str | None) -> str:
    existing_name = series_queries.get_comic_name(series_id)
    if existing_name:
        return existing_name
    provider = series_kind.provider_of(series_id)
    if provider not in series_kind.MANGA_PROVIDERS:
        return requested_name or "Unknown"

    from comicarr import importer

    try:
        if provider is series_kind.SeriesProvider.MYANIMELIST:
            result = importer.addMangaToDB_MAL(series_id)
        else:
            result = importer.addMangaToDB(series_id)
    except Exception as e:
        raise _fail("Error adding manga: %s" % e, phase="series") from e

    if not result or result.get("status") != "complete":
        raise _fail("Failed to add manga: %s" % series_id, phase="series")
    return result.get("comicname") or requested_name or series_queries.get_comic_name(series_id) or "Unknown"


def _ensure_target_directory(target_directory: str | None) -> None:
    if not target_directory or target_directory == "None":
        raise _fail("Target series has no library directory", phase="preflight")
    if os.path.isdir(target_directory):
        return
    if os.path.exists(target_directory):
        raise _fail("Import target path is not a directory: %s" % target_directory, phase="preflight")

    from comicarr import filechecker

    try:
        created = filechecker.validateAndCreateDirectory(target_directory, True)
    except Exception as e:
        raise _fail("Error creating import target directory %s: %s" % (target_directory, e), phase="preflight") from e
    if not created:
        raise _fail("Could not create import target directory: %s" % target_directory, phase="preflight")


def _issue_number(row: dict) -> str | None:
    value = row.get("IssueNumber")
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized if normalized and normalized != "None" else None


def _resolve_issue_ids(rows: Sequence[dict], series_id: str, fallback_issue_id: str | None) -> list[dict]:
    resolved = []
    for row in rows:
        resolved_row = dict(row)
        issue_number = _issue_number(row)
        resolved_row["_ResolvedIssueID"] = (
            import_queries.get_issue_id(series_id, issue_number) if issue_number else None
        ) or fallback_issue_id
        resolved.append(resolved_row)
    return resolved


def _destination_path(row: dict, series_id: str, series_name: str, target_directory: str, config) -> str:
    source_path = row["ComicLocation"]
    original_filename = row.get("ComicFilename") or os.path.basename(source_path)
    destination_filename = original_filename

    if getattr(config, "IMP_RENAME", False) and getattr(config, "FILE_FORMAT", ""):
        issue_number = _issue_number(row)
        issue_id = row.get("_ResolvedIssueID")
        if issue_number or issue_id:
            from comicarr import helpers

            try:
                renamed = helpers.rename_param(
                    series_id,
                    series_name,
                    issue_number,
                    original_filename,
                    issueid=issue_id,
                )
            except Exception as e:
                logger.fdebug(
                    "[IMPORT-MATCH] Could not rename import file %s, keeping original filename: %s" % (source_path, e)
                )
            else:
                if renamed and renamed.get("nfilename"):
                    destination_filename = renamed["nfilename"]
                else:
                    logger.fdebug(
                        "[IMPORT-MATCH] Could not resolve renamed filename for %s, keeping original filename"
                        % source_path
                    )
        else:
            logger.fdebug("[IMPORT-MATCH] No issue number for %s, keeping original filename" % source_path)

    return os.path.join(target_directory, destination_filename)


def _build_move_plan(rows: Sequence[dict], series_id: str, series_name: str, target_directory: str, config):
    move_plan = []
    destination_paths = set()
    for row in rows:
        destination_path = _destination_path(row, series_id, series_name, target_directory, config)
        normalized_destination = os.path.abspath(destination_path)
        if normalized_destination in destination_paths:
            raise _fail(
                "Multiple import files resolve to the same destination: %s" % destination_path,
                phase="preflight",
            )
        if os.path.exists(destination_path):
            raise _fail("Import destination already exists: %s" % destination_path, phase="preflight")
        destination_paths.add(normalized_destination)
        move_plan.append((row["ComicLocation"], destination_path))
    return move_plan


def _rollback_moves(placed, series_id: str, *, reconcile: bool) -> list[str]:
    """Undo completed placements, newest first.

    Which undo applies is read off each `PlacementResult`, never off config. The
    configured mode and what actually ran can disagree -- a `hardlink` that hit
    EXDEV reports `copy` -- and a rollback that guesses wrong destroys the
    operator's only copy.
    """
    errors = []
    for source_path, result in reversed(placed):
        destination_path = result.destination
        if not os.path.lexists(destination_path):
            if not os.path.lexists(source_path):
                errors.append("%s -> %s: source and destination are missing" % (destination_path, source_path))
            continue
        try:
            if result.source_survived:
                os.unlink(destination_path)
                logger.fdebug(
                    "[IMPORT-MATCH] Removed placed import file %s; %s never left" % (destination_path, source_path)
                )
            else:
                placement.restore_moved_file(destination_path, source_path)
                logger.fdebug("[IMPORT-MATCH] Rolled back moved import file %s to %s" % (destination_path, source_path))
        except (OSError, IOError) as e:
            errors.append("%s -> %s: %s" % (destination_path, source_path, e))

    if reconcile:
        from comicarr import updater

        try:
            updater.forceRescan(series_id)
        except Exception as e:
            errors.append("series reconciliation failed: %s" % e)
    if errors:
        logger.error("[IMPORT-MATCH] Compensation failed: %s" % "; ".join(errors))
    return errors


def _move_and_rescan(move_plan, series_id: str, config):
    from comicarr import updater

    placed = []
    for source_path, destination_path in move_plan:
        logger.fdebug("[IMPORT-MATCH] Placing %s at %s" % (source_path, destination_path))
        if os.path.exists(destination_path):
            rollback_errors = _rollback_moves(placed, series_id, reconcile=False)
            message = "Import destination now exists: %s" % destination_path
            if rollback_errors:
                message += "; rollback incomplete: %s" % "; ".join(rollback_errors)
            raise _fail(message, phase="move", rollback_failed=bool(rollback_errors))
        try:
            result = placement.place(
                source_path,
                destination_path,
                placement.Purpose.IMPORT,
                on_existing=placement.OnExisting.REFUSE,
                config=config,
            )
        except (OSError, IOError) as e:
            rollback_errors = _rollback_moves(placed, series_id, reconcile=False)
            message = "Failed to move import file %s to %s: %s" % (source_path, destination_path, e)
            if rollback_errors:
                message += "; rollback incomplete: %s" % "; ".join(rollback_errors)
            raise _fail(message, phase="move", rollback_failed=bool(rollback_errors)) from e
        placed.append((source_path, result))

    try:
        updater.forceRescan(series_id)
    except Exception as e:
        rollback_errors = _rollback_moves(placed, series_id, reconcile=True)
        message = "Failed to rescan imported series %s: %s" % (series_id, e)
        if rollback_errors:
            message += "; rollback incomplete: %s" % "; ".join(rollback_errors)
        raise _fail(message, phase="rescan", rollback_failed=bool(rollback_errors)) from e
    return placed


def _archive_and_rescan(rows: Sequence[dict], series_id: str) -> None:
    from comicarr import updater

    archive_directories = []
    for row in rows:
        archive_directory = os.path.abspath(os.path.dirname(row["ComicLocation"]))
        if archive_directory not in archive_directories:
            archive_directories.append(archive_directory)

    try:
        for archive_directory in archive_directories:
            logger.fdebug("[IMPORT-MATCH] Archiving import directory in place: %s" % archive_directory)
            updater.forceRescan(series_id, archive=archive_directory)
        updater.forceRescan(series_id)
    except Exception as e:
        raise _fail("Failed to rescan imported series %s: %s" % (series_id, e), phase="rescan") from e


def _import_tagging_enabled(config) -> bool:
    """IMP_METADATA is the import-only switch; tagging still honours ENABLE_META / CBR2CBZ_ONLY."""
    if config is None:
        return False
    if not getattr(config, "IMP_METADATA", False):
        return False
    return bool(getattr(config, "ENABLE_META", False) or getattr(config, "CBR2CBZ_ONLY", False))


def _install_tagged_file(library_path: str, tagged_path: str) -> str:
    """Copy ComicTagger's cache result into the library, handling CBR->CBZ.

    `cmtag.run` cannot write into an existing archive, so it copies into
    CACHE_DIR and may return a .cbz for a .cbr. The result is staged beside the
    target and swapped in with `os.replace`: writing through the existing path
    would truncate an inode a FILE_OPTS=hardlink import shares with the inbox
    original, and a crash mid-copy would corrupt the only library copy.
    """
    destination_path = os.path.join(os.path.dirname(library_path), os.path.basename(tagged_path))
    renamed = os.path.abspath(library_path) != os.path.abspath(destination_path)
    if renamed and os.path.lexists(destination_path):
        raise FileExistsError("%s already exists; leaving %s untagged" % (destination_path, library_path))
    if os.path.abspath(tagged_path) != os.path.abspath(destination_path):
        fd, staged_path = tempfile.mkstemp(prefix=".comicarr-tag-", dir=os.path.dirname(destination_path))
        os.close(fd)
        try:
            shutil.copy(tagged_path, staged_path)
            os.replace(staged_path, destination_path)
        except Exception:
            try:
                os.remove(staged_path)
            except OSError:
                pass
            raise
        try:
            os.remove(tagged_path)
        except OSError:
            pass
        cache_dir = os.path.dirname(tagged_path)
        try:
            if os.path.isdir(cache_dir) and not os.listdir(cache_dir):
                os.rmdir(cache_dir)
        except OSError:
            pass
    if renamed and os.path.lexists(library_path):
        try:
            os.remove(library_path)
        except OSError:
            pass
    return destination_path


@dataclass(frozen=True)
class _PendingTagging:
    rows: Sequence[dict]
    placed: Sequence
    series: dict
    series_id: str
    config: object


def _tag_imported_files(pending: _PendingTagging) -> None:
    """Best-effort tagging after a committed import. Never raises.

    Inbox auto-import and manual match share `finalize_manual_match`, so both
    honour IMP_METADATA through this one call to `cmtag.run` — the same entry
    post-processing and POST /api/metadata/metatag already use. It runs after
    `_FINALIZATION_LOCK` is released: ComicTagger has no timeout, and a slow or
    wedged run must not block every other import.
    """
    if not _import_tagging_enabled(pending.config):
        return

    series_id = pending.series_id
    placed_by_source = {source_path: result.destination for source_path, result in pending.placed}
    renamed = False
    archive_directories = []
    for row in pending.rows:
        issue_id = row.get("_ResolvedIssueID")
        source_path = row["ComicLocation"]
        if not issue_id:
            logger.fdebug("[IMPORT-MATCH] No issue ID for %s, skipping metatag" % source_path)
            continue
        filepath = placed_by_source.get(source_path, source_path)
        try:
            from comicarr import cmtag
            from comicarr.app.metadata import service as metadata_service

            series_arguments = metadata_service.cmtag_series_arguments(
                issue_id,
                series_id,
                pending.series.get("ComicVersion"),
                pending.series.get("ComicYear"),
                pending.series.get("AgeRating"),
            )
            metaresponse = cmtag.run(
                os.path.dirname(filepath),
                issueid=issue_id,
                filename=filepath,
                manualmeta=True,
                **series_arguments,
            )
        except Exception as e:
            logger.warn("[IMPORT-MATCH] Metatagging raised for %s: %s" % (filepath, e))
            continue
        if not isinstance(metaresponse, str) or not os.path.isfile(metaresponse):
            logger.warn(
                "[IMPORT-MATCH] Unable to write metadata to %s [%s] - leaving the imported file untagged"
                % (os.path.basename(filepath), metaresponse)
            )
            continue
        try:
            installed = _install_tagged_file(filepath, metaresponse)
        except Exception as e:
            logger.warn("[IMPORT-MATCH] Could not install tagged file for %s: %s" % (filepath, e))
            continue
        if os.path.abspath(installed) != os.path.abspath(filepath):
            renamed = True
            if source_path not in placed_by_source:
                # Archived in place: the series rescan only sees files outside
                # the series folder when given their directory.
                archive_directory = os.path.abspath(os.path.dirname(installed))
                if archive_directory not in archive_directories:
                    archive_directories.append(archive_directory)
            logger.info(
                "[IMPORT-MATCH] Wrote metadata: %s -> %s" % (os.path.basename(filepath), os.path.basename(installed))
            )
        else:
            logger.info("[IMPORT-MATCH] Wrote metadata to %s" % os.path.basename(installed))

    if not renamed:
        return
    try:
        from comicarr import updater

        for archive_directory in archive_directories:
            updater.forceRescan(series_id, archive=archive_directory)
        updater.forceRescan(series_id)
    except Exception as e:
        logger.warn("[IMPORT-MATCH] Rescan after metatag rename failed for %s: %s" % (series_id, e))


def _finalize_locked(
    ctx: AppContext,
    import_ids: Sequence[str],
    series_id: str,
    *,
    series_name: str | None,
    fallback_issue_id: str | None,
    match_source: str,
    match_confidence: int,
) -> tuple[ImportFinalizationResult, _PendingTagging]:
    normalized_ids = _normalize_import_ids(import_ids)
    rows = _load_and_validate_rows(normalized_ids)
    ensured_name = _ensure_series(series_id, series_name)

    series = series_queries.get_comic_for_import(series_id)
    if not series:
        raise _fail("Target series not found in library: %s" % series_id, phase="series")
    effective_name = series.get("ComicName") or ensured_name
    target_directory = series.get("ComicLocation")
    rows = _resolve_issue_ids(rows, series_id, fallback_issue_id)
    _ensure_target_directory(target_directory)
    config = getattr(ctx, "config", None) or getattr(comicarr, "CONFIG", None)
    move_enabled = bool(getattr(config, "IMP_MOVE", False))
    moved_files = []
    if move_enabled:
        move_plan = _build_move_plan(rows, series_id, effective_name, target_directory, config)
        moved_files = _move_and_rescan(move_plan, series_id, config)
        moved = len(rows)
        archived = 0
    else:
        _archive_and_rescan(rows, series_id)
        moved = 0
        archived = len(rows)

    matches = [(row["impID"], row.get("_ResolvedIssueID")) for row in rows]
    try:
        import_queries.mark_imported(
            matches,
            series_id,
            effective_name,
            match_source=match_source,
            match_confidence=match_confidence,
        )
    except Exception as e:
        rollback_errors = _rollback_moves(moved_files, series_id, reconcile=True) if move_enabled else []
        message = "Failed to record finalized imports for %s: %s" % (series_id, e)
        if rollback_errors:
            message += "; rollback incomplete: %s" % "; ".join(rollback_errors)
        raise _fail(message, phase="commit", rollback_failed=bool(rollback_errors)) from e

    result = ImportFinalizationResult(
        matched=len(rows),
        series_id=series_id,
        series_name=effective_name,
        moved=moved,
        archived=archived,
    )
    return result, _PendingTagging(rows=rows, placed=moved_files, series=series, series_id=series_id, config=config)


def finalize_manual_match(
    ctx: AppContext,
    import_ids: Sequence[str],
    series_id: str,
    *,
    series_name: str | None = None,
    fallback_issue_id: str | None = None,
    match_source: str = "manual",
    match_confidence: int = 100,
) -> ImportFinalizationResult:
    """Finalize one operator-confirmed match through a single testable seam."""
    try:
        with _FINALIZATION_LOCK:
            result, pending_tagging = _finalize_locked(
                ctx,
                import_ids,
                series_id,
                series_name=series_name,
                fallback_issue_id=fallback_issue_id,
                match_source=match_source,
                match_confidence=match_confidence,
            )
    except ImportFinalizationError as e:
        logger.error("[IMPORT-MATCH] [%s] %s" % (e.phase, e))
        raise
    except Exception as e:
        error = _fail("Failed to finalize imports for %s: %s" % (series_id, e), phase="finalization")
        logger.error("[IMPORT-MATCH] [%s] %s" % (error.phase, error))
        raise error from e

    # After commit and outside the lock: a tagging failure must not roll back
    # a finished import.
    try:
        _tag_imported_files(pending_tagging)
    except Exception as e:
        logger.warn("[IMPORT-MATCH] Metatagging failed after import of %s: %s" % (series_id, e))
    return result
