#  Copyright (C) 2025-2026 Comicarr contributors
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

"""Normalize series names into the key Comicarr matches folders and pull lists by."""

import re

DYNAMIC_HANDLERS = [
    "/",
    "-",
    ":",
    ";",
    "'",
    '"',
    ",",
    "&",
    "?",
    "!",
    "+",
    "*",
    "(",
    ")",
    "\\u2014",
    "\\u2013",
    "\\u2019",
]
DYNAMIC_REPLACEMENTS = ["and", "the"]


def dynamic_series_name(series_name):
    """``series_name`` with punctuation and "and"/"the" marked as ``|`` wildcards.

    Moved unchanged from ``FileChecker.dynamic_replace`` (#1416).
    """
    series_name = re.sub(r"[\u2014|\u2013|\u2e3a|\u2e3b]", " - ", series_name)
    series_name = re.sub("\u2019", " ' ", series_name)
    seriesdynamic_handlers_match = [x for x in DYNAMIC_HANDLERS if x.lower() in series_name.lower()]
    seriesdynamic_replacements_match = [x for x in DYNAMIC_REPLACEMENTS if x.lower() in series_name.lower()]
    mod_seriesname = re.sub(r"[\s\s+\_\.]", "%$", series_name)
    mod_seriesname = re.sub(r"[\#]", "", mod_seriesname)
    ser_find = []
    sdrm_find = []
    if any([seriesdynamic_handlers_match, seriesdynamic_replacements_match]):
        for sdhm in seriesdynamic_handlers_match:
            ser_find.extend([m.start() for m in re.finditer("\\" + sdhm, mod_seriesname)])
            if len(ser_find) > 0:
                for sf in ser_find:
                    spacer = ""
                    for _i in range(0, len(sdhm)):
                        spacer += "|"
                    mod_seriesname = mod_seriesname[:sf] + spacer + mod_seriesname[sf + 1 :]

        for sdrm in seriesdynamic_replacements_match:
            sdrm_find.extend([m.start() for m in re.finditer(sdrm.lower(), mod_seriesname.lower())])
            if len(sdrm_find) > 0:
                for sd in sdrm_find:
                    spacer = ""
                    for _i in range(0, len(sdrm)):
                        spacer += "|"
                    mod_seriesname = mod_seriesname[:sd] + spacer + mod_seriesname[sd + len(sdrm) :]

    mod_seriesname = re.sub(r"\|+", "|", mod_seriesname)
    if mod_seriesname.endswith("|"):
        mod_seriesname = mod_seriesname[:-1]
    return re.sub(r"[\%\$]+", "", mod_seriesname)


def dynamic_series_key(series_name):
    """The ``DynamicComicName`` lookup key post-processing matches files against.

    Post-processing runs a filename's series through :func:`dynamic_series_name`
    and drops spaces and ``|`` before comparing it with this column, so every
    writer must store it the same way.
    """
    return re.sub(r"[\|\s]", "", dynamic_series_name(series_name).lower()).strip()
