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
import shlex
import subprocess
import sys
from collections import namedtuple

import comicarr
from comicarr import db, logger
from comicarr.app.core.security import LoginRateLimiter
from comicarr.tables import comics, jobhistory, storyarcs

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
    ctx.config.process_kwargs(
        {
            "http_username": username,
            "http_password": hashed_password,
            "authentication": 2,
        }
    )
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
        "COMIC_DIR",
        "DESTINATION_DIR",
        "HTTP_HOST",
        "HTTP_PORT",
        "HTTP_ROOT",
        "ENABLE_HTTPS",
        "AUTHENTICATION",
        "LAUNCH_BROWSER",
        "LOG_LEVEL",
        "DOWNLOAD_SCAN_INTERVAL",
        "NZB_STARTUP_SEARCH",
        "SEARCH_INTERVAL",
        "SEARCH_DELAY",
        "RSS_CHECK_INTERVAL",
        "AUTO_UPDATE",
        "ANNUALS_ON",
        "WEEKFOLDER",
        "REPLACE_SPACES",
        "ZERO_LEVEL",
        "ZERO_LEVEL_N",
        "LOWERCASE_FILENAMES",
        "FOLDER_FORMAT",
        "FILE_FORMAT",
        "COMICVINE_API",
        "ENABLE_META",
        "OPDS_ENABLE",
    ]
    result = {}
    for key in safe_keys:
        val = getattr(ctx.config, key, None)
        if val is not None:
            result[key] = val
    version = ctx.current_version
    if not version:
        try:
            from importlib.metadata import version as get_version
            version = get_version("comicarr")
        except Exception:
            version = None
    if version:
        result["version"] = version
    return result


WRITABLE_CONFIG_KEYS = {
    "COMIC_DIR",
    "DESTINATION_DIR",
    "HTTP_HOST",
    "HTTP_PORT",
    "HTTP_ROOT",
    "ENABLE_HTTPS",
    "LAUNCH_BROWSER",
    "LOG_LEVEL",
    "DOWNLOAD_SCAN_INTERVAL",
    "NZB_STARTUP_SEARCH",
    "SEARCH_INTERVAL",
    "SEARCH_DELAY",
    "RSS_CHECK_INTERVAL",
    "DBUPDATE_INTERVAL",
    "AUTO_UPDATE",
    "ANNUALS_ON",
    "WEEKFOLDER",
    "REPLACE_SPACES",
    "ZERO_LEVEL",
    "ZERO_LEVEL_N",
    "LOWERCASE_FILENAMES",
    "FOLDER_FORMAT",
    "FILE_FORMAT",
    "COMICVINE_API",
    "ENABLE_META",
    "OPDS_ENABLE",
    "OPDS_PAGESIZE",
    "MULTIPLE_DEST_DIRS",
    "CREATE_FOLDERS",
    "CHECK_FOLDER",
    "STORYARC_LOCATION",
}


def update_config(ctx, key_values):
    """Update configuration key-values and trigger scheduler reconfiguration."""
    import comicarr

    if not ctx.config:
        return {"success": False, "error": "Config not loaded"}

    # Filter to only writable keys — prevents privilege escalation via
    # overwriting HTTP_PASSWORD, API_KEY, AUTHENTICATION, etc.
    rejected = [k for k in key_values if k not in WRITABLE_CONFIG_KEYS]
    if rejected:
        logger.info("[CONFIG] Rejected non-writable keys: %s" % rejected)
    filtered = {k: v for k, v in key_values.items() if k in WRITABLE_CONFIG_KEYS}
    if not filtered:
        return {"success": False, "error": "No valid config keys provided"}

    # Apply scheduler change first (idempotent), then write config
    interval_keys = {"SEARCH_INTERVAL", "RSS_CHECK_INTERVAL", "DOWNLOAD_SCAN_INTERVAL", "DBUPDATE_INTERVAL"}
    interval_changed = any(k in interval_keys for k in filtered)

    ctx.config.process_kwargs(filtered)
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
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
        )
    return {"jobs": jobs}


def get_startup_diagnostics(ctx):
    """Return startup diagnostics (db empty, migration dismissed)."""
    import comicarr as _comicarr

    return {
        "db_empty": _comicarr.DB_EMPTY,
        "migration_dismissed": getattr(ctx.config, "MIGRATION_DISMISSED", False) if ctx.config else False,
    }


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
    """Start a migration in a background thread."""
    import comicarr as _comicarr

    if not path:
        return {"success": False, "error": "path parameter is required"}

    if _comicarr.MIGRATION_IN_PROGRESS:
        return {"success": False, "error": "Migration already in progress"}

    import threading

    from comicarr import migration

    m = migration.Mylar3Migration(path)
    result = m.validate()
    if not result.get("valid"):
        return {"success": False, "error": "Invalid Mylar3 data path"}

    t = threading.Thread(target=m.execute, name="MigrationThread")
    t.daemon = True
    t.start()
    return {"status": "started"}


def get_migration_progress(ctx):
    """Return current migration progress."""
    import comicarr as _comicarr

    return {
        "status": _comicarr.MIGRATION_STATUS,
        "current_table": _comicarr.MIGRATION_CURRENT_TABLE,
        "tables_complete": _comicarr.MIGRATION_TABLES_COMPLETE,
        "tables_total": _comicarr.MIGRATION_TABLES_TOTAL,
        "error": _comicarr.MIGRATION_ERROR,
    }


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
            db.upsert("Comics", newVal, CtrlVal)

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
    comicarr.CONFIG.DYNAMIC_UPDATE = 4
    comicarr.CONFIG.writeconfig()
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
    write=False, job=None, last_run_completed=None, current_run=None, status=None, failure=False, startup=False
):
    from comicarr.helpers import utctimestamp

    jobresults = []

    if startup is True:
        # on startup - db status will over-ride any settings to ensure persistent state
        from sqlalchemy import select

        job_info = db.select_all(
            select(jobhistory.c.JobName, jobhistory.c.status, jobhistory.c.prev_run_timestamp).distinct()
        )
        for ji in job_info:
            jstatus = ji["status"]
            if any([jstatus is None, jstatus == "Running"]):
                jstatus = "Waiting"
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
                    comicarr.SCHED_WEEKLY_LAST = ji["prev_run_timestamp"]
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
                "next_run_timestamp": jobtime,
                "prev_run_timestamp": prev_run_timestamp,
                "status": sched_status,
            }
        )

    if not write:
        if len(jobresults) == 0:
            return monitors
        else:
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
                pr_datetime = datetime.datetime.utcfromtimestamp(current_run)
                pr_datetime = pr_datetime.replace(microsecond=0)
                updateVals = {"prev_run_timestamp": current_run, "prev_run_datetime": pr_datetime, "status": status}
            elif last_run_completed is not None:
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
                                    nextrun_stamp = utctimestamp() + (int(comicarr.DBUPDATE_INTERVAL) * 60)
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
                                if comicarr.CONFIG.ALT_PULL == 2:
                                    wkt = 4
                                else:
                                    wkt = 24
                                nextrun_stamp = utctimestamp() + (wkt * 60 * 60)
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
                            nextrun_date = datetime.datetime.utcfromtimestamp(nextrun_stamp)
                            jobstore.modify(next_run_time=nextrun_date)
                            nextrun_date = nextrun_date.replace(microsecond=0)
                    else:
                        # if the rss is enabled after startup, we have to re-set it up...
                        nextrun_stamp = utctimestamp() + (int(comicarr.CONFIG.RSS_CHECKINTERVAL) * 60)
                        nextrun_date = datetime.datetime.utcfromtimestamp(nextrun_stamp)
                        comicarr.SCHED_RSS_LAST = last_run_completed

                if nextrun_date is not None:
                    logger.fdebug("ReScheduled job: %s to %s" % (job, comicarr.helpers.utc_date_to_local(nextrun_date)))
                lastrun_comp = datetime.datetime.utcfromtimestamp(last_run_completed)
                lastrun_comp = lastrun_comp.replace(microsecond=0)
                # if it's completed, then update the last run time to the ending time of the job
                updateVals = {
                    "prev_run_timestamp": last_run_completed,
                    "prev_run_datetime": lastrun_comp,
                    "last_run_completed": "True",
                    "next_run_timestamp": nextrun_stamp,
                    "next_run_datetime": nextrun_date,
                    "status": status,
                }

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
