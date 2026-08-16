#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
System domain service — auth verification, config management, admin ops.

Module-level functions (not classes) — matches existing codebase style.
"""

import calendar
import ctypes
import datetime
import hmac
import json
import os
import platform
import re
import secrets
import shlex
import subprocess
import sys
import threading
from collections import deque, namedtuple
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
)
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

import comicarr
from comicarr import db, logger
from comicarr.app.acquisition.models import DispatchState
from comicarr.app.common.dates import normalize_utc_datetime
from comicarr.app.common.redaction import redact_sensitive_text
from comicarr.app.config.log_level import (
    ACCEPTED_FORMS,
    NAME_FOR_LEVEL,
    SOURCE_SETTINGS,
    parse_level,
    resolve_effective_log_level,
)
from comicarr.app.config.registry import (
    readable_keys,
    scheduler_job_intervals,
    scheduler_job_required_config,
    writable_keys,
)
from comicarr.app.core.security import LoginRateLimiter
from comicarr.app.core.workers import start_background_thread
from comicarr.app.search.provider_config import (
    SearchProvider,
    normalize_category_list,
    providers_from_config,
)
from comicarr.tables import comics, jobhistory, storyarcs

# Shared rate limiter instance for authentication endpoints.
_rate_limiter = LoginRateLimiter()
_fallback_weekly_refresh_lock = threading.Lock()

WEEKLY_JOB_NAME = "Weekly Pullist"
SCHEDULER_JOB_NAMES = {
    "dbupdater": "DB Updater",
    "search": "Auto-Search",
    "weekly": WEEKLY_JOB_NAME,
    "rss": "RSS Feeds",
    "version": "Check Version",
    "monitor": "Folder Monitor",
    "importinbox": "Import Inbox Scanner",
    "ddl_health": "DDL Health Check",
    "ledger_retention": "Ledger Retention",
    "activity_retention": "Activity Event Retention",
    "interactive_search_retention": "Interactive Search Retention",
    "manga_sync": "Manga ledger sync",
}

SETUP_PERSISTENCE_ERROR = "Failed to persist initial credentials"
CONFIG_PERSISTENCE_ERROR = "Failed to persist configuration"
PROVIDER_CONFIG_PERSISTENCE_ERROR = "Failed to persist provider configuration"


def get_weekly_refresh_lock():
    """Return the process-wide weekly lock after package initialization."""
    return getattr(comicarr, "WEEKLY_REFRESH_LOCK", _fallback_weekly_refresh_lock)


def _secret_is_configured(value):
    """Return True when a config secret has a meaningful stored value."""
    return bool(value and value != "None")


def verify_login(ctx, username, password, ip):
    """Verify login credentials with rate limiting and bcrypt migration.

    Returns dict with 'success' key and optional 'error' or 'username'.
    """
    from comicarr import encrypted

    if _rate_limiter.is_locked_out(ip):
        logger.info("[AUTH] Login attempt blocked (rate limited) from IP: %s" % ip)
        return {"success": False, "error": "Incorrect username or password."}

    forms_user = getattr(ctx.config, "HTTP_USERNAME", None) if ctx.config else None
    forms_pass = getattr(ctx.config, "HTTP_PASSWORD", None) if ctx.config else None

    if not forms_user or not forms_pass:
        return {"success": False, "error": "Authentication not configured"}

    if not hmac.compare_digest(username, forms_user):
        _rate_limiter.record_failure(ip)
        logger.info("[AUTH-AUDIT] Failed login attempt — invalid username from IP: %s" % ip)
        return {"success": False, "error": "Incorrect username or password."}

    # Three-state password verification (bcrypt → legacy base64 → plaintext)
    if forms_pass.startswith("$2b$") or forms_pass.startswith("$2a$"):
        if encrypted.verify_password(password, forms_pass):
            _rate_limiter.record_success(ip)
            logger.info("[AUTH-AUDIT] Successful login for user '%s' from IP: %s" % (username, ip))
            return {"success": True, "username": username}
        else:
            _rate_limiter.record_failure(ip)
            logger.info("[AUTH-AUDIT] Failed login — wrong password for '%s' from IP: %s" % (username, ip))
            return {"success": False, "error": "Incorrect username or password."}
    elif forms_pass.startswith("^~$z$"):
        edc = encrypted.Encryptor(forms_pass, logon=True)
        ed_chk = edc.decrypt_it()
        if ed_chk["status"] is True and ed_chk["password"] == password:
            _migrate_password(ctx, password)
            _rate_limiter.record_success(ip)
            logger.info("[AUTH-AUDIT] Successful login for user '%s' from IP: %s" % (username, ip))
            return {"success": True, "username": username}
        else:
            _rate_limiter.record_failure(ip)
            return {"success": False, "error": "Incorrect username or password."}
    else:
        # Plaintext comparison + auto-migrate
        if password == forms_pass:
            _migrate_password(ctx, password)
            _rate_limiter.record_success(ip)
            logger.info("[AUTH-AUDIT] Successful login for user '%s' from IP: %s" % (username, ip))
            return {"success": True, "username": username}
        else:
            _rate_limiter.record_failure(ip)
            return {"success": False, "error": "Incorrect username or password."}


def _migrate_password(ctx, plaintext_password):
    """Auto-migrate password to bcrypt hash."""
    from comicarr import encrypted

    new_hash = encrypted.hash_password(plaintext_password)
    if ctx.config and ctx.config.apply_transaction({"http_password": new_hash}, configure=False):
        logger.info("[AUTH] Password migrated to bcrypt")
    else:
        logger.error("[AUTH] Failed to persist bcrypt password migration")


def announce_setup_token(setup_token):
    """Announce the first-run setup token, including stdout at level 0."""
    messages = [
        "[SETUP] *** First-run setup required ***",
        "[SETUP] Setup token: %s" % setup_token,
        "[SETUP] Provide this token when setting up credentials via the web interface.",
    ]

    for message in messages:
        logger.info(message)

    # At level 0 the console sink is at WARNING, so the INFO lines above never
    # reach it — and without the token the operator cannot finish setup at all.
    if logger.current_log_level() == 0:
        for message in messages:
            print(message, flush=True)


def initial_setup(ctx, username, password, setup_token):
    """Handle first-run credential setup."""
    from comicarr import encrypted
    from comicarr.app.core.runtime import set_runtime_field

    if getattr(ctx.config, "HTTP_USERNAME", None) and getattr(ctx.config, "HTTP_PASSWORD", None):
        return {"success": False, "error": "Credentials already configured"}

    if ctx.setup_token is not None:
        if not setup_token or not hmac.compare_digest(setup_token, ctx.setup_token):
            return {"success": False, "error": "Invalid setup token. Check the server console log."}

    if not username or not password:
        return {"success": False, "error": "Username and password required"}

    if len(password) < 8:
        return {"success": False, "error": "Password must be at least 8 characters"}

    try:
        hashed_password = encrypted.hash_password(password)
        persisted = ctx.config.apply_transaction(
            {
                "http_username": username,
                "http_password": hashed_password,
                "authentication": 2,
            }
        )
    except Exception as e:
        logger.error("[AUTH-SETUP] Failed to persist initial credentials: %s" % e)
        persisted = False

    if not persisted:
        return {"success": False, "error": SETUP_PERSISTENCE_ERROR}

    logger.info("[AUTH-SETUP] Initial credentials configured for user: %s" % username)

    set_runtime_field(ctx, "setup_token", None)

    # Signal restart for session config to take effect
    set_runtime_field(ctx, "signal", "restart")

    return {"success": True, "username": username, "needs_restart": True}


# Sorted so the response key order is stable; get_safe_config reads it every call.
_READABLE_KEYS = sorted(readable_keys())

# Repo root: comicarr/app/system/service.py → ../../../..
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def get_release_version():
    """Return the Changesets-managed release version (semver), not a git SHA.

    User-facing ``config.version`` must match the frontend package badge. The
    runtime ``current_version`` field is often a commit hash or an unexpanded
    export-subst placeholder; those stay on ``/api/system/version`` / build
    identity, not on the app version string.

    Preference order:
    1. ``pyproject.toml`` project.version (release SSOT in source/Docker trees)
    2. ``importlib.metadata`` for pure installs without a nearby pyproject
    """
    version = _read_pyproject_version()
    if version:
        return version
    try:
        from importlib.metadata import version as package_version

        return package_version("comicarr")
    except Exception:
        return None


def _read_pyproject_version():
    """Read [project].version from the repo pyproject.toml when present."""
    pyproject = _REPO_ROOT / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        try:
            import tomllib
        except ModuleNotFoundError:  # Python 3.10
            import tomli as tomllib
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        version = data.get("project", {}).get("version")
        if not version or "%" in str(version) or "$" in str(version):
            return None
        return str(version)
    except Exception:
        return None


def get_safe_config(ctx):
    """Return configuration as a safe dict (no passwords/keys)."""
    if not ctx.config:
        return {}

    safe_keys = _READABLE_KEYS
    result = {}
    for key in safe_keys:
        val = getattr(ctx.config, key, None)
        if val is not None:
            result[key] = val
    if "SAB_HOST" in result:
        result["SAB_HOST"] = _safe_provider_host(result["SAB_HOST"])

    secret_indicators = {
        "api_key_set": "API_KEY",
        "comicvine_api_set": "COMICVINE_API",
        "ai_api_key_set": "AI_API_KEY",
        "metron_password_set": "METRON_PASSWORD",
        "mal_client_id_set": "MAL_CLIENT_ID",
        "prowl_keys_set": "PROWL_KEYS",
        "slack_webhook_url_set": "SLACK_WEBHOOK_URL",
        "mattermost_webhook_url_set": "MATTERMOST_WEBHOOK_URL",
        "discord_webhook_url_set": "DISCORD_WEBHOOK_URL",
        "sab_apikey_set": "SAB_APIKEY",
    }
    for output_key, config_key in secret_indicators.items():
        result[output_key] = _secret_is_configured(getattr(ctx.config, config_key, None))

    # Add derived download client labels (must match config.py enums)
    nzb_labels = {0: "SABnzbd", 1: "NZBGet", 2: "Blackhole", 3: "Disabled"}
    torrent_labels = {0: "Watchfolder", 1: "uTorrent", 2: "rTorrent", 3: "Transmission", 4: "Deluge", 5: "qBittorrent"}
    nzb_val = getattr(ctx.config, "NZB_DOWNLOADER", None)
    torrent_val = getattr(ctx.config, "TORRENT_DOWNLOADER", None)
    if nzb_val is not None:
        result["nzb_downloader_label"] = nzb_labels.get(nzb_val, "None")
    if torrent_val is not None:
        result["torrent_downloader_label"] = torrent_labels.get(torrent_val, "None")

    # Lowercase all keys for frontend convention
    result = {k.lower(): v for k, v in result.items()}
    # Release semver only — never ctx.current_version (git SHA / install id).
    version = get_release_version()
    if version:
        result["version"] = version
    result["newznab"] = _safe_provider_projection(ctx.config, "newznab")
    result["torznab"] = _safe_provider_projection(ctx.config, "torznab")
    return result


def _safe_provider_host(value):
    """Return a provider URL without userinfo credentials."""
    host = str(value or "")
    try:
        parsed = urlsplit(host)
        if parsed.username or parsed.password:
            safe_netloc = parsed.netloc.rsplit("@", 1)[-1]
            host = urlunsplit((parsed.scheme, safe_netloc, parsed.path, parsed.query, parsed.fragment))
    except ValueError:
        return ""
    return redact_sensitive_text(host)


def _http_origin(value):
    """Return a normalized HTTP origin for binding a stored credential."""
    try:
        parsed = urlsplit(str(value or ""))
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname.lower() if parsed.hostname else None
        if scheme not in {"http", "https"} or not hostname:
            return None
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, hostname, port


def _safe_provider_projection(config, provider_type):
    """Build the credential-free provider projection returned by the API."""
    enabled_key = "NEWZNAB" if provider_type == "newznab" else "ENABLE_TORZNAB"
    rows = []
    for provider in providers_from_config(config, provider_type):
        row = {
            "name": provider.name,
            "host": _safe_provider_host(provider.host),
            "verify": provider.verify,
            "categories": ",".join(provider.categories),
            "enabled": provider.enabled,
            "api_key_set": _secret_is_configured(provider.api_key),
        }
        if provider_type == "newznab":
            row["rss_uid"] = provider.rss_uid
        if provider.id is not None:
            row["id"] = provider.id
        rows.append(row)
    return {"enabled": bool(getattr(config, enabled_key, False)), "providers": rows}


def get_provider_config(ctx):
    """Return credential-free Newznab and Torznab settings for the UI."""
    if not ctx.config:
        return {"newznab": {"enabled": False, "providers": []}, "torznab": {"enabled": False, "providers": []}}
    return {
        "newznab": _safe_provider_projection(ctx.config, "newznab"),
        "torznab": _safe_provider_projection(ctx.config, "torznab"),
    }


WRITABLE_CONFIG_KEYS = writable_keys()


def update_config(ctx, key_values):
    """Update configuration key-values and trigger scheduler reconfiguration."""
    import comicarr
    from comicarr.config import config_transaction_lock

    if not ctx.config:
        return {"success": False, "error": "Config not loaded"}

    # Normalize incoming keys to uppercase — frontend sends lowercase,
    # but config internals use UPPERCASE.
    key_values = {k.upper(): v for k, v in key_values.items()}

    # Filter to only writable keys — prevents privilege escalation via
    # overwriting HTTP_PASSWORD, API_KEY, AUTHENTICATION, etc.
    rejected = [k for k in key_values if k not in WRITABLE_CONFIG_KEYS]
    if rejected:
        logger.info("[CONFIG] Rejected non-writable keys: %s" % rejected)
    filtered = {k: v for k, v in key_values.items() if k in WRITABLE_CONFIG_KEYS}
    if not filtered:
        return {"success": False, "error": "No valid config keys provided"}

    level_notices = []
    if "LOG_LEVEL" in filtered:
        # Read by the same rules as every other source of the level, so a value
        # typed into Settings behaves like one passed on the command line: both
        # notations are accepted, out of range clamps, and anything else is
        # refused. A startup source is clamped rather than rejected because
        # refusing to boot helps nobody; an HTTP request can simply be told it
        # was wrong, and persisting garbage would leave the level silently
        # ignored at the next start. Whichever form arrives, an integer is what
        # gets stored.
        level, level_notices = parse_level(filtered["LOG_LEVEL"], SOURCE_SETTINGS)
        if level is None:
            return {
                "success": False,
                "error": "LOG_LEVEL must be %s" % ACCEPTED_FORMS,
            }
        filtered["LOG_LEVEL"] = level

    if "NZB_DOWNLOADER" in filtered:
        nzb_downloader = filtered["NZB_DOWNLOADER"]
        if isinstance(nzb_downloader, bool) or not isinstance(nzb_downloader, int) or not 0 <= nzb_downloader <= 3:
            return {"success": False, "error": "NZB_DOWNLOADER must be an integer between 0 and 3"}

    if "SAB_HOST" in filtered:
        new_origin = _http_origin(filtered["SAB_HOST"])
        if new_origin is None:
            return {"success": False, "error": "SABnzbd server must be a valid HTTP or HTTPS URL"}
        old_origin = _http_origin(getattr(ctx.config, "SAB_HOST", None))
        stored_key = getattr(ctx.config, "SAB_APIKEY", None)
        replacement_key = filtered.get("SAB_APIKEY")
        if (
            old_origin != new_origin
            and _secret_is_configured(stored_key)
            and not _secret_is_configured(replacement_key)
        ):
            return {
                "success": False,
                "error": "SABnzbd API key is required when changing the server origin",
            }

    interval_changed = any(k in set(SCHEDULER_JOB_INTERVALS.values()) for k in filtered)

    # Writing the level and applying it have to be one step. apply_transaction
    # serializes the write on this same (reentrant) lock, but on its own that
    # only orders the writes: two saves racing could persist B and then apply A,
    # leaving config.ini and the running logger disagreeing about the dial —
    # exactly the confusion this dial exists to remove. Scheduler
    # reconfiguration is deliberately left outside; it is slow, it touches
    # APScheduler's own locks, and no config write depends on it having run.
    with config_transaction_lock():
        try:
            persisted = ctx.config.apply_transaction(filtered)
        except Exception as e:
            logger.error("[CONFIG] Failed to persist configuration update: %s" % e)
            persisted = False

        if not persisted:
            return {"success": False, "error": CONFIG_PERSISTENCE_ERROR}

        # Sync back to globals during transition
        comicarr.CONFIG = ctx.config

        if "LOG_LEVEL" in filtered:
            # After the global sync: configure_log_level rebuilds the handlers
            # from comicarr.CONFIG, so it has to see the config just written.
            _apply_log_level_now(filtered["LOG_LEVEL"])

    if interval_changed:
        _reconfigure_schedulers(ctx)

    for notice in level_notices:
        # WARNING rather than INFO, because it passes at every level by
        # contract: a clamp notice logged at INFO is invisible at exactly the
        # level a downward clamp lands on. It is warning-shaped anyway — the
        # operator asked for a level they did not get. Emitted after the change
        # is in force, so "using 0" describes what happened rather than what
        # was about to be attempted.
        logger.warn("[CONFIG] %s" % notice)

    return {"success": True}


def _apply_log_level_now(level):
    """Make a saved log level take effect immediately, without a restart.

    The point of raising verbosity is to catch a problem *while it is
    happening* (#610); a dial that waits for a restart destroys the state the
    operator was trying to capture. `logger.configure_log_level` has always
    done the live reconfigure — until now its only caller was maintenance
    mode, so the settings key was writable, invisible, and inert until startup.

    Persisting comes first and stays committed even if this fails: a level that
    survives the restart but is not yet live is a far smaller failure than a
    live level the next start forgets. Rebuilding the handlers can fail on a
    log directory that has become unwritable, and that is not a reason to
    report the save itself as failed.
    """
    try:
        logger.configure_log_level(level)
        return True
    except Exception as e:
        logger.error("[CONFIG] Saved log level %s but could not apply it until restart: %s" % (level, e))
        return False


def regenerate_api_key(ctx, username, ip):
    """Regenerate and persist the full API key."""
    import comicarr

    if not ctx.config:
        return {"success": False, "error": "Config not loaded"}

    new_api_key = secrets.token_hex(16)
    try:
        if ctx.config.apply_transaction({"api_key": new_api_key}) is False:
            raise OSError("config write failed")
    except Exception as e:
        logger.error("[API-KEY] Failed to persist regenerated API key: %s" % e)
        return {"success": False, "error": "Failed to persist new API key"}

    # Sync back to globals during transition
    comicarr.CONFIG = ctx.config

    # Rotation revokes every outstanding API credential, so record who did it —
    # otherwise integrations start failing with nothing in the log to explain why.
    logger.info("[AUTH-AUDIT] API key regenerated by user '%s' from IP: %s" % (username, ip))

    return {"success": True, "api_key": new_api_key}


def update_providers(ctx, provider_data):
    """Update Newznab/Torznab provider configuration.

    Object-payload ``verify`` and ``enabled`` — on each provider row and the
    top-level enablement flag — must be JSON booleans when present. Non-boolean
    values are rejected so a string like ``"false"`` cannot silently enable a
    provider.
    """

    if not ctx.config:
        return {"success": False, "error": "Config not loaded"}

    if not isinstance(provider_data, dict):
        return {"success": False, "error": "Invalid provider payload"}

    provider_type = provider_data.get("type")
    providers = provider_data.get("providers", [])
    object_payload = any(isinstance(row, dict) for row in providers) if isinstance(providers, list) else False

    if provider_type not in ("newznab", "torznab"):
        return {"success": False, "error": "Invalid provider type"}
    if not isinstance(providers, list):
        return {"success": False, "error": "Invalid provider list"}
    if "enabled" in provider_data and not isinstance(provider_data["enabled"], bool):
        return {"success": False, "error": "Provider enabled must be a boolean"}

    config_key = "EXTRA_NEWZNABS" if provider_type == "newznab" else "EXTRA_TORZNABS"
    if object_payload:
        existing = providers_from_config(ctx.config, provider_type)
        by_id = {str(record.id): record for record in existing if record.id is not None}
        by_identity = {(record.name, _safe_provider_host(record.host)): record for record in existing}
        normalized = []
        for row in providers:
            if not isinstance(row, dict):
                return {"success": False, "error": "Invalid provider configuration"}
            if "enabled" in row and not isinstance(row["enabled"], bool):
                return {"success": False, "error": "Provider enabled must be a boolean"}
            if "verify" in row and not isinstance(row["verify"], bool):
                return {"success": False, "error": "Provider verify must be a boolean"}
            old = by_id.get(str(row.get("id"))) or by_identity.get(
                (str(row.get("name") or ""), _safe_provider_host(row.get("host")))
            )
            credential = row.get("api_key", row.get("apikey"))
            host = str(row.get("host") or "")
            new_origin = _http_origin(host)
            if new_origin is None:
                return {"success": False, "error": "Provider URL must use HTTP or HTTPS"}
            if credential in (None, "") and old is not None and _secret_is_configured(old.api_key):
                if _http_origin(old.host) != new_origin:
                    return {
                        "success": False,
                        "error": "A new API key is required when changing a provider origin",
                    }
                credential = old.api_key
            if old is not None and host == _safe_provider_host(old.host):
                host = old.host
            rss_uid = None
            if provider_type == "newznab":
                # Keep the uid the operator is already using when the client
                # does not send one back, so editing categories cannot silently
                # repoint the indexer's RSS feed at a different user.
                rss_uid = row.get("rss_uid")
                if rss_uid in (None, ""):
                    rss_uid = old.rss_uid if old is not None else None
            provider_id = row.get("id") if row.get("id") is not None else (old.id if old is not None else None)
            record = SearchProvider(
                kind=provider_type,
                name=row.get("name", ""),
                host=host,
                verify=bool(row.get("verify")),
                api_key=credential or "",
                categories=tuple(normalize_category_list(row.get("categories"))),
                enabled=bool(row.get("enabled")),
                rss_uid=rss_uid,
                id=provider_id,
            )
            normalized.append(list(record.to_entry()))
        providers = normalized
    try:
        ctx.config.validate_provider_extra_value(config_key, providers)
    except (TypeError, ValueError):
        return {"success": False, "error": "Invalid provider configuration"}
    values = {config_key: providers}
    if "enabled" in provider_data:
        enabled_key = "NEWZNAB" if provider_type == "newznab" else "ENABLE_TORZNAB"
        values[enabled_key] = provider_data["enabled"]
    try:
        persisted = ctx.config.apply_transaction(values, configure=False)
    except Exception as e:
        logger.error("[PROVIDERS] Failed to persist provider configuration: %s" % type(e).__name__)
        persisted = False

    if persisted is False:
        return {"success": False, "error": PROVIDER_CONFIG_PERSISTENCE_ERROR}

    result = {"success": True}
    if object_payload:
        result.update(_safe_provider_projection(ctx.config, provider_type))
    return result


# Scheduler job id -> the config attribute that drives its cadence, in minutes.
SCHEDULER_JOB_INTERVALS = scheduler_job_intervals()

# Scheduler job id -> a config attribute that must be set for the job to do
# anything. Mirrors the CHECK_FOLDER / IMPORT_DIR guards in comicarr.start().
SCHEDULER_JOB_REQUIRED_CONFIG = scheduler_job_required_config()

# Job ids this process parked because their interval was non-positive, so a
# later positive interval can bring them back.
#
# APScheduler's pause_job() is just next_run_time=None, so a paused job cannot
# say why it is paused -- and job_management() reads that same state back into
# comicarr.<JOB>_STATUS, which means a job we parked starts looking exactly like
# one the operator paused from the jobs UI. Remembering who did the parking is
# what keeps the two apart. A job the operator paused is never in this set and
# is therefore never resumed here.
#
# Process-scoped on purpose: a pause that outlives the process is replayed from
# jobhistory by job_management(startup=True), and at that point nothing can say
# why it was paused, so start() stays the authority.
_INTERVAL_PARKED_JOBS = set()


def _job_may_run(ctx, job_id):
    """Whether job_id is allowed to run at all, mirroring comicarr.start()'s gates.

    These are the conditions that have nothing to do with the interval, so they
    still hold for a job this module parked itself.
    """
    if getattr(ctx, "acquisition_workers_blocked", False):
        # Every job in SCHEDULER_JOB_INTERVALS is a producer or consumer of
        # acquisition work; start() leaves them all paused behind this gate.
        return False

    required_key = SCHEDULER_JOB_REQUIRED_CONFIG.get(job_id)
    if required_key and not getattr(ctx.config, required_key, None):
        return False

    return True


def _reconfigure_schedulers(ctx):
    """Apply changed intervals to the running scheduler.

    Returns the job ids that were rescheduled. Never raises: the durable config
    write has already happened by the time this runs, so a scheduler failure
    must not turn a successful save into a failed response.
    """
    scheduler = getattr(ctx, "scheduler", None)
    if scheduler is None or not ctx.config:
        return ()

    now = datetime.datetime.now(datetime.timezone.utc)
    rescheduled = []
    for job_id, config_key in SCHEDULER_JOB_INTERVALS.items():
        try:
            minutes = int(getattr(ctx.config, config_key, None))
        except (TypeError, ValueError):
            logger.error(
                "[SYSTEM] Could not reschedule %s: %s is not a usable interval (%r)"
                % (job_id, config_key, getattr(ctx.config, config_key, None))
            )
            continue

        try:
            job = scheduler.get_job(job_id)
            if job is None:
                continue
            if minutes <= 0:
                scheduler.pause_job(job_id)
                _INTERVAL_PARKED_JOBS.add(job_id)
                continue

            trigger = IntervalTrigger(minutes=minutes, timezone="UTC")
            pending = job.next_run_time
            if pending is None:
                if job_id in _INTERVAL_PARKED_JOBS and _job_may_run(ctx, job_id):
                    # We parked this one for a non-positive interval; a positive
                    # one is the operator asking for it back.
                    job.modify(trigger=trigger, next_run_time=now + datetime.timedelta(minutes=minutes))
                    _INTERVAL_PARKED_JOBS.discard(job_id)
                else:
                    # Paused by someone else, so it stays paused. job.modify(trigger=...)
                    # leaves next_run_time alone; scheduler.reschedule_job() recomputes
                    # it from the trigger and would silently resume the job.
                    job.modify(trigger=trigger)
            else:
                _INTERVAL_PARKED_JOBS.discard(job_id)
                # Shortening an interval takes effect now; lengthening one takes
                # effect after the run that is already scheduled. A pending run
                # is never pushed later.
                job.modify(
                    trigger=trigger,
                    next_run_time=min(pending, now + datetime.timedelta(minutes=minutes)),
                )
            rescheduled.append(job_id)
        except Exception as e:
            logger.error("[SYSTEM] Could not reschedule %s: %s" % (job_id, e))

    if rescheduled:
        logger.fdebug("[SYSTEM] Rescheduled jobs after config change: %s" % ", ".join(rescheduled))
    return tuple(rescheduled)


def get_version_info(ctx):
    """Return version information.

    Update availability is Changesets semver (``update_state``), not commit lag.
    ``release_version`` is the local release line; ``current_version`` remains
    the install/build identity (often a SHA).
    """
    update_state = getattr(ctx, "update_state", None) or "unknown"
    update_reason = getattr(ctx, "update_reason", None)
    if update_state != "unknown":
        update_reason = None
    elif update_reason is None:
        update_reason = "never_checked"
    from comicarr.app.system.whats_new import resolve_pending_whats_new

    # Seed LAST_SEEN_VERSION when absent (fresh install / first boot after
    # feature); may write once. Pending compare itself is read-only.
    pending_whats_new = resolve_pending_whats_new(ctx)

    return {
        "current_version": ctx.current_version,
        "current_version_name": ctx.current_version_name,
        "current_release_name": ctx.current_release_name,
        "latest_version": ctx.latest_version,
        "release_version": get_release_version(),
        "update_state": update_state,
        "update_reason": update_reason,
        "install_type": ctx.install_type,
        "current_branch": ctx.current_branch,
        "build": get_build_identity(ctx),
        "pending_whats_new": pending_whats_new,
    }


def get_release_notes(ctx, after, through):
    """Return structured release-note sections for ``(after, through]``.

    Mechanical transform of local CHANGELOG.md (and optional cached remote
    body when the operator is behind). See ``comicarr.changelog_notes``.
    """
    from comicarr.changelog_notes import get_release_notes as _get_notes

    return _get_notes(ctx, after=after, through=through)


def dismiss_whats_new(ctx):
    """Acknowledge What's New — write LAST_SEEN_VERSION = current."""
    from comicarr.app.system.whats_new import dismiss_whats_new as _dismiss

    return _dismiss(ctx)


def get_whats_new_archive(ctx):
    """Settings → About archive: floored/padded sections + pending range."""
    from comicarr.app.system.whats_new import get_archive_notes

    return get_archive_notes(ctx)


def force_version_check(ctx):
    """Run one release check, ignoring the automatic-check switch.

    ``CHECK_GITHUB`` off means no unsolicited traffic, not "refuse when asked".
    Auth is the caller's responsibility (router uses require_session).
    """
    import comicarr

    # Deliberately does not consult CHECK_GITHUB — Settings "Check now" must
    # work while automatic checks are off (Settings → About → Updates).
    runner = comicarr.versioncheckit.CheckVersion()
    check_result = runner.run(scheduled_job=False) or {}
    info = get_version_info(ctx)
    message = check_result.get("message")
    if message:
        info = {**info, "message": message}
    return info


def get_build_identity(ctx):
    """Return deploy identity without treating runtime fallbacks as verified."""
    declared_build_id = (os.environ.get("COMICARR_BUILD_ID") or "").strip() or None
    declared_build_commit = (os.environ.get("COMICARR_BUILD_COMMIT") or "").strip() or None
    build_id = declared_build_id
    build_commit = declared_build_commit
    source = "environment" if declared_build_id or declared_build_commit else "runtime"
    runtime_commit = getattr(ctx, "current_version", None)
    if not build_commit and runtime_commit and re.fullmatch(r"[0-9a-fA-F]{7,64}", str(runtime_commit)):
        build_commit = str(runtime_commit)
    release = getattr(ctx, "current_version_name", None) or getattr(ctx, "current_release_name", None)
    version = getattr(ctx, "current_version", None)
    if not build_id:
        build_id = release or version or "unknown"
    return {
        "id": str(build_id),
        "commit": str(build_commit) if build_commit else None,
        "release": release,
        "version": version,
        "source": source,
        # A version string or runtime Git SHA is useful diagnostic context,
        # but only the image build arguments bind both values to the deployed
        # artifact. Do not present a local/dev fallback as release-verified.
        "verified": bool(declared_build_id and declared_build_commit),
    }


# How many trailing lines Settings → Logs asks for by default, and the ceiling
# on what it may ask for. The file is capped at MAX_LOGSIZE anyway; the ceiling
# is here so one request cannot be made to hold an entire rotation in memory.
DEFAULT_LOG_LINES = 200
MAX_LOG_LINES = 5000


def _log_level_context(ctx):
    """The three levels the Settings dial has to be honest about.

    `saved` is what the dial edits, `effective` is what the process is logging
    at this second, and `restart` is what the startup chain resolves to next
    time. They can all differ, and #610 is what happens when the UI shows only
    the first one.
    """
    config_level = getattr(ctx.config, "LOG_LEVEL", None) if ctx.config else None
    effective = resolve_effective_log_level(logger.current_log_level(), config_level=config_level)
    return {
        "effective": effective.level,
        "effective_name": NAME_FOR_LEVEL[effective.level],
        "saved": effective.saved,
        "saved_name": NAME_FOR_LEVEL[effective.saved],
        "restart_level": effective.restart_level,
        "restart_name": NAME_FOR_LEVEL[effective.restart_level],
        "restart_source": effective.restart_source,
        "pinned": effective.pinned,
    }


def get_recent_logs(ctx, lines=DEFAULT_LOG_LINES):
    """Return the tail of `comicarr.log`, with the level context the dial needs.

    Only the current file: rotated `comicarr.log.1` and friends are deliberately
    unreachable here, and there is no pagination — the surface exists so an
    operator can raise the level, reproduce, and paste, not to browse history.
    """
    requested = max(1, min(int(lines or DEFAULT_LOG_LINES), MAX_LOG_LINES))
    level = _log_level_context(ctx)

    log_dir = getattr(ctx.config, "LOG_DIR", None) if ctx.config else None
    if not log_dir:
        log_dir = os.path.join(ctx.data_dir, "logs") if ctx.data_dir else None

    if not log_dir:
        return {"logs": [], "level": level, "requested": requested, "path": None}

    log_file = os.path.join(log_dir, "comicarr.log")
    if not os.path.exists(log_file):
        return {"logs": [], "level": level, "requested": requested, "path": log_file}

    try:
        # A deque with a maxlen keeps only the tail in memory. `readlines()` on a
        # 10 MB log allocated the whole file on every Refresh, and the viewer was
        # always going to throw all but the last N away.
        with open(log_file, "r") as f:
            tail = deque(f, maxlen=requested)
        provider_secrets = []
        if ctx.config:
            for attr_name in ("EXTRA_NEWZNABS", "EXTRA_TORZNABS"):
                for entry in getattr(ctx.config, attr_name, []) or []:
                    if isinstance(entry, (list, tuple)) and len(entry) > 3:
                        provider_secrets.append(entry[3])
        return {
            "logs": [redact_sensitive_text(line, provider_secrets) for line in tail],
            "level": level,
            "requested": requested,
            "path": log_file,
        }
    except Exception as e:
        logger.error("[SYSTEM] Error reading logs: %s" % e)
        return {"logs": [], "level": level, "requested": requested, "path": log_file, "error": str(e)}


def get_job_info(ctx, include_acquisition=True):
    """Return scheduled job information."""
    acquisition = None
    if include_acquisition:
        try:
            from comicarr.app.search.health import get_acquisition_health

            acquisition = get_acquisition_health()
        except Exception as e:
            acquisition = {"unavailable": {"reason": "schema_unavailable", "error": sanitize_job_error(e)}}
    if not ctx.scheduler:
        result = {"jobs": []}
        if include_acquisition:
            result["acquisition"] = acquisition
        return result

    jobs = []
    for job in ctx.scheduler.get_jobs():
        history = _get_weekly_job_history() if job.id == "weekly" else _get_job_history(job.name)
        status = history.get("status") or "Waiting"
        if job.next_run_time is None:
            status = "Paused"
        job_info = {
            "id": job.id,
            "name": job.name,
            "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            "trigger": str(job.trigger),
            "status": status,
            "state": _weekly_state(status),
            "dispatch": {
                "state": _weekly_state(status),
                "last_attempt": history.get("prev_run_timestamp"),
                "last_success": history.get("last_success_timestamp"),
                "last_failure": history.get("last_failure_timestamp"),
                "last_error": sanitize_job_error(history.get("last_error")) if history.get("last_error") else None,
            },
        }
        if job.id == "weekly":
            if not history.get("status"):
                status = getattr(comicarr, "WEEKLY_STATUS", "Waiting")
                job_info["status"] = status
                job_info["state"] = _weekly_state(status)
                job_info["dispatch"]["state"] = _weekly_state(status)
            job_info.update(
                {
                    "last_success_timestamp": history.get("last_success_timestamp"),
                    "last_failure_timestamp": history.get("last_failure_timestamp"),
                    "last_error": sanitize_job_error(history.get("last_error")) if history.get("last_error") else None,
                }
            )
        jobs.append(job_info)
    result = {"jobs": jobs}
    if include_acquisition:
        result["acquisition"] = acquisition
    return result


def _weekly_state(status):
    """Normalize persisted scheduler status for API consumers."""
    return (status or "Waiting").strip().lower()


def _get_weekly_job_history():
    """Read durable weekly-job outcome data without making job status unavailable on DB errors."""
    try:
        return (
            db.select_one(
                select(
                    jobhistory.c.status,
                    jobhistory.c.prev_run_timestamp,
                    jobhistory.c.last_success_timestamp,
                    jobhistory.c.last_failure_timestamp,
                    jobhistory.c.last_error,
                ).where(jobhistory.c.JobName == WEEKLY_JOB_NAME)
            )
            or {}
        )
    except Exception as e:
        logger.warn("[WEEKLY] Could not read durable refresh status: %s" % e)
        return {}


def _get_job_history(job_name):
    """Read one durable scheduler outcome without making diagnostics fail."""
    try:
        return (
            db.select_one(
                select(
                    jobhistory.c.status,
                    jobhistory.c.prev_run_timestamp,
                    jobhistory.c.last_success_timestamp,
                    jobhistory.c.last_failure_timestamp,
                    jobhistory.c.last_error,
                ).where(jobhistory.c.JobName == str(job_name))
            )
            or {}
        )
    except Exception as e:
        logger.warn("[SCHEDULER] Could not read durable status for %s: %s" % (job_name, e))
        return {}


def request_weekly_refresh(ctx):
    """Queue the existing weekly APScheduler job for an immediate, coalesced run."""
    from comicarr.app.core.runtime import set_runtime_field

    with get_weekly_refresh_lock():
        scheduler = getattr(ctx, "scheduler", None)
        if scheduler is None:
            return {"accepted": False, "state": "unavailable", "error": "Weekly scheduler is unavailable"}

        job = scheduler.get_job("weekly")
        if job is None:
            return {"accepted": False, "state": "unavailable", "error": "Weekly scheduler job is unavailable"}

        state = _weekly_state(ctx.weekly_status)
        if state == "running":
            return {
                "accepted": False,
                "state": "running",
                "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            }
        if job.next_run_time is None:
            return {"accepted": False, "state": "paused", "error": "Weekly refresh is paused"}
        if state == "queued":
            return {
                "accepted": False,
                "state": "queued",
                "next_run_time": str(job.next_run_time),
            }

        next_run_time = datetime.datetime.utcnow()
        set_runtime_field(ctx, "weekly_manual_next_run", job.next_run_time)
        job.modify(next_run_time=next_run_time)
        set_runtime_field(ctx, "weekly_status", "Queued")
        try:
            db.upsert("jobhistory", {"status": "Queued"}, {"JobName": WEEKLY_JOB_NAME})
        except Exception as e:
            logger.warn("[WEEKLY] Could not persist refresh request state: %s" % e)

        return {
            "accepted": True,
            "state": "queued",
            "next_run_time": str(next_run_time),
        }


def sanitize_job_error(error):
    """Keep operational errors useful without persisting credentials or large tracebacks."""
    message = re.sub(r"\s+", " ", str(error or "")).strip()
    message = redact_sensitive_text(message)
    return message[:500] or "Scheduled job failed; check server logs for details."


def _event_timestamp(event):
    scheduled = getattr(event, "scheduled_run_time", None)
    if scheduled is None:
        scheduled_runs = getattr(event, "scheduled_run_times", None) or []
        scheduled = scheduled_runs[-1] if scheduled_runs else None
    if isinstance(scheduled, datetime.datetime):
        return normalize_utc_datetime(scheduled).timestamp()
    return datetime.datetime.now(datetime.timezone.utc).timestamp()


def persist_scheduler_event(event):
    """Persist APScheduler dispatch outcome without claiming acquisition completion."""
    job_id = str(getattr(event, "job_id", "unknown"))
    job_name = SCHEDULER_JOB_NAMES.get(job_id, job_id)
    timestamp = _event_timestamp(event)
    event_code = getattr(event, "code", None)
    values = {
        "prev_run_timestamp": timestamp,
        "prev_run_datetime": datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc).isoformat(),
        "last_run_completed": "True",
    }
    if event_code == EVENT_JOB_EXECUTED:
        values.update(
            {
                "status": DispatchState.ACCEPTED.value,
                "last_success_timestamp": timestamp,
                "last_error": None,
            }
        )
    elif event_code == EVENT_JOB_ERROR:
        values.update(
            {
                "status": DispatchState.ERROR.value,
                "last_failure_timestamp": timestamp,
                "last_error": sanitize_job_error(getattr(event, "exception", None)),
            }
        )
    elif event_code == EVENT_JOB_MISSED:
        values.update(
            {
                "status": DispatchState.MISSED.value,
                "last_failure_timestamp": timestamp,
                "last_error": "Scheduled run was missed.",
            }
        )
    elif event_code == EVENT_JOB_MAX_INSTANCES:
        values.update(
            {
                "status": DispatchState.MAX_INSTANCES.value,
                "last_failure_timestamp": timestamp,
                "last_error": "Scheduled run was blocked by the max-instance limit.",
            }
        )
    else:
        return False
    db.upsert("jobhistory", values, {"JobName": job_name})
    return True


def register_scheduler_health_listener(scheduler):
    """Register the durable listener once per scheduler instance."""
    if scheduler.__dict__.get("_comicarr_health_listener", False):
        return False
    mask = EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED | EVENT_JOB_MAX_INSTANCES
    scheduler.add_listener(persist_scheduler_event, mask)
    scheduler._comicarr_health_listener = True
    return True


def get_startup_diagnostics(ctx, include_acquisition=True):
    """Return startup diagnostics (db empty, migration dismissed).

    db_empty is computed live so it reflects the current library state rather
    than the boot-time snapshot — adding series via the normal flow flips it
    without requiring a restart.
    """
    from sqlalchemy import func, select

    db_empty = True
    try:
        with comicarr.sql_db() as conn:
            count = conn.execute(select(func.count()).select_from(comics)).scalar() or 0
            db_empty = count == 0
    except Exception as e:
        logger.warn("[DIAGNOSTICS] Live db_empty check failed, falling back to startup flag: %s" % e)
        db_empty = ctx.db_empty

    result = {
        "db_empty": db_empty,
        "migration_dismissed": getattr(ctx.config, "MIGRATION_DISMISSED", False) if ctx.config else False,
        "build": get_build_identity(ctx),
    }
    if include_acquisition:
        try:
            from comicarr.app.search.health import get_search_health

            result["acquisition"] = get_search_health(
                ctx.config,
                provider_blocklist=ctx.provider_blocklist,
            )
        except Exception as e:
            result["acquisition"] = {"blocked": True, "reason": "health_unavailable", "error": sanitize_job_error(e)}
    return result


def preview_migration(ctx, path):
    """Validate a Mylar3 source path and return preview data."""
    if not path:
        return {"success": False, "error": "path parameter is required"}

    from comicarr import migration

    m = migration.Mylar3Migration(path)
    result = m.validate()
    if result.get("valid"):
        return result
    return {"success": False, "error": result.get("error", "Invalid Mylar3 data path")}


def start_migration(ctx, path):
    """Start a migration only after globally fencing acquisition work."""
    import comicarr as _comicarr

    if not path:
        return {"success": False, "error": "path parameter is required"}

    if _comicarr.MIGRATION_IN_PROGRESS:
        return {"success": False, "error": "Migration already in progress"}

    import time
    import uuid

    from comicarr import migration
    from comicarr.app.acquisition.maintenance import (
        MaintenanceConflict,
        MaintenanceController,
        set_reconciliation_state,
    )

    m = migration.Mylar3Migration(path)
    result = m.validate()
    if not result.get("valid"):
        return {"success": False, "error": "Invalid Mylar3 data path"}

    controller = MaintenanceController(db.get_engine())
    initial = controller.status()
    if initial.active and (initial.owner != "migration" or not str(initial.run_id or "").startswith("migration-")):
        return {"success": False, "error": "Acquisition maintenance is owned by another operation", "status_code": 423}
    if initial.active_leases and not initial.active:
        # Avoid taking a fence merely to report an existing busy worker. A
        # race after this check is handled by the fenced thread below.
        return {"success": False, "error": "Acquisition workers must drain before migration", "status_code": 423}

    run_id = "migration-%s" % uuid.uuid4()
    try:
        fence = controller.acquire_fence("migration", run_id, "Mylar3 migration")
    except MaintenanceConflict as e:
        return {"success": False, "error": str(e), "status_code": 423}

    set_reconciliation_state("migrating", "Mylar3 migration is waiting for acquisition quiescence", db.get_engine())

    def _run_fenced_migration():
        success = False
        try:
            _comicarr.MIGRATION_STATUS = "waiting_for_quiescence"
            # Existing side effects predate the fence and must finish. New
            # claims are blocked by it. Heartbeat while waiting so diagnostics
            # distinguish an intentional drain from an abandoned fence.
            deadline = time.monotonic() + 300
            while not controller.status().drained:
                controller.heartbeat_fence("migration", run_id, fence.epoch)
                if time.monotonic() >= deadline:
                    _comicarr.MIGRATION_STATUS = "blocked"
                    _comicarr.MIGRATION_ERROR = "Acquisition workers did not drain before migration"
                    set_reconciliation_state(
                        "failed",
                        "Acquisition workers did not drain before migration; operator review required",
                        db.get_engine(),
                    )
                    return
                time.sleep(0.25)
            success = bool(m.execute())
            if not success:
                set_reconciliation_state(
                    "failed",
                    "Mylar3 migration failed; operator review required before acquisition resumes",
                    db.get_engine(),
                )
        except Exception as e:
            logger.error("[MIGRATION] Fenced migration runner failed: %s" % e)
            _comicarr.MIGRATION_STATUS = "error"
            _comicarr.MIGRATION_ERROR = "Migration runner failed"
            try:
                set_reconciliation_state(
                    "failed",
                    "Mylar3 migration runner failed; operator review required",
                    db.get_engine(),
                )
            except Exception as state_error:
                logger.error("[MIGRATION] Unable to record runner failure: %s" % state_error)
        finally:
            status = controller.status()
            if status.active and status.owner == "migration" and status.run_id == run_id and status.drained:
                try:
                    controller.release_fence("migration", run_id, status.epoch)
                except MaintenanceConflict as e:
                    logger.error("[MIGRATION] Unable to release migration fence: %s" % e)
            try:
                from comicarr.app.acquisition.maintenance import get_reconciliation_status, refresh_runtime_state

                gate = refresh_runtime_state(ctx.config, db.get_engine())
                _comicarr.MIGRATION_RECONCILIATION = get_reconciliation_status(db.get_engine())
                if gate.blocked:
                    logger.info("[MIGRATION] Acquisition remains blocked: %s" % gate.reason)
            except Exception as gate_error:
                _comicarr.ACQUISITION_WORKERS_BLOCKED = True
                _comicarr.ACQUISITION_BLOCK_REASON = "migration_reconciliation_gate_unavailable"
                logger.error("[MIGRATION] Unable to refresh acquisition reconciliation gate: %s" % gate_error)

    start_background_thread(
        _run_fenced_migration,
        name="MigrationThread",
        daemon=True,
        registry=ctx.background_workers,
    )
    return {"status": "started", "run_id": run_id}


def get_migration_progress(ctx):
    """Return current migration progress."""
    import comicarr as _comicarr

    try:
        from comicarr.app.acquisition.maintenance import get_reconciliation_status

        reconciliation = get_reconciliation_status(db.get_engine())
        _comicarr.MIGRATION_RECONCILIATION = reconciliation
    except Exception as e:
        reconciliation = {"state": "unavailable", "reason": "reconciliation status unavailable"}
        logger.error("[MIGRATION] Unable to read reconciliation state: %s" % e)

    return {
        "status": _comicarr.MIGRATION_STATUS,
        "current_table": _comicarr.MIGRATION_CURRENT_TABLE,
        "tables_complete": _comicarr.MIGRATION_TABLES_COMPLETE,
        "tables_total": _comicarr.MIGRATION_TABLES_TOTAL,
        "error": _comicarr.MIGRATION_ERROR,
        "reconciliation": reconciliation,
    }


def mark_reconciliation_ready(ctx, *, actor, reason):
    """Explicitly lift the durable post-migration acquisition gate."""
    if not reason or not str(reason).strip():
        return {"success": False, "error": "a reconciliation release reason is required", "status_code": 400}
    try:
        from comicarr.app.acquisition.maintenance import (
            MaintenanceController,
            get_reconciliation_status,
            refresh_runtime_state,
            set_reconciliation_state,
        )

        controller = MaintenanceController(db.get_engine())
        if controller.status().active:
            return {
                "success": False,
                "error": "release acquisition maintenance before resuming automatic work",
                "status_code": 423,
            }
        current = get_reconciliation_status(db.get_engine())
        if current["state"] == "migrating":
            return {"success": False, "error": "migration is still running", "status_code": 409}
        reconciliation = set_reconciliation_state(
            "ready",
            "operator %s: %s" % (str(actor)[:80], str(reason)[:160]),
            db.get_engine(),
        )
        gate = refresh_runtime_state(ctx.config, db.get_engine())
        try:
            runtime = comicarr.resume_acquisition_runtime(ctx.config)
        except Exception as e:
            reconciliation = set_reconciliation_state(
                "failed",
                "automatic acquisition resume failed: %s" % type(e).__name__,
                db.get_engine(),
            )
            gate = refresh_runtime_state(ctx.config, db.get_engine())
            comicarr.MIGRATION_RECONCILIATION = reconciliation
            logger.error("[MIGRATION] Automatic acquisition resume failed closed: %s" % type(e).__name__)
            return {
                "success": False,
                "error": "automatic acquisition could not be resumed; the gate remains closed",
                "status_code": 500,
                "reconciliation": reconciliation,
                "gate": gate.as_dict(),
            }
        comicarr.MIGRATION_RECONCILIATION = reconciliation
        return {
            "success": True,
            "reconciliation": reconciliation,
            "gate": gate.as_dict(),
            "runtime": runtime,
        }
    except Exception as e:
        logger.error("[MIGRATION] Unable to mark reconciliation ready: %s" % e)
        return {"success": False, "error": "unable to resume acquisition", "status_code": 500}


def abort_acquisition_maintenance(ctx, *, actor, reason, force_stale_leases=False):
    """Audited escape hatch for a drained, abandoned repair/migration fence."""

    if not reason or not str(reason).strip():
        return {"success": False, "error": "a maintenance abort reason is required", "status_code": 400}
    try:
        from comicarr.app.acquisition.maintenance import (
            MaintenanceBlocked,
            MaintenanceConflict,
            MaintenanceController,
        )

        controller = MaintenanceController(db.get_engine())
        status = controller.abort_fence(str(actor), str(reason).strip(), force_stale_leases=bool(force_stale_leases))
        from comicarr.app.acquisition.maintenance import (
            get_reconciliation_status,
            refresh_runtime_state,
            set_reconciliation_state,
        )

        reconciliation = get_reconciliation_status(db.get_engine())
        if reconciliation["state"] == "migrating":
            reconciliation = set_reconciliation_state(
                "failed",
                "migration fence aborted by operator %s: %s" % (str(actor)[:80], str(reason)[:160]),
                db.get_engine(),
            )
        gate = refresh_runtime_state(ctx.config, db.get_engine())
        return {
            "success": True,
            "maintenance": {
                "active": status.active,
                "epoch": status.epoch,
                "owner": status.owner,
                "run_id": status.run_id,
                "reason": status.reason,
                "heartbeat_at": status.heartbeat_at,
                "active_leases": status.active_leases,
            },
            "reconciliation": reconciliation,
            "gate": gate.as_dict(),
        }
    except (MaintenanceBlocked, MaintenanceConflict) as e:
        return {"success": False, "error": str(e), "status_code": 423}
    except Exception as e:
        logger.error("[MAINTENANCE] Unable to abort acquisition maintenance: %s" % e)
        return {"success": False, "error": "unable to abort acquisition maintenance", "status_code": 500}


# ---------------------------------------------------------------------------
# Acquisition repair (session-bound, owner only)
# ---------------------------------------------------------------------------


def _repair_service():
    from comicarr.app.system.acquisition_repair import RepairService

    return RepairService(db.get_engine())


def _repair_error_response(exc):
    from comicarr.app.system.acquisition_repair import (
        RepairBlocked,
        RepairConfirmationError,
        RepairError,
    )

    if isinstance(exc, KeyError):
        return {"success": False, "error": str(exc) or "not found", "status_code": 404}
    if isinstance(exc, RepairConfirmationError):
        return {"success": False, "error": str(exc), "status_code": 409}
    if isinstance(exc, RepairBlocked):
        return {"success": False, "error": str(exc), "status_code": 423}
    if isinstance(exc, (RepairError, ValueError)):
        return {"success": False, "error": str(exc), "status_code": 400}
    logger.error("[REPAIR] Unexpected repair failure: %s" % exc)
    return {"success": False, "error": "repair failed", "status_code": 500}


def preview_acquisition_repair(ctx, series_id, *, actor, session_id):
    """Create a read-only series-scoped repair preview and one-shot token."""
    try:
        result = _repair_service().preview_series(series_id, actor=actor, session_id=session_id)
        result["success"] = True
        return result
    except Exception as e:
        return _repair_error_response(e)


def confirm_acquisition_repair(
    ctx,
    run_id,
    *,
    actor,
    session_id,
    preview_token,
    fingerprint,
    selected_optional_keys=None,
    canary_entity_key=None,
):
    """Freeze an immutable repair manifest with the one-shot preview token."""
    try:
        result = _repair_service().confirm(
            run_id,
            preview_token=preview_token,
            fingerprint=fingerprint,
            actor=actor,
            session_id=session_id,
            selected_optional_keys=selected_optional_keys or (),
            canary_entity_key=canary_entity_key,
        )
        result["success"] = True
        return result
    except Exception as e:
        return _repair_error_response(e)


def apply_acquisition_repair(
    ctx,
    run_id,
    *,
    actor,
    session_id,
    max_items=None,
    canary_only=False,
):
    """Apply a confirmed repair manifest under the maintenance fence."""
    try:
        result = _repair_service().apply(
            run_id,
            actor=actor,
            session_id=session_id,
            max_items=max_items,
            canary_only=bool(canary_only),
        )
        result["success"] = True
        return result
    except Exception as e:
        return _repair_error_response(e)


def get_acquisition_repair_run(ctx, run_id, *, actor, session_id, include_items=True):
    """Return a repair run and its ordered items for the owning session."""
    try:
        service = _repair_service()
        projection = service.read_public_run(
            run_id,
            actor=actor,
            session_id=session_id,
            include_items=bool(include_items),
        )
        if projection is None:
            return {"success": False, "error": "unknown repair run", "status_code": 404}
        return {"success": True, **projection}
    except Exception as e:
        return _repair_error_response(e)


def rollback_acquisition_repair(ctx, run_id, *, actor, session_id, reason):
    """Conditionally roll back applied repair values when they have not drifted."""
    try:
        result = _repair_service().rollback(
            run_id,
            actor=actor,
            session_id=session_id,
            reason=reason,
        )
        result["success"] = True
        return result
    except Exception as e:
        return _repair_error_response(e)


def authorize_acquisition_canary(ctx, run_id, *, actor, session_id, release_key, route):
    """Authorize one named, restart-safe external handoff under maintenance."""
    try:
        result = _repair_service().authorize_acquisition_canary(
            run_id,
            actor=actor,
            session_id=session_id,
            release_key=release_key,
            route=route,
        )
        result["success"] = True
        return result
    except Exception as e:
        return _repair_error_response(e)


def get_acquisition_canary(ctx, permit_id, *, actor, session_id):
    """Return the terminally audited state of the named handoff canary."""
    try:
        result = _repair_service().get_acquisition_canary(permit_id, actor=actor, session_id=session_id)
        result["success"] = True
        return result
    except Exception as e:
        return _repair_error_response(e)


def release_acquisition_canary(ctx, permit_id, *, actor, session_id, reason):
    """Release the canary fence only after inspection or explicit cancellation."""
    try:
        result = _repair_service().release_acquisition_canary(
            permit_id,
            actor=actor,
            session_id=session_id,
            reason=reason,
        )
        result["success"] = True
        return result
    except Exception as e:
        return _repair_error_response(e)


# --- Extracted from helpers.py ---


def upgrade_dynamic():
    dynamic_comiclist = []
    # update the comicdb to include the Dynamic Names (and any futher changes as required)
    from sqlalchemy import select

    clist = db.select_all(select(comics))
    for cl in clist:
        cl_d = comicarr.filechecker.FileChecker(watchcomic=cl["ComicName"])
        cl_dyninfo = cl_d.dynamic_replace(cl["ComicName"])
        dynamic_comiclist.append(
            {
                "DynamicComicName": re.sub(r"[\|\s]", "", cl_dyninfo["mod_seriesname"].lower()).strip(),
                "ComicID": cl["ComicID"],
            }
        )

    if len(dynamic_comiclist) > 0:
        for dl in dynamic_comiclist:
            CtrlVal = {"ComicID": dl["ComicID"]}
            newVal = {"DynamicComicName": dl["DynamicComicName"]}
            db.upsert("comics", newVal, CtrlVal)

    # update the storyarcsdb to include the Dynamic Names (and any futher changes as required)
    dynamic_storylist = []
    rlist = db.select_all(select(storyarcs).where(storyarcs.c.StoryArcID.isnot(None)))
    for rl in rlist:
        comicarr.filechecker.FileChecker(watchcomic=rl["ComicName"])
        rl_dyninfo = cl_d.dynamic_replace(rl["ComicName"])
        dynamic_storylist.append(
            {
                "DynamicComicName": re.sub(r"[\|\s]", "", rl_dyninfo["mod_seriesname"].lower()).strip(),
                "IssueArcID": rl["IssueArcID"],
            }
        )

    if len(dynamic_storylist) > 0:
        for ds in dynamic_storylist:
            CtrlVal = {"IssueArcID": ds["IssueArcID"]}
            newVal = {"DynamicComicName": ds["DynamicComicName"]}
            db.upsert("storyarcs", newVal, CtrlVal)

    logger.info(
        "Finished updating "
        + str(len(dynamic_comiclist))
        + " / "
        + str(len(dynamic_storylist))
        + " entries within the db."
    )
    comicarr.CONFIG.writeconfig(values={"dynamic_update": 4})
    return


def notify_ddl_stuck(item, age_minutes):
    """
    Send notifications for a stuck DDL download.
    Follows the same notifier pattern as notify_snatch() in search.py.
    """
    from comicarr import notifiers

    stuck_name = "%s (%s)" % (item["series"], item["year"])
    if item["issues"]:
        stuck_name += " #%s" % item["issues"]

    subject = "DDL Queue Stuck!"
    message = "%s has been downloading for %d minutes without progress." % (stuck_name, age_minutes)

    if comicarr.CONFIG.PROWL_ENABLED and comicarr.CONFIG.PROWL_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Prowl notification")
        prowl = notifiers.PROWL()
        prowl.notify(message, subject)

    if comicarr.CONFIG.PUSHOVER_ENABLED and comicarr.CONFIG.PUSHOVER_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Pushover notification")
        pushover = notifiers.PUSHOVER()
        pushover.notify(subject, message, None, "DDL", "Comicarr")

    if comicarr.CONFIG.BOXCAR_ENABLED and comicarr.CONFIG.BOXCAR_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Boxcar notification")
        boxcar = notifiers.BOXCAR()
        boxcar.notify(snatched_nzb=stuck_name, sent_to="DDL", snline=subject)

    if comicarr.CONFIG.PUSHBULLET_ENABLED and comicarr.CONFIG.PUSHBULLET_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Pushbullet notification")
        pushbullet = notifiers.PUSHBULLET()
        pushbullet.notify(snline=subject, snatched=stuck_name, sent_to="DDL", prov="DDL", method="POST")

    if comicarr.CONFIG.TELEGRAM_ENABLED and comicarr.CONFIG.TELEGRAM_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Telegram notification")
        telegram = notifiers.TELEGRAM()
        telegram.notify("%s - %s" % (subject, message))

    if comicarr.CONFIG.SLACK_ENABLED and comicarr.CONFIG.SLACK_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Slack notification")
        slack = notifiers.SLACK()
        slack.notify("DDL Stuck", subject, snatched_nzb=stuck_name, sent_to="DDL", prov="DDL")

    if comicarr.CONFIG.DISCORD_ENABLED and comicarr.CONFIG.DISCORD_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Discord notification")
        discord = notifiers.DISCORD()
        discord.notify("DDL Stuck", subject, snatched_nzb=stuck_name, sent_to="DDL", prov="DDL")

    if comicarr.CONFIG.EMAIL_ENABLED and comicarr.CONFIG.EMAIL_ONGRAB:
        logger.info("[DDL-HEALTH] Sending email notification")
        email = notifiers.EMAIL()
        email.notify(message, "Comicarr - DDL Queue Stuck", module="[DDL-HEALTH]")

    if comicarr.CONFIG.GOTIFY_ENABLED and comicarr.CONFIG.GOTIFY_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Gotify notification")
        gotify = notifiers.GOTIFY()
        gotify.notify("DDL Stuck", subject, snatched_nzb=stuck_name, sent_to="DDL", prov="DDL")

    if comicarr.CONFIG.MATRIX_ENABLED and comicarr.CONFIG.MATRIX_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Matrix notification")
        matrix = notifiers.MATRIX()
        matrix.notify("DDL Stuck", subject, snatched_nzb=stuck_name, sent_to="DDL", prov="DDL")


QueueInfo = namedtuple("QueueInfo", ("name", "is_alive", "size"))


def queue_info():
    yield from (
        QueueInfo(queue_name, thread_obj.is_alive() if thread_obj is not None else None, queue.qsize())
        for (queue_name, thread_obj, queue) in [
            ("AUTO-COMPLETE-NZB", comicarr.NZBPOOL, comicarr.NZB_QUEUE),
            ("AUTO-SNATCHER", comicarr.SNPOOL, comicarr.SNATCHED_QUEUE),
            ("DDL-QUEUE", comicarr.DDLPOOL, comicarr.DDL_QUEUE),
            ("POST-PROCESS-QUEUE", comicarr.PPPOOL, comicarr.PP_QUEUE),
            ("SEARCH-QUEUE", comicarr.SEARCHPOOL, comicarr.SEARCH_QUEUE),
        ]
    )


def script_env(mode, vars):
    # mode = on-snatch, pre-postprocess, post-postprocess
    # var = dictionary containing variables to pass
    comicarr_env = os.environ.copy()
    shell_cmd = sys.executable
    if mode == "on-snatch":
        runscript = comicarr.CONFIG.SNATCH_SCRIPT
        if comicarr.CONFIG.SNATCH_SHELL_LOCATION is not None:
            shell_cmd = comicarr.CONFIG.SNATCH_SHELL_LOCATION
        if "torrentinfo" in vars:
            if "hash" in vars["torrentinfo"]:
                comicarr_env["comicarr_release_hash"] = vars["torrentinfo"]["hash"]
            if "torrent_filename" in vars["torrentinfo"]:
                comicarr_env["comicarr_torrent_filename"] = vars["torrentinfo"]["torrent_filename"]
            if "name" in vars["torrentinfo"]:
                comicarr_env["comicarr_release_name"] = vars["torrentinfo"]["name"]
            if "folder" in vars["torrentinfo"]:
                comicarr_env["comicarr_release_folder"] = vars["torrentinfo"]["folder"]
            if "label" in vars["torrentinfo"]:
                comicarr_env["comicarr_release_label"] = vars["torrentinfo"]["label"]
            if "total_filesize" in vars["torrentinfo"]:
                comicarr_env["comicarr_release_filesize"] = str(vars["torrentinfo"]["total_filesize"])
            if "time_started" in vars["torrentinfo"]:
                comicarr_env["comicarr_release_start"] = str(vars["torrentinfo"]["time_started"])
            if "filepath" in vars["torrentinfo"]:
                comicarr_env["comicarr_torrent_file"] = str(vars["torrentinfo"]["filepath"])
            else:
                try:
                    comicarr_env["comicarr_release_files"] = "|".join(vars["torrentinfo"]["files"])
                except TypeError:
                    comicarr_env["comicarr_release_files"] = "|".join(json.dumps(vars["torrentinfo"]["files"]))
        elif "nzbinfo" in vars:
            comicarr_env["comicarr_release_id"] = vars["nzbinfo"]["id"]
            if "client_id" in vars["nzbinfo"]:
                comicarr_env["comicarr_client_id"] = vars["nzbinfo"]["client_id"]
            comicarr_env["comicarr_release_nzbname"] = vars["nzbinfo"]["nzbname"]
            comicarr_env["comicarr_release_link"] = vars["nzbinfo"]["link"]
            comicarr_env["comicarr_release_nzbpath"] = vars["nzbinfo"]["nzbpath"]
            if "blackhole" in vars["nzbinfo"]:
                comicarr_env["comicarr_release_blackhole"] = vars["nzbinfo"]["blackhole"]
        comicarr_env["comicarr_release_provider"] = vars["provider"]
        if "comicinfo" in vars:
            try:
                if vars["comicinfo"]["comicid"] is not None:
                    comicarr_env["comicarr_comicid"] = vars["comicinfo"][
                        "comicid"
                    ]  # comicid/issueid are unknown for one-offs (should be fixable tho)
                else:
                    comicarr_env["comicarr_comicid"] = "None"
            except Exception:
                pass
            try:
                if vars["comicinfo"]["issueid"] is not None:
                    comicarr_env["comicarr_issueid"] = vars["comicinfo"]["issueid"]
                else:
                    comicarr_env["comicarr_issueid"] = "None"
            except Exception:
                pass
            try:
                if vars["comicinfo"]["issuearcid"] is not None:
                    comicarr_env["comicarr_issuearcid"] = vars["comicinfo"]["issuearcid"]
                else:
                    comicarr_env["comicarr_issuearcid"] = "None"
            except Exception:
                pass
            comicarr_env["comicarr_comicname"] = vars["comicinfo"]["comicname"]
            comicarr_env["comicarr_issuenumber"] = str(vars["comicinfo"]["issuenumber"])
            try:
                comicarr_env["comicarr_comicvolume"] = str(vars["comicinfo"]["volume"])
            except Exception:
                pass
            try:
                comicarr_env["comicarr_seriesyear"] = str(vars["comicinfo"]["seriesyear"])
            except Exception:
                pass
            try:
                comicarr_env["comicarr_issuedate"] = str(vars["comicinfo"]["issuedate"])
            except Exception:
                pass

        comicarr_env["comicarr_release_pack"] = str(vars["pack"])
        if vars["pack"] is True:
            if vars["pack_numbers"] is not None:
                comicarr_env["comicarr_release_pack_numbers"] = vars["pack_numbers"]
            if vars["pack_issuelist"] is not None:
                comicarr_env["comicarr_release_pack_issuelist"] = vars["pack_issuelist"]
        comicarr_env["comicarr_method"] = vars["method"]
        comicarr_env["comicarr_client"] = vars["clientmode"]

    elif mode == "post-process":
        # to-do
        runscript = comicarr.CONFIG.EXTRA_SCRIPTS
        if comicarr.CONFIG.ES_SHELL_LOCATION is not None:
            shell_cmd = comicarr.CONFIG.ES_SHELL_LOCATION

    elif mode == "pre-process":
        # to-do
        runscript = comicarr.CONFIG.PRE_SCRIPTS
        if comicarr.CONFIG.PRE_SHELL_LOCATION is not None:
            shell_cmd = comicarr.CONFIG.PRE_SHELL_LOCATION

    logger.fdebug("Initiating " + mode + " script detection.")
    with open(runscript, "r") as f:
        first_line = f.readline()

    if runscript.endswith(".sh"):
        shell_cmd = re.sub("#!", "", first_line)
        if shell_cmd == "" or shell_cmd is None:
            shell_cmd = "/bin/bash"

    curScriptName = shell_cmd + " " + runscript  # .decode("string_escape")
    logger.fdebug("snatch script detected...enabling: " + str(curScriptName))

    script_cmd = shlex.split(curScriptName)
    logger.fdebug("Executing command " + str(script_cmd))
    try:
        subprocess.call(script_cmd, env=dict(comicarr_env))
    except OSError:
        logger.warn("Unable to run extra_script: " + str(script_cmd))
        return False
    except TypeError as e:
        bad_environment = False
        for key, value in comicarr_env.items():
            if not isinstance(key, str) or not isinstance(value, str):
                bad_environment = True
                if key in os.environ:
                    logger.error("Invalid global environment variable: {k!r} = {v!r}".format(k=key, v=value))
                else:
                    logger.error("Invalid Comicarr environment variable: {k!r} = {v!r}".format(k=key, v=value))
        if not bad_environment:
            raise e
    else:
        return True


def job_management(
    write=False,
    job=None,
    last_run_completed=None,
    current_run=None,
    status=None,
    failure=False,
    failure_message=None,
    startup=False,
):
    from comicarr.helpers import utctimestamp

    jobresults = []

    if startup is True:
        # on startup - db status will over-ride any settings to ensure persistent state
        from sqlalchemy import select

        job_info = db.select_all(
            select(
                jobhistory.c.JobName,
                jobhistory.c.status,
                jobhistory.c.prev_run_timestamp,
                jobhistory.c.last_success_timestamp,
            ).distinct()
        )
        for ji in job_info:
            jstatus = ji["status"]
            if jstatus is None:
                jstatus = "Waiting"
            elif jstatus == "Running" or (jstatus == "Queued" and "weekly" in ji["JobName"].lower()):
                was_running = jstatus == "Running"
                jstatus = "Waiting"
                recovery_values = {"status": jstatus}
                if was_running:
                    if "weekly" in ji["JobName"].lower():
                        interrupted_error = "Previous weekly refresh was interrupted by restart."
                    else:
                        interrupted_error = "Previous %s run was interrupted by restart." % ji["JobName"]
                    recovery_values.update(
                        {
                            "status": "Interrupted",
                            "last_failure_timestamp": ji["prev_run_timestamp"],
                            "last_error": interrupted_error,
                        }
                    )
                db.upsert("jobhistory", recovery_values, {"JobName": ji["JobName"]})
            if "update" in ji["JobName"].lower():
                if comicarr.SCHED_DBUPDATE_LAST is None:
                    comicarr.SCHED_DBUPDATE_LAST = ji["prev_run_timestamp"]
                if jstatus is None:
                    jstatus = "Waiting"
                comicarr.UPDATER_STATUS = jstatus
            elif "search" in ji["JobName"].lower():
                if comicarr.SCHED_SEARCH_LAST is None:
                    comicarr.SCHED_SEARCH_LAST = ji["prev_run_timestamp"]
                if jstatus is None:
                    jstatus = "Waiting"
                comicarr.SEARCH_STATUS = jstatus
            elif "rss" in ji["JobName"].lower():
                # db value isn't used in startup as config option controls status
                if comicarr.SCHED_RSS_LAST is None:
                    comicarr.SCHED_RSS_LAST = ji["prev_run_timestamp"]
                if jstatus is None:
                    if comicarr.CONFIG.ENABLE_RSS:
                        jstatus = "Waiting"
                if any([jstatus == "Waiting", jstatus == "Running"]) and comicarr.CONFIG.ENABLE_RSS is False:
                    jstatus = "Paused"
                comicarr.RSS_STATUS = jstatus
            elif "weekly" in ji["JobName"].lower():
                if comicarr.SCHED_WEEKLY_LAST is None:
                    comicarr.SCHED_WEEKLY_LAST = ji["last_success_timestamp"] or ji["prev_run_timestamp"]
                if jstatus is None:
                    jstatus = "Waiting"
                comicarr.WEEKLY_STATUS = jstatus
            elif "version" in ji["JobName"].lower():
                # db value isn't used in startup as config option controls status
                if comicarr.SCHED_VERSION_LAST is None:
                    comicarr.SCHED_VERSION_LAST = ji["prev_run_timestamp"]
                if jstatus is None:
                    if comicarr.CONFIG.CHECK_GITHUB:
                        jstatus = "Waiting"
                if any([jstatus == "Waiting", jstatus == "Running"]) and comicarr.CONFIG.CHECK_GITHUB is False:
                    jstatus = "Paused"
                comicarr.VERSION_STATUS = jstatus
            elif "monitor" in ji["JobName"].lower():
                # db value isn't used in startup as config option controls status
                if comicarr.SCHED_MONITOR_LAST is None:
                    comicarr.SCHED_MONITOR_LAST = ji["prev_run_timestamp"]
                if jstatus is None:
                    if comicarr.CONFIG.CHECK_FOLDER:
                        jstatus = "Waiting"
                if any([jstatus == "Waiting", jstatus == "Running"]) and comicarr.CONFIG.CHECK_FOLDER is False:
                    jstatus = "Paused"
                comicarr.MONITOR_STATUS = jstatus

        return {
            "weekly": {"last": comicarr.SCHED_WEEKLY_LAST, "status": comicarr.WEEKLY_STATUS},
            "monitor": {"last": comicarr.SCHED_MONITOR_LAST, "status": comicarr.MONITOR_STATUS},
            "search": {"last": comicarr.SCHED_SEARCH_LAST, "status": comicarr.SEARCH_STATUS},
            "updater": {"last": comicarr.SCHED_DBUPDATE_LAST, "status": comicarr.UPDATER_STATUS},
            "version": {"last": comicarr.SCHED_VERSION_LAST, "status": comicarr.VERSION_STATUS},
            "rss": {"last": comicarr.SCHED_RSS_LAST, "status": comicarr.RSS_STATUS},
        }

    for jb in comicarr.SCHED.get_jobs():
        jobinfo = str(jb)
        jobname = jobinfo[: jobinfo.find("(") - 1].strip()
        jobstatus = jobinfo[jobinfo.find("],") + 2 : len(jobinfo) - 1].strip()
        next_the_run = False
        prev_run_timestamp = None
        sched_status = "Waiting" if "next run" in jobstatus else "Paused"

        if jobname == "DB Updater":
            prev_run_timestamp = comicarr.SCHED_DBUPDATE_LAST
            if "next run" in jobstatus:
                comicarr.UPDATER_STATUS = "Waiting"
                if any(ky == "updater" for ky, vl in comicarr.FORCE_STATUS.items()):
                    comicarr.UPDATER_STATUS = comicarr.FORCE_STATUS["updater"]
                    next_the_run = True
            else:
                comicarr.UPDATER_STATUS = "Paused"
            sched_status = comicarr.UPDATER_STATUS
        elif jobname == "Auto-Search":
            prev_run_timestamp = comicarr.SCHED_SEARCH_LAST
            if "next run" in jobstatus:
                comicarr.SEARCH_STATUS = "Waiting"
                if any(ky == "search" for ky, vl in comicarr.FORCE_STATUS.items()):
                    comicarr.SEARCH_STATUS = comicarr.FORCE_STATUS["search"]
                    next_the_run = True
            else:
                comicarr.SEARCH_STATUS = "Paused"
            sched_status = comicarr.SEARCH_STATUS
        elif jobname == "RSS Feeds":
            prev_run_timestamp = comicarr.SCHED_RSS_LAST
            if "next run" in jobstatus:
                comicarr.RSS_STATUS = "Waiting"
                if any(ky == "rss" for ky, vl in comicarr.FORCE_STATUS.items()):
                    comicarr.RSS_STATUS = comicarr.FORCE_STATUS["rss"]
                    next_the_run = True
            else:
                comicarr.RSS_STATUS = "Paused"
            sched_status = comicarr.RSS_STATUS
        elif jobname == "Weekly Pullist":
            prev_run_timestamp = comicarr.SCHED_WEEKLY_LAST
            if "next run" in jobstatus:
                if comicarr.WEEKLY_STATUS not in {"Error", "Running", "Queued"}:
                    comicarr.WEEKLY_STATUS = "Waiting"
                if any(ky == "weekly" for ky, vl in comicarr.FORCE_STATUS.items()):
                    comicarr.WEEKLY_STATUS = comicarr.FORCE_STATUS["weekly"]
                    next_the_run = True
            else:
                comicarr.WEEKLY_STATUS = "Paused"
            sched_status = comicarr.WEEKLY_STATUS
        elif jobname == "Check Version":
            prev_run_timestamp = comicarr.SCHED_VERSION_LAST
            if "next run" in jobstatus:
                comicarr.VERSION_STATUS = "Waiting"
                if any(ky == "version" for ky, vl in comicarr.FORCE_STATUS.items()):
                    comicarr.VERSION_STATUS = comicarr.FORCE_STATUS["version"]
                    next_the_run = True
            else:
                comicarr.VERSION_STATUS = "Paused"
            sched_status = comicarr.VERSION_STATUS
        elif jobname == "Folder Monitor":
            prev_run_timestamp = comicarr.SCHED_MONITOR_LAST
            if "next run" in jobstatus:
                comicarr.MONITOR_STATUS = "Waiting"
                if any(ky == "monitor" for ky, vl in comicarr.FORCE_STATUS.items()):
                    comicarr.MONITOR_STATUS = comicarr.FORCE_STATUS["monitor"]
                    next_the_run = True
            else:
                comicarr.MONITOR_STATUS = "Paused"
            sched_status = comicarr.MONITOR_STATUS

        jtime = None
        try:
            jobtimetmp = jobinfo.split("at: ")[1].split(".")[0].strip()
        except Exception:
            jobtime = None
        else:
            if next_the_run is False:
                jtime = float(
                    calendar.timegm(datetime.datetime.strptime(jobtimetmp[:-1], "%Y-%m-%d %H:%M:%S %Z").timetuple())
                )
                jobtime = datetime.datetime.utcfromtimestamp(jtime)
            else:
                jobtime = None

        if prev_run_timestamp is not None:
            prev_run_time_utc = datetime.datetime.utcfromtimestamp(float(prev_run_timestamp))
            prev_run_time_utc = prev_run_time_utc.replace(microsecond=0)
        else:
            prev_run_time_utc = None

        jobresults.append(
            {
                "jobname": jobname,
                "next_run_datetime": jobtime,
                "prev_run_datetime": prev_run_time_utc,
                "next_run_timestamp": jtime,
                "prev_run_timestamp": prev_run_timestamp,
                "status": sched_status,
            }
        )

    if not write:
        return jobresults
    else:
        if job is None:
            for x in jobresults:
                updateCtrl = {"JobName": x["jobname"]}
                updateVals = {
                    "next_run_timestamp": x["next_run_timestamp"],
                    "prev_run_timestamp": x["prev_run_timestamp"],
                    "next_run_datetime": x["next_run_datetime"],
                    "prev_run_datetime": x["prev_run_datetime"],
                    "status": x["status"],
                }

                db.upsert("jobhistory", updateVals, updateCtrl)
        else:
            updateCtrl = {"JobName": job}
            if current_run is not None:
                pr_datetime = datetime.datetime.fromtimestamp(current_run, tz=datetime.timezone.utc)
                pr_datetime = pr_datetime.replace(microsecond=0)
                updateVals = {
                    "prev_run_timestamp": current_run,
                    "prev_run_datetime": pr_datetime.isoformat(),
                    "status": status,
                }
            elif last_run_completed is not None:
                # Persist the terminal fact before scheduler inspection, date
                # presentation, or logging. Those secondary operations must
                # never be able to mask a completed/failed dispatch.
                terminal_datetime = datetime.datetime.fromtimestamp(
                    last_run_completed, tz=datetime.timezone.utc
                ).replace(microsecond=0)
                terminal_values = {
                    "prev_run_timestamp": last_run_completed,
                    "prev_run_datetime": terminal_datetime.isoformat(),
                    "last_run_completed": "True",
                    "status": status,
                }
                if failure:
                    terminal_values.update(
                        {
                            "last_failure_timestamp": last_run_completed,
                            "last_error": sanitize_job_error(failure_message),
                        }
                    )
                else:
                    terminal_values.update(
                        {
                            "last_success_timestamp": last_run_completed,
                            "last_error": None,
                        }
                    )
                db.upsert("jobhistory", terminal_values, updateCtrl)
                if any(
                    [
                        job == "DB Updater",
                        job == "Auto-Search",
                        job == "RSS Feeds",
                        job == "Weekly Pullist",
                        job == "Check Version",
                        job == "Folder Monitor",
                    ]
                ):
                    jobstore = None
                    nextrun_stamp = None
                    nextrun_date = None
                    for jbst in comicarr.SCHED.get_jobs():
                        jb = str(jbst)
                        if "Status Updater" in jb.lower():
                            continue
                        elif job == "DB Updater" and "update" in jb.lower():
                            if any(ky == "updater" for ky, vl in comicarr.FORCE_STATUS.items()):
                                comicarr.UPDATER_STATUS = comicarr.FORCE_STATUS["updater"]
                                comicarr.FORCE_STATUS.pop("updater")

                            if comicarr.UPDATER_STATUS != "Paused":
                                if comicarr.DB_BACKFILL is True:
                                    # if backfilling, set it for every 15 mins
                                    nextrun_stamp = utctimestamp() + (comicarr.CONFIG.BACKFILL_TIMESPAN * 60)
                                    logger.fdebug(
                                        "[BACKFILL-UPDATER] Will fire off every %s"
                                        " minutes until backlog is decimated." % (comicarr.CONFIG.BACKFILL_TIMESPAN)
                                    )
                                else:
                                    nextrun_stamp = utctimestamp() + (int(comicarr.CONFIG.DBUPDATE_INTERVAL) * 60)
                            else:
                                comicarr.SCHED.pause_job("dbupdater")
                            jobstore = jbst
                            break
                        elif job == "Auto-Search" and "search" in jb.lower():
                            if any(ky == "search" for ky, vl in comicarr.FORCE_STATUS.items()):
                                comicarr.SEARCH_STATUS = comicarr.FORCE_STATUS["search"]
                                comicarr.FORCE_STATUS.pop("search")

                            if comicarr.SEARCH_STATUS != "Paused":
                                if failure is True:
                                    logger.info(
                                        "Previous job could not run due to other jobs. Scheduling Auto-Search for 10 minutes from now."
                                    )
                                    s_interval = 10 * 60
                                else:
                                    s_interval = comicarr.CONFIG.SEARCH_INTERVAL * 60
                                nextrun_stamp = utctimestamp() + s_interval
                            else:
                                comicarr.SCHED.pause_job("search")
                            jobstore = jbst
                            break
                        elif job == "RSS Feeds" and "rss" in jb.lower():
                            if any(ky == "rss" for ky, vl in comicarr.FORCE_STATUS.items()):
                                comicarr.RSS_STATUS = comicarr.FORCE_STATUS["rss"]
                                comicarr.FORCE_STATUS.pop("rss")

                            if comicarr.RSS_STATUS != "Paused":
                                nextrun_stamp = utctimestamp() + (int(comicarr.CONFIG.RSS_CHECKINTERVAL) * 60)
                            else:
                                comicarr.SCHED.pause_job("rss")
                            comicarr.SCHED_RSS_LAST = last_run_completed
                            jobstore = jbst
                            break
                        elif job == "Weekly Pullist" and "weekly" in jb.lower():
                            if any(ky == "weekly" for ky, vl in comicarr.FORCE_STATUS.items()):
                                comicarr.WEEKLY_STATUS = comicarr.FORCE_STATUS["weekly"]
                                comicarr.FORCE_STATUS.pop("weekly")

                            if comicarr.WEEKLY_STATUS != "Paused":
                                # APScheduler has already advanced the interval trigger
                                # before the job body runs. Preserve that cadence after a
                                # manual refresh instead of replacing it with a one-off
                                # delay that drifts from the configured schedule.
                                nextrun_date = getattr(jbst, "next_run_time", None)
                                if nextrun_date is not None:
                                    nextrun_stamp = nextrun_date.timestamp()
                            else:
                                comicarr.SCHED.pause_job("weekly")
                            comicarr.SCHED_WEEKLY_LAST = last_run_completed
                            jobstore = jbst
                            break
                        elif job == "Check Version" and "version" in jb.lower():
                            if any(ky == "version" for ky, vl in comicarr.FORCE_STATUS.items()):
                                comicarr.VERSION_STATUS = comicarr.FORCE_STATUS["version"]
                                comicarr.FORCE_STATUS.pop("version")

                            if comicarr.VERSION_STATUS != "Paused":
                                nextrun_stamp = utctimestamp() + (comicarr.CONFIG.CHECK_GITHUB_INTERVAL * 60)
                            else:
                                comicarr.SCHED.pause_job("version")
                            jobstore = jbst
                            break
                        elif job == "Folder Monitor" and "monitor" in jb.lower():
                            if any(ky == "monitor" for ky, vl in comicarr.FORCE_STATUS.items()):
                                comicarr.MONITOR_STATUS = comicarr.FORCE_STATUS["monitor"]
                                comicarr.FORCE_STATUS.pop("monitor")

                            if comicarr.MONITOR_STATUS != "Paused":
                                nextrun_stamp = utctimestamp() + (int(comicarr.CONFIG.DOWNLOAD_SCAN_INTERVAL) * 60)
                            else:
                                comicarr.SCHED.pause_job("monitor")
                            jobstore = jbst
                            break

                    if jobstore is not None:
                        if nextrun_stamp is not None:
                            if job == "Weekly Pullist":
                                nextrun_date = getattr(jobstore, "next_run_time", None)
                            else:
                                nextrun_date = datetime.datetime.fromtimestamp(nextrun_stamp, tz=datetime.timezone.utc)
                                jobstore.modify(next_run_time=nextrun_date)
                            if nextrun_date is not None:
                                nextrun_date = nextrun_date.replace(microsecond=0)
                    else:
                        # if the rss is enabled after startup, we have to re-set it up...
                        nextrun_stamp = utctimestamp() + (int(comicarr.CONFIG.RSS_CHECKINTERVAL) * 60)
                        nextrun_date = datetime.datetime.fromtimestamp(nextrun_stamp, tz=datetime.timezone.utc)
                        comicarr.SCHED_RSS_LAST = last_run_completed

                if nextrun_date is not None:
                    logger.fdebug("ReScheduled job: %s to %s" % (job, comicarr.helpers.utc_date_to_local(nextrun_date)))
                lastrun_comp = datetime.datetime.fromtimestamp(last_run_completed, tz=datetime.timezone.utc)
                lastrun_comp = lastrun_comp.replace(microsecond=0)
                # if it's completed, then update the last run time to the ending time of the job
                updateVals = {
                    "prev_run_timestamp": last_run_completed,
                    "prev_run_datetime": lastrun_comp.isoformat(),
                    "last_run_completed": "True",
                    "next_run_timestamp": nextrun_stamp,
                    "next_run_datetime": nextrun_date.isoformat() if nextrun_date is not None else None,
                    "status": status,
                }
                if failure:
                    updateVals.update(
                        {
                            "last_failure_timestamp": last_run_completed,
                            "last_error": sanitize_job_error(failure_message),
                        }
                    )
                else:
                    updateVals.update(
                        {
                            "last_success_timestamp": last_run_completed,
                            "last_error": None,
                        }
                    )

            logger.fdebug("Job update for %s: %s" % (updateCtrl, updateVals))
            db.upsert("jobhistory", updateVals, updateCtrl)


def stupidchk():
    from sqlalchemy import func, select

    with db.get_engine().connect() as conn:
        result_active = conn.execute(select(func.count()).select_from(comics).where(comics.c.Status == "Active"))
        comicarr.COUNT_COMICS = result_active.scalar()
        result_other = conn.execute(
            select(func.count()).select_from(comics).where(comics.c.Status.in_(["Loading", "Paused"]))
        )
        comicarr.EN_OOMICS = result_other.scalar()


def get_free_space(folder):
    from comicarr.helpers import sizeof_fmt

    min_threshold = 100000000  # threshold for minimum amount of freespace available (#100mb)
    if platform.system() == "Windows":
        free_bytes = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(folder), None, None, ctypes.pointer(free_bytes))
        dst_freesize = free_bytes.value
    else:
        st = os.statvfs(folder)
        dst_freesize = st.f_bavail * st.f_frsize
    logger.fdebug("[FREESPACE-CHECK] %s has %s free" % (folder, sizeof_fmt(dst_freesize)))
    if min_threshold > dst_freesize:
        logger.warn("[FREESPACE-CHECK] There is only %s space left on %s" % (dst_freesize, folder))
        return False
    else:
        return True


def tail_that_log():
    """Tail a file and get X lines from the end"""
    # place holder for the lines found
    lines_found = []

    f = open(os.path.join(comicarr.CONFIG.LOG_DIR, "comicarr.log"), "r")
    lines = 100
    buffer = 4098

    # block counter will be multiplied by buffer
    # to get the block size from the end
    block_counter = -1

    # loop until we find X lines
    while len(lines_found) <= lines:
        try:
            f.seek(block_counter * buffer, os.SEEK_END)
        except IOError:  # either file is too small, or too many lines requested
            f.seek(0)
            lines_found = f.readlines()
            break

        lines_found = f.readlines()

        # decrement the block counter to get the
        # next X bytes
        block_counter -= 1

    return lines_found[-lines:]
