#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Small, import-safe helpers for Comicarr's PID-file lifecycle."""

import sys
from pathlib import Path


def check_stale_pidfile(pidfile, *, platform_name=None, proc_root="/proc"):
    """Return whether a Linux PID file is stale without starting Comicarr.

    Unsupported platforms deliberately return ``False`` because there is no
    portable process-command-line check with the same certainty as Linux
    ``/proc``. A numeric PID whose command line does not mention Python is
    treated as stale so a non-Comicarr process cannot hold the PID file.
    """
    platform_name = platform_name or sys.platform
    proc_root = Path(proc_root)
    if platform_name != "linux" or not proc_root.exists():
        return False

    try:
        value = Path(pidfile).read_text(encoding="utf-8").strip()
    except OSError:
        return False

    if not value.isdigit():
        return True

    cmdline_path = proc_root / value / "cmdline"
    if not cmdline_path.exists():
        return True

    try:
        cmdline = cmdline_path.read_text(encoding="utf-8", errors="replace").replace("\0", " ")
    except OSError:
        return False

    return "python" not in cmdline.lower()
