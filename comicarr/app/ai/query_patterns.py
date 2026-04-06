#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Parameterized query patterns for natural language library chat.

Each pattern maps a user intent to a safe, parameterized SQL query.
The LLM selects a pattern_id and provides parameter values; execution
uses only positional placeholders (?) to prevent SQL injection.
"""

import re

from comicarr import db, logger

QUERY_PATTERNS = {
    "search_series": {
        "description": "Search series by name (fuzzy)",
        "sql": "SELECT ComicID, ComicName, ComicYear, ComicPublisher, Have, Total, ComicImage, Status FROM comics WHERE LOWER(ComicName) LIKE LOWER(?) LIMIT ?",
        "params": ["name", "limit"],
        "defaults": {"limit": 20},
    },
    "completion_filter": {
        "description": "Filter series by completion percentage",
        "sql": "SELECT ComicID, ComicName, ComicYear, Have, Total, ComicImage, CASE WHEN Total > 0 THEN CAST(Have AS FLOAT) / Total * 100 ELSE 0 END as pct FROM comics WHERE Status != 'Paused' HAVING pct >= ? AND pct <= ? ORDER BY pct DESC LIMIT ?",
        "params": ["min_pct", "max_pct", "limit"],
        "defaults": {"limit": 20},
    },
    "series_with_gaps": {
        "description": "Find series with most/fewest gaps",
        "sql": "SELECT ComicID, ComicName, ComicYear, Have, Total, (Total - Have) as gaps, ComicImage FROM comics WHERE Total > 0 AND Status != 'Paused' ORDER BY gaps %s LIMIT ?",
        "params": ["order", "limit"],
        "defaults": {"order": "DESC", "limit": 10},
    },
    "issues_by_status": {
        "description": "List issues by status",
        "sql": "SELECT i.IssueID, i.ComicName, i.Issue_Number, i.Status, i.IssueDate, c.ComicID, c.ComicImage FROM issues i JOIN comics c ON i.ComicID = c.ComicID WHERE i.Status = ? LIMIT ?",
        "params": ["status", "limit"],
        "defaults": {"limit": 20},
    },
    "series_by_publisher": {
        "description": "Find series by publisher",
        "sql": "SELECT ComicID, ComicName, ComicYear, ComicPublisher, Have, Total, ComicImage FROM comics WHERE LOWER(ComicPublisher) LIKE LOWER(?) LIMIT ?",
        "params": ["publisher", "limit"],
        "defaults": {"limit": 20},
    },
    "recently_added": {
        "description": "Recently added issues",
        "sql": "SELECT s.ComicName, s.Issue_Number, s.DateAdded, s.Provider, s.ComicID, c.ComicImage FROM snatched s LEFT JOIN comics c ON s.ComicID = c.ComicID ORDER BY s.DateAdded DESC LIMIT ?",
        "params": ["limit"],
        "defaults": {"limit": 10},
    },
    "series_issues": {
        "description": "List issues for a series",
        "sql": "SELECT i.IssueID, i.Issue_Number, i.Status, i.IssueDate, i.ComicName FROM issues i JOIN comics c ON i.ComicID = c.ComicID WHERE LOWER(c.ComicName) LIKE LOWER(?) ORDER BY i.Int_IssueNumber LIMIT ?",
        "params": ["series_name", "limit"],
        "defaults": {"limit": 50},
    },
    "series_by_year": {
        "description": "Find series by year/decade",
        "sql": "SELECT ComicID, ComicName, ComicYear, ComicPublisher, Have, Total, ComicImage FROM comics WHERE CAST(ComicYear AS INTEGER) >= ? AND CAST(ComicYear AS INTEGER) <= ? LIMIT ?",
        "params": ["year_start", "year_end", "limit"],
        "defaults": {"limit": 20},
    },
    "download_history": {
        "description": "Download history",
        "sql": "SELECT ComicName, Issue_Number, DateAdded, Status, Provider, ComicID FROM snatched ORDER BY DateAdded DESC LIMIT ?",
        "params": ["limit"],
        "defaults": {"limit": 20},
    },
    "incomplete_arcs": {
        "description": "Incomplete story arcs",
        "sql": "SELECT StoryArc, COUNT(*) as total, SUM(CASE WHEN Status = 'Downloaded' THEN 1 ELSE 0 END) as have FROM storyarcs GROUP BY StoryArc HAVING (total - have) >= ? ORDER BY (total - have) DESC LIMIT ?",
        "params": ["min_missing", "limit"],
        "defaults": {"min_missing": 1, "limit": 10},
    },
}

# Allowed ORDER BY directions — whitelist to prevent injection
_ALLOWED_ORDERS = {"ASC", "DESC"}

# Allowed issue statuses — whitelist for the issues_by_status pattern
_ALLOWED_STATUSES = {"Wanted", "Downloaded", "Snatched", "Skipped", "Archived"}

# Maximum result limit to prevent resource exhaustion
_MAX_LIMIT = 100


def _validate_order(value):
    """Validate an ORDER BY direction against a whitelist."""
    upper = str(value).upper().strip()
    if upper not in _ALLOWED_ORDERS:
        return "DESC"
    return upper


def _validate_limit(value):
    """Validate and clamp a LIMIT parameter."""
    try:
        limit = int(value)
    except (ValueError, TypeError):
        return 20
    if limit < 1:
        return 1
    if limit > _MAX_LIMIT:
        return _MAX_LIMIT
    return limit


def _validate_numeric(value, default=0):
    """Validate a numeric parameter."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _validate_string(value):
    """Validate a string parameter, stripping dangerous characters."""
    if not value:
        return ""
    s = str(value)
    # Remove characters that could break SQL even in parameterized queries
    s = re.sub(r"[;'\"\\\x00]", "", s)
    return s.strip()


def _validate_status(value):
    """Validate an issue status against a whitelist."""
    s = str(value).strip()
    # Try case-insensitive match
    for allowed in _ALLOWED_STATUSES:
        if s.lower() == allowed.lower():
            return allowed
    return "Wanted"


def execute_pattern(pattern_id, params):
    """Execute a query pattern with validated parameters.

    Returns a list of row dicts on success, or raises ValueError
    if the pattern_id is unknown.
    """
    if pattern_id not in QUERY_PATTERNS:
        raise ValueError("Unknown query pattern: %s" % pattern_id)

    pattern = QUERY_PATTERNS[pattern_id]
    sql_template = pattern["sql"]
    param_names = pattern["params"]
    defaults = pattern.get("defaults", {})

    # Merge defaults with provided params
    merged = dict(defaults)
    if params:
        merged.update(params)

    # Build the query arguments list based on the pattern
    query_args = []
    final_sql = sql_template

    for name in param_names:
        raw_value = merged.get(name, defaults.get(name))

        if name == "order":
            # ORDER BY direction is injected via string formatting (whitelisted)
            validated = _validate_order(raw_value)
            final_sql = final_sql % validated
            continue
        elif name in ("limit",):
            query_args.append(_validate_limit(raw_value))
        elif name in ("min_pct", "max_pct", "year_start", "year_end", "min_missing"):
            query_args.append(_validate_numeric(raw_value, 0))
        elif name == "status":
            query_args.append(_validate_status(raw_value))
        elif name in ("name", "publisher", "series_name"):
            # Wrap with % for LIKE queries
            clean = _validate_string(raw_value)
            if clean and not clean.startswith("%"):
                clean = "%" + clean
            if clean and not clean.endswith("%"):
                clean = clean + "%"
            query_args.append(clean)
        else:
            query_args.append(_validate_string(raw_value))

    try:
        rows = db.raw_select_all(final_sql, query_args)
        return rows if rows else []
    except Exception as e:
        logger.error("[AI-QUERY] Failed to execute pattern '%s': %s" % (pattern_id, e))
        raise


def get_pattern_descriptions():
    """Return a formatted string describing all available patterns for the LLM."""
    lines = []
    for pid, pattern in QUERY_PATTERNS.items():
        params_str = ", ".join(pattern["params"])
        defaults_str = ", ".join("%s=%s" % (k, v) for k, v in pattern.get("defaults", {}).items())
        lines.append(
            "- %s: %s (params: %s%s)"
            % (
                pid,
                pattern["description"],
                params_str,
                " | defaults: %s" % defaults_str if defaults_str else "",
            )
        )
    return "\n".join(lines)
