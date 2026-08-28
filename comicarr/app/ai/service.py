#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
AI service — business logic for activity logging, status, and connection testing.
"""

import datetime
import time

from comicarr import logger
from comicarr.app.ai import queries as ai_queries
from comicarr.app.ai.runtime import get_ai_runtime


def log_activity(
    feature_type,
    action,
    model,
    prompt_tokens,
    completion_tokens,
    latency_ms,
    success,
    error_message=None,
    entity_type=None,
    entity_id=None,
):
    """Write an entry to ai_activity_log and publish an SSE event."""
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    success_str = "true" if success else "false"

    try:
        ai_queries.insert_activity(
            {
                "timestamp": timestamp,
                "feature_type": feature_type,
                "action_description": action,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": latency_ms,
                "success": success_str,
                "error_message": error_message,
                "entity_type": entity_type,
                "entity_id": entity_id,
            }
        )
    except Exception as e:
        logger.error("[AI-SERVICE] Failed to log activity: %s" % e)

    try:
        ctx = get_ai_runtime()
        event_bus = ctx.event_bus if ctx is not None else None
        if event_bus:
            event_bus.publish_sync(
                "ai_activity",
                {
                    "feature_type": feature_type,
                    "action": action,
                    "success": success,
                    "latency_ms": latency_ms,
                },
            )
    except Exception:
        pass


def get_activity(limit=50, offset=0):
    """Read recent activity log entries."""
    try:
        rows = ai_queries.get_activity(limit, offset)
        return rows if rows else []
    except Exception as e:
        logger.error("[AI-SERVICE] Failed to read activity log: %s" % e)
        return []


def get_ai_status():
    """Return a dict describing current AI configuration and usage state."""
    ctx = get_ai_runtime()
    config = ctx.config if ctx is not None else None

    configured = (
        bool(
            getattr(config, "AI_BASE_URL", None)
            and getattr(config, "AI_API_KEY", None)
            and getattr(config, "AI_MODEL", None)
        )
        if config
        else False
    )

    circuit_state = "closed"
    cb = ctx.ai_circuit_breaker if ctx is not None else None
    if cb:
        circuit_state = cb.state

    today_tokens = 0
    today_requests = 0
    rl = ctx.ai_rate_limiter if ctx is not None else None
    if rl:
        today_tokens = rl.today_tokens
        today_requests = rl.today_requests

    daily_limit = getattr(config, "AI_DAILY_TOKEN_LIMIT", 100000) if config else 100000
    rpm_limit = getattr(config, "AI_RPM_LIMIT", 20) if config else 20

    model = getattr(config, "AI_MODEL", None) if config else None
    library_series = 0
    try:
        library_series = ai_queries.get_active_series_count()
    except Exception as e:
        logger.fdebug("[AI-SERVICE] Could not count indexed series: %s" % e)

    return {
        "configured": configured,
        "circuit_state": circuit_state,
        "model": model or None,
        "library_series": library_series,
        "today_tokens": today_tokens,
        "today_requests": today_requests,
        "daily_limit": daily_limit,
        "rpm_limit": rpm_limit,
    }


def test_connection(base_url, api_key, model):
    """Test an AI connection with a simple prompt. Returns dict with success/error."""
    from comicarr.app.ai.client import create_ai_clients

    class _TempConfig:
        pass

    temp = _TempConfig()
    temp.AI_BASE_URL = base_url
    temp.AI_API_KEY = api_key
    temp.AI_MODEL = model

    sync_client, _ = create_ai_clients(temp)
    if not sync_client:
        return {"success": False, "error": "Failed to create client — check URL and API key"}

    try:
        start = time.time()
        response = sync_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a test assistant."},
                {"role": "user", "content": "Respond with exactly: CONNECTION_OK"},
            ],
            max_tokens=20,
            timeout=15,
        )
        latency = int((time.time() - start) * 1000)
        content = response.choices[0].message.content or ""
        return {
            "success": True,
            "latency_ms": latency,
            "response": content.strip(),
            "model": model,
        }
    except Exception as e:
        logger.error("[AI-SERVICE] Connection test failed: %s" % e)
        return {"success": False, "error": str(e)}
    finally:
        try:
            sync_client.close()
        except Exception:
            pass
