#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""What an issue's most recent search saw, for the issue page.

Automatic search evaluates every release a provider returns, then keeps only
the ones it hands off. The issue page needs the rest too: "41 results, 38
rejected, 3 acceptable", and which reasons ruled the others out. This keeps
one summary row per issue, replaced by each new search, built from the
evaluation session's public projections (no provider URLs or credentials).
"""

from __future__ import annotations

import datetime
import json
from collections import Counter

from sqlalchemy import delete, insert, select

from comicarr import db, logger
from comicarr.tables import issue_search_history

ACCEPTED_LIMIT = 20
REJECTED_SAMPLE = 40

# Short labels for the reason breakdown under "Searched N indexers".
REASON_LABELS = {
    "rejected.issue_mismatch": "wrong issue",
    "rejected.series_mismatch": "wrong series",
    "rejected.alternate_series": "alternate name only",
    "rejected.pack_issue_absent": "packs without it",
    "rejected.size_below_min": "too small",
    "rejected.size_above_max": "too large",
    "rejected.cover_only": "cover only",
    "rejected.before_reference_date": "too old",
    "rejected.book_type": "wrong format",
    "rejected.unparseable_title": "unreadable title",
    "rejected.year_mismatch": "wrong year",
    "rejected.volume_mismatch": "wrong volume",
    "ignored.search_word": "ignored word",
    "blocked.duplicate": "duplicates",
    "invalid.pubdate_missing": "no date",
    "invalid.pubdate_unparseable": "bad date",
    "invalid.reference_date_missing": "issue has no date",
}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _row(item):
    candidate = item.get("candidate") or {}
    verdict = item.get("verdict") or {}
    reasons = verdict.get("reasons") or [{}]
    return {
        "title": str(candidate.get("title") or "Untitled release")[:300],
        "provider": str(candidate.get("provider") or "")[:80],
        "source_kind": candidate.get("source_kind"),
        "size_bytes": candidate.get("size_bytes"),
        "pack": bool(candidate.get("pack")),
        "status": verdict.get("status"),
        "reason_code": verdict.get("reason_code"),
        "reason": reasons[0].get("message"),
    }


def build_summary(observed):
    rows = [_row(item) for item in observed or []]
    accepted = [row for row in rows if row["status"] == "accepted"]
    rejected = [row for row in rows if row["status"] != "accepted"]
    counts = Counter(row["reason_code"] or "unknown" for row in rejected)
    return {
        "total": len(rows),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "providers": sorted({row["provider"] for row in rows if row["provider"]}),
        "accepted": accepted[:ACCEPTED_LIMIT],
        "rejected": rejected[:REJECTED_SAMPLE],
        "reasons": [
            {"code": code, "label": REASON_LABELS.get(code, code.split(".")[-1].replace("_", " ")), "count": n}
            for code, n in counts.most_common()
        ],
    }


def record(issue_id, observed, *, searched_at=None):
    """Replace ``issue_id``'s search history with what this search saw."""
    if issue_id in (None, ""):
        return None
    summary = build_summary(observed)
    values = {
        "issue_id": str(issue_id)[:255],
        "searched_at": searched_at or _now(),
        "total": summary["total"],
        "summary_json": json.dumps(summary, separators=(",", ":")),
    }
    try:
        with db.get_engine().begin() as conn:
            conn.execute(delete(issue_search_history).where(issue_search_history.c.issue_id == values["issue_id"]))
            conn.execute(insert(issue_search_history).values(**values))
    except Exception as e:
        logger.fdebug("[SEARCH-HISTORY] Could not save search history for %s: %s" % (issue_id, e))
        return None
    return summary


def read(issue_id):
    """The last search's summary for ``issue_id``, or None if it was never searched."""
    row = db.select_one(select(issue_search_history).where(issue_search_history.c.issue_id == str(issue_id)))
    if not row:
        return None
    try:
        summary = json.loads(row["summary_json"])
    except (TypeError, ValueError):
        return None
    summary["searched_at"] = row["searched_at"]
    return summary
