#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""An operator-chosen library folder for one Series (#1006).

`ComicLocation` is where new files go; `dirlocked` marks it as the operator's
choice. A change records the leave state first (absolute paths for files kept
elsewhere, their folders in `RetainedLocations`), then moves any planned files,
so a move that fails part way never leaves a row pointing at nothing.
"""

import json
import os
from contextlib import contextmanager
from typing import NamedTuple

import comicarr
from comicarr import logger, series_kind
from comicarr.app.acquisition.evidence import has_verified_library_file
from comicarr.app.common import placement
from comicarr.app.common.library_roots import configured_library_roots, is_strict_library_descendant
from comicarr.app.imports import finalization as import_finalization
from comicarr.app.series import queries as series_queries


class SeriesLocationError(ValueError):
    """A folder change was refused before it changed anything."""

    def __init__(self, message, *, status=400):
        super().__init__(message)
        self.detail = message
        self.status = status


def retained_locations(series):
    raw = (series or {}).get("RetainedLocations")
    if not raw:
        return []
    try:
        folders = json.loads(raw)
    except (TypeError, ValueError):
        logger.warn("[SERIES-LOCATION] Ignoring unreadable RetainedLocations: %r" % raw)
        return []
    return [folder for folder in folders if isinstance(folder, str) and folder]


def is_location_override(series):
    try:
        return int((series or {}).get("dirlocked") or 0) == 1
    except (TypeError, ValueError):
        return False


def _real(path):
    return os.path.normcase(os.path.realpath(path))


def _overlaps(left, right):
    left, right = _real(left), _real(right)
    try:
        common = os.path.commonpath([left, right])
    except ValueError:
        return False
    return common in (left, right)


def validate_series_folder(folder, config, *, comic_id=None):
    """Return the normalized folder, or raise SeriesLocationError."""
    if not isinstance(folder, str) or not folder.strip():
        raise SeriesLocationError("Folder must be a server path.")
    folder = folder.strip()
    if not os.path.isabs(folder):
        raise SeriesLocationError("Folder must be an absolute server path, such as /comics/Magazines/Wizard.")
    folder = os.path.normpath(folder)
    if not is_strict_library_descendant(folder, config):
        roots = ", ".join(configured_library_roots(config)) or "none configured"
        raise SeriesLocationError(
            "Folder must be inside a library root, not the root itself. Allowed roots: %s. "
            "Add another root under Settings → Media → Additional library roots." % roots
        )
    for other in series_queries.list_other_series_locations(comic_id):
        for taken in [other.get("ComicLocation"), *retained_locations(other)]:
            if taken and _overlaps(folder, taken):
                raise SeriesLocationError(
                    "Folder overlaps %s's folder (%s). Each Series needs its own folder."
                    % (other.get("ComicName") or other.get("ComicID"), taken)
                )
    return folder


def folder_for_new_series(comic_id, folder, config):
    """Validate an add-time folder before the add is queued; None keeps the automatic one."""
    if folder is None or (isinstance(folder, str) and not folder.strip()):
        return None
    if series_queries.get_series_location(comic_id):
        raise SeriesLocationError(
            "This Series is already in the library. Change its folder from the Series page.", status=409
        )
    return validate_series_folder(folder, config, comic_id=comic_id)


def default_series_location(series):
    if series_kind.is_manga(series):
        from comicarr.app.series.service import _manga_destination, manga_series_location

        return manga_series_location(series.get("ComicName"), _manga_destination())

    from comicarr import filers

    try:
        created = filers.FileHandlers(comic=dict(series)).folder_create()
    except Exception as e:
        logger.warn("[SERIES-LOCATION] Could not derive a default folder for %s: %s" % (series.get("ComicID"), e))
        return None
    return (created or {}).get("comlocation")


@contextmanager
def _library_writes_paused():
    api_lock = comicarr.APILOCK
    if not api_lock.acquire(blocking=False):
        raise SeriesLocationError("Post-processing is running. Try again when it finishes.", status=409)
    try:
        with import_finalization.finalization_paused() as paused:
            if not paused:
                raise SeriesLocationError("An import is being finalized. Try again when it finishes.", status=409)
            yield
    finally:
        api_lock.release()


class Holding(NamedTuple):
    table: str
    issue_id: str
    path: str


def _held_files(comic_id, previous, retained):
    held = []
    for row in series_queries.get_series_holdings(comic_id):
        stored = row["Location"]
        if not has_verified_library_file(previous, stored, retained):
            continue
        path = stored if os.path.isabs(stored) else os.path.join(previous, stored)
        held.append(Holding(row["table"], row["IssueID"], os.path.realpath(path)))
    return held


def _inside(path, folder):
    return os.path.dirname(_real(path)) == _real(folder)


def _stored_path(path, target):
    return os.path.basename(path) if _inside(path, target) else path


def _holding_folders(held, target, candidates):
    outside = [holding.path for holding in held if not _inside(holding.path, target)]
    folders = []
    for folder in candidates:
        if not folder or _real(folder) == _real(target):
            continue
        if folder not in folders and any(_overlaps(path, folder) for path in outside):
            folders.append(folder)
    return folders


def _prepare_folder(target):
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as e:
        logger.error("[SERIES-LOCATION] Could not create %s: %s" % (target, e))
        raise SeriesLocationError(
            "Could not create %s. Check that Comicarr can write to its parent folder." % target
        ) from e
    if not os.access(target, os.W_OK | os.X_OK):
        raise SeriesLocationError("Comicarr cannot write to %s." % target)


def _validated_move_plan(held, target, previous, retained):
    for source_folder in [previous, *retained]:
        if source_folder and _overlaps(target, source_folder) and _real(target) != _real(source_folder):
            raise SeriesLocationError(
                "The new folder and %s overlap, so files cannot be moved between them." % source_folder
            )
    plan = []
    destinations = set()
    for holding in held:
        if _inside(holding.path, target):
            continue
        source_folder = os.path.dirname(holding.path)
        destination = os.path.join(target, os.path.basename(holding.path))
        if not os.access(source_folder, os.W_OK | os.X_OK):
            raise SeriesLocationError("Comicarr cannot move files out of %s." % source_folder)
        if _real(destination) in destinations or os.path.lexists(destination):
            raise SeriesLocationError("%s already exists in the new folder. Nothing was moved." % destination)
        destinations.add(_real(destination))
        plan.append((holding, destination))
    return plan


def _record_leave_state(comic_id, series, target, override, held, candidates):
    series_queries.relocate_series(
        comic_id,
        location=target,
        override=override,
        retained=_holding_folders(held, target, candidates),
        holding_locations=[(h.table, h.issue_id, _stored_path(h.path, target)) for h in held],
    )
    logger.info(
        "[SERIES-LOCATION] %s (%s) now uses %s (was %s)"
        % (series.get("ComicName"), comic_id, target, series.get("ComicLocation"))
    )


def _move_planned_files(plan):
    """Move each file and repoint its row; stop at the first failure. Returns (moved, error)."""
    moved = []
    for holding, destination in plan:
        try:
            placement.place(
                holding.path, destination, placement.Purpose.RELOCATE, on_existing=placement.OnExisting.REFUSE
            )
        except OSError as e:
            logger.error(
                "[SERIES-LOCATION] Moved %d of %d files, then could not move %s: %s"
                % (len(moved), len(plan), holding.path, e)
            )
            error = "Moved %d of %d files, then could not move %s. The log has the reason." % (
                len(moved),
                len(plan),
                holding.path,
            )
            return moved, error
        series_queries.set_holding_location(holding.table, holding.issue_id, os.path.basename(destination))
        moved.append(holding._replace(path=destination))
    return moved, None


def _remove_if_empty(folder):
    if not folder or not is_strict_library_descendant(folder, comicarr.CONFIG):
        return
    try:
        os.rmdir(folder)
        logger.fdebug("[SERIES-LOCATION] Removed emptied folder %s" % folder)
    except OSError:
        pass


def change_series_location(ctx, comic_id, folder, *, move_files=False):
    """Point a Series at a chosen folder, or back at its automatic one.

    Raises SeriesLocationError when the request is refused before any change.
    Returns ``success: False`` only for a move that failed part way; the files
    it did not move stay reachable where they were.
    """
    config = getattr(ctx, "config", None) or comicarr.CONFIG
    series = series_queries.get_series_location(comic_id)
    if not series:
        raise SeriesLocationError("Series %s is not in the library." % comic_id, status=404)

    override = bool(folder and str(folder).strip())
    if override:
        target = validate_series_folder(folder, config, comic_id=comic_id)
    else:
        target = default_series_location(series)
        if not target:
            raise SeriesLocationError("Comicarr has no automatic folder for this Series. Set a destination first.")
        target = validate_series_folder(target, config, comic_id=comic_id)

    with _library_writes_paused():
        series = series_queries.get_series_location(comic_id)
        if (series.get("Status") or "") == "Loading":
            raise SeriesLocationError("This Series is refreshing. Try again when it finishes.", status=409)

        previous = series.get("ComicLocation")
        retained = retained_locations(series)
        held = _held_files(comic_id, previous, retained)
        plan = _validated_move_plan(held, target, previous, retained) if move_files else []
        _prepare_folder(target)

        candidates = [previous, *retained]
        _record_leave_state(comic_id, series, target, override, held, candidates)
        moved, error = _move_planned_files(plan)

        if moved:
            moved_keys = {(h.table, h.issue_id) for h in moved}
            held = [h for h in held if (h.table, h.issue_id) not in moved_keys] + moved
        still_holding = _holding_folders(held, target, candidates)
        if moved:
            series_queries.set_retained_locations(comic_id, still_holding)
            for emptied in candidates:
                if emptied and emptied not in still_holding and not _overlaps(emptied, target):
                    _remove_if_empty(emptied)

        from comicarr import updater

        updater.forceRescan(comic_id)

    result = {
        "success": error is None,
        "comic_location": target,
        "previous_location": previous,
        "override": override,
        "files_moved": len(moved),
        "files_left": sum(1 for h in held if not _inside(h.path, target)),
        "retained_locations": still_holding,
    }
    if error:
        result["error"] = error
    return result
