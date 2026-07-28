#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The one place a file is put somewhere.

Callers pass **intent** -- a `Purpose` and an `OnExisting` policy -- never a
resolved file-operation mode. The mode is read from config *inside* `place()`,
at call time, so a caller cannot bind a stale value: there is no public callable
that accepts one. That is the whole point of the module. Reading `FILE_OPTS`
early and passing it down is what let manga post-processing destroy the
operator's download while the setting said `hardlink`.

Config is injected as a *source* (`config`), defaulting to `comicarr.CONFIG`, so
tests swap the object rather than the values.

Failures always raise `PlacementError`. It subclasses `OSError` so callers that
already catch `OSError` keep working unchanged.
"""

import errno
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from enum import Enum, auto

log = logging.getLogger("comicarr")

DISPLACED_SUFFIX = ".comicarr-displaced"


class Purpose(Enum):
    """Why a file is being placed. Selects the config key and the mechanics."""

    SERIES = auto()  # FILE_OPTS,   plain mechanics
    IMPORT = auto()  # FILE_OPTS,   plain mechanics
    ONE_OFF = auto()  # ARC_FILEOPS, plain mechanics
    ARC = auto()  # ARC_FILEOPS, preserve source + reverse link direction


class OnExisting(Enum):
    """What to do when the destination is already occupied."""

    UNGUARDED = auto()  # no check; the mode's native behaviour decides
    DISPLACE = auto()  # rename aside, place, then delete-or-restore
    SKIP = auto()  # any file at the destination means no placement at all
    REFUSE = auto()  # atomic no-clobber: the publish itself refuses


class Outcome(Enum):
    PLACED = auto()
    ALREADY_PLACED = auto()


class PlacementError(OSError):
    """A placement did not happen.

    Subclasses OSError deliberately: `storyarcs/service.py` catches the narrow
    `(OSError, IOError)`, so migration stays mechanical rather than
    behaviour-changing.
    """

    def __init__(self, message, *, purpose=None, mode=None, source=None, destination=None):
        super().__init__(message)
        self.purpose = purpose
        self.mode = mode
        self.source = source
        self.destination = destination


@dataclass(frozen=True)
class PlacementResult:
    """What actually happened. Describes success only -- failures raise.

    `source_survived` and `source_is_symlink` are recorded by the mechanic that
    ran rather than re-derived from the mode, because the same mode does
    different things to the source depending on purpose and policy: non-arc
    `softlink` moves the file and leaves a symlink behind at the source path,
    arc `softlink` does not touch the source at all, and the REFUSE publish uses
    a third shape again. Deriving that from `(purpose, effective_mode)` was the
    original plan and it is not derivable.
    """

    outcome: Outcome
    effective_mode: str
    destination: str
    purpose: Purpose
    on_existing: OnExisting
    source_survived: bool
    source_is_symlink: bool


def place(source, destination, purpose, *, on_existing, multiple=False, config=None) -> PlacementResult:
    """Place `source` at `destination` according to intent.

    `on_existing` is required and has no default. UNGUARDED covers five of the
    eight call sites and would be the obvious default, which is exactly why it
    is not one -- it is the policy nobody chose, and a default would let new
    callers inherit it silently.
    """
    if config is None:
        import comicarr

        config = comicarr.CONFIG

    mode = _resolve_mode(config, purpose, multiple)
    arc = purpose is Purpose.ARC
    softlink_type = _resolve_softlink_type(config, purpose)

    if on_existing is OnExisting.SKIP:
        # isfile, not lexists -- matches storyarcs' guard exactly, so a dangling
        # symlink at the destination is still replaced.
        if os.path.isfile(destination):
            return _already_placed(destination, purpose, on_existing, mode)

    elif on_existing is OnExisting.DISPLACE:
        return _place_displacing(
            source, destination, purpose, on_existing, mode=mode, arc=arc, softlink_type=softlink_type
        )

    elif on_existing is OnExisting.REFUSE:
        return _place_refusing(source, destination, purpose, on_existing, mode=mode)

    effective, survived, is_symlink = _apply(
        source, destination, purpose=purpose, mode=mode, arc=arc, softlink_type=softlink_type
    )
    return PlacementResult(
        outcome=Outcome.PLACED,
        effective_mode=effective,
        destination=destination,
        purpose=purpose,
        on_existing=on_existing,
        source_survived=survived,
        source_is_symlink=is_symlink,
    )


def _already_placed(destination, purpose, on_existing, mode) -> PlacementResult:
    return PlacementResult(
        outcome=Outcome.ALREADY_PLACED,
        effective_mode=mode,
        destination=destination,
        purpose=purpose,
        on_existing=on_existing,
        source_survived=True,
        source_is_symlink=False,
    )


def _resolve_mode(config, purpose, multiple):
    """Read the operative mode from config. Called once per `place()`, never cached."""
    if purpose in (Purpose.ONE_OFF, Purpose.ARC):
        # `multiple` is a genuine bool at the one call site that passes it
        # (postprocessor assigns literal True/False), so the identity check the
        # legacy helper used is sound and is preserved.
        if multiple is True:
            return "copy"
        return config.ARC_FILEOPS
    return config.FILE_OPTS


def _resolve_softlink_type(config, purpose):
    if purpose in (Purpose.ONE_OFF, Purpose.ARC):
        if config.ARC_FILEOPS_SOFTLINK_RELATIVE is True:
            return "relative"
    return "absolute"


def _fail(message, *, purpose, mode, source, destination, cause=None):
    error = PlacementError(message, purpose=purpose, mode=mode, source=source, destination=destination)
    if cause is not None:
        raise error from cause
    raise error


# ---------------------------------------------------------------------------
# Mechanics
#
# Two families. `_apply` reproduces the legacy `file_ops` behaviour exactly,
# including its fallbacks, and serves UNGUARDED / DISPLACE / SKIP. `_publish`
# is the atomic no-clobber family and serves REFUSE alone.
# ---------------------------------------------------------------------------


def _apply(path, dst, *, purpose, mode, arc, softlink_type):
    """The legacy mechanics, preserved. Returns (effective_mode, source_survived, source_is_symlink)."""
    if mode == "copy" or (arc and mode in ("copy", "move")):
        # An arc must keep the series file, so `move` degrades to a copy.
        try:
            shutil.copy(path, dst)
        except Exception as e:
            log.error("[%s] error : %s" % (mode, e))
            _fail("copy failed: %s" % e, purpose=purpose, mode=mode, source=path, destination=dst, cause=e)
        return "copy", True, False

    if mode == "move":
        try:
            shutil.move(path, dst)
        except Exception as e:
            log.error("[MOVE] error : %s" % e)
            _fail("move failed: %s" % e, purpose=purpose, mode=mode, source=path, destination=dst, cause=e)
        return "move", False, False

    if mode == "hardlink":
        return _apply_hardlink(path, dst, purpose=purpose, mode=mode)

    if mode == "softlink":
        return _apply_softlink(path, dst, purpose=purpose, mode=mode, arc=arc, softlink_type=softlink_type)

    _fail("unsupported file operation: %r" % (mode,), purpose=purpose, mode=mode, source=path, destination=dst)


def _apply_hardlink(path, dst, *, purpose, mode):
    try:
        os.link(path, dst)
    except OSError as e:
        if e.errno == errno.EXDEV:
            log.warning(
                "[%s] Hardlinking failure. Could not create hardlink - dropping down to copy mode so that this "
                "operation can complete. Intervention is required if you wish to continue using hardlinks." % e
            )
            try:
                shutil.copy(path, dst)
            except Exception as copy_error:
                log.error("[COPY] error : %s" % copy_error)
                _fail(
                    "hardlink fell back to copy and the copy failed: %s" % copy_error,
                    purpose=purpose,
                    mode=mode,
                    source=path,
                    destination=dst,
                    cause=copy_error,
                )
            log.debug("Successfully copied file to : " + dst)
            return "copy", True, False

        log.warning(
            "[%s] Hardlinking failure. Could not create hardlink - Intervention is required if you wish to "
            "continue using hardlinks." % e
        )
        _fail("hardlink failed: %s" % e, purpose=purpose, mode=mode, source=path, destination=dst, cause=e)

    hardlinks = os.lstat(dst).st_nlink
    if hardlinks > 1:
        log.info("Created hard link [" + str(hardlinks) + "] successfully!! (" + dst + ")")
    else:
        log.warning("Hardlink cannot be verified. You should probably verify that it is created properly.")
    return "hardlink", True, False


def _apply_softlink(path, dst, *, purpose, mode, arc, softlink_type):
    try:
        if not arc:
            # Non-arc: the file itself moves to the destination and the source
            # path is replaced by a symlink pointing at it. The source path
            # survives, but as a link -- which is why `source_is_symlink` is not
            # derivable from the mode alone.
            shutil.move(path, dst)
            if os.path.lexists(path):
                os.remove(path)
            if softlink_type == "absolute":
                os.symlink(dst, path)
                log.debug("Successfully created softlink [" + dst + " --> " + path + "]")
            else:
                os.symlink(os.path.relpath(dst, os.path.dirname(path)), path)
                log.debug(
                    "Successfully created (relative) softlink [%s --> %s]"
                    % (os.path.relpath(dst, os.path.dirname(path)), path)
                )
        else:
            # Arc: the series file stays put and the arc directory gets the link.
            if softlink_type == "absolute":
                os.symlink(path, dst)
                log.debug("Successfully created softlink [" + path + " --> " + dst + "]")
            else:
                os.symlink(os.path.relpath(path, os.path.dirname(dst)), dst)
                log.debug(
                    "Successfully created (relative) softlink [%s --> %s]"
                    % (os.path.relpath(path, os.path.dirname(dst)), dst)
                )
    except OSError as e:
        log.warning(
            "[%s] Unable to create symlink. Dropping down to copy mode so that this operation can continue." % e
        )
        try:
            if arc:
                shutil.copy(path, dst)
                log.debug("Successfully copied file [" + path + " --> " + dst + "]")
            else:
                # The move already happened, so the copy restores the source.
                shutil.copy(dst, path)
                log.debug("Successfully copied file [" + dst + " --> " + path + "]")
        except Exception as copy_error:
            log.error("[COPY] error : %s" % copy_error)
            _fail(
                "softlink fell back to copy and the copy failed: %s" % copy_error,
                purpose=purpose,
                mode=mode,
                source=path,
                destination=dst,
                cause=copy_error,
            )
        return "copy", True, False

    # The source path exists either way; only its nature differs. Arc leaves the
    # real file untouched, non-arc leaves a symlink standing where it used to be.
    return "softlink", True, not arc


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def _place_displacing(source, destination, purpose, on_existing, *, mode, arc, softlink_type):
    """Rename what is there aside, place, then delete it or put it back.

    Deliberately not a delete-first: copy and move truncate the destination as
    they write, so an up-front delete would leave the library with nothing while
    the database still reports the issue as Downloaded. A rename frees the
    destination for every mode and keeps the old file restorable.
    """
    displaced = None
    if os.path.lexists(destination):
        try:
            # Same inode (hardlinked) or same target (softlinked) means an
            # earlier pass already placed this file; re-linking it would only
            # fail, and the source must survive either way.
            if os.path.samefile(source, destination):
                return _already_placed(destination, purpose, on_existing, mode)
        except OSError:
            pass

        displaced = destination + DISPLACED_SUFFIX
        if os.path.lexists(displaced):
            # An orphan from a crash between displace and restore. Clobbering it
            # loses a stale backup; refusing would strand this file permanently
            # after a single crash, which is the worse failure.
            log.warning("Replacing an orphaned displaced file: %s" % displaced)
        try:
            os.replace(destination, displaced)
        except OSError as e:
            _fail(
                "could not displace the existing file: %s" % e,
                purpose=purpose,
                mode=mode,
                source=source,
                destination=destination,
                cause=e,
            )

    try:
        effective, survived, is_symlink = _apply(
            source, destination, purpose=purpose, mode=mode, arc=arc, softlink_type=softlink_type
        )
    except PlacementError:
        if displaced is not None:
            try:
                os.replace(displaced, destination)
                log.info("Restored the previous %s after a failed placement" % destination)
            except OSError as restore_error:
                # The original is still on disk under its marker name, which is
                # strictly better than gone.
                log.error("Failed to restore the previous %s: %s" % (destination, restore_error))
        raise

    if displaced is not None:
        try:
            os.remove(displaced)
        except OSError as e:
            log.warning("Failed to clean up %s: %s" % (displaced, e))

    return PlacementResult(
        outcome=Outcome.PLACED,
        effective_mode=effective,
        destination=destination,
        purpose=purpose,
        on_existing=on_existing,
        source_survived=survived,
        source_is_symlink=is_symlink,
    )


def _place_refusing(source, destination, purpose, on_existing, *, mode):
    """Never replace an existing destination, and prove it atomically.

    The guarantee is atomicity, not refusal. `os.link` and `os.symlink` fail with
    EEXIST as part of creating the destination, so there is no window between
    checking and writing. A caller-side `os.path.exists` check is not an
    acceptable substitute and must not replace this.
    """
    if mode == "move":
        effective = _publish_move(source, destination, purpose=purpose, mode=mode)
        return PlacementResult(
            outcome=Outcome.PLACED,
            effective_mode=effective,
            destination=destination,
            purpose=purpose,
            on_existing=on_existing,
            source_survived=False,
            source_is_symlink=False,
        )

    if mode == "copy":
        _publish_copy(source, destination, purpose=purpose, mode=mode)
        effective = "copy"

    elif mode == "hardlink":
        try:
            os.link(source, destination)
            effective = "hardlink"
        except OSError as e:
            if e.errno != errno.EXDEV:
                _fail(
                    "hardlink failed: %s" % e,
                    purpose=purpose,
                    mode=mode,
                    source=source,
                    destination=destination,
                    cause=e,
                )
            # EXDEV is the dominant topology, not the exception -- two Docker
            # volumes off one NAS volume are always cross-device. Degrade to the
            # atomic copy publish, which preserves the source exactly as a
            # hardlink would, so rollback is unaffected.
            log.warning("[%s] Cannot hardlink across filesystems - dropping down to copy mode." % e)
            _publish_copy(source, destination, purpose=purpose, mode=mode)
            effective = "copy"

    elif mode == "softlink":
        # Deliberately not the non-arc move-then-link-back shape: an import must
        # not consume the operator's inbox file and leave a link in its place.
        # os.symlink is already atomically no-clobber.
        try:
            os.symlink(source, destination)
            effective = "softlink"
        except OSError as e:
            _fail(
                "softlink failed: %s" % e,
                purpose=purpose,
                mode=mode,
                source=source,
                destination=destination,
                cause=e,
            )

    else:
        _fail(
            "unsupported file operation: %r" % (mode,),
            purpose=purpose,
            mode=mode,
            source=source,
            destination=destination,
        )

    return PlacementResult(
        outcome=Outcome.PLACED,
        effective_mode=effective,
        destination=destination,
        purpose=purpose,
        on_existing=on_existing,
        source_survived=True,
        source_is_symlink=False,
    )


def _publish_copy(source, destination, *, purpose, mode):
    """Copy to a private file on the target filesystem, then publish atomically."""
    temporary_path = None
    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".comicarr-import-",
            dir=os.path.dirname(destination),
        )
        os.close(descriptor)
        shutil.copy2(source, temporary_path)
        os.link(temporary_path, destination)
    except OSError as e:
        _fail(
            "could not publish %s: %s" % (destination, e),
            purpose=purpose,
            mode=mode,
            source=source,
            destination=destination,
            cause=e,
        )
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def _publish_move(source, destination, *, purpose, mode):
    """Move without ever replacing an existing destination.

    Hard-link publication gives same-filesystem moves an atomic no-clobber
    boundary. Cross-filesystem moves first copy to a private file on the target
    filesystem, then publish that complete file through the same boundary.
    """
    temporary_path = None
    published_reference = source
    try:
        try:
            os.link(source, destination)
        except OSError as e:
            if e.errno != errno.EXDEV:
                _fail(
                    "could not publish %s: %s" % (destination, e),
                    purpose=purpose,
                    mode=mode,
                    source=source,
                    destination=destination,
                    cause=e,
                )

            descriptor, temporary_path = tempfile.mkstemp(
                prefix=".comicarr-import-",
                dir=os.path.dirname(destination),
            )
            os.close(descriptor)
            shutil.copy2(source, temporary_path)
            published_reference = temporary_path
            os.link(temporary_path, destination)

        try:
            os.unlink(source)
        except OSError as e:
            remove_transfer_destination(destination, published_reference)
            _fail(
                "published %s but could not consume the source: %s" % (destination, e),
                purpose=purpose,
                mode=mode,
                source=source,
                destination=destination,
                cause=e,
            )
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass

    return "move"


def remove_transfer_destination(destination_path: str, reference_path: str) -> None:
    """Remove a destination only while it still names this transfer's file.

    Reachable only from the move publish, where a successful publish is followed
    by a failed source unlink. The source-preserving modes never unlink the
    source, so they never undo a publish this way.
    """
    try:
        if os.path.samestat(os.stat(destination_path), os.stat(reference_path)):
            os.unlink(destination_path)
    except FileNotFoundError:
        pass
