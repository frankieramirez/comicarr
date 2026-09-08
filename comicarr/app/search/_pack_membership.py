#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Private library lookup and legacy queue claims for release evaluation."""

import re

import comicarr
from comicarr import db, logger
from comicarr.app.manga.ledger import is_volume_target, volume_numbers_match
from comicarr.tables import issues


def _pack_row_matches(row, int_iss, iss_item, kind):
    """Decide whether one issues-table row belongs to a pack range entry.

    A volume pack (e.g. ``v01-14``) covers rows by their ``VolumeNumber``
    — including manga chapter rows that belong to a covered volume — but
    must never claim a chapter numbered like a volume (a chapter 7 with
    an unknown volume is not volume 7). Rows without volume metadata
    (TPB/GN-tracked series) fall back to the plain issue-number match.
    Issue/chapter packs symmetrically never claim volume rows.
    """
    volume = row.get("VolumeNumber")
    chapter = row.get("ChapterNumber")
    if kind == "volume":
        if volume not in (None, ""):
            return volume_numbers_match(volume, iss_item)
        if chapter not in (None, ""):
            return False
    elif is_volume_target(chapter, volume):
        return False
    return row["Int_IssueNumber"] == int_iss


def _register_pack_claims(write_valids, valid):
    if valid:
        for wv in write_valids:
            comicarr.PACK_ISSUEIDS_DONT_QUEUE[wv["issueid"]] = wv["pack_id"]


def _row_released_after(row, cutoff_year):
    """True when the row's first usable date is later than cutoff_year.

    A pack whose title span ends in ``cutoff_year`` cannot contain anything
    published after it. Rows with no parseable date (or the 0000-00-00
    sentinel) are not excluded — the pack keeps the benefit of the doubt.
    """
    for field in ("ReleaseDate", "IssueDate", "DigitalDate"):
        value = str(row.get(field) or "")
        if len(value) >= 4 and value[:4].isdigit() and int(value[:4]) > 0:
            return int(value[:4]) > cutoff_year
    return False


def issue_find_ids(ComicName, ComicID, pack, IssueNumber, pack_id, kind="issue", span_end=None):
    from sqlalchemy import select

    from comicarr.helpers import issuedigits

    issuelist = db.select_all(select(issues).where(issues.c.ComicID == ComicID))

    if kind == "series":
        try:
            cutoff = int(span_end)
        except (TypeError, ValueError):
            cutoff = None
        Int_IssueNumber = issuedigits(IssueNumber)
        issueinfo = []
        write_valids = []
        valid = False
        for xb in issuelist:
            if xb["Status"] == "Downloaded":
                continue
            if cutoff is not None and _row_released_after(xb, cutoff):
                continue
            if Int_IssueNumber == xb["Int_IssueNumber"]:
                valid = True
            issueinfo.append(
                {
                    "issueid": xb["IssueID"],
                    "int_iss": xb["Int_IssueNumber"],
                    "issuenumber": xb["Issue_Number"],
                }
            )
            write_valids.append({"issueid": xb["IssueID"], "pack_id": pack_id})
        _register_pack_claims(write_valids, valid)
        return {
            "issues": issueinfo,
            "issue_range": [x["issuenumber"] for x in issueinfo],
            "valid": valid,
        }

    if "Annual" not in pack:
        if "," not in pack:
            packlist = pack.split(" ")
            pack = re.sub("#", "", pack).strip()
        else:
            packlist = [x.strip() for x in pack.split(",")]
        plist = []
        pack_issues = []
        for pl in packlist:
            pl = re.sub("#", "", pl).strip()
            if "-" in pl:
                le_range = list(range(int(pack[: pack.find("-")]), int(pack[pack.find("-") + 1 :]) + 1))
                for x in le_range:
                    if not [y for y in plist if y == x]:
                        plist.append(int(x))
            else:
                if not [x for x in plist if x == int(pl)]:
                    plist.append(int(pl))

        for pi in plist:
            if type(pi) == list:
                for x in pi:
                    pack_issues.append(x)
            else:
                pack_issues.append(pi)
        pack_issues.sort()
    else:
        tmp_pack = re.sub("[annual/annuals/+]", "", pack.lower()).strip()
        pack_issues_numbers = re.findall(r"\d+", tmp_pack)
        pack_issues = list(range(int(pack_issues_numbers[0]), int(pack_issues_numbers[1]) + 1))

    iss = {}
    issueinfo = []
    write_valids = []

    Int_IssueNumber = issuedigits(IssueNumber)
    valid = False
    ignores = []
    for iss_item in pack_issues:
        int_iss = issuedigits(str(iss_item))
        for xb in issuelist:
            if xb["Status"] != "Downloaded":
                if _pack_row_matches(xb, int_iss, iss_item, kind):
                    if Int_IssueNumber == xb["Int_IssueNumber"]:
                        valid = True
                    issueinfo.append({"issueid": xb["IssueID"], "int_iss": int_iss, "issuenumber": xb["Issue_Number"]})
                    write_valids.append({"issueid": xb["IssueID"], "pack_id": pack_id})
                    if kind != "volume":
                        break
            else:
                ignores.append(iss_item)

    _register_pack_claims(write_valids, valid)

    iss["issues"] = issueinfo

    if len(iss["issues"]) == len(pack_issues):
        logger.fdebug(
            "Complete issue count of %s issues are available within this pack for %s" % (len(pack_issues), ComicName)
        )

    iss["issue_range"] = pack_issues
    iss["valid"] = valid
    return iss
