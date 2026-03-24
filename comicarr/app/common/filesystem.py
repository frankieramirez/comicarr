#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Filesystem utilities extracted from helpers.py.

is_path_within_allowed_dirs requires config access — takes allowed_dirs
as a parameter to stay free of global state.
"""

import os


def is_path_within_allowed_dirs(path, allowed_dirs):
    """Check if a path is within any of the allowed directories.

    Uses os.path.realpath + os.path.commonpath to prevent path traversal.
    Unlike the original helpers.py version, this takes allowed_dirs as a
    parameter instead of reading from global config.
    """
    real_path = os.path.realpath(path)
    for root in allowed_dirs:
        if not root:
            continue
        real_root = os.path.realpath(root)
        try:
            if os.path.commonpath([real_root, real_path]) == real_root:
                return True
        except ValueError:
            continue
    return False
