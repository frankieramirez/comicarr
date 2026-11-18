#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Safety boundaries for filenames and archives received from remote services."""

import logging
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from comicarr.app.core import runtime

MAX_ZIP_MEMBERS = 10_000
MAX_ZIP_UNCOMPRESSED_BYTES = 20 * 1024 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200
ZIP_RATIO_CHECK_MIN_BYTES = 1024 * 1024
ZIP_DISK_RESERVE_BYTES = 256 * 1024 * 1024
FILE_STAGING_PREFIX = ".comicarr-part-"
ZIP_STAGING_PREFIX = ".comicarr-extract-"
ZIP_BACKUP_PREFIX = ".comicarr-backup-"

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_LOGGER = logging.getLogger(__name__)
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "COM¹",
    "COM²",
    "COM³",
    "CON",
    "CONIN$",
    "CONOUT$",
    "CLOCK$",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
    "LPT¹",
    "LPT²",
    "LPT³",
    "NUL",
    "PRN",
}


class RemoteArtifactError(ValueError):
    """Raised when a remote filename or archive cannot be handled safely."""


def safe_remote_filename(filename):
    """Normalize an untrusted filename to one portable path component.

    Path separators and platform-invalid characters are replaced rather than
    discarding the surrounding title, while valid Unicode is preserved.
    """
    if filename is None:
        raise RemoteArtifactError("Remote filename is missing")
    if isinstance(filename, bytes):
        filename = filename.decode("utf-8", errors="replace")

    normalized = unicodedata.normalize("NFC", str(filename)).strip()
    normalized = _INVALID_FILENAME_CHARS.sub("-", normalized).strip(" .")
    if not normalized or not any(character not in ".- " for character in normalized):
        raise RemoteArtifactError("Remote filename is empty after normalization")
    if normalized.split(".", 1)[0].rstrip(" .").upper() in _WINDOWS_RESERVED_NAMES:
        normalized = "_" + normalized
    return normalized


def ensure_path_within_directory(directory, path):
    """Return a resolved path only when it is strictly inside ``directory``."""
    root = Path(directory).expanduser().resolve()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        contained = os.path.commonpath([str(root), str(candidate)]) == str(root)
    except ValueError as e:
        raise RemoteArtifactError("Remote artifact path is on a different volume") from e
    if not contained or candidate == root:
        raise RemoteArtifactError("Remote artifact path escapes its destination")
    return candidate


def resolve_remote_artifact_path(directory, filename):
    """Normalize ``filename`` and resolve it strictly inside ``directory``."""
    return ensure_path_within_directory(directory, safe_remote_filename(filename))


def _permission_mode(value, fallback, allowed_mask=0o777):
    """Parse an octal mode and remove bits disallowed for the artifact type.

    Remote files never receive privilege-bearing special bits. Directories may
    retain setgid and sticky bits for shared-library collaboration, but setuid
    is not meaningful or safe for this boundary.
    """
    if value is None or isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        if 0 <= value <= 0o777:
            return value & allowed_mask
        if value <= 999 and re.fullmatch(r"[0-7]{3}", str(value)):
            return int(str(value), 8) & allowed_mask
        if 0 <= value <= 0o7777:
            return value & allowed_mask
        return fallback

    mode_text = str(value).strip().lower()
    if mode_text.startswith("0o"):
        mode_text = mode_text[2:]
    if not re.fullmatch(r"[0-7]{1,4}", mode_text):
        return fallback
    mode = int(mode_text, 8)
    return mode & allowed_mask if 0 <= mode <= 0o7777 else fallback


def _configured_permission(config, attribute, fallback, allowed_mask=0o777):
    return _permission_mode(getattr(config, attribute, None), fallback, allowed_mask=allowed_mask)


def _ownership_supported():
    return all(hasattr(os, attribute) for attribute in ("chown", "getuid", "getgid"))


def _unset_identity(value):
    return value is None or str(value).strip().lower() in {"", "none"}


def _resolve_identity(value, identity_type):
    if isinstance(value, int):
        if value < 0:
            raise RemoteArtifactError("Configured %s cannot be negative" % identity_type)
        return value

    identity = str(value).strip()
    if identity.isdigit():
        return int(identity)
    try:
        if identity_type == "owner":
            import pwd

            return pwd.getpwnam(identity).pw_uid
        import grp

        return grp.getgrnam(identity).gr_gid
    except (ImportError, KeyError) as e:
        raise RemoteArtifactError("Configured %s does not exist: %s" % (identity_type, identity)) from e


def _configured_ownership(config):
    if not _ownership_supported():
        return None
    configured_group = getattr(config, "CHGROUP", None)
    if _unset_identity(configured_group):
        return None
    configured_owner = getattr(config, "CHOWNER", None)
    owner = os.getuid() if _unset_identity(configured_owner) else _resolve_identity(configured_owner, "owner")
    group = _resolve_identity(configured_group, "group")
    return owner, group


def _new_artifact_policy():

    config = runtime.current().config
    if bool(getattr(config, "ENFORCE_PERMS", False)):
        return (
            _configured_permission(config, "CHMOD_FILE", 0o600),
            _configured_permission(config, "CHMOD_DIR", 0o700, allowed_mask=0o3777),
            _configured_ownership(config),
        )

    captured_umask = _permission_mode(runtime.current().umask, None)
    if captured_umask is None:
        return 0o600, 0o700, None
    return 0o666 & ~captured_umask, 0o777 & ~captured_umask, None


def _stat_ownership(stat_result):
    if not _ownership_supported():
        return None
    return stat_result.st_uid, stat_result.st_gid


def _apply_ownership(path, ownership):
    if ownership is not None:
        os.chown(path, ownership[0], ownership[1])


def _apply_artifact_metadata(path, mode, ownership):
    _apply_ownership(path, ownership)
    os.chmod(path, mode)


def _replacement_file_metadata(destination):
    if destination.is_symlink():
        raise RemoteArtifactError("Remote artifact destination is a symbolic link")
    if destination.exists():
        existing_stat = destination.stat()
        return stat.S_IMODE(existing_stat.st_mode), _stat_ownership(existing_stat)
    file_mode, _, ownership = _new_artifact_policy()
    return file_mode, ownership


def write_chunks_atomically(destination, chunks):
    """Write byte chunks beside ``destination`` and atomically publish on success."""
    destination = Path(destination)
    file_mode, ownership = _replacement_file_metadata(destination)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=FILE_STAGING_PREFIX,
        suffix=".part",
        dir=destination.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as output:
            for chunk in chunks:
                if chunk:
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        _apply_artifact_metadata(temporary_path, file_mode, ownership)
        os.replace(temporary_path, destination)
    except Exception as e:
        try:
            temporary_path.unlink(missing_ok=True)
        except Exception as cleanup_error:
            _LOGGER.warning(
                "Unable to clean up failed download staging file %s after %s: %s",
                temporary_path,
                e,
                cleanup_error,
            )
        raise


def _portable_zip_component(component):
    if component != component.rstrip(" ."):
        raise RemoteArtifactError("Archive contains a non-portable member name")
    component = unicodedata.normalize("NFC", component)
    if not component or _INVALID_FILENAME_CHARS.search(component):
        raise RemoteArtifactError("Archive contains a non-portable member name")
    device_basename = component.split(".", 1)[0].rstrip(" .").upper()
    if device_basename in _WINDOWS_RESERVED_NAMES:
        raise RemoteArtifactError("Archive contains a non-portable member name")
    return component


def _portable_collision_key(relative_parts):
    return tuple(unicodedata.normalize("NFC", part.casefold()) for part in relative_parts)


def _validated_zip_members(zip_file, destination, existing_size=0):
    members = zip_file.infolist()
    if len(members) > MAX_ZIP_MEMBERS:
        raise RemoteArtifactError("Archive contains too many members")

    total_uncompressed = 0
    total_compressed = 0
    normalized_targets = set()
    portable_prefixes = {}
    validated = []
    destination = Path(destination).resolve()

    for member in members:
        raw_name = member.filename.replace("\\", "/")
        posix_path = PurePosixPath(raw_name)
        windows_path = PureWindowsPath(raw_name)
        if (
            not raw_name
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or ".." in posix_path.parts
        ):
            raise RemoteArtifactError("Archive contains an invalid member name")

        raw_relative_parts = tuple(part for part in posix_path.parts if part not in {"", "."})
        relative_parts = tuple(_portable_zip_component(part) for part in raw_relative_parts)
        if not relative_parts:
            raise RemoteArtifactError("Archive contains an empty member name")
        for prefix_length in range(1, len(relative_parts) + 1):
            canonical_prefix = _portable_collision_key(relative_parts[:prefix_length])
            raw_prefix = raw_relative_parts[:prefix_length]
            previous_prefix = portable_prefixes.get(canonical_prefix)
            if previous_prefix is not None and previous_prefix != raw_prefix:
                raise RemoteArtifactError("Archive contains duplicate portable member paths")
            portable_prefixes[canonical_prefix] = raw_prefix
        target = destination.joinpath(*relative_parts).resolve()
        try:
            contained = os.path.commonpath([str(destination), str(target)]) == str(destination)
        except ValueError as e:
            raise RemoteArtifactError("Archive member is on a different volume") from e
        if not contained or target == destination:
            raise RemoteArtifactError("Archive member resolves outside its destination")
        current_path = destination
        for relative_part in relative_parts:
            current_path = current_path / relative_part
            if current_path.is_symlink():
                raise RemoteArtifactError("Archive member collides with an existing symbolic link")

        target_key = _portable_collision_key(relative_parts)
        if target_key in normalized_targets:
            raise RemoteArtifactError("Archive contains duplicate member paths")
        normalized_targets.add(target_key)

        member_mode = (member.external_attr >> 16) & 0o170000
        if member_mode == stat.S_IFLNK:
            raise RemoteArtifactError("Archive contains a symbolic link")
        if member.flag_bits & 0x1:
            raise RemoteArtifactError("Encrypted archives are not supported")

        total_uncompressed += member.file_size
        total_compressed += member.compress_size
        if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise RemoteArtifactError("Archive expands beyond the configured size limit")
        if member.file_size >= ZIP_RATIO_CHECK_MIN_BYTES and (
            member.compress_size == 0 or member.file_size / member.compress_size > MAX_ZIP_COMPRESSION_RATIO
        ):
            raise RemoteArtifactError("Archive member has a suspicious compression ratio")

        validated.append((member, relative_parts))

    if total_uncompressed >= ZIP_RATIO_CHECK_MIN_BYTES and (
        total_compressed == 0 or total_uncompressed / total_compressed > MAX_ZIP_COMPRESSION_RATIO
    ):
        raise RemoteArtifactError("Archive has a suspicious aggregate compression ratio")

    free_bytes = shutil.disk_usage(destination.parent).free
    available_bytes = max(0, free_bytes - ZIP_DISK_RESERVE_BYTES)
    if total_uncompressed + existing_size > available_bytes:
        raise RemoteArtifactError("Archive requires more free disk space than is available")
    return validated


def _make_directories(path, mode, ownership):
    path = Path(path)
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    for directory in reversed(missing):
        _apply_artifact_metadata(directory, mode, ownership)


def _extract_zip_member(
    zip_file,
    member,
    destination,
    file_mode=0o600,
    directory_mode=0o700,
    ownership=None,
):
    if member.is_dir():
        _make_directories(destination, directory_mode, ownership)
        return

    destination_existed = destination.exists()
    _make_directories(destination.parent, directory_mode, ownership)
    bytes_written = 0
    with zip_file.open(member, "r") as source, destination.open("wb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            bytes_written += len(chunk)
            if bytes_written > member.file_size:
                raise RemoteArtifactError("Archive member expanded beyond its declared size")
            output.write(chunk)
    if bytes_written != member.file_size:
        raise RemoteArtifactError("Archive member size does not match its metadata")
    if not destination_existed:
        _apply_artifact_metadata(destination, file_mode, ownership)


def _remove_path(path):
    path = Path(path)
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _directory_size(path):
    total_size = 0
    for root, directories, filenames in os.walk(path, followlinks=False):
        for name in directories + filenames:
            candidate = Path(root) / name
            try:
                total_size += candidate.lstat().st_size
            except FileNotFoundError:
                continue
    return total_size


def _preserve_tree_metadata(source, destination):
    if not _ownership_supported():
        return

    source = Path(source)
    destination = Path(destination)
    source_paths = [source]
    for root, directories, filenames in os.walk(source, followlinks=False):
        source_root = Path(root)
        source_paths.extend(source_root / name for name in directories + filenames)

    for source_path in source_paths:
        if source_path.is_symlink():
            continue
        source_stat = source_path.stat()
        relative_path = source_path.relative_to(source)
        destination_path = destination / relative_path
        _apply_artifact_metadata(
            destination_path,
            stat.S_IMODE(source_stat.st_mode),
            _stat_ownership(source_stat),
        )


def extract_zip_atomically(archive_path, destination):
    """Validate and overlay a ZIP in staging before publishing the result.

    Existing extraction directories are copied into staging first so successful
    retries retain the legacy merge behavior without exposing partial output.
    """
    archive_path = Path(archive_path)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_path = Path(
        tempfile.mkdtemp(
            prefix=ZIP_STAGING_PREFIX,
            dir=destination.parent,
        )
    )
    backup_path = None

    try:
        destination_exists = os.path.lexists(destination)
        if destination_exists and (destination.is_symlink() or not destination.is_dir()):
            raise RemoteArtifactError("Archive destination is not a directory")
        existing_size = _directory_size(destination) if destination_exists else 0
        file_mode, directory_mode, new_ownership = _new_artifact_policy()
        root_mode = stat.S_IMODE(destination.stat().st_mode) if destination_exists else directory_mode
        root_ownership = _stat_ownership(destination.stat()) if destination_exists else new_ownership
        with zipfile.ZipFile(archive_path, "r") as zip_file:
            members = _validated_zip_members(zip_file, destination, existing_size=existing_size)
            if destination_exists:
                shutil.copytree(destination, staging_path, dirs_exist_ok=True, symlinks=True)
            for member, relative_parts in members:
                _extract_zip_member(
                    zip_file,
                    member,
                    staging_path.joinpath(*relative_parts),
                    file_mode=file_mode,
                    directory_mode=directory_mode,
                    ownership=new_ownership,
                )
        if destination_exists:
            _preserve_tree_metadata(destination, staging_path)
        _apply_artifact_metadata(staging_path, root_mode, root_ownership)

        if destination_exists:
            backup_path = Path(
                tempfile.mkdtemp(
                    prefix=ZIP_BACKUP_PREFIX,
                    dir=destination.parent,
                )
            )
            backup_path.rmdir()
            os.replace(destination, backup_path)
        try:
            os.replace(staging_path, destination)
        except Exception as e:
            _LOGGER.debug("Unable to publish extraction staging directory %s: %s", staging_path, e)
            if backup_path is not None:
                os.replace(backup_path, destination)
                backup_path = None
            raise
    except Exception as e:
        try:
            _remove_path(staging_path)
        except Exception as cleanup_error:
            _LOGGER.warning(
                "Unable to clean up failed extraction staging directory %s after %s: %s",
                staging_path,
                e,
                cleanup_error,
            )
        raise
    else:
        if backup_path is not None:
            try:
                _remove_path(backup_path)
            except Exception as e:
                _LOGGER.warning("Unable to remove replaced extraction backup %s: %s", backup_path, e)
    return destination
