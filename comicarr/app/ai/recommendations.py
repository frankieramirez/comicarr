#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
AI-powered "because you read X" series recommendations.

Suggests series the user does not already track based on their tracked
library — shared creators, publishers, imprints, characters, and eras. Each
pick is resolved through the configured metadata provider so cards carry real
cover, year, publisher, and issue data. Results are cached in ai_cache.
"""

import json
import time
from datetime import datetime, timedelta

from comicarr import logger
from comicarr.app.ai import queries as ai_queries
from comicarr.app.ai import service as ai_service
from comicarr.app.ai.pull_list import get_collection_patterns
from comicarr.app.ai.runtime import get_ai_runtime
from comicarr.app.ai.schemas import SeriesRecommendations
from comicarr.app.ai.structured import request_structured
from comicarr.app.search import service as search_service

CACHE_KEY = "library_recommendations"
CACHE_TYPE = "recommendations"
CACHE_TTL_HOURS = 24
MAX_RECOMMENDATIONS = 8


def generate_recommendations(force=False, collection_patterns=None):
    """Generate library-based series recommendations, return list of dicts.

    Each dict carries: comic_name, publisher, reason, because_of, plus resolved
    provider data (comicid, comicyear, issues, comicimage) when a provider match
    was found. Results are cached in ai_cache with cache_type="recommendations".
    """
    ctx = get_ai_runtime()
    if ctx is None or ctx.ai_client is None or ctx.config is None:
        logger.fdebug("[AI-RECS] AI not configured, skipping recommendations")
        return []

    if ctx.ai_circuit_breaker is None or not ctx.ai_circuit_breaker.allow_request():
        logger.fdebug("[AI-RECS] Circuit breaker open, skipping recommendations")
        return []

    if ctx.ai_rate_limiter is None or not ctx.ai_rate_limiter.can_request():
        logger.fdebug("[AI-RECS] Rate limit reached, skipping recommendations")
        return []

    if not force:
        cached = _get_cached_recommendations()
        if cached is not None:
            logger.fdebug("[AI-RECS] Returning %d cached recommendations" % len(cached))
            return cached

    if collection_patterns is None:
        collection_patterns = get_collection_patterns()

    monitored = collection_patterns.get("monitored_series") or []
    if not monitored:
        logger.fdebug("[AI-RECS] No tracked series to base recommendations on")
        return []

    system_prompt = (
        "You are a comic book recommendation assistant. Based on the series the user "
        "already tracks, suggest comic series they would enjoy but do not track. Older "
        "and finished series are welcome. Prefer shared writers or artists, shared "
        "publishers or imprints, related characters, and the same era. For each "
        "suggestion, name the tracked series it follows from in because_of and give a "
        "brief reason. Never suggest a series the user already tracks. "
        "Limit suggestions to %d maximum." % MAX_RECOMMENDATIONS
    )

    user_prompt = (
        "User's collection patterns:\n%s\n\n"
        "Suggest up to %d comic series. Each suggestion must be a real published "
        "comic series findable on ComicVine." % (_format_patterns(collection_patterns), MAX_RECOMMENDATIONS)
    )

    start_time = time.time()
    try:
        result = request_structured(
            client=ctx.ai_client,
            model=ctx.config.AI_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_class=SeriesRecommendations,
            temperature=0.3,
            timeout=getattr(ctx.config, "AI_TIMEOUT", 30) or 30,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        ctx.ai_circuit_breaker.record_success()

        recommendations = _resolve_recommendations(ctx, result.recommendations[:MAX_RECOMMENDATIONS])

        _cache_recommendations(recommendations)

        ai_service.log_activity(
            feature_type="recommendations",
            action="Generated %d series recommendations" % len(recommendations),
            model=ctx.config.AI_MODEL,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            success=True,
        )

        logger.fdebug("[AI-RECS] Generated %d recommendations" % len(recommendations))
        return recommendations

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        ctx.ai_circuit_breaker.record_failure()
        ai_service.log_activity(
            feature_type="recommendations",
            action="Series recommendation generation failed",
            model=getattr(ctx.config, "AI_MODEL", "") or "",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            success=False,
            error_message=str(e)[:200],
        )
        logger.error("[AI-RECS] Recommendation generation error: %s" % e)
        return []


def get_cached_recommendations():
    """Public accessor for cached recommendations. Returns list or empty list."""
    cached = _get_cached_recommendations()
    return cached if cached is not None else []


def _resolve_recommendations(ctx, items):
    """Attach provider data to each pick, resolving only untracked matches."""
    recommendations = []
    for item in items:
        resolved = _resolve_series(ctx, item.comic_name) or {}
        recommendations.append(
            {
                "comic_name": resolved.get("name") or item.comic_name,
                "publisher": resolved.get("publisher") or item.publisher,
                "reason": item.reason,
                "because_of": item.because_of,
                "comicid": resolved.get("comicid"),
                "comicyear": resolved.get("comicyear"),
                "issues": resolved.get("issues"),
                "comicimage": resolved.get("comicimage") or resolved.get("comicthumb"),
            }
        )
    return recommendations


def _resolve_series(ctx, series_name):
    """Return the first untracked provider match for a suggested name, or None."""
    try:
        result = search_service.find_comic(ctx, name=series_name, type_="comic", mode="series", limit=5)
    except Exception as e:
        logger.error("[AI-RECS] Provider search failed for %s: %s" % (series_name, e))
        return None

    if not isinstance(result, dict) or not result.get("results"):
        return None

    candidates = [c for c in result["results"] if not c.get("in_library")]
    if not candidates:
        return None

    lowered = series_name.strip().lower()
    for candidate in candidates:
        if (candidate.get("name") or "").strip().lower() == lowered:
            return candidate
    return candidates[0]


def _get_cached_recommendations():
    """Retrieve cached recommendations if still fresh. Returns list or None."""
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
        logger.error("[AI-RECS] Cache read error: %s" % e)
    return None


def _cache_recommendations(recommendations):
    """Write recommendations to ai_cache with TTL."""
    try:
        now = datetime.utcnow()
        expires = now + timedelta(hours=CACHE_TTL_HOURS)
        ai_queries.upsert_cache_entry(
            CACHE_KEY,
            CACHE_TYPE,
            json.dumps(recommendations),
            now.strftime("%Y-%m-%d %H:%M:%S"),
            expires.strftime("%Y-%m-%d %H:%M:%S"),
        )
    except Exception as e:
        logger.error("[AI-RECS] Cache write error: %s" % e)


def _format_patterns(patterns):
    """Format collection patterns into a readable string for the LLM prompt."""
    lines = []
    if patterns.get("series_count"):
        lines.append("- Monitoring %d active series" % patterns["series_count"])
    if patterns.get("top_publishers"):
        lines.append("- Top publishers: %s" % ", ".join(patterns["top_publishers"]))
    if patterns.get("monitored_series"):
        lines.append("- Currently tracking: %s" % ", ".join(patterns["monitored_series"][:30]))
    return "\n".join(lines) if lines else "No collection data available"
