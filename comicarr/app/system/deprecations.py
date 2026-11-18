#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The deprecation registry (ADR-0006).

One entry per deprecated feature. An operator hears about an entry only when
its ``in_use()`` says this install relies on it: one warning in the log at
startup, and a row in Activity > Health through ``GET /api/system/deprecations``.
"""

from __future__ import annotations

import calendar
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from sqlalchemy import exists, select

from comicarr.app.core import db, logger, runtime
from comicarr.app.core.tables import annuals, comics, issues, mcp_tool_calls, storyarcs


@dataclass(frozen=True)
class Deprecation:
    id: str
    name: str
    announced_in: str
    removable_from: str
    replacement: str
    docs_url: str
    in_use: Callable[[], bool]
    # Set only for a renamed MCP tool: the old name stays callable as an alias
    # of ``mcp_replacement`` until the entry is removed.
    mcp_tool: str | None = None
    mcp_replacement: str | None = None

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "announced_in": self.announced_in,
            "removable_from": self.removable_from,
            "replacement": self.replacement,
            "docs_url": self.docs_url,
        }


DOCS_URL = "https://comicarr.com/docs/deprecations"
ADD_MISSING_SERIES = "Add what's missing on the story arc, so its series join your library and the arc's issues download and copy to the arc folder the normal way"


def _arc_issue_wanted_without_library_issue() -> bool:
    in_library = exists().where(issues.c.IssueID == storyarcs.c.IssueID)
    in_annuals = exists().where(annuals.c.IssueID == storyarcs.c.IssueID)
    row = db.select_one(
        select(storyarcs.c.IssueArcID)
        .where(storyarcs.c.Status.in_(["Wanted", "Snatched"]), ~in_library, ~in_annuals)
        .limit(1)
    )
    return row is not None


def _arc_folder_matching_on() -> bool:
    if getattr(runtime.current().config, "STORYARCDIR", False) is not True:
        return False
    return db.select_one(select(storyarcs.c.StoryArcID).limit(1)) is not None


def _config_flag(name: str, value: object) -> bool:
    return getattr(runtime.current().config, name, None) == value


def _gcd_in_use() -> bool:
    if _config_flag("CV_ONLY", False):
        return True
    return db.select_one(select(comics.c.ComicID).where(comics.c.ComicID.like("G%")).limit(1)) is not None


# Integrations whose remote site stopped working. They were removed rather than
# ported (ADR-0007); the entries tell installs that still had them switched on.
DEAD_SITE_REMOVED_IN = "0.60.0"


MCP_TOOL_IN_USE_DAYS = 30


def mcp_tool_called_recently(name: str, days: int = MCP_TOOL_IN_USE_DAYS) -> bool:
    """True when an agent called the MCP tool ``name`` in the last ``days`` days.

    ``mcp_tool_calls`` is written at most hourly per name, so this can lag a
    call by up to an hour, which a 30-day window does not notice.
    """
    row = db.select_one(select(mcp_tool_calls.c.last_called_at).where(mcp_tool_calls.c.tool_name == name))
    if row is None:
        return False
    try:
        called = calendar.timegm(time.strptime(row["last_called_at"], "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return False
    return time.time() - called < days * 86400


def mcp_tool_rename(old_name: str, new_name: str, *, announced_in: str, removable_from: str) -> Deprecation:
    """The registry entry for an MCP tool renamed from ``old_name`` to ``new_name``.

    The server keeps ``old_name`` as a deprecated alias while the entry exists.
    """
    anchor = "mcp-tool-" + old_name.replace("_", "-")
    return Deprecation(
        id=anchor,
        name="The MCP tool %s" % old_name,
        announced_in=announced_in,
        removable_from=removable_from,
        replacement="The MCP tool %s, which does the same thing" % new_name,
        docs_url=DOCS_URL + "#" + anchor,
        in_use=partial(mcp_tool_called_recently, old_name),
        mcp_tool=old_name,
        mcp_replacement=new_name,
    )


def route_usage_key(entry_id: str) -> str:
    """The ``mcp_tool_calls`` row that records calls to a deprecated HTTP route.

    The table holds one last-called time per name, which is all an HTTP route
    needs too. The ``route:`` prefix keeps these names apart from MCP tools.
    """
    return "route:" + entry_id


def api_route_alias(
    entry_id: str, old_route: str, new_route: str, *, announced_in: str, removable_from: str, same: bool = True
) -> Deprecation:
    """The registry entry for a REST route kept as a deprecated alias of ``new_route``.

    ``same`` says the replacement takes the same request and returns the same
    answer. When it is false, the replacement does the job with a different
    request shape, and the entry says so.
    """
    replacement = "%s, which does the same thing" % new_route if same else "%s, which replaces it" % new_route
    return Deprecation(
        id=entry_id,
        name="The API route %s" % old_route,
        announced_in=announced_in,
        removable_from=removable_from,
        replacement=replacement,
        docs_url=DOCS_URL + "#" + entry_id,
        in_use=partial(mcp_tool_called_recently, route_usage_key(entry_id)),
    )


DUPLICATE_ROUTES_ANNOUNCED_IN = "0.64.0"


REGISTRY: list[Deprecation] = [
    Deprecation(
        id="storyarc-oneoff",
        name="Downloading story-arc issues whose series is not in your library",
        announced_in="0.52.0",
        removable_from="1.0.0",
        replacement=ADD_MISSING_SERIES,
        docs_url=DOCS_URL + "#storyarc-oneoff",
        in_use=_arc_issue_wanted_without_library_issue,
    ),
    Deprecation(
        id="storyarc-folder-match",
        name="Matching scanned files to a story arc when their series is not in your library",
        announced_in="0.52.0",
        removable_from="1.0.0",
        replacement=ADD_MISSING_SERIES,
        docs_url=DOCS_URL + "#storyarc-folder-match",
        in_use=_arc_folder_matching_on,
    ),
    Deprecation(
        id="removed-32p",
        name="The 32P torrent tracker (removed: the site is gone)",
        announced_in=DEAD_SITE_REMOVED_IN,
        removable_from=DEAD_SITE_REMOVED_IN,
        replacement="A torrent indexer added through Prowlarr or as a Torznab provider",
        docs_url=DOCS_URL + "#removed-32p",
        in_use=partial(_config_flag, "ENABLE_32P", True),
    ),
    Deprecation(
        id="removed-experimental-search",
        name="Experimental NZB search through NZBIndex (removed: its feed is gone)",
        announced_in=DEAD_SITE_REMOVED_IN,
        removable_from=DEAD_SITE_REMOVED_IN,
        replacement="A Usenet indexer added through Prowlarr or as a Newznab provider",
        docs_url=DOCS_URL + "#removed-experimental-search",
        in_use=partial(_config_flag, "EXPERIMENTAL", True),
    ),
    Deprecation(
        id="removed-gcd",
        name="Series data from the Grand Comics Database (removed: the site refuses its requests)",
        announced_in=DEAD_SITE_REMOVED_IN,
        removable_from=DEAD_SITE_REMOVED_IN,
        replacement="Add the series again from ComicVine so it keeps updating",
        docs_url=DOCS_URL + "#removed-gcd",
        in_use=_gcd_in_use,
    ),
    api_route_alias(
        "api-metadata-search",
        "POST /api/metadata/search",
        "POST /api/search/comics",
        announced_in=DUPLICATE_ROUTES_ANNOUNCED_IN,
        removable_from="1.0.0",
    ),
    api_route_alias(
        "api-metadata-search-manga",
        "POST /api/metadata/search/manga",
        "POST /api/search/manga",
        announced_in=DUPLICATE_ROUTES_ANNOUNCED_IN,
        removable_from="1.0.0",
    ),
    api_route_alias(
        "api-ai-chat-stream",
        "POST /api/ai/chat/stream",
        "POST /api/ai/chat/turns/stream",
        announced_in=DUPLICATE_ROUTES_ANNOUNCED_IN,
        removable_from="1.0.0",
        same=False,
    ),
]


def entry(entry_id: str) -> Deprecation:
    """The registry entry ``entry_id``. Raises ``KeyError`` for an unknown id."""
    for item in REGISTRY:
        if item.id == entry_id:
            return item
    raise KeyError(entry_id)


def deprecations_in_use() -> list[Deprecation]:
    """Entries this install relies on. A predicate that raises counts as not in use."""
    found = []
    for entry in REGISTRY:
        try:
            if entry.in_use():
                found.append(entry)
        except Exception as e:
            logger.error("[DEPRECATION] Could not tell whether %s is in use: %s" % (entry.id, e))
    return found


def warn_deprecations_in_use() -> None:
    """Log one warning per entry in use. Called once at startup."""
    for entry in deprecations_in_use():
        logger.warn(
            "[DEPRECATION] %s is deprecated since %s and may be removed from %s. Use instead: %s. See %s"
            % (entry.name, entry.announced_in, entry.removable_from, entry.replacement, entry.docs_url)
        )
