#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Validated post-processing commands and symlink-safe directory walks."""

import os
from pathlib import Path, PurePath

import comicarr


class PostProcessCommandError(ValueError):
    """A post-processing command cannot be proven safe to execute."""


_ROOT_CONFIG_KEYS = (
    "DDL_LOCATION",
    "SAB_DIRECTORY",
    "NZBGET_DIRECTORY",
    "RTORRENT_DIRECTORY",
    "DELUGE_DOWNLOAD_DIRECTORY",
    "QBITTORRENT_FOLDER",
    "LOCAL_WATCHDIR",
    "CHECK_FOLDER",
    "MANUAL_PP_FOLDER",
)


def additional_check_folders(config=None):
    """Return the absolute paths listed one per line in ADDITIONAL_CHECK_FOLDERS."""
    config = config if config is not None else getattr(comicarr, "CONFIG", None)
    raw = getattr(config, "ADDITIONAL_CHECK_FOLDERS", None) if config is not None else None
    if not isinstance(raw, str) or raw.strip().lower() in {"", "none"}:
        return []
    folders = []
    for line in raw.splitlines():
        line = line.strip()
        if line and os.path.isabs(line) and line not in folders:
            folders.append(line)
    return folders


def monitored_folders(config=None):
    """The Folder Monitor's scan list: CHECK_FOLDER first, then the additional folders.

    The additional folders supplement CHECK_FOLDER rather than replace it, so
    they are only scanned while CHECK_FOLDER is set (it still gates the job).
    """
    config = config if config is not None else getattr(comicarr, "CONFIG", None)
    primary = getattr(config, "CHECK_FOLDER", None) if config is not None else None
    if primary is None or not str(primary).strip() or str(primary).strip().lower() == "none":
        return []
    primary = str(primary).strip()
    return [primary] + [folder for folder in additional_check_folders(config) if folder != primary]


def configured_roots(config=None):
    config = config if config is not None else getattr(comicarr, "CONFIG", None)
    roots = []
    for key in _ROOT_CONFIG_KEYS:
        value = getattr(config, key, None) if config is not None else None
        if value and str(value).strip().lower() != "none":
            roots.append(Path(str(value)).expanduser())
    roots.extend(Path(folder).expanduser() for folder in additional_check_folders(config))
    return roots


def _contains(root, candidate):
    return candidate.is_relative_to(root)


def _canonical_path(value, label):
    if value is None or not str(value).strip():
        raise PostProcessCommandError("%s is required" % label)
    raw = str(value).strip()
    if "\x00" in raw or "\\" in raw:
        raise PostProcessCommandError("%s contains an unsafe path separator" % label)
    if ".." in PurePath(raw).parts:
        raise PostProcessCommandError("%s contains traversal" % label)
    return Path(raw).expanduser().resolve(strict=False)


def validate_mapped_path(path, roots=None, require_exists=True):
    """Canonicalize a local path and prove containment under an allowed root."""
    candidate = _canonical_path(path, "nzb_folder")
    if require_exists and not candidate.exists():
        raise PostProcessCommandError("nzb_folder does not exist")
    allowed = [_canonical_path(root, "post-processing root") for root in (roots or configured_roots())]
    if not allowed:
        raise PostProcessCommandError("no post-processing route root is configured")
    if not any(_contains(root, candidate) for root in allowed):
        raise PostProcessCommandError("nzb_folder is outside configured post-processing roots")
    return candidate


def _validate_basename(value):
    if value is None or not str(value).strip():
        raise PostProcessCommandError("nzb_name is required")
    name = str(value).strip()
    if len(name) > 1024:
        raise PostProcessCommandError("nzb_name is too long")
    if "\x00" in name or "\\" in name or "/" in name:
        raise PostProcessCommandError("nzb_name must be a basename")
    if Path(name).is_absolute() or name in {".", ".."} or ".." in PurePath(name).parts:
        raise PostProcessCommandError("nzb_name must be a safe basename")
    if os.path.basename(name) != name:
        raise PostProcessCommandError("nzb_name must be a basename")
    return name


def _is_boolean_flag(value):
    """True when the value is one of the explicit boolean forms the boundary accepts.

    Type-aware on purpose. ``bool`` subclasses ``int`` and numeric types compare
    across themselves, so ``1.0 == 1 == True``; a plain membership test against
    ``(None, True, False, 0, 1, "0", "1")`` therefore admits ``1.0`` and ``0.0``.
    """
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int):  # bool is already handled above
        return value in (0, 1)
    return value in ("0", "1")


def _is_failed_download(value):
    """True only for an explicit failed flag; anything else gets full validation."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):  # bool is already handled above
        return value == 1
    return value == "1"


def validate_postprocess_item(item, roots=None, require_exists=True):
    """Return a normalized copy after validating the PP side-effect boundary."""
    if not isinstance(item, dict):
        raise PostProcessCommandError("post-processing command must be an object")
    command = dict(item)
    command["nzb_name"] = _validate_basename(command.get("nzb_name"))
    # Prove the flags are boolean before anything branches on them, so an
    # unsupported form is reported as itself rather than as a path rejection.
    for key in ("failed", "apicall", "ddl", "oneoff"):
        if key in command and not _is_boolean_flag(command[key]):
            raise PostProcessCommandError("%s must be boolean" % key)
    failed = _is_failed_download(command.get("failed"))
    if failed:
        # A failed download is never imported from this folder. It routes to
        # failed-download handling, which only needs to know the release failed
        # so it can look for a different one. Its folder legitimately sits
        # outside the post-processing roots: NZBGet leaves a FAILURE/* item
        # under InterDir, so the folder reported here is InterDir's parent
        # rather than the completed-download root.
        #
        # Requiring containment rejects the command before the failed path ever
        # runs, so the release parks in manual_review, the failure is never
        # recorded, and the identical release is grabbed again on every
        # subsequent search. Sanitize the path, but do not require containment.
        command["nzb_folder"] = str(_canonical_path(command.get("nzb_folder"), "nzb_folder"))
    else:
        command["nzb_folder"] = str(
            validate_mapped_path(command.get("nzb_folder"), roots=roots, require_exists=require_exists)
        )
    if "failed" in command:
        # Normalize to a real bool. process.Process.post_process() only rewrites
        # the string forms and then branches on `failed is False` / `is True`,
        # so an integer 1 would match neither branch: no PostProcessor, no
        # FailedProcessor, and the item silently does nothing. Canonicalizing
        # here — the one place the command is proven safe — means every accepted
        # truthy form actually reaches failed-download handling.
        command["failed"] = failed
    for key in ("issueid", "comicid"):
        if key in command and command[key] is not None and not str(command[key]).strip():
            raise PostProcessCommandError("%s cannot be blank" % key)
    download_info = command.get("download_info")
    if download_info is not None and not isinstance(download_info, dict):
        raise PostProcessCommandError("download_info must be an object")
    release_key = command.get("journal_release_key")
    if release_key is not None:
        if not str(release_key).strip() or len(str(release_key)) > 1024 or "\x00" in str(release_key):
            raise PostProcessCommandError("journal_release_key is invalid")
        command["journal_release_key"] = str(release_key)
    return command


def safe_walk(root):
    """Walk without following links and omit every entry resolving outside root."""
    canonical_root = Path(root).resolve(strict=False)
    for current, dirnames, filenames in os.walk(canonical_root, followlinks=False):
        current_path = Path(current).resolve(strict=False)
        if not _contains(canonical_root, current_path):
            dirnames[:] = []
            continue
        dirnames[:] = [
            name
            for name in dirnames
            if not (Path(current) / name).is_symlink()
            and _contains(canonical_root, (Path(current) / name).resolve(strict=False))
        ]
        safe_files = [
            name
            for name in filenames
            if not (Path(current) / name).is_symlink()
            and _contains(canonical_root, (Path(current) / name).resolve(strict=False))
        ]
        yield current, dirnames, safe_files
