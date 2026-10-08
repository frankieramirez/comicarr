#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Shared, conservative fulfillment evidence helpers."""

from pathlib import Path


def resolve_library_root(series_location):
    """Return a strict series root, or None when it cannot prove ownership."""

    if not series_location:
        return None
    try:
        return Path(str(series_location)).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None


def has_verified_file_under_root(root, issue_location):
    """Return whether an issue path is an existing file beneath ``root``."""

    if root is None or not issue_location:
        return False
    try:
        raw = Path(str(issue_location)).expanduser()
        candidate = raw if raw.is_absolute() else root / raw
        candidate = candidate.resolve(strict=True)
        return candidate.is_relative_to(root) and candidate.is_file()
    except (OSError, RuntimeError, ValueError):
        return False


def has_verified_library_file(series_location, issue_location, retained_locations=()):
    """Return whether an issue path is an existing file beneath its series root.

    A non-empty migrated path is not ownership evidence. Resolving both paths
    strictly rejects missing paths and symlink escapes before the canonical API
    or repair manifest can label a row downloaded. An absolute path may instead
    sit beneath a folder the Series retained when its location changed and the
    operator left its files in place.
    """

    if has_verified_file_under_root(resolve_library_root(series_location), issue_location):
        return True
    if not issue_location or not Path(str(issue_location)).expanduser().is_absolute():
        return False
    return any(
        has_verified_file_under_root(resolve_library_root(retained), issue_location)
        for retained in retained_locations or ()
    )
