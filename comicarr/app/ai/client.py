#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
AI client factory — creates OpenAI-compatible sync and async clients.

Validates configuration before constructing clients:
  - base URL must use http or https (https required for non-localhost)
  - API key must not be an undecrypted Fernet token (starts with gAAAAA)
"""

from urllib.parse import urlparse

from openai import AsyncOpenAI, OpenAI

from comicarr import logger


def create_ai_clients(config):
    """Return (sync_client, async_client) or (None, None) if not configured."""
    base_url = getattr(config, "AI_BASE_URL", None)
    api_key = getattr(config, "AI_API_KEY", None)
    model = getattr(config, "AI_MODEL", None)

    if not base_url or not api_key or not model:
        logger.fdebug("[AI-CLIENT] AI not configured — missing base_url, api_key, or model")
        return (None, None)

    # Validate URL scheme
    try:
        parsed = urlparse(base_url)
    except Exception as e:
        logger.error("[AI-CLIENT] Invalid AI_BASE_URL: %s" % e)
        return (None, None)

    if parsed.scheme not in ("http", "https"):
        logger.error("[AI-CLIENT] AI_BASE_URL must use http or https, got: %s" % parsed.scheme)
        return (None, None)

    # Require https for non-localhost
    hostname = parsed.hostname or ""
    is_local = (
        hostname in ("localhost", "127.0.0.1", "::1") or hostname.startswith("192.168.") or hostname.startswith("10.")
    )
    if parsed.scheme != "https" and not is_local:
        logger.error("[AI-CLIENT] AI_BASE_URL requires https for non-local hosts: %s" % base_url)
        return (None, None)

    # Check for failed Fernet decryption
    if api_key.startswith("gAAAAA"):
        logger.error("[AI-CLIENT] AI_API_KEY appears to be an undecrypted Fernet token — skipping")
        return (None, None)

    try:
        sync_client = OpenAI(base_url=base_url, api_key=api_key)
        async_client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        logger.fdebug("[AI-CLIENT] Clients created for %s" % base_url)
        return (sync_client, async_client)
    except Exception as e:
        logger.error("[AI-CLIENT] Failed to create AI clients: %s" % e)
        return (None, None)
