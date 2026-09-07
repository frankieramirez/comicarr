#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""Series edition inference for TPB / volume vs One-Shot.

ComicVine often lists a collected album as a one-issue Print volume whose
issue number is 1. The historical fallback then forced One-Shot once the
series year was in the past. That made a Vol. 1 / Book 1 trade look like a
standalone #1, and GetComics titles such as "Series Vol. 1 (2024)" failed
to match.

This helper is the single decision for that fallback. It does not invent a
title-specific override: a volume number, Book/Vol naming, or collected-
edition language keeps the series as a TPB (or HC/GN) instead of a one-shot.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterable

COLLECTED_TYPES = ("TPB", "HC", "GN")
EXPLICIT_TYPES = ("One-Shot", "TPB", "HC", "GN")

_VOLUME_OR_BOOK = re.compile(
    r"\b(?:vol(?:ume)?\.?|book)\s*\.?\s*(\d+)\b",
    re.IGNORECASE,
)
_TPB_WORD = re.compile(r"\btpb\b", re.IGNORECASE)
_EMPTY = {"", "none", "null"}


def _as_int(value):
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _EMPTY:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        digits = re.sub(r"[^0-9]", "", text)
        if not digits:
            return None
        try:
            return int(digits)
        except ValueError:
            return None


def _clean_text(*parts):
    chunks = []
    for part in parts:
        if part is None:
            continue
        text = str(part).strip()
        if text.lower() in _EMPTY:
            continue
        chunks.append(text)
    return " ".join(chunks)


def volume_number(volume):
    """Return the integer volume when metadata recorded one, else None."""
    return _as_int(volume)


def collected_edition_type(
    *,
    description=None,
    deck=None,
    issue_names=None,
    series_name=None,
    volume=None,
):
    """Return TPB, HC, or GN when metadata names a collected edition.

    A recorded volume number is enough: ComicVine uses that for album / book
    volumes even when the deck never says "paperback".
    """
    if volume_number(volume) is not None:
        return "TPB"

    names = list(issue_names or ())
    blob = _clean_text(description, deck, series_name, *names).lower()
    if not blob:
        return None

    if "hardcover" in blob and "hardcover can be found" not in blob:
        return "HC"
    if "graphic novel" in blob and "graphic novel can be found" not in blob:
        return "GN"
    if "trade paperback" in blob:
        return "TPB"
    if "paperback" in blob and "paperback can be found" not in blob:
        return "TPB"
    if _TPB_WORD.search(blob):
        return "TPB"
    if _VOLUME_OR_BOOK.search(blob):
        return "TPB"
    if "collecting" in blob or re.search(r"\bcollects\b", blob):
        return "TPB"
    return None


def resolve_series_edition(
    *,
    series_type,
    issue_count,
    series_year,
    current_year=None,
    volume=None,
    description=None,
    deck=None,
    issue_names: Iterable[str] | None = None,
    series_name=None,
):
    """Return the edition string stored on the series (Print, TPB, One-Shot, ...).

    Explicit ComicVine types are kept. A single-issue series with volume or
    collected-edition signals becomes TPB/HC/GN instead of being forced to
    One-Shot. The historic one-issue + past-year fallback still applies when
    nothing indicates a volume.
    """
    typed = None if series_type in (None, "", "None") else str(series_type)
    if typed in EXPLICIT_TYPES:
        return typed

    collected = collected_edition_type(
        description=description,
        deck=deck,
        issue_names=issue_names,
        series_name=series_name,
        volume=volume,
    )
    count = _as_int(issue_count)
    year = _as_int(series_year)
    current = _as_int(current_year)
    if current is None:
        current = datetime.date.today().year

    if collected and count == 1:
        return collected

    if count == 1 and year is not None and year < current:
        return "One-Shot"

    return typed
