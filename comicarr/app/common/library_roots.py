#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import os

from comicarr.app.common.filesystem import is_path_within_allowed_dirs

_LIBRARY_ROOT_CONFIG_KEYS = (
    "DESTINATION_DIR",
    "MANGA_DESTINATION_DIR",
    "COMIC_DIR",
    "MANGA_DIR",
    "MULTIPLE_DEST_DIRS",
    "NEWCOM_DIR",
)
_SERVABLE_EXTRA_KEYS = ("STORYARC_LOCATION", "GRABBAG_DIR")


def _root_text(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or value.lower() == "none":
        return None
    return value


def additional_library_roots(config):
    """Return the absolute paths listed one per line in ADDITIONAL_LIBRARY_ROOTS."""
    raw = _root_text(getattr(config, "ADDITIONAL_LIBRARY_ROOTS", None)) if config is not None else None
    if raw is None:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip() and os.path.isabs(line.strip())]


def configured_library_roots(config):
    if config is None:
        return []
    roots = [root for root in (_root_text(getattr(config, key, None)) for key in _LIBRARY_ROOT_CONFIG_KEYS) if root]
    return roots + additional_library_roots(config)


def is_strict_library_descendant(path, config):
    if not isinstance(path, (str, os.PathLike)):
        return False

    roots = configured_library_roots(config)
    if not roots:
        return False

    try:
        return is_path_within_allowed_dirs(path, roots, strict=True)
    except (OSError, TypeError, ValueError):
        return False


def is_servable_library_file(path, config):
    """True when a file resolves inside a library root or the story-arc or grab-bag folder."""
    roots = configured_library_roots(config)
    if config is not None:
        roots += [root for root in (_root_text(getattr(config, key, None)) for key in _SERVABLE_EXTRA_KEYS) if root]
    try:
        return is_path_within_allowed_dirs(path, roots, strict=True)
    except (OSError, TypeError, ValueError):
        return False
