#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
AI metadata enrichment — fills blank ComicInfo.xml fields (genre, age rating)
using LLM inference from existing metadata context.

Runs after cmtag.run() completes during post-processing. Stores originals
in ai_metadata_history for per-field revert.
"""

import os
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile

import comicarr
from comicarr import db, logger
from comicarr.app.ai import service as ai_service
from comicarr.app.ai.sanitize import sanitize_input, spotlight_wrap
from comicarr.app.ai.schemas import MetadataEnrichment
from comicarr.app.ai.structured import request_structured

# Only enrich these fields (per plan's hallucination risk mitigation).
ENRICHABLE_FIELDS = ["Genre", "AgeRating"]

# ComicInfo.xml context fields used to build the AI prompt.
CONTEXT_FIELDS = ["Title", "Series", "Number", "Publisher", "Year", "Writer", "Penciller"]


def enrich_metadata(cbz_path, issue_id):
    """Enrich blank ComicInfo.xml fields in a CBZ via AI.

    Runs AFTER cmtag.run() completes.  Opens CBZ, reads ComicInfo.xml,
    identifies blank enrichable fields, calls AI, writes enriched values
    back, and stores originals in ai_metadata_history for per-field revert.

    Returns number of fields enriched, or 0 on skip/failure.
    """
    if comicarr.AI_CLIENT is None:
        return 0
    if not comicarr.AI_CIRCUIT_BREAKER.allow_request():
        return 0
    if not comicarr.AI_RATE_LIMITER.can_request():
        return 0

    # Read ComicInfo.xml from CBZ
    comic_info = _read_comicinfo(cbz_path)
    if comic_info is None:
        return 0

    # Identify blank enrichable fields
    blank_fields = []
    for field in ENRICHABLE_FIELDS:
        value = comic_info.get(field, "")
        if not value or value.strip() == "":
            blank_fields.append(field)

    if not blank_fields:
        return 0

    # Build context from non-blank fields
    context_fields = {}
    for key in CONTEXT_FIELDS:
        val = comic_info.get(key, "")
        if val and val.strip():
            context_fields[key] = sanitize_input(val, max_length=200)

    if not context_fields:
        logger.fdebug("[AI-ENRICH] No context fields available for issue %s — skipping" % issue_id)
        return 0

    system_prompt = (
        "From the metadata fields about a comic issue, generate values for the missing fields. "
        "Only return values you are confident about. Return a JSON object mapping field names "
        "to values. Only include the requested blank fields."
    )

    user_prompt = "Existing metadata:\n"
    for k, v in context_fields.items():
        user_prompt += "  %s: %s\n" % (k, spotlight_wrap(v))
    user_prompt += "\nGenerate values for these blank fields: %s" % ", ".join(blank_fields)

    start_time = time.time()
    try:
        result = request_structured(
            client=comicarr.AI_CLIENT,
            model=comicarr.CONFIG.AI_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_class=MetadataEnrichment,
            temperature=0.1,
            timeout=comicarr.CONFIG.AI_TIMEOUT or 30,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        comicarr.AI_CIRCUIT_BREAKER.record_success()

        # Filter: only accept values for fields that were actually blank
        enriched = {}
        for field_name, value in result.fields.items():
            if field_name in blank_fields and value and value.strip():
                enriched[field_name] = value.strip()

        if not enriched:
            return 0

        # Write enriched values to ComicInfo.xml in CBZ
        _write_comicinfo(cbz_path, enriched)

        # Store in ai_metadata_history for revert
        _store_history(issue_id, enriched)

        ai_service.log_activity(
            feature_type="enrichment",
            action="Enriched %d fields for issue %s" % (len(enriched), issue_id),
            model=comicarr.CONFIG.AI_MODEL,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            success=True,
            entity_type="issue",
            entity_id=issue_id,
        )

        logger.fdebug("[AI-ENRICH] Enriched %d fields for issue %s" % (len(enriched), issue_id))
        return len(enriched)

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        comicarr.AI_CIRCUIT_BREAKER.record_failure()
        ai_service.log_activity(
            feature_type="enrichment",
            action="Enrichment failed for issue %s" % issue_id,
            model=comicarr.CONFIG.AI_MODEL or "",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            success=False,
            error_message=str(e)[:200],
        )
        logger.error("[AI-ENRICH] Error: %s" % e)
        return 0


def _read_comicinfo(cbz_path):
    """Read ComicInfo.xml from a CBZ file. Returns dict of field->value or None."""
    try:
        with zipfile.ZipFile(cbz_path, "r") as zf:
            if "ComicInfo.xml" not in zf.namelist():
                return None
            xml_data = zf.read("ComicInfo.xml")
    except Exception as e:
        logger.error("[AI-ENRICH] Cannot read CBZ %s: %s" % (cbz_path, e))
        return None

    try:
        root = ET.fromstring(xml_data)
        result = {}
        for child in root:
            tag = child.tag
            result[tag] = child.text or ""
        return result
    except Exception as e:
        logger.error("[AI-ENRICH] Cannot parse ComicInfo.xml: %s" % e)
        return None


def _write_comicinfo(cbz_path, enriched_fields):
    """Write enriched values into ComicInfo.xml inside the CBZ."""
    try:
        # Read existing ComicInfo.xml
        with zipfile.ZipFile(cbz_path, "r") as zf:
            xml_data = zf.read("ComicInfo.xml")

        root = ET.fromstring(xml_data)

        # Update blank fields with enriched values
        for field_name, value in enriched_fields.items():
            elem = root.find(field_name)
            if elem is not None:
                elem.text = value
            else:
                new_elem = ET.SubElement(root, field_name)
                new_elem.text = value

        updated_xml = ET.tostring(root, encoding="unicode", xml_declaration=True)

        # Rewrite CBZ with updated ComicInfo.xml
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".cbz")
        os.close(tmp_fd)

        try:
            with zipfile.ZipFile(cbz_path, "r") as zf_in:
                with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf_out:
                    for item in zf_in.namelist():
                        if item == "ComicInfo.xml":
                            zf_out.writestr("ComicInfo.xml", updated_xml)
                        else:
                            zf_out.writestr(item, zf_in.read(item))

            shutil.move(tmp_path, cbz_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
    except Exception as e:
        logger.error("[AI-ENRICH] Cannot write ComicInfo.xml: %s" % e)
        raise


def _store_history(issue_id, enriched_fields):
    """Store enrichment history for per-field revert."""
    from datetime import datetime

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    for field_name, ai_value in enriched_fields.items():
        db.DBConnection().action(
            "INSERT INTO ai_metadata_history "
            "(entity_type, entity_id, field_name, original_value, ai_value, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["issue", issue_id, field_name, None, ai_value, "enrichment", now],
        )


def revert_field(issue_id, field_name, cbz_path):
    """Revert an AI-enriched field back to blank."""
    # Validate issue exists
    issue = db.DBConnection().select("SELECT IssueID FROM issues WHERE IssueID = ?", [issue_id])
    if not issue:
        raise ValueError("Issue %s not found" % issue_id)

    # Remove enriched value from CBZ (set field to empty)
    _write_comicinfo(cbz_path, {field_name: ""})

    # Delete history entry
    db.DBConnection().action(
        "DELETE FROM ai_metadata_history WHERE entity_type = ? AND entity_id = ? AND field_name = ? AND source = ?",
        ["issue", issue_id, field_name, "enrichment"],
    )

    logger.fdebug("[AI-ENRICH] Reverted %s for issue %s" % (field_name, issue_id))
