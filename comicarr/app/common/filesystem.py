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

import logging
import os


def is_path_within_allowed_dirs(path, allowed_dirs, *, strict=False):
    """Check if a path is within any of the allowed directories.

    Uses os.path.realpath + os.path.commonpath to prevent path traversal.
    Unlike the original helpers.py version, this takes allowed_dirs as a
    parameter instead of reading from global config.

    When strict=True, the path must be a real descendant of a root — equality
    with a root is rejected (needed for destructive operations that must never
    target a configured library root itself). Overbroad roots that realpath to
    the filesystem root are ignored in strict mode so they cannot authorize
    arbitrary absolute paths.
    """
    real_path = os.path.realpath(path)
    for root in allowed_dirs:
        if not root:
            continue
        real_root = os.path.realpath(root)
        if strict and real_root == os.sep:
            continue
        if strict and real_path == real_root:
            continue
        try:
            if os.path.commonpath([real_root, real_path]) == real_root:
                return True
        except ValueError:
            continue
    return False


def checkFolder(folderpath=None, check_folder=None, postprocessor=None, queue_cls=None):
    """Validate/create directory and run post-processing on snatched files.

    Takes dependencies as parameters to stay free of global state.
    The wrapper in helpers.py passes in the comicarr globals.
    """
    import queue as queue_module

    log = logging.getLogger("comicarr")
    q = queue_module.Queue()
    if folderpath is None:
        log.info("Checking folder " + check_folder + " for newly snatched downloads")
        path = check_folder
    else:
        log.info("Submitted folder " + folderpath + " for direct folder post-processing")
        path = folderpath

    PostProcess = postprocessor.PostProcessor("Manual Run", path, queue=q)
    PostProcess.Process()
    return
