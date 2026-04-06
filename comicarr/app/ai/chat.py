#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Chat service — streams conversational responses with library query execution.

The LLM receives available query patterns in the system prompt. It responds
with a JSON block selecting a pattern + params, followed by conversational
text. The backend executes the pattern, then yields SSE events:
  - {"type": "text", "content": "..."} for streaming text chunks
  - {"type": "results", "pattern_id": "...", "data": [...]} for query results
  - {"type": "error", "content": "..."} for errors
  - {"type": "done"} to signal completion
"""

import json
import time

from comicarr import logger
from comicarr.app.ai import service as ai_service
from comicarr.app.ai.query_patterns import (
    QUERY_PATTERNS,
    execute_pattern,
    get_pattern_descriptions,
)
from comicarr.app.ai.sanitize import sanitize_input

_SYSTEM_PROMPT = """You are a helpful comic book library assistant for Comicarr.
You answer questions about the user's comic collection by selecting the appropriate
query pattern and providing conversational context.

Available query patterns:
{patterns}

When the user asks a question about their library, respond with EXACTLY this JSON
format on the FIRST line, followed by your conversational response:

{{"pattern_id": "<pattern_name>", "parameters": {{"param1": "value1"}}}}

Rules:
- ALWAYS include the JSON line first if a query is needed
- For name/publisher searches, extract the core search term (e.g., "Batman" from "What Batman series...")
- For completion queries, use min_pct/max_pct (e.g., "closest to complete" = min_pct: 80, max_pct: 100)
- For gap queries, use order "DESC" for most gaps, "ASC" for fewest
- For "recent downloads" or "what did I download", use recently_added or download_history
- For decade queries, set year_start/year_end (e.g., 1990s = 1990-1999)
- If the question is general chat (not library-related), skip the JSON and just respond conversationally
- Keep responses concise and helpful
- Do not mention SQL, databases, or query patterns to the user
- Valid issue statuses: Wanted, Downloaded, Snatched, Skipped, Archived"""


def _build_system_prompt():
    """Build the system prompt with current pattern descriptions."""
    return _SYSTEM_PROMPT.format(patterns=get_pattern_descriptions())


def _extract_pattern_json(text):
    """Extract the JSON pattern selection from the first line of LLM response.

    Returns (pattern_dict, remaining_text) or (None, original_text).
    """
    if not text:
        return None, text

    lines = text.strip().split("\n", 1)
    first_line = lines[0].strip()

    # Try to parse the first line as JSON
    try:
        data = json.loads(first_line)
        if isinstance(data, dict) and "pattern_id" in data:
            remaining = lines[1].strip() if len(lines) > 1 else ""
            return data, remaining
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to find JSON embedded in the first few lines
    for i, line in enumerate(text.strip().split("\n")[:5]):
        line = line.strip()
        if line.startswith("{") and "pattern_id" in line:
            try:
                data = json.loads(line)
                if isinstance(data, dict) and "pattern_id" in data:
                    remaining_lines = text.strip().split("\n")[i + 1:]
                    remaining = "\n".join(remaining_lines).strip()
                    return data, remaining
            except (json.JSONDecodeError, ValueError):
                continue

    return None, text


async def stream_chat_response(messages, ctx):
    """Stream a chat response, executing query patterns as needed.

    Yields dicts suitable for SSE serialization:
      {"type": "text", "content": "..."}
      {"type": "results", "pattern_id": "...", "data": [...]}
      {"type": "error", "content": "..."}
      {"type": "done"}
    """
    ai_client = getattr(ctx, "ai_async_client", None)
    config = getattr(ctx, "config", None)
    model = getattr(config, "AI_MODEL", None) if config else None
    circuit_breaker = getattr(ctx, "ai_circuit_breaker", None)
    rate_limiter = getattr(ctx, "ai_rate_limiter", None)

    if not ai_client or not model:
        yield {"type": "error", "content": "AI is not configured. Please set up an AI provider in Settings."}
        yield {"type": "done"}
        return

    # Check circuit breaker
    if circuit_breaker and not circuit_breaker.allow_request():
        yield {"type": "error", "content": "AI service is temporarily unavailable. Please try again later."}
        yield {"type": "done"}
        return

    # Check rate limiter
    if rate_limiter and not rate_limiter.can_request():
        yield {"type": "error", "content": "Rate limit reached. Please try again in a moment."}
        yield {"type": "done"}
        return

    # Sanitize user messages
    sanitized_messages = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            content = sanitize_input(content, max_length=1000)
        sanitized_messages.append({"role": role, "content": content})

    # Build the full message list with system prompt
    full_messages = [
        {"role": "system", "content": _build_system_prompt()},
    ] + sanitized_messages

    start_time = time.time()
    prompt_tokens = 0
    completion_tokens = 0

    try:
        response = await ai_client.chat.completions.create(
            model=model,
            messages=full_messages,
            temperature=0.3,
            max_tokens=1000,
            timeout=30,
        )

        raw_content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        if usage:
            prompt_tokens = getattr(usage, "prompt_tokens", 0)
            completion_tokens = getattr(usage, "completion_tokens", 0)

        latency_ms = int((time.time() - start_time) * 1000)

        # Record success with circuit breaker
        if circuit_breaker:
            circuit_breaker.record_success()

        # Record with rate limiter
        if rate_limiter:
            total_tokens = prompt_tokens + completion_tokens
            rate_limiter.record_request(total_tokens)

        # Extract pattern selection from response
        pattern_data, text_content = _extract_pattern_json(raw_content)

        # Execute query pattern if selected
        if pattern_data:
            pattern_id = pattern_data.get("pattern_id", "")
            parameters = pattern_data.get("parameters", {})

            if pattern_id in QUERY_PATTERNS:
                try:
                    results = execute_pattern(pattern_id, parameters)
                    yield {"type": "results", "pattern_id": pattern_id, "data": results}
                except Exception as e:
                    logger.error("[AI-CHAT] Query execution failed: %s" % e)
                    yield {"type": "error", "content": "Failed to query your library. Please try rephrasing."}

        # Yield the conversational text
        if text_content:
            yield {"type": "text", "content": text_content}
        elif not pattern_data:
            # No pattern and no text — yield the raw response
            yield {"type": "text", "content": raw_content}

        # Log activity
        ai_service.log_activity(
            feature_type="chat",
            action="Library chat query",
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            success=True,
        )

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error("[AI-CHAT] Chat stream failed: %s" % e)

        if circuit_breaker:
            circuit_breaker.record_failure()

        ai_service.log_activity(
            feature_type="chat",
            action="Library chat query",
            model=model or "unknown",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            success=False,
            error_message=str(e),
        )

        yield {"type": "error", "content": "Something went wrong. Please try again."}

    yield {"type": "done"}
