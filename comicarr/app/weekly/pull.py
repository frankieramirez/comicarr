#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Seam for the legacy weekly pull list (ADR-0005, #1203).

``comicarr/app/`` reaches ``weeklypull`` and ``weeklypullit`` only through
these functions. Each one delegates to the legacy body unchanged; the bodies
move behind this module later, one stage at a time.
"""

from __future__ import annotations

from typing import Any


def run_weekly_refresh() -> None:
    """Run the scheduled Weekly Pullist job once: fetch, match, future check.

    Records job status as the scheduler job does and re-raises a failed pull.
    """
    from comicarr import weeklypullit

    weeklypullit.Weekly().run()


def fetch_pull_list(
    forcecheck: str | None = None,
    weeknumber: int | str | None = None,
    year: int | str | None = None,
) -> dict[str, Any] | None:
    """Load the pull list from its configured source and match it to the library.

    With the default source the result is ``{"status": ...}`` plus optional
    ``retry_after``, ``origin_error``, ``cause`` and ``source``; other sources
    return ``None``.
    """
    from comicarr import weeklypull

    return weeklypull.pullit(forcecheck=forcecheck, weeknumber=weeknumber, year=year)


def match_pull_list(weeknumber: int | str, year: int | str) -> None:
    """Match one stored pull-list week against the library, marking issues Wanted."""
    from comicarr import weeklypull

    weeklypull.new_pullcheck(weeknumber, year)


def check_future_releases() -> None:
    """Look up new series on the future pull list and add the auto-watched ones."""
    from comicarr import weeklypull

    weeklypull.future_check()
