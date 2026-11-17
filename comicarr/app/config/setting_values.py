#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Reject a settings save whose values Comicarr would otherwise change quietly.

Before #1492 a search interval of -5 was saved as 360, and the page still said
"Saved". This check runs in `update_config` before anything is written, so a
value is either stored as typed or refused with a reason.

A refusal carries a `code`, the `field` (wire name) and `params`, so the
Settings page can show a translated message on the field itself. `error` is the
English text for API clients that only read that.

Loading an INI file still raises a low value to its minimum (`ini.py`), because
nobody is there to read an error.
"""

from __future__ import annotations

import re

from comicarr.app.config.registry import REGISTRY

# MangaDex language codes are ISO 639-1, with an optional region or script
# suffix: en, ja, pt-br, es-la, zh-hk, ja-ro.
_LANGUAGE_CODE = re.compile(r"^[a-z]{2}(-[a-z]{2})?$")

MANGADEX_CONTENT_RATINGS = ("safe", "suggestive", "erotica", "pornographic")


def _refusal(code, key, error, **params):
    return {
        "success": False,
        "error": error,
        "code": code,
        "field": key.lower(),
        "params": params,
    }


def _split_list(value):
    return [part.strip().casefold() for part in str(value or "").split(",") if part.strip()]


def _secret_is_set(value):
    return bool(value and value != "None")


def check_setting_values(config, filtered):
    """Return a refusal dict for the first value that cannot be saved, else None.

    `filtered` holds uppercase keys already limited to writable ones. It is
    normalised in place where the stored form differs only in spacing, case or
    repeats (MangaDex lists), which changes no meaning. An empty MangaDex list
    stays empty: MangaDex then uses its defaults, as before.
    """
    for name, value in filtered.items():
        key = REGISTRY.get(name)
        if key is None or key.minimum is None:
            continue
        if isinstance(value, bool):
            number = None
        else:
            try:
                number = int(str(value).strip())
            except (TypeError, ValueError):
                number = None
        if number is None:
            return _refusal("setting_not_whole_number", name, "%s must be a whole number" % name.lower())
        if number < key.minimum:
            return _refusal(
                "setting_below_minimum",
                name,
                "%s must be at least %d" % (name.lower(), key.minimum),
                minimum=key.minimum,
            )
        filtered[name] = number

    if "MANGADEX_LANGUAGES" in filtered:
        codes = _split_list(filtered["MANGADEX_LANGUAGES"])
        unknown = [code for code in codes if not _LANGUAGE_CODE.match(code)]
        if unknown:
            return _refusal(
                "mangadex_language_unknown",
                "MANGADEX_LANGUAGES",
                "Unknown MangaDex language code: %s" % ", ".join(unknown),
                codes=", ".join(unknown),
            )
        filtered["MANGADEX_LANGUAGES"] = ",".join(dict.fromkeys(codes))

    if "MANGADEX_CONTENT_RATING" in filtered:
        ratings = _split_list(filtered["MANGADEX_CONTENT_RATING"])
        unknown = [rating for rating in ratings if rating not in MANGADEX_CONTENT_RATINGS]
        if unknown:
            return _refusal(
                "mangadex_rating_unknown",
                "MANGADEX_CONTENT_RATING",
                "Unknown MangaDex content rating: %s" % ", ".join(unknown),
                ratings=", ".join(unknown),
            )
        filtered["MANGADEX_CONTENT_RATING"] = ",".join(dict.fromkeys(ratings))

    if "DISCORD_ENABLED" in filtered or "DISCORD_WEBHOOK_URL" in filtered:
        enabled = filtered.get("DISCORD_ENABLED", getattr(config, "DISCORD_ENABLED", False))
        if "DISCORD_WEBHOOK_URL" in filtered:
            webhook = filtered["DISCORD_WEBHOOK_URL"]
        else:
            webhook = getattr(config, "DISCORD_WEBHOOK_URL", None)
        if enabled is True and not (isinstance(webhook, str) and _secret_is_set(webhook.strip())):
            return _refusal(
                "discord_webhook_required",
                "DISCORD_WEBHOOK_URL",
                "Enter a Discord webhook URL to turn on Discord notifications",
            )

    return None
