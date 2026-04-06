#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
AI filename parsing fallback — routes unparseable filenames to the LLM
for structured metadata extraction when regex-based parsing fails.
"""

import time

import comicarr
from comicarr import db, logger
from comicarr.app.ai import service as ai_service
from comicarr.app.ai.sanitize import sanitize_input
from comicarr.app.ai.schemas import FilenameParse
from comicarr.app.ai.structured import request_structured


def ai_parse_filename(filename, watchcomic=None, publisher=None):
    """Attempt AI-based filename parsing when regex fails.

    Returns a parseit()-compatible dict on success, or None on failure.
    """
    # Check AI is configured and available
    if comicarr.AI_CLIENT is None:
        return None
    if not comicarr.AI_CIRCUIT_BREAKER.allow_request():
        logger.fdebug('[AI-PARSE] Circuit breaker open — skipping AI parse')
        return None
    if not comicarr.AI_RATE_LIMITER.can_request():
        logger.fdebug('[AI-PARSE] Rate limit reached — skipping AI parse')
        return None

    sanitized_filename = sanitize_input(filename, max_length=500)

    system_prompt = (
        "You are a comic book filename parser. Extract metadata from the given filename. "
        "Return a JSON object with: series_name (string), issue_number (string), "
        "year (string or null), volume (string or null). "
        "Only include fields you are confident about."
    )

    user_prompt = "Parse this comic filename: %s" % sanitized_filename
    if watchcomic:
        user_prompt += "\nExpected series: %s" % sanitize_input(watchcomic, max_length=200)
    if publisher:
        user_prompt += "\nPublisher: %s" % sanitize_input(publisher, max_length=100)

    start_time = time.time()
    try:
        result = request_structured(
            client=comicarr.AI_CLIENT,
            model=comicarr.CONFIG.AI_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_class=FilenameParse,
            temperature=0.1,
            timeout=comicarr.CONFIG.AI_TIMEOUT or 30,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        comicarr.AI_CIRCUIT_BREAKER.record_success()

        # Validate against monitored series
        if not _validate_against_library(result.series_name):
            ai_service.log_activity(
                feature_type="parsing",
                action="AI parsed '%s' but no library match for '%s'" % (filename, result.series_name),
                model=comicarr.CONFIG.AI_MODEL,
                prompt_tokens=0, completion_tokens=0,
                latency_ms=latency_ms,
                success=False,
                error_message="No library match",
            )
            logger.fdebug('[AI-PARSE] No library match for series: %s' % result.series_name)
            return None

        # Build parseit()-compatible dict
        parsed = _build_parse_dict(result, filename)

        ai_service.log_activity(
            feature_type="parsing",
            action="AI parsed '%s' → %s #%s" % (filename, result.series_name, result.issue_number),
            model=comicarr.CONFIG.AI_MODEL,
            prompt_tokens=0, completion_tokens=0,
            latency_ms=latency_ms,
            success=True,
        )
        logger.fdebug('[AI-PARSE] Successfully parsed: %s → %s #%s' % (filename, result.series_name, result.issue_number))

        return parsed

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        comicarr.AI_CIRCUIT_BREAKER.record_failure()
        ai_service.log_activity(
            feature_type="parsing",
            action="AI parse failed for '%s'" % filename,
            model=comicarr.CONFIG.AI_MODEL or "",
            prompt_tokens=0, completion_tokens=0,
            latency_ms=latency_ms,
            success=False,
            error_message=str(e)[:200],
        )
        logger.error('[AI-PARSE] Error parsing filename: %s' % e)
        return None


def _validate_against_library(series_name):
    """Fuzzy match series_name against comics table ComicName + AlternateSearch."""
    if not series_name:
        return False

    # Exact match first
    result = db.DBConnection().select(
        "SELECT ComicID FROM comics WHERE ComicName = ? OR DynamicComicName = ? LIMIT 1",
        [series_name, series_name.lower().strip()]
    )
    if result:
        return True

    # Case-insensitive match
    result = db.DBConnection().select(
        "SELECT ComicID FROM comics WHERE LOWER(ComicName) = LOWER(?) LIMIT 1",
        [series_name]
    )
    if result:
        return True

    # Check AlternateSearch field (##-delimited)
    result = db.DBConnection().select(
        "SELECT AlternateSearch FROM comics WHERE AlternateSearch IS NOT NULL"
    )
    search_lower = series_name.lower()
    for row in (result or []):
        alternates = (row.get("AlternateSearch") or "").split("##")
        for alt in alternates:
            if alt.strip().lower() == search_lower:
                return True

    return False


def _build_parse_dict(ai_result, original_filename):
    """Build a parseit()-compatible return dict from AI parse results."""
    series_name = ai_result.series_name
    issue_number = ai_result.issue_number or ""

    return {
        "parse_status": "success",
        "sub": None,
        "comicfilename": original_filename,
        "comiclocation": None,
        "series_name": series_name,
        "series_name_decoded": series_name,
        "dynamic_name": series_name.lower().strip() if series_name else "",
        "issue_number": issue_number,
        "justthedigits": issue_number,
        "issue_year": ai_result.year,
        "series_volume": ai_result.volume,
        "issueid": None,
        "alt_series": None,
        "alt_issue": None,
        "annual_comicid": None,
        "booktype": None,
        "scangroup": None,
        "reading_order": None,
        "ai_parsed": True,
    }
