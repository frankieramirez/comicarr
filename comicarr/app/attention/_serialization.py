#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Private compatibility serialization for immutable Attention contracts."""

from comicarr.app.attention._policy import cause_copy


def serialize_member(member):
    return {
        "release_key": member.release_key,
        "issue_label": member.issue_label,
        "issueid": member.issue_id,
        "stage": member.stage,
        "available_actions": list(member.available_actions),
        "updated_date": member.updated_at,
    }


def serialize_group(group):
    return {
        "group_key": group.group_key,
        "comicid": group.comic_id,
        "series_label": group.series_label,
        "base_reason": group.base_reason,
        "reason_phrase": group.reason_phrase,
        "member_count": group.member_count,
        "newest_updated_at": group.newest_updated_at,
        "oldest_updated_at": group.oldest_updated_at,
        "members": [serialize_member(member) for member in group.members],
        "stage": group.stage,
        "available_actions": list(group.available_actions),
    }


def serialize_groups(groups):
    return [serialize_group(group) for group in groups]


def _cause_key(group):
    return "%s|%s" % (group.base_reason or "", group.stage or "")


def serialize_causes(groups):
    """Fold series groups that share one base reason and stage into a cause.

    A cause is what the dashboard's "Needs you" row shows: one problem, every
    series it touches, and the release keys a single action resolves. Stage is
    part of the key so a cause's actions are never a guess across stages; a
    mixed-stage group stays its own cause with no actions, as it does today.
    Causes are ordered by how many issues they hold, then by recency.
    """
    buckets = {}
    for group in groups:
        key = _cause_key(group)
        bucket = buckets.get(key)
        if bucket is None:
            copy = cause_copy(group.base_reason)
            bucket = {
                "cause_key": key,
                "base_reason": group.base_reason,
                "reason_phrase": group.reason_phrase,
                "headline": copy["headline"],
                "hint": copy["hint"],
                "icon": copy["icon"],
                "fix": copy["fix"],
                "stage": group.stage,
                "available_actions": list(group.available_actions),
                "series_count": 0,
                "member_count": 0,
                "newest_updated_at": group.newest_updated_at,
                "series": [],
                "release_keys": [],
            }
            buckets[key] = bucket
        bucket["series_count"] += 1
        bucket["member_count"] += group.member_count
        bucket["series"].append(
            {
                "group_key": group.group_key,
                "comicid": group.comic_id,
                "series_label": group.series_label,
                "member_count": group.member_count,
                "issue_labels": [member.issue_label for member in group.members[:3]],
            }
        )
        bucket["release_keys"].extend(member.release_key for member in group.members)
        if (group.newest_updated_at or "") > (bucket["newest_updated_at"] or ""):
            bucket["newest_updated_at"] = group.newest_updated_at

    causes = list(buckets.values())
    for cause in causes:
        cause["series"].sort(key=lambda series: (-series["member_count"], series["series_label"] or ""))
    causes.sort(key=lambda cause: (cause["newest_updated_at"] or "", cause["cause_key"]), reverse=True)
    causes.sort(key=lambda cause: cause["member_count"], reverse=True)
    return causes


def serialize_view(view, *, preview_cap):
    return {
        "results": serialize_groups(view.groups),
        "causes": serialize_causes(view.groups),
        "total": view.total,
        "member_total": view.member_total,
        "preview_cap": preview_cap,
    }
