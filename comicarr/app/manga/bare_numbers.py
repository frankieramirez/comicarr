#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Per-series bare-number interpretation for manga filenames.

Prefixed tokens (`v10`, `c001`) always win. A bare number (`Naruto 12.cbr`)
is a volume, a chapter, or auto — auto compares the folder's bare-number
set to known volume and chapter counts.
"""

MODES = frozenset({"volumes", "chapters", "auto"})
DEFAULT_MODE = "auto"


def normalize_mode(value):
    if value is None:
        return DEFAULT_MODE
    mode = str(value).strip().lower()
    return mode if mode in MODES else DEFAULT_MODE


def interpret_bare_numbers(mode, *, bare_numbers, volume_count=None, chapter_count=None):
    """Return ``volumes`` or ``chapters`` for a folder of bare-numbered files.

    Rules (auto):
    1. If any bare number is greater than the known volume count, they are
       chapters (One Piece 1161 vs 115 volumes).
    2. Otherwise pick the ledger whose count is closer to the file count
       (19 files vs 72 volumes / 700 chapters → volumes).
    3. Tie → volumes when a volume count is known, else chapters.
    """
    mode = normalize_mode(mode)
    if mode in {"volumes", "chapters"}:
        return mode

    numbers = [int(n) for n in (bare_numbers or ()) if str(n).strip().isdigit()]
    file_count = len(numbers)
    vol_count = _as_int(volume_count)
    ch_count = _as_int(chapter_count)

    if vol_count is not None and numbers and max(numbers) > vol_count:
        return "chapters"
    if file_count == 0:
        return "chapters"

    vol_delta = abs(file_count - vol_count) if vol_count is not None else None
    ch_delta = abs(file_count - ch_count) if ch_count is not None else None
    if vol_delta is not None and ch_delta is not None:
        if vol_delta < ch_delta:
            return "volumes"
        if ch_delta < vol_delta:
            return "chapters"
        return "volumes"
    if vol_delta is not None:
        return "volumes"
    if ch_delta is not None:
        return "chapters"
    return "chapters"


def apply_bare_number(result, mode):
    """Rewrite a parser result that used the bare-number chapter group."""
    if not result or result.get("volume_number") is not None:
        return result
    if result.get("chapter_number") is None:
        return result
    if normalize_mode(mode) != "volumes":
        return result
    rewritten = dict(result)
    rewritten["volume_number"] = int(result["chapter_number"])
    rewritten["chapter_number"] = None
    return rewritten


def _as_int(value):
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
