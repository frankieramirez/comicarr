#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
AI-powered weekly pull list curation.

Analyzes user collection patterns against weekly releases to highlight
new comics the user might be interested in but is not currently tracking.
Results are cached in ai_cache for quick retrieval.
"""

import json
import time
from datetime import datetime, timedelta

from comicarr import logger
from comicarr.app.ai import queries as ai_queries
from comicarr.app.ai import service as ai_service
from comicarr.app.ai.runtime import get_ai_runtime
from comicarr.app.ai.schemas import PullSuggestions
from comicarr.app.ai.structured import request_structured

CACHE_KEY = "pull_suggestions"
CACHE_TYPE = "suggestions"
CACHE_TTL_HOURS = 24


def generate_suggestions(weekly_data=None, collection_patterns=None):
    """Analyze user collection against weekly releases, return suggestions.

    Returns a list of suggestion dicts, each with: comic_name, publisher, reason.
    Results are cached in ai_cache with cache_type="suggestions".
    """
    ctx = get_ai_runtime()
    if ctx is None or ctx.ai_client is None or ctx.config is None:
        logger.fdebug("[AI-PULLLIST] AI not configured, skipping suggestions")
        return []

    if ctx.ai_circuit_breaker is None or not ctx.ai_circuit_breaker.allow_request():
        logger.fdebug("[AI-PULLLIST] Circuit breaker open, skipping suggestions")
        return []

    if ctx.ai_rate_limiter is None or not ctx.ai_rate_limiter.can_request():
        logger.fdebug("[AI-PULLLIST] Rate limit reached, skipping suggestions")
        return []

    cached = _get_cached_suggestions()
    if cached is not None:
        logger.fdebug("[AI-PULLLIST] Returning %d cached suggestions" % len(cached))
        return cached

    if collection_patterns is None:
        collection_patterns = get_collection_patterns()

    if weekly_data is None:
        weekly_data = _get_weekly_releases()

    if not weekly_data:
        logger.fdebug("[AI-PULLLIST] No weekly releases to analyze")
        return []

    system_prompt = (
        "You are a comic book recommendation assistant. Based on the user's collection "
        "patterns and this week's new releases, suggest comics they might enjoy but are "
        "not currently tracking. Provide a brief reason for each suggestion. "
        "Only suggest comics from the weekly releases list that the user is NOT already tracking. "
        "Limit suggestions to 5 maximum."
    )

    patterns_text = _format_patterns(collection_patterns)
    weekly_text = _format_weekly(weekly_data)

    user_prompt = (
        "User's collection patterns:\n%s\n\n"
        "This week's new releases (not currently tracked):\n%s\n\n"
        "Suggest up to 5 comics from the weekly releases that match the user's interests."
        % (patterns_text, weekly_text)
    )

    start_time = time.time()
    try:
        result = request_structured(
            client=ctx.ai_client,
            model=ctx.config.AI_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_class=PullSuggestions,
            temperature=0.3,
            timeout=getattr(ctx.config, "AI_TIMEOUT", 30) or 30,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        ctx.ai_circuit_breaker.record_success()

        suggestions = []
        for item in result.suggestions[:5]:
            suggestions.append(
                {
                    "comic_name": item.comic_name,
                    "publisher": item.publisher,
                    "reason": item.reason,
                    "resolved_comic_id": item.resolved_comic_id,
                }
            )

        _cache_suggestions(suggestions)

        ai_service.log_activity(
            feature_type="pulllist",
            action="Generated %d pull list suggestions" % len(suggestions),
            model=ctx.config.AI_MODEL,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            success=True,
        )

        logger.fdebug("[AI-PULLLIST] Generated %d suggestions" % len(suggestions))
        return suggestions

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        ctx.ai_circuit_breaker.record_failure()
        ai_service.log_activity(
            feature_type="pulllist",
            action="Pull list suggestion generation failed",
            model=getattr(ctx.config, "AI_MODEL", "") or "",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            success=False,
            error_message=str(e)[:200],
        )
        logger.error("[AI-PULLLIST] Suggestion generation error: %s" % e)
        return []


def get_collection_patterns():
    """Aggregate collection data: publishers, monitored series, completion rates.

    Returns a dict with keys: publishers, series_count, top_publishers,
    avg_completion, monitored_series.
    """
    patterns = {
        "publishers": [],
        "series_count": 0,
        "top_publishers": [],
        "avg_completion": 0,
        "monitored_series": [],
    }

    try:
        publisher_rows = ai_queries.get_active_publisher_counts()
        if publisher_rows:
            patterns["publishers"] = [
                {"name": r["ComicPublisher"], "count": r["count"]} for r in publisher_rows if r.get("ComicPublisher")
            ]
            patterns["top_publishers"] = [r["ComicPublisher"] for r in publisher_rows[:5] if r.get("ComicPublisher")]

        patterns["series_count"] = ai_queries.get_active_series_count()

        patterns["monitored_series"] = ai_queries.get_active_series_names()

        average_completion = ai_queries.get_active_completion_rate()
        if average_completion is not None:
            patterns["avg_completion"] = round(average_completion, 1)

    except Exception as e:
        logger.error("[AI-PULLLIST] Failed to gather collection patterns: %s" % e)

    return patterns


def get_cached_suggestions():
    """Public accessor for cached suggestions. Returns list or empty list."""
    cached = _get_cached_suggestions()
    return cached if cached is not None else []


def _get_weekly_releases():
    """Get this week's releases that are NOT currently tracked by the user."""
    try:
        results = ai_queries.get_untracked_weekly_releases()
        return results if results else []
    except Exception as e:
        logger.error("[AI-PULLLIST] Failed to get weekly releases: %s" % e)
        return []


def _get_cached_suggestions():
    """Retrieve cached suggestions if still fresh. Returns list or None."""
    try:
        row = ai_queries.get_cache_entry(CACHE_KEY, CACHE_TYPE)
        if row and row.get("data"):
            expires_at = row.get("expires_at", "")
            if expires_at:
                try:
                    expiry = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                    if datetime.utcnow() > expiry:
                        return None
                except (ValueError, TypeError):
                    pass
            return json.loads(row["data"])
    except Exception as e:
        logger.error("[AI-PULLLIST] Cache read error: %s" % e)
    return None


def _cache_suggestions(suggestions):
    """Write suggestions to ai_cache with TTL."""
    try:
        now = datetime.utcnow()
        expires = now + timedelta(hours=CACHE_TTL_HOURS)
        ai_queries.upsert_cache_entry(
            CACHE_KEY,
            CACHE_TYPE,
            json.dumps(suggestions),
            now.strftime("%Y-%m-%d %H:%M:%S"),
            expires.strftime("%Y-%m-%d %H:%M:%S"),
        )
    except Exception as e:
        logger.error("[AI-PULLLIST] Cache write error: %s" % e)


def _format_patterns(patterns):
    """Format collection patterns into a readable string for the LLM prompt."""
    lines = []
    if patterns.get("series_count"):
        lines.append("- Monitoring %d active series" % patterns["series_count"])
    if patterns.get("top_publishers"):
        lines.append("- Top publishers: %s" % ", ".join(patterns["top_publishers"]))
    if patterns.get("avg_completion"):
        lines.append("- Average collection completion: %.1f%%" % patterns["avg_completion"])
    if patterns.get("monitored_series"):
        series_list = patterns["monitored_series"][:15]
        lines.append("- Currently tracking: %s" % ", ".join(series_list))
    return "\n".join(lines) if lines else "No collection data available"


def _format_weekly(weekly_data):
    """Format weekly releases into a readable string for the LLM prompt."""
    lines = []
    for release in weekly_data[:50]:
        comic = release.get("COMIC", "")
        publisher = release.get("PUBLISHER", "")
        issue = release.get("ISSUE", "")
        if comic:
            line = "%s #%s" % (comic, issue) if issue else comic
            if publisher:
                line += " (%s)" % publisher
            lines.append("- %s" % line)
    return "\n".join(lines) if lines else "No weekly releases available"
