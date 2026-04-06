#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
AI metadata conflict reconciliation — when ComicVine metadata (written
by cmtag) conflicts with pre-existing ComicInfo.xml values, use the LLM
to select the best value per field.

Stores per-provider originals in ai_metadata_history for revert.
If AI is not configured, existing behaviour (CV wins) is preserved.
"""

import time

import comicarr
from comicarr import db, logger
from comicarr.app.ai import service as ai_service
from comicarr.app.ai.enrichment import _write_comicinfo
from comicarr.app.ai.sanitize import spotlight_wrap
from comicarr.app.ai.schemas import ReconciliationChoice
from comicarr.app.ai.structured import request_structured

# Fields eligible for AI reconciliation between ComicInfo.xml and CV.
RECONCILABLE_FIELDS = [
    "Title",
    "Summary",
    "Publisher",
    "Genre",
    "AgeRating",
    "Writer",
    "Penciller",
    "Inker",
    "Colorist",
    "Letterer",
]


def reconcile_metadata(cbz_path, issue_id, pre_cmtag_info, post_cmtag_info):
    """Reconcile conflicting metadata between pre-cmtag and post-cmtag ComicInfo.xml.

    Compares pre-cmtag (original ComicInfo.xml) values against post-cmtag
    (ComicVine) values for RECONCILABLE_FIELDS.  When conflicts exist and
    AI is available, asks the LLM to pick the best value per field.

    Returns number of fields reconciled, or 0 on skip/failure.
    """
    if pre_cmtag_info is None or post_cmtag_info is None:
        return 0

    # Build conflict map: fields where both sources are non-empty and differ
    conflicts = {}
    for field in RECONCILABLE_FIELDS:
        pre_val = (pre_cmtag_info.get(field) or "").strip()
        post_val = (post_cmtag_info.get(field) or "").strip()
        if pre_val and post_val and pre_val != post_val:
            conflicts[field] = {"comicinfo": pre_val, "cv": post_val}

    if not conflicts:
        return 0

    logger.fdebug(
        "[AI-RECONCILE] Found %d conflicting fields for issue %s: %s"
        % (len(conflicts), issue_id, ", ".join(conflicts.keys()))
    )

    # Check AI availability — if not available, CV wins by default
    if comicarr.AI_CLIENT is None:
        logger.fdebug("[AI-RECONCILE] AI not configured — CV values win by default")
        return 0
    if not comicarr.AI_CIRCUIT_BREAKER.allow_request():
        logger.fdebug("[AI-RECONCILE] Circuit breaker open — CV values win by default")
        return 0
    if not comicarr.AI_RATE_LIMITER.can_request():
        logger.fdebug("[AI-RECONCILE] Rate limiter at cap — CV values win by default")
        return 0

    # Build prompt
    system_prompt = (
        "For each field, select the most accurate value from the given options. "
        "Do not synthesize new values — pick from the provided options only. "
        "Return a JSON object mapping field names to selected values."
    )

    user_prompt = "Select the best value for each conflicting metadata field:\n\n"
    for field, sources in conflicts.items():
        user_prompt += "%s:\n  Option A (ComicInfo.xml): %s\n  Option B (ComicVine): %s\n\n" % (
            field,
            spotlight_wrap(sources["comicinfo"]),
            spotlight_wrap(sources["cv"]),
        )

    start_time = time.time()
    try:
        result = request_structured(
            client=comicarr.AI_CLIENT,
            model=comicarr.CONFIG.AI_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_class=ReconciliationChoice,
            temperature=0.1,
            timeout=comicarr.CONFIG.AI_TIMEOUT or 30,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        comicarr.AI_CIRCUIT_BREAKER.record_success()

        # Validate: each selected value MUST match one of the input values
        resolved = {}
        for field, sources in conflicts.items():
            chosen = result.choices.get(field)
            if chosen is None:
                # AI didn't return this field — CV wins
                continue
            chosen = chosen.strip()
            if chosen == sources["comicinfo"] or chosen == sources["cv"]:
                resolved[field] = chosen
            else:
                # AI synthesised a new value — reject it, CV wins
                logger.fdebug("[AI-RECONCILE] Rejected synthesised value for %s — CV wins" % field)
                resolved[field] = sources["cv"]

        if not resolved:
            return 0

        # Write AI-selected values to CBZ
        _write_comicinfo(cbz_path, resolved)

        # Store per-provider originals in ai_metadata_history
        _store_reconciliation_history(issue_id, conflicts, resolved)

        ai_service.log_activity(
            feature_type="reconciliation",
            action="Reconciled %d fields for issue %s" % (len(resolved), issue_id),
            model=comicarr.CONFIG.AI_MODEL,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            success=True,
            entity_type="issue",
            entity_id=issue_id,
        )

        logger.fdebug("[AI-RECONCILE] Reconciled %d fields for issue %s" % (len(resolved), issue_id))
        return len(resolved)

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        comicarr.AI_CIRCUIT_BREAKER.record_failure()
        ai_service.log_activity(
            feature_type="reconciliation",
            action="Reconciliation failed for issue %s" % issue_id,
            model=comicarr.CONFIG.AI_MODEL or "",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            success=False,
            error_message=str(e)[:200],
        )
        logger.error("[AI-RECONCILE] Error: %s" % e)
        return 0


def _store_reconciliation_history(issue_id, conflicts, resolved):
    """Store per-provider originals in ai_metadata_history for revert."""
    from datetime import datetime

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    for field, sources in conflicts.items():
        ai_value = resolved.get(field)
        if ai_value is None:
            continue
        # Row for comicinfo provider value
        db.DBConnection().action(
            "INSERT INTO ai_metadata_history "
            "(entity_type, entity_id, field_name, original_value, ai_value, source, provider, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["issue", issue_id, field, sources["comicinfo"], ai_value, "reconciliation", "comicinfo", now],
        )
        # Row for cv provider value
        db.DBConnection().action(
            "INSERT INTO ai_metadata_history "
            "(entity_type, entity_id, field_name, original_value, ai_value, source, provider, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["issue", issue_id, field, sources["cv"], ai_value, "reconciliation", "cv", now],
        )
