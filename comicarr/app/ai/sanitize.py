#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Input sanitization for prompt injection defense.

Strips common injection patterns and wraps user-supplied metadata
values with Microsoft Spotlighting delimiters.
"""

import re

# Patterns that may indicate prompt injection attempts
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?above\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"^system\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"<\|im_start\|>"),
    re.compile(r"<\|im_end\|>"),
    re.compile(r"<\|endoftext\|>"),
    re.compile(r"```"),
]


def sanitize_input(text, max_length=2000):
    """Strip injection patterns, truncate to max_length, and return cleaned text."""
    if not text:
        return ""

    if not isinstance(text, str):
        text = str(text)

    for pattern in _INJECTION_PATTERNS:
        text = pattern.sub("", text)

    text = text.strip()

    if len(text) > max_length:
        text = text[:max_length]

    return text


def spotlight_wrap(text):
    """Wrap metadata values with Microsoft Spotlighting delimiters.

    Spotlighting helps the model distinguish between instructions
    and user-supplied data, reducing prompt injection risk.
    """
    if not text:
        return ""
    return "<<<" + str(text) + ">>>"
