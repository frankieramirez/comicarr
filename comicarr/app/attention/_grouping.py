#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Private grouping implementation for Needs attention."""

from comicarr.app.attention._policy import STAGE_ACTIONS, base_reason, reason_phrase
from comicarr.app.attention.contracts import AttentionGroup, AttentionMember
from comicarr.app.downloads import journal

MIXED_STAGE = "mixed"


def _payload_of(row):
    payload = journal.load_payload(row.get("payload_json"))
    return payload if isinstance(payload, dict) else {}


def _text(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _short_release_key(release_key):
    key = _text(release_key) or ""
    tail = key.rsplit("|", 1)[-1]
    return tail[:24] if tail else key[:24]


def _series_key(payload, release_key):
    comicid = _text(payload.get("comicid")) or _text(payload.get("ComicID"))
    if comicid:
        return comicid, True
    return _text(release_key) or "", False


def _group_key(series_identity, reason_token):
    return "%s|%s" % (series_identity, reason_token or "")


def _series_label(payload, release_key, has_comicid):
    name = _text(payload.get("comicname")) or _text(payload.get("ComicName"))
    if name:
        return name
    if has_comicid:
        comicid = _text(payload.get("comicid")) or _text(payload.get("ComicID"))
        return "Series %s" % comicid
    nzbname = _text(payload.get("nzbname")) or _text(payload.get("nzb_name"))
    if nzbname:
        return nzbname
    return _short_release_key(release_key)


def _member_label(row, payload):
    name = _text(payload.get("comicname")) or _text(payload.get("ComicName"))
    number = _text(payload.get("issuenumber")) or _text(payload.get("Issue_Number"))
    if name and number:
        return "%s #%s" % (name, number)
    if name:
        return name
    nzbname = _text(payload.get("nzbname")) or _text(payload.get("nzb_name")) or _text(row.get("nzbname"))
    if nzbname:
        return nzbname
    issueid = _text(row.get("issueid")) or _text(payload.get("issueid"))
    if issueid:
        return "issue %s" % issueid
    return _short_release_key(row.get("release_key"))


def _member_actions(stage):
    return tuple(STAGE_ACTIONS.get(stage, ()))


def _available_actions(stages):
    if len(stages) != 1:
        return ()
    return _member_actions(next(iter(stages)))


def _stage_of(stages):
    if len(stages) == 1:
        return next(iter(stages))
    return MIXED_STAGE


def build_groups(rows):
    """Group admitted rows by series identity and base reason, newest first."""
    buckets = {}
    order = []

    for row in rows or []:
        payload = _payload_of(row)
        release_key = row.get("release_key")
        identity, has_comicid = _series_key(payload, release_key)
        token = base_reason(row.get("fail_reason"))
        key = _group_key(identity, token)
        updated = _text(row.get("updated_date")) or ""
        member = AttentionMember(
            release_key=release_key,
            issue_label=_member_label(row, payload),
            issue_id=_text(row.get("issueid")) or _text(payload.get("issueid")),
            stage=row.get("stage"),
            available_actions=_member_actions(row.get("stage")),
            updated_at=row.get("updated_date"),
        )

        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "group_key": key,
                "comicid": identity if has_comicid else None,
                "series_label": _series_label(payload, release_key, has_comicid),
                "base_reason": token,
                "reason_phrase": reason_phrase(row.get("fail_reason")),
                "member_count": 0,
                "newest_updated_at": updated,
                "oldest_updated_at": updated,
                "members": [],
                "_stages": set(),
            }
            buckets[key] = bucket
            order.append(key)

        bucket["member_count"] += 1
        bucket["members"].append(member)
        bucket["_stages"].add(row.get("stage"))
        if updated > (bucket["newest_updated_at"] or ""):
            bucket["newest_updated_at"] = updated
        if not bucket["oldest_updated_at"] or (updated and updated < bucket["oldest_updated_at"]):
            bucket["oldest_updated_at"] = updated

    groups = []
    for key in order:
        bucket = buckets[key]
        stages = bucket["_stages"]
        groups.append(
            AttentionGroup(
                group_key=bucket["group_key"],
                comic_id=bucket["comicid"],
                series_label=bucket["series_label"],
                base_reason=bucket["base_reason"],
                reason_phrase=bucket["reason_phrase"],
                member_count=bucket["member_count"],
                newest_updated_at=bucket["newest_updated_at"],
                oldest_updated_at=bucket["oldest_updated_at"],
                stage=_stage_of(stages),
                available_actions=_available_actions(stages),
                members=tuple(bucket["members"]),
            )
        )

    groups.sort(key=lambda group: (group.newest_updated_at or "", group.group_key), reverse=True)
    return tuple(groups)
