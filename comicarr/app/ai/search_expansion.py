#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
AI-powered search query expansion.

When all search providers return zero results for a series, generates
alternate query formulations via LLM, enabling retry with different
search terms. Successful expansions are persisted to the AlternateSearch
field for future searches.
"""

import json
import time
from datetime import datetime

import comicarr
from comicarr import db, logger
from comicarr.app.ai import service as ai_service
from comicarr.app.ai.sanitize import sanitize_input
from comicarr.app.ai.schemas import SearchExpansion
from comicarr.app.ai.structured import request_structured


def expand_search_queries(comic_id, series_name, publisher=None, year=None):
    """Generate alternate search queries via AI when zero results returned.

    Returns list of alternate query strings, or empty list on failure.
    """
    if comicarr.AI_CLIENT is None:
        return []
    if not comicarr.AI_CIRCUIT_BREAKER.allow_request():
        logger.fdebug('[AI-SEARCH] Circuit breaker open, skipping expansion for %s' % comic_id)
        return []
    if not comicarr.AI_RATE_LIMITER.can_request():
        logger.fdebug('[AI-SEARCH] Rate limit reached, skipping expansion for %s' % comic_id)
        return []

    # Check if we already expanded this series (capped at 5 AI entries)
    existing_ai_expansions = _get_ai_expansions(comic_id)
    if len(existing_ai_expansions) >= 5:
        logger.fdebug('[AI-SEARCH] Series %s already has 5 AI expansions, skipping' % comic_id)
        return []

    # Get current AlternateSearch values
    current_alternates = _get_alternate_search(comic_id)

    sanitized_name = sanitize_input(series_name, max_length=200)

    system_prompt = (
        "You are a comic book search assistant. Generate 2-3 alternate search query "
        "formulations for this comic series. Consider abbreviations, alternate titles, "
        "volume year variants, common misspellings. Return only the alternate names."
    )

    user_prompt = "Series: %s" % sanitized_name
    if publisher:
        user_prompt += "\nPublisher: %s" % sanitize_input(publisher, max_length=100)
    if year:
        user_prompt += "\nYear: %s" % str(year)
    if current_alternates:
        user_prompt += "\nExisting alternates (don't repeat these): %s" % ", ".join(current_alternates[:10])

    start_time = time.time()
    try:
        result = request_structured(
            client=comicarr.AI_CLIENT,
            model=comicarr.CONFIG.AI_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_class=SearchExpansion,
            temperature=0.3,
            timeout=comicarr.CONFIG.AI_TIMEOUT or 30,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        comicarr.AI_CIRCUIT_BREAKER.record_success()

        # Deduplicate against existing alternates
        new_alternates = []
        existing_lower = {a.lower() for a in current_alternates}
        existing_lower.add(series_name.lower())

        for alt in result.queries[:3]:
            alt_clean = alt.strip()
            if alt_clean and alt_clean.lower() not in existing_lower:
                new_alternates.append(alt_clean)
                existing_lower.add(alt_clean.lower())

        ai_service.log_activity(
            feature_type="search",
            action="Generated %d alternates for '%s'" % (len(new_alternates), series_name),
            model=comicarr.CONFIG.AI_MODEL,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            success=True,
            entity_type="comic",
            entity_id=comic_id,
        )

        logger.fdebug('[AI-SEARCH] Generated %d alternate queries for "%s"' % (len(new_alternates), series_name))
        return new_alternates

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        comicarr.AI_CIRCUIT_BREAKER.record_failure()
        ai_service.log_activity(
            feature_type="search",
            action="Search expansion failed for '%s'" % series_name,
            model=comicarr.CONFIG.AI_MODEL or "",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            success=False,
            error_message=str(e)[:200],
        )
        logger.error('[AI-SEARCH] Expansion error: %s' % e)
        return []


def persist_successful_expansion(comic_id, successful_alternate):
    """Persist a successful search expansion to AlternateSearch and ai_cache."""
    # Add to AlternateSearch field
    current = _get_alternate_search(comic_id)
    if successful_alternate.lower() not in {a.lower() for a in current}:
        new_value = "##".join(current + [successful_alternate]) if current else successful_alternate
        db.DBConnection().action(
            "UPDATE comics SET AlternateSearch = ? WHERE ComicID = ?",
            [new_value, comic_id]
        )

    # Track in ai_cache for counting AI expansions
    existing = _get_ai_expansions(comic_id)
    existing.append(successful_alternate)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    db.DBConnection().action(
        "INSERT OR REPLACE INTO ai_cache (cache_key, cache_type, data, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ["expansion_%s" % comic_id, "expansion", json.dumps(existing), now, "9999-12-31"]
    )

    logger.fdebug('[AI-SEARCH] Persisted expansion "%s" for comic %s' % (successful_alternate, comic_id))


def _get_alternate_search(comic_id):
    """Get current AlternateSearch values for a comic."""
    result = db.DBConnection().select(
        "SELECT AlternateSearch FROM comics WHERE ComicID = ?",
        [comic_id]
    )
    if result and result[0].get("AlternateSearch"):
        return [a.strip() for a in result[0]["AlternateSearch"].split("##") if a.strip()]
    return []


def _get_ai_expansions(comic_id):
    """Get AI-generated expansions from cache."""
    result = db.DBConnection().select(
        "SELECT data FROM ai_cache WHERE cache_key = ? AND cache_type = ?",
        ["expansion_%s" % comic_id, "expansion"]
    )
    if result and result[0].get("data"):
        try:
            return json.loads(result[0]["data"])
        except (json.JSONDecodeError, TypeError):
            pass
    return []
