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

import hmac
import os

from comicarr import logger
from comicarr.auth import LoginRateLimiter

# Shared rate limiter instance (same object used by CherryPy and FastAPI)
_rate_limiter = LoginRateLimiter()


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
    if ctx.config:
        ctx.config.process_kwargs({"http_password": new_hash})
        ctx.config.writeconfig()
    logger.info("[AUTH] Password migrated to bcrypt")


def initial_setup(ctx, username, password, setup_token):
    """Handle first-run credential setup."""
    import comicarr
    from comicarr import encrypted

    if getattr(ctx.config, "HTTP_USERNAME", None) and getattr(ctx.config, "HTTP_PASSWORD", None):
        return {"success": False, "error": "Credentials already configured"}

    if ctx.setup_token is not None:
        if not setup_token or not hmac.compare_digest(setup_token, ctx.setup_token):
            return {"success": False, "error": "Invalid setup token. Check the server console log."}

    if not username or not password:
        return {"success": False, "error": "Username and password required"}

    if len(password) < 8:
        return {"success": False, "error": "Password must be at least 8 characters"}

    hashed_password = encrypted.hash_password(password)
    ctx.config.process_kwargs({
        "http_username": username,
        "http_password": hashed_password,
        "authentication": 2,
    })
    ctx.config.writeconfig()
    ctx.config.configure(update=True, startup=False)

    logger.info("[AUTH-SETUP] Initial credentials configured for user: %s" % username)

    ctx.setup_token = None
    comicarr.SETUP_TOKEN = None

    # Signal restart for session config to take effect
    ctx.signal = "restart"
    comicarr.SIGNAL = "restart"

    return {"success": True, "username": username, "needs_restart": True}


def get_safe_config(ctx):
    """Return configuration as a safe dict (no passwords/keys)."""
    if not ctx.config:
        return {}

    safe_keys = [
        "COMIC_DIR", "DESTINATION_DIR", "HTTP_HOST", "HTTP_PORT", "HTTP_ROOT",
        "ENABLE_HTTPS", "AUTHENTICATION", "LAUNCH_BROWSER", "LOG_LEVEL",
        "DOWNLOAD_SCAN_INTERVAL", "NZB_STARTUP_SEARCH", "SEARCH_INTERVAL",
        "SEARCH_DELAY", "RSS_CHECK_INTERVAL", "AUTO_UPDATE", "ANNUALS_ON",
        "WEEKFOLDER", "REPLACE_SPACES", "ZERO_LEVEL", "ZERO_LEVEL_N",
        "LOWERCASE_FILENAMES", "FOLDER_FORMAT", "FILE_FORMAT",
        "COMICVINE_API", "ENABLE_META", "OPDS_ENABLE",
    ]
    result = {}
    for key in safe_keys:
        val = getattr(ctx.config, key, None)
        if val is not None:
            result[key] = val
    return result


def update_config(ctx, key_values):
    """Update configuration key-values and trigger scheduler reconfiguration."""
    import comicarr

    if not ctx.config:
        return {"success": False, "error": "Config not loaded"}

    # Apply scheduler change first (idempotent), then write config
    interval_keys = {"SEARCH_INTERVAL", "RSS_CHECK_INTERVAL", "DOWNLOAD_SCAN_INTERVAL", "DBUPDATE_INTERVAL"}
    interval_changed = any(k in interval_keys for k in key_values)

    ctx.config.process_kwargs(key_values)
    ctx.config.writeconfig()
    ctx.config.configure(update=True, startup=False)

    if interval_changed:
        _reconfigure_schedulers(ctx)

    # Sync back to globals during transition
    comicarr.CONFIG = ctx.config

    return {"success": True}


def update_providers(ctx, provider_data):
    """Update Newznab/Torznab provider configuration."""
    if not ctx.config:
        return {"success": False, "error": "Config not loaded"}

    provider_type = provider_data.get("type")
    providers = provider_data.get("providers", [])

    if provider_type not in ("newznab", "torznab"):
        return {"success": False, "error": "Invalid provider type"}

    # Delegate to config's provider handling
    ctx.config.process_kwargs({provider_type: providers})
    ctx.config.writeconfig()
    ctx.config.configure(update=True, startup=False)

    return {"success": True}


def _reconfigure_schedulers(ctx):
    """Reconfigure scheduler intervals after config change."""
    if not ctx.scheduler:
        return

    try:
        import comicarr
        comicarr.config.configure_schedulers()
    except Exception as e:
        logger.error("[SYSTEM] Error reconfiguring schedulers: %s" % e)


def get_version_info(ctx):
    """Return version information."""
    return {
        "current_version": ctx.current_version,
        "current_version_name": ctx.current_version_name,
        "current_release_name": ctx.current_release_name,
        "latest_version": ctx.latest_version,
        "commits_behind": ctx.commits_behind,
        "install_type": ctx.install_type,
        "current_branch": ctx.current_branch,
    }


def get_recent_logs(ctx):
    """Return recent log entries."""
    log_dir = getattr(ctx.config, "LOG_DIR", None) if ctx.config else None
    if not log_dir:
        log_dir = os.path.join(ctx.data_dir, "logs") if ctx.data_dir else None

    if not log_dir:
        return {"logs": []}

    log_file = os.path.join(log_dir, "comicarr.log")
    if not os.path.exists(log_file):
        return {"logs": []}

    try:
        with open(log_file, "r") as f:
            lines = f.readlines()
        return {"logs": lines[-200:]}  # Last 200 lines
    except Exception as e:
        logger.error("[SYSTEM] Error reading logs: %s" % e)
        return {"logs": [], "error": str(e)}


def get_job_info(ctx):
    """Return scheduled job information."""
    if not ctx.scheduler:
        return {"jobs": []}

    jobs = []
    for job in ctx.scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return {"jobs": jobs}
