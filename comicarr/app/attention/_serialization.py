#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Private compatibility serialization for immutable Attention contracts."""


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


def serialize_view(view, *, preview_cap):
    return {
        "results": serialize_groups(view.groups),
        "total": view.total,
        "member_total": view.member_total,
        "preview_cap": preview_cap,
    }
