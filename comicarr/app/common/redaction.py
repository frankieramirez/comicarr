#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Shared secret redaction for operator-visible diagnostic text."""

import re
import traceback

_PROVIDER_STRUCTURE_PATTERN = re.compile(r"(?i)(provider_list|newznab_info|torznab_info)\s*:\s*[^\r\n]*")
_AUTHORIZATION_PATTERN = re.compile(
    r"(?i)([\"']?authorization[\"']?\s*[:=]\s*[\"']?)(?:basic|bearer|token|digest)\s+[^\s,;\"'}\]]+"
)
_NAMED_SECRET_PATTERN = re.compile(
    r"(?i)([\"']?(?:api[ _-]?key|authorization|password|passkey|authkey|token)[\"']?\s*[=:]\s*[\"']?)(?!\[redacted\])([^\s,;\"'}\]]+)([\"']?)"
)
_QUERY_SECRET_PATTERN = re.compile(r"(?i)([?&](?:apikey|api_key|r|token|password|passkey|auth|authkey)=)[^&\s]+")
_URL_USERINFO_PATTERN = re.compile(r"(?i)(https?://)[^/@\s]+@")


def redact_sensitive_text(value, secrets=()):
    """Redact known runtime secrets and common structured credential forms."""
    message = str(value or "")
    for secret in sorted(
        (str(secret) for secret in secrets if secret not in (None, "", "None") and len(str(secret)) > 3),
        key=len,
        reverse=True,
    ):
        message = message.replace(secret, "[redacted]")

    message = _PROVIDER_STRUCTURE_PATTERN.sub(r"\1: [redacted]", message)
    message = _AUTHORIZATION_PATTERN.sub(r"\1[redacted]", message)
    message = _NAMED_SECRET_PATTERN.sub(r"\1[redacted]\3", message)
    message = _QUERY_SECRET_PATTERN.sub(r"\1[redacted]", message)
    return _URL_USERINFO_PATTERN.sub(r"\1[redacted]@", message)


def redacted_traceback(error):
    return redact_sensitive_text("".join(traceback.format_exception(error)).rstrip())
