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

"""Read a date out of free text (ComicVine descriptions, release names).

Moved unchanged from ``FileChecker.checkthedate`` (#1415).
"""

import datetime as dt
import re

from comicarr.app.common import strings as common_strings


def parse_text_date(txt, fulldate=False, cnt=0):

    fmts = (
        "%Y",
        "%Y-",
        "%b %d, %Y",
        "%B %d, %Y",
        "%B %d %Y",
        "%m/%d/%Y",
        "%m/%d/%y",
        "(%m/%d/%Y)",
        "%b %Y",
        "%B%Y",
        "%b %d,%Y",
        "%m-%Y",
        "%B %Y",
        "%Y-%m-%d",
        "%Y-%m",
        "%Y%m",
        "%Y-%m-00",
    )
    mnths = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    parsed = []

    if fulldate is False:
        for e in txt.splitlines():
            for fmt in fmts:
                try:
                    t = dt.datetime.strptime(e, fmt)
                    parsed.append((e, fmt, t))
                    break
                except ValueError:
                    pass
    else:
        for e in txt.split():
            if cnt == 0:
                for x in mnths:
                    mnth = re.sub(r"\.", "", e.lower())
                    if x.lower() in mnth and len(mnth) <= 4:
                        add_date = x + " "
                        cnt += 1
                        break

            elif cnt == 1:
                issnumb = re.sub(",", "", e).strip()
                if issnumb.isdigit() and int(issnumb) < 31:
                    add_date += issnumb + ", "
                    cnt += 1
            elif cnt == 2:
                possyear = common_strings.cleanhtml(re.sub(r"\.", "", e).strip())
                if type(possyear) == bytes:
                    possyear = possyear.decode("utf-8")
                if possyear.isdigit() and int(possyear) > 1970 and int(possyear) < 2020:
                    add_date += possyear
                    cnt += 1
            if cnt == 3:
                return parse_text_date(add_date, fulldate=False, cnt=-1)

            if cnt <= 0:
                for fmt in fmts:
                    try:
                        t = dt.datetime.strptime(e, fmt)
                        parsed.append((e, fmt, t))
                        break
                    except ValueError:
                        pass
    dateline = None

    for t in parsed:
        if fulldate is False and cnt != -1:
            dateline = t[2].year
        else:
            dateline = t[2].strftime("%Y-%m-%d")
        break

    return dateline
