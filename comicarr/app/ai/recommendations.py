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
import re
import threading
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
_generation_lock = threading.Lock()


class RecommendationGenerationError(Exception):
    def __init__(self, message, status_code=503):
        super().__init__(message)
        self.status_code = status_code


def generate_recommendations(force=False, collection_patterns=None):
    """Generate provider-verified recommendations, or raise on failure."""
    with _generation_lock:
        return _generate_recommendations(force, collection_patterns)


def _generate_recommendations(force, collection_patterns):
    ctx = get_ai_runtime()
    if ctx is None or ctx.ai_client is None or ctx.config is None:
        _invalidate_cache()
        raise RecommendationGenerationError("AI is not configured")

    if ctx.ai_circuit_breaker is None or not ctx.ai_circuit_breaker.allow_request():
        _invalidate_cache()
        raise RecommendationGenerationError("AI is temporarily unavailable")

    if not force:
        cached = _get_cached_recommendations()
        if cached is not None:
            logger.fdebug("[AI-RECS] Returning %d cached recommendations" % len(cached))
            return _filter_untracked(cached)

    if collection_patterns is None:
        collection_patterns = get_collection_patterns()

    monitored = collection_patterns.get("monitored_series") or []
    if not monitored:
        logger.fdebug("[AI-RECS] No tracked series to base recommendations on")
        _cache_recommendations([])
        return []

    if ctx.ai_rate_limiter is None or not ctx.ai_rate_limiter.reserve_request():
        raise RecommendationGenerationError("AI request or token limit reached", status_code=429)

    system_prompt = (
        "You are a comic book recommendation assistant. Based on the series the user "
        "already tracks, suggest comic series they would enjoy but do not track. Older "
        "and finished series are welcome. Prefer shared writers or artists, shared "
        "publishers or imprints, related characters, and the same era. For each "
        "suggestion, name the tracked series it follows from in because_of and give a "
        "brief reason. Include publisher and original publication start year when known. "
        "Never suggest a series the user already tracks. "
        "Limit suggestions to %d maximum." % MAX_RECOMMENDATIONS
    )

    user_prompt = (
        "User's collection patterns:\n%s\n\n"
        "Suggest up to %d comic series. Each suggestion must be a real published "
        "comic series findable on ComicVine." % (_format_patterns(collection_patterns), MAX_RECOMMENDATIONS)
    )

    start_time = time.time()
    usage = {"prompt": 0, "completion": 0}

    def record_usage(response, full_user_prompt):
        response_usage = getattr(response, "usage", None)
        if response_usage is None:
            # One UTF-8 byte per token is a conservative budget estimate for
            # OpenAI-compatible tokenizers when a provider omits usage.
            try:
                raw = response.choices[0].message.content or ""
            except (AttributeError, IndexError, TypeError):
                raw = ""
            usage["prompt"] = len((system_prompt + full_user_prompt).encode("utf-8"))
            usage["completion"] = len(raw.encode("utf-8"))
        else:
            usage["prompt"] = int(getattr(response_usage, "prompt_tokens", 0) or 0)
            usage["completion"] = int(getattr(response_usage, "completion_tokens", 0) or 0)
            total = int(getattr(response_usage, "total_tokens", 0) or 0)
            if total > usage["prompt"] + usage["completion"]:
                usage["completion"] = total - usage["prompt"]
        ctx.ai_rate_limiter.record_usage(usage["prompt"] + usage["completion"])

    model_completed = False
    try:
        result = request_structured(
            client=ctx.ai_client,
            model=ctx.config.AI_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_class=SeriesRecommendations,
            temperature=0.3,
            timeout=getattr(ctx.config, "AI_TIMEOUT", 30) or 30,
            on_response=record_usage,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        model_completed = True
        ctx.ai_circuit_breaker.record_success()
        recommendations = _resolve_recommendations(ctx, result.recommendations[:MAX_RECOMMENDATIONS], monitored)
        recommendations = _filter_untracked(recommendations, strict=True)

        _cache_recommendations(recommendations)

        ai_service.log_activity(
            feature_type="recommendations",
            action="Generated %d series recommendations" % len(recommendations),
            model=ctx.config.AI_MODEL,
            prompt_tokens=usage["prompt"],
            completion_tokens=usage["completion"],
            latency_ms=latency_ms,
            success=True,
        )

        logger.fdebug("[AI-RECS] Generated %d recommendations" % len(recommendations))
        return recommendations

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        if not model_completed:
            ctx.ai_circuit_breaker.record_failure()
            _invalidate_cache()
        ai_service.log_activity(
            feature_type="recommendations",
            action="Series recommendation generation failed",
            model=getattr(ctx.config, "AI_MODEL", "") or "",
            prompt_tokens=usage["prompt"],
            completion_tokens=usage["completion"],
            latency_ms=latency_ms,
            success=False,
            error_message=str(e)[:200],
        )
        logger.error("[AI-RECS] Recommendation generation error: %s" % e)
        raise RecommendationGenerationError("Recommendation generation failed") from e


def get_cached_recommendations():
    """Public accessor for cached recommendations. Returns list or empty list."""
    ctx = get_ai_runtime()
    if ctx is None or ctx.ai_client is None or ctx.config is None:
        return []
    if ctx.ai_circuit_breaker is None or ctx.ai_circuit_breaker.state == "open":
        return []
    cached = _get_cached_recommendations()
    return _filter_untracked(cached) if cached is not None else []


def _resolve_recommendations(ctx, items, monitored):
    """Attach provider data to each pick, resolving only untracked matches."""
    recommendations = []
    tracked_names = {_normalize_name(name) for name in monitored}
    seen_ids = set()
    for item in items:
        if _normalize_name(item.comic_name) in tracked_names:
            continue
        resolved = _resolve_series(ctx, item)
        if resolved is None or str(resolved["comicid"]) in seen_ids:
            continue
        seen_ids.add(str(resolved["comicid"]))
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


def _resolve_series(ctx, item):
    """Return an unambiguous untracked provider volume, or None."""
    series_name = item.comic_name
    try:
        result = search_service.find_comic(ctx, name=series_name, type_="comic", mode="series", limit=5)
    except Exception as e:
        logger.error("[AI-RECS] Provider search failed for %s: %s" % (series_name, e))
        raise

    if not isinstance(result, dict):
        raise ValueError("Invalid provider search response")
    if result.get("error") and result["error"] != "Search returned no results":
        raise ValueError("Provider search failed: %s" % result["error"])
    if not result.get("results"):
        return None

    candidates = [
        c
        for c in result["results"]
        if c.get("comicid")
        and c.get("in_library") is False
        and _normalize_name(c.get("name")) == _normalize_name(series_name)
    ]
    if item.publisher:
        candidates = [
            c for c in candidates if _normalize_publisher(c.get("publisher")) == _normalize_publisher(item.publisher)
        ]
    if item.comicyear:
        candidates = [c for c in candidates if str(c.get("comicyear") or "") == str(item.comicyear)]
    if not candidates:
        return None
    return candidates[0] if len(candidates) == 1 else None


def _normalize_name(value):
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def _normalize_publisher(value):
    return re.sub(r"\s+comics$", "", _normalize_name(value))


def _filter_untracked(recommendations, strict=False):
    if not recommendations:
        return []
    try:
        candidate_ids = {str(r["comicid"]) for r in recommendations if r.get("comicid")}
        tracked_ids = ai_queries.get_library_comic_ids(candidate_ids)
    except Exception as e:
        logger.error("[AI-RECS] Failed to check tracked series: %s" % e)
        if strict:
            raise
        return []
    return [r for r in recommendations if r.get("comicid") and str(r["comicid"]) not in tracked_ids]


def _invalidate_cache():
    try:
        ai_queries.delete_cache_entry(CACHE_KEY, CACHE_TYPE)
    except Exception as e:
        logger.error("[AI-RECS] Failed to invalidate recommendation cache: %s" % e)


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
