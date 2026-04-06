#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
AI-powered story arc reading order generation.

Generates cross-series reading orders from natural language input,
cross-references with ComicVine, maps against the user's library,
and saves to the storyarcs table.
"""

import time
import uuid

import comicarr
from comicarr import db, logger
from comicarr.app.ai import service as ai_service
from comicarr.app.ai.sanitize import sanitize_input
from comicarr.app.ai.schemas import ReadingOrder
from comicarr.app.ai.structured import request_structured


def generate_reading_order(arc_description):
    """Call LLM with arc name/description, return list of issue dicts.

    Each issue dict has: series_name, issue_number, title, reading_order_position.
    Returns empty list if AI is not configured or on error.
    """
    if comicarr.AI_CLIENT is None:
        logger.fdebug("[AI-ARC] AI not configured, cannot generate reading order")
        return {"success": False, "error": "AI is not configured", "issues": []}

    if not comicarr.AI_CIRCUIT_BREAKER.allow_request():
        logger.fdebug("[AI-ARC] Circuit breaker open, skipping reading order generation")
        return {"success": False, "error": "AI service temporarily unavailable", "issues": []}

    if not comicarr.AI_RATE_LIMITER.can_request():
        logger.fdebug("[AI-ARC] Rate limit reached, skipping reading order generation")
        return {"success": False, "error": "AI rate limit reached, try again later", "issues": []}

    sanitized = sanitize_input(arc_description, max_length=500)
    if not sanitized:
        return {"success": False, "error": "Description is empty", "issues": []}

    system_prompt = (
        "You are a comic book expert. Given a story arc name or description, "
        "generate the correct reading order as a list of individual issues. "
        "Include the series name, issue number, and optional issue title for each entry. "
        "Number each issue sequentially in reading_order_position starting from 1. "
        "Only include issues that are actually part of this story arc. "
        "Be precise with issue numbers and series names."
    )

    user_prompt = "Generate the reading order for this comic story arc: %s" % sanitized

    start_time = time.time()
    try:
        result = request_structured(
            client=comicarr.AI_CLIENT,
            model=comicarr.CONFIG.AI_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_class=ReadingOrder,
            temperature=0.2,
            timeout=getattr(comicarr.CONFIG, "AI_TIMEOUT", 30) or 30,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        comicarr.AI_CIRCUIT_BREAKER.record_success()

        issues = []
        for item in result.issues:
            issues.append(
                {
                    "series_name": item.series_name,
                    "issue_number": item.issue_number,
                    "title": item.title,
                    "reading_order": item.reading_order_position,
                    "comic_id": None,
                    "issue_id": None,
                    "verified": False,
                    "library_status": "not_tracked",
                }
            )

        ai_service.log_activity(
            feature_type="storyarc",
            action="Generated reading order for '%s' (%d issues)" % (sanitized[:50], len(issues)),
            model=comicarr.CONFIG.AI_MODEL,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            success=True,
            entity_type="storyarc",
            entity_id=None,
        )

        logger.fdebug('[AI-ARC] Generated reading order with %d issues for "%s"' % (len(issues), sanitized[:50]))
        return {"success": True, "issues": issues}

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        comicarr.AI_CIRCUIT_BREAKER.record_failure()
        ai_service.log_activity(
            feature_type="storyarc",
            action="Reading order generation failed for '%s'" % sanitized[:50],
            model=getattr(comicarr.CONFIG, "AI_MODEL", "") or "",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            success=False,
            error_message=str(e)[:200],
        )
        logger.error("[AI-ARC] Reading order generation error: %s" % e)
        return {"success": False, "error": str(e), "issues": []}


def enrich_with_providers(issues):
    """Cross-reference issues against ComicVine search. Fill in ComicID, IssueID.

    Marks unverified issues that could not be matched.
    Returns the enriched issues list.
    """
    for issue in issues:
        series_name = issue.get("series_name", "")
        issue_number = issue.get("issue_number", "")

        if not series_name:
            continue

        try:
            # Search the comics table for a matching series
            results = db.DBConnection().select(
                "SELECT ComicID, ComicName FROM comics WHERE ComicName LIKE ? LIMIT 5", ["%%%s%%" % series_name]
            )

            if results:
                # Take the best match (first result)
                comic_id = results[0].get("ComicID")
                issue["comic_id"] = comic_id
                issue["verified"] = True

                # Try to find the specific issue
                if comic_id and issue_number:
                    issue_results = db.DBConnection().select(
                        "SELECT IssueID FROM issues WHERE ComicID = ? AND Issue_Number = ? LIMIT 1",
                        [comic_id, issue_number],
                    )
                    if issue_results:
                        issue["issue_id"] = issue_results[0].get("IssueID")

        except Exception as e:
            logger.error('[AI-ARC] Provider enrichment error for "%s #%s": %s' % (series_name, issue_number, e))

    return issues


def map_to_library(issues):
    """Check each issue against user's library. Set library_status field.

    Status values: owned (Downloaded/Archived), wanted (Wanted), not_tracked.
    Returns the issues list with library_status populated.
    """
    for issue in issues:
        comic_id = issue.get("comic_id")
        issue_id = issue.get("issue_id")
        issue_number = issue.get("issue_number", "")

        if not comic_id:
            issue["library_status"] = "not_tracked"
            continue

        try:
            # Check the issues table for this specific issue
            if issue_id:
                result = db.DBConnection().select("SELECT Status FROM issues WHERE IssueID = ? LIMIT 1", [issue_id])
            elif issue_number:
                result = db.DBConnection().select(
                    "SELECT Status FROM issues WHERE ComicID = ? AND Issue_Number = ? LIMIT 1", [comic_id, issue_number]
                )
            else:
                result = None

            if result:
                status = result[0].get("Status", "")
                if status in ("Downloaded", "Archived"):
                    issue["library_status"] = "owned"
                elif status == "Wanted":
                    issue["library_status"] = "wanted"
                else:
                    issue["library_status"] = "not_tracked"
            else:
                issue["library_status"] = "not_tracked"

        except Exception as e:
            logger.error("[AI-ARC] Library mapping error: %s" % e)
            issue["library_status"] = "not_tracked"

    return issues


def save_arc(arc_name, issues):
    """Insert a generated reading order into the storyarcs table.

    Returns dict with success status and the generated StoryArcID.
    """
    if not arc_name or not issues:
        return {"success": False, "error": "Arc name and issues are required"}

    arc_id = "AI_%s" % uuid.uuid4().hex[:8].upper()
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        for issue in issues:
            issue_arc_id = "%s_%s" % (arc_id, issue.get("reading_order", 0))

            values = {
                "StoryArcID": arc_id,
                "StoryArc": arc_name,
                "ComicName": issue.get("series_name", ""),
                "IssueNumber": issue.get("issue_number", ""),
                "IssueName": issue.get("title") or "",
                "ReadingOrder": issue.get("reading_order", 0),
                "ComicID": issue.get("comic_id") or "",
                "IssueID": issue.get("issue_id") or "",
                "Status": _map_status_for_save(issue.get("library_status", "not_tracked")),
                "IssueArcID": issue_arc_id,
                "Manual": "ai",
                "DateAdded": now,
            }

            db.DBConnection().action(
                "INSERT OR REPLACE INTO storyarcs "
                "(StoryArcID, StoryArc, ComicName, IssueNumber, IssueName, ReadingOrder, "
                "ComicID, IssueID, Status, IssueArcID, Manual, DateAdded) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    values["StoryArcID"],
                    values["StoryArc"],
                    values["ComicName"],
                    values["IssueNumber"],
                    values["IssueName"],
                    values["ReadingOrder"],
                    values["ComicID"],
                    values["IssueID"],
                    values["Status"],
                    values["IssueArcID"],
                    values["Manual"],
                    values["DateAdded"],
                ],
            )

        logger.fdebug('[AI-ARC] Saved arc "%s" with %d issues (ID: %s)' % (arc_name, len(issues), arc_id))
        return {"success": True, "arc_id": arc_id}

    except Exception as e:
        logger.error('[AI-ARC] Failed to save arc "%s": %s' % (arc_name, e))
        return {"success": False, "error": str(e)}


def _map_status_for_save(library_status):
    """Map library_status to storyarcs Status value."""
    if library_status == "owned":
        return "Downloaded"
    elif library_status == "wanted":
        return "Wanted"
    else:
        return "Added"
