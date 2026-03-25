#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Date/time utilities extracted from helpers.py.

Pure functions — no comicarr imports, no side effects.
"""

import datetime
import os
import time
from datetime import date, timedelta


def today():
    """Return today's date as ISO format string (YYYY-MM-DD)."""
    return datetime.date.isoformat(datetime.date.today())


def now(format_string=None):
    """Return current datetime as formatted string."""
    if format_string is None:
        format_string = "%Y-%m-%d %H:%M:%S"
    return datetime.datetime.now().strftime(format_string)


def utctimestamp():
    """Return current UTC timestamp as float."""
    return time.time()


def utc_date_to_local(run_time):
    """Convert a UTC datetime to local datetime."""
    pr = (run_time - datetime.datetime.utcfromtimestamp(0)).total_seconds()
    try:
        return datetime.datetime.fromtimestamp(int(pr))
    except Exception:
        return datetime.datetime.fromtimestamp(pr)


def convert_milliseconds(ms):
    """Convert milliseconds to HH:MM:SS or MM:SS string."""
    seconds = ms / 1000
    gmtime = time.gmtime(seconds)
    if seconds > 3600:
        return time.strftime("%H:%M:%S", gmtime)
    return time.strftime("%M:%S", gmtime)


def convert_seconds(s):
    """Convert seconds to HH:MM:SS or MM:SS string."""
    gmtime = time.gmtime(s)
    if s > 3600:
        return time.strftime("%H:%M:%S", gmtime)
    return time.strftime("%M:%S", gmtime)


def fullmonth(monthno):
    """Convert a month number to its full name (e.g., 1 -> 'January')."""
    basmonths = {
        "1": "January",
        "2": "February",
        "3": "March",
        "4": "April",
        "5": "May",
        "6": "June",
        "7": "July",
        "8": "August",
        "9": "September",
        "10": "October",
        "11": "November",
        "12": "December",
    }

    monthconv = None

    for numbs in basmonths:
        if int(numbs) == int(monthno):
            monthconv = basmonths[numbs]

    return monthconv


def humanize_time(amount, units="seconds"):
    """Convert a time amount to a human-readable string."""

    def process_time(amount, units):

        INTERVALS = [
            1,
            60,
            60 * 60,
            60 * 60 * 24,
            60 * 60 * 24 * 7,
            60 * 60 * 24 * 7 * 4,
            60 * 60 * 24 * 7 * 4 * 12,
            60 * 60 * 24 * 7 * 4 * 12 * 100,
            60 * 60 * 24 * 7 * 4 * 12 * 100 * 10,
        ]
        NAMES = [
            ("second", "seconds"),
            ("minute", "minutes"),
            ("hour", "hours"),
            ("day", "days"),
            ("week", "weeks"),
            ("month", "months"),
            ("year", "years"),
            ("century", "centuries"),
            ("millennium", "millennia"),
        ]

        result = []

        unit = [a[1] for a in NAMES].index(units)
        # Convert to seconds
        amount = amount * INTERVALS[unit]

        for i in range(len(NAMES) - 1, -1, -1):
            a = amount // INTERVALS[i]
            if a > 0:
                result.append((a, NAMES[i][1 % a]))
                amount -= a * INTERVALS[i]

        return result

    rd = process_time(int(amount), units)
    cont = 0
    for u in rd:
        if u[0] > 0:
            cont += 1

    buf = ""
    i = 0
    for u in rd:
        if u[0] > 0:
            buf += "%d %s" % (u[0], u[1])
            cont -= 1

        if i < (len(rd) - 1):
            if cont > 1:
                buf += ", "
            else:
                buf += " and "

        i += 1

    return buf


def date_conversion(originaldate):
    """Return the number of hours elapsed between originaldate and now."""
    c_obj_date = datetime.datetime.strptime(originaldate, "%Y-%m-%d %H:%M:%S")
    n_date = datetime.datetime.now()
    absdiff = abs(n_date - c_obj_date)
    hours = (absdiff.days * 24 * 60 * 60 + absdiff.seconds) / 3600.0
    return hours


def weekly_info(week=None, year=None, current=None,
                weekfolder_loc=None, destination_dir=None,
                weekfolder_format=None, sched_weekly_last=None):
    """Calculate week start/end dates and navigation info.

    Takes config values as parameters to stay free of global state.
    The wrapper in helpers.py passes in the comicarr globals.
    """
    # find the current week and save it as a reference point.
    todaydate = datetime.datetime.today()
    if todaydate.year == 2025:
        current_weeknumber = todaydate.isocalendar()[1]
    else:
        current_weeknumber = int(todaydate.strftime("%U"))
    if current is not None:
        c_weeknumber = int(current[: current.find("-")])
        c_weekyear = int(current[current.find("-") + 1 :])
    else:
        c_weeknumber = week
        c_weekyear = year

    if week:
        weeknumber = int(week)
        year = int(year)
    else:
        # find the given week number for the current day
        weeknumber = current_weeknumber
        year = int(todaydate.strftime("%Y"))

    # monkey patch for 2018/2019 - week 52/week 0
    if all([weeknumber == 52, c_weeknumber == 51, c_weekyear == 2018]):
        weeknumber = 0
        year = 2019
    elif all([weeknumber == 52, c_weeknumber == 0, c_weekyear == 2019]):
        weeknumber = 51
        year = 2018

    # monkey patch for 2019/2020 - week 52/week 0
    if all([weeknumber == 52, c_weeknumber == 51, c_weekyear == 2019]) or all([weeknumber == "52", year == "2019"]):
        weeknumber = 0
        year = 2020
    elif all([weeknumber == 52, c_weeknumber == 0, c_weekyear == 2020]):
        weeknumber = 51
        year = 2019

    # monkey patch for 2020/2021 - week 52/week 0
    if all([int(weeknumber) == 0, int(year) == 2021]) or all([int(weeknumber) == 52, int(year) == 2020]):
        weeknumber = 52
        year = 2020

    # monkey patch for 2021/2022 - week 52/week 0
    if all([int(weeknumber) == 0, int(year) == 2022]) or all([int(weeknumber) == 52, int(year) == 2021]):
        weeknumber = 52
        year = 2021

    # monkey patch for 2024/2025 - week 52/week 0
    if all([weeknumber == 52, c_weeknumber == 51, c_weekyear == 2024]) or all([weeknumber == "52", year == "2024"]):
        weeknumber = 1
        year = 2025
    elif any([weeknumber == 52, weeknumber == 0]) and all([c_weeknumber == 1, c_weekyear == 2025]):
        weeknumber = 51
        year = 2024

    startofyear = date(year, 1, 1)
    week0 = startofyear - timedelta(days=startofyear.isoweekday())
    stweek = datetime.datetime.strptime(week0.strftime("%Y-%m-%d"), "%Y-%m-%d")
    if year == 2025:
        startweek = stweek + timedelta(weeks=weeknumber - 1)
    else:
        startweek = stweek + timedelta(weeks=weeknumber)

    midweek = startweek + timedelta(days=3)
    endweek = startweek + timedelta(days=6)

    if all([weeknumber == 1, year == 2021]):
        # make sure the arrow going back will hit the correct week in the previous year.
        prev_week = 52
        prev_year = 2020
    elif all([weeknumber == 0, year == 2022]):
        # make sure the arrow going back will hit the correct week in the previous year.
        prev_week = 52
        prev_year = 2021
    elif all([weeknumber == 0, year == 2025]):
        # make sure the arrow going back will hit the correct week in the previous year.
        prev_week = 51
        prev_year = 2024
    else:
        prev_week = int(weeknumber) - 1
        prev_year = year
        if prev_week < 0:
            prev_week = 52
            prev_year = int(year) - 1

    next_week = int(weeknumber) + 1
    next_year = year
    if next_week > 52:
        next_year = int(year) + 1
        if all([weeknumber == 52, year == 2020]):
            # make sure the next arrow will hit the correct week in the following year.
            next_week = "1"
        elif all([weeknumber == 52, year == 2021]):
            # make sure the next arrow will hit the correct week in the following year.
            next_week = "1"
        elif all([weeknumber == 51, year == 2024]):
            # make sure the next arrow will hit the correct week in the following year.
            next_week = "1"
        else:
            next_week = datetime.date(int(next_year), 1, 1).strftime("%U")

    date_fmt = "%B %d, %Y"
    try:
        con_startweek = "" + startweek.strftime(date_fmt)
        con_endweek = "" + endweek.strftime(date_fmt)
    except:
        con_startweek = "" + startweek.strftime(date_fmt)
        con_endweek = "" + endweek.strftime(date_fmt)

    if weekfolder_loc is not None:
        weekdst = weekfolder_loc
    else:
        weekdst = destination_dir

    if sched_weekly_last is not None:
        weekly_stamp = datetime.datetime.fromtimestamp(sched_weekly_last)
        weekly_last = weekly_stamp.replace(microsecond=0)
    else:
        weekly_last = "None"

    weekinfo = {
        "weeknumber": weeknumber,
        "startweek": con_startweek,
        "midweek": midweek.strftime("%Y-%m-%d"),
        "endweek": con_endweek,
        "year": year,
        "prev_weeknumber": prev_week,
        "prev_year": prev_year,
        "next_weeknumber": next_week,
        "next_year": next_year,
        "current_weeknumber": current_weeknumber,
        "last_update": weekly_last,
    }

    if weekdst is not None:
        if weekfolder_format == 0:
            weekn = weeknumber
            if len(str(weekn)) == 1:
                weekn = "%s%s" % ("0", str(weekn))
            weekfold = os.path.join(weekdst, "%s-%s" % (weekinfo["year"], weekn))
        else:
            weekfold = os.path.join(weekdst, str(str(weekinfo["midweek"])))
    else:
        weekfold = None

    weekinfo["week_folder"] = weekfold

    return weekinfo
