#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Structured output helper — sends prompts to the LLM with a Pydantic
schema embedded in the user message and validates the response.
"""

import json
import re

from comicarr import logger


def request_structured(client, model, system_prompt, user_prompt, schema_class, temperature=0.1, timeout=30):
    """Send a structured output request and return a validated Pydantic model.

    Embeds the JSON schema from *schema_class* in the user prompt so the
    model knows the expected shape. Validates the response with
    ``schema_class.model_validate_json()``.

    Falls back to extracting JSON from markdown fences if initial parsing
    fails.

    Raises ``ValueError`` on validation failure or ``Exception`` on API error.
    """
    schema_json = json.dumps(schema_class.model_json_schema(), indent=2)
    full_user_prompt = "%s\n\nRespond with valid JSON matching this schema:\n%s" % (user_prompt, schema_json)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=temperature,
        timeout=timeout,
    )

    raw = response.choices[0].message.content

    # Try direct parse first
    try:
        return schema_class.model_validate_json(raw)
    except Exception:
        pass

    # Fallback: extract from markdown fences
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if match:
        try:
            return schema_class.model_validate_json(match.group(1).strip())
        except Exception:
            pass

    # Final attempt: try parsing as dict and validating
    try:
        data = json.loads(raw)
        return schema_class.model_validate(data)
    except Exception as e:
        logger.error("[AI-STRUCTURED] Failed to parse LLM response: %s" % e)
        raise ValueError("Failed to parse structured response from LLM: %s" % e)
