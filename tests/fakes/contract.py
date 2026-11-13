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

"""Compare a live download-client response with its recording by shape.

The fakes replay recorded responses, so a recording is only as good as its
match with what the client sends today. ``differences`` walks a recording and
a live response together and reports where their shape differs: a key one has
and the other lacks, a value of another type, or a different status code.
Values themselves are ignored, because IDs, times, sizes and paths change on
every run.
"""

from __future__ import annotations

from collections.abc import Mapping

# Keys whose value is compared exactly rather than by type.
EXACT_KEYS = frozenset({"status_code"})


def _kind(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return type(value).__name__


def differences(recorded, live, path: str = "$") -> list[str]:
    """Every place ``live`` differs in shape from ``recorded``, as readable lines."""
    found: list[str] = []
    _compare(recorded, live, path, found)
    return found


def _compare(recorded, live, path, found):
    recorded_kind, live_kind = _kind(recorded), _kind(live)
    # A null on either side says nothing about the type the client would
    # send when it has a value, so it never counts as a mismatch.
    if "null" in (recorded_kind, live_kind):
        return
    if recorded_kind != live_kind:
        found.append("%s: recorded %s, live %s" % (path, recorded_kind, live_kind))
        return
    if recorded_kind == "object":
        for key in sorted(set(recorded) - set(live), key=str):
            found.append("%s.%s: in the recording, missing from the live response" % (path, key))
        for key in sorted(set(live) - set(recorded), key=str):
            found.append("%s.%s: in the live response, missing from the recording" % (path, key))
        for key in sorted(set(recorded) & set(live), key=str):
            child = "%s.%s" % (path, key)
            if key in EXACT_KEYS and recorded[key] != live[key]:
                found.append("%s: recorded %r, live %r" % (child, recorded[key], live[key]))
                continue
            _compare(recorded[key], live[key], child, found)
    elif recorded_kind == "array" and recorded and live:
        if len({_kind(item) for item in recorded}) > 1:
            # A mixed list is a tuple, such as XML-RPC call parameters:
            # position N always means the same thing.
            if len(recorded) != len(live):
                found.append("%s: recorded %d items, live %d" % (path, len(recorded), len(live)))
            for index, (expected, item) in enumerate(zip(recorded, live, strict=False)):
                _compare(expected, item, "%s[%d]" % (path, index), found)
            return
        # Items of one list share a shape; compare every live item with the
        # first recorded one, which is what the fakes build their entries from.
        for index, item in enumerate(live):
            _compare(recorded[0], item, "%s[%d]" % (path, index), found)


def compare_recordings(recorded: dict[str, dict], live: dict[str, dict]) -> dict[str, list[str]]:
    """Name -> differences for every recording, including ones the live run did not produce."""
    report = {}
    for name in sorted(recorded):
        if name not in live:
            report[name] = ["$: recorded, but the live run produced no response"]
            continue
        found = differences(recorded[name], live[name])
        if found:
            report[name] = found
    return report
