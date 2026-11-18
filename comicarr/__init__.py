#  Copyright (C) 2012–2024 Mylar3 contributors
#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Originally based on Mylar3 (https://github.com/mylar3/mylar3).
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.


import csv
import datetime
import glob
import hashlib
import importlib
import itertools
import json
import locale
import os
import platform
import queue
import random
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import timedelta

import requests
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

import comicarr.app.config.ini
from comicarr.app.common import dates as common_dates
from comicarr.app.common.redaction import redact_diagnostic_error
from comicarr.app.core import db, logger, runtime
from comicarr.app.downloads import sabnzbd
from comicarr.app.downloads import service as downloads_service
from comicarr.app.search import rss_runner
from comicarr.app.search import service as search_service
from comicarr.app.search.queue import FairSearchQueue
from comicarr.app.series import service as series_service
from comicarr.app.series import watchlist_refresh
from comicarr.app.system import maintenance, versioncheck, versioncheckit
from comicarr.app.system import service as system_service
from comicarr.app.weekly import pull_runner

# Landed Alembic revision 0001 runs ``from comicarr.tables import metadata``, and a
# landed revision can never be edited. Keep that import path working after the
# move to app/core (tests/unit/test_landed_revision_imports.py pins it).
sys.modules.setdefault("comicarr.tables", importlib.import_module("comicarr.app.core.tables"))


_INITIALIZED = False


def _add_recurring_job(**kwargs):
    return runtime.current().scheduler.add_job(max_instances=1, coalesce=True, **kwargs)


def ensure_sab_completed_reconcile():
    """Keep the completed-SABnzbd sweep scheduled while client post-processing is on.

    The job is a no-op when SABnzbd monitoring is off, and it is not added for
    NZBGet. Enabling the setting at runtime starts it; disabling pauses it.
    """
    from comicarr.app.downloads.sab_reconcile import (
        INTERVAL_MINUTES,
        JOB_ID,
        reconcile_completed_sab_downloads,
        sab_client_post_processing_enabled,
    )

    enabled = sab_client_post_processing_enabled()
    try:
        existing = runtime.current().scheduler.get_job(JOB_ID)
    except Exception:
        existing = None
    if not enabled:
        if existing is not None:
            existing.pause()
        return existing
    if existing is not None:
        try:
            existing.resume()
        except Exception as e:
            logger.fdebug("[SAB-RECONCILE] could not resume %s: %s" % (JOB_ID, e))
        return existing
    job = _add_recurring_job(
        func=reconcile_completed_sab_downloads,
        id=JOB_ID,
        name="SABnzbd Completed Reconcile",
        trigger=IntervalTrigger(minutes=INTERVAL_MINUTES, timezone="UTC"),
    )
    logger.info("[SAB-RECONCILE] Checking completed SABnzbd history every %s minutes." % INTERVAL_MINUTES)
    return job


def initialize(config_file):
    with runtime.current().init_lock:
        global _INITIALIZED

        cc = comicarr.app.config.ini.Config(config_file)
        runtime.current().config = cc.read(startup=True)

        assert runtime.current().config is not None

        if _INITIALIZED:
            return False

        logger.info("Checking to see if the database has all tables....")
        try:
            from comicarr.app.core.schema import upgrade_database

            upgrade_database()
        except Exception as e:
            diagnostic_error = redact_diagnostic_error(e)
            runtime.current().acquisition_schema_ready = False
            runtime.current().acquisition_schema_error = diagnostic_error
            runtime.current().acquisition_workers_blocked = True
            runtime.current().acquisition_block_reason = "schema_migration_failed"
            logger.error("[SCHEMA-MIGRATION] Worker startup blocked after migration failure: %s" % diagnostic_error)
        else:
            try:
                with db.get_engine().connect() as conn:
                    row = conn.execute(text("SELECT COUNT(*) FROM comics")).first()
                    comic_count = row[0] if row else 0
                    if comic_count > 0:
                        if runtime.current().config.BACKUP_ON_START:
                            backup_dir = os.path.join(runtime.current().data_dir, "backups")
                            retention = (
                                runtime.current().config.BACKUP_RETENTION
                                if runtime.current().config.BACKUP_RETENTION
                                else 4
                            )
                            maintenance.auto_backup_db(runtime.current().db_file, backup_dir, retention)
                    else:
                        runtime.current().db_empty = True
            except Exception as e:
                logger.warn("[STARTUP] Startup diagnostics skipped: %s" % e)

            if runtime.current().maintenance is False:
                cc.provider_sequence()

            chk = maintenance.Maintenance(mode="db update")
            chk.check_failed_update()

            chk.db_update_check()

        try:
            from comicarr.app.acquisition.maintenance import refresh_runtime_state

            refresh_runtime_state(runtime.current().config)
        except Exception as e:
            runtime.current().acquisition_workers_blocked = True
            runtime.current().acquisition_block_reason = "maintenance_gate_unavailable"
            logger.error("[ACQUISITION] Maintenance gate unavailable; workers remain blocked: %s" % e)

        if runtime.current().maintenance_update:
            runtime.current().maintenance = True

        if runtime.current().maintenance is False:
            comicarr.app.config.ini.ddl_creations()

            if runtime.current().logtype == "clog":
                logprog = "Concurrent Rotational Log Handler"
            else:
                logprog = "Rotational Log Handler (default)"

            logger.fdebug("Logger set to use : " + logprog)
            if runtime.current().logtype == "log" and runtime.current().os_detect == "Windows":
                logger.fdebug(
                    "ConcurrentLogHandler package not installed. Using builtin log handler for Rotational logs (default)"
                )
                logger.fdebug(
                    "[Windows Users] If you are experiencing log file locking and want this auto-enabled, you need to install Python Extensions for Windows ( http://sourceforge.net/projects/pywin32/ )"
                )

            if runtime.current().config.SYNO_FIX:
                parsepath = os.path.join(runtime.current().data_dir, "bs4", "builder", "_lxml.py")
                if os.path.isfile(parsepath):
                    print("found bs4...renaming appropriate file.")
                    src = os.path.join(parsepath)
                    dst = os.path.join(runtime.current().data_dir, "bs4", "builder", "lxml.py")
                    try:
                        shutil.move(src, dst)
                    except (OSError, IOError):
                        logger.error(
                            "Unable to rename file...shutdown Comicarr and go to "
                            + src.encode("utf-8")
                            + " and rename the _lxml.py file to lxml.py"
                        )
                        logger.error("NOT doing this will result in errors when adding / refreshing a series")
                else:
                    logger.info("Synology Parsing Fix already implemented. No changes required at this time.")

            if runtime.current().sse_key is None:
                import secrets

                runtime.current().sse_key = secrets.token_hex(16)

            if not runtime.current().config.API_KEY or len(runtime.current().config.API_KEY) != 32:
                import secrets

                runtime.current().config.API_KEY = secrets.token_hex(16)
                runtime.current().config.API_ENABLED = True
                runtime.current().config.WRITE_THE_CONFIG = True
                logger.info("[STARTUP] API key was not set - auto-generated a new API key")

            from comicarr.app.downloads.ddl import external_server as des

            logger.info("[DDL] External server configuration available to be loaded: %s" % des.EXT_SERVER)

        runtime.current().cv_headers = {"User-Agent": runtime.current().config.CV_USER_AGENT}

        def initialize_cv_session():
            """Initialize ComicVine API session with connection pooling"""
            if runtime.current().cv_session is None:
                runtime.current().cv_session = requests.Session()
                runtime.current().cv_session.headers.update(runtime.current().cv_headers)
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=10, pool_maxsize=20, max_retries=3, pool_block=False
                )
                runtime.current().cv_session.mount("https://", adapter)
                runtime.current().cv_session.mount("http://", adapter)
                logger.info("ComicVine API session initialized with connection pooling")

            if runtime.current().cv_rate_limiter is None:
                from comicarr.app.metadata import rate_limiter

                cvapi_rate = (
                    runtime.current().config.CVAPI_RATE
                    if runtime.current().config.CVAPI_RATE and runtime.current().config.CVAPI_RATE >= 2
                    else 2
                )
                runtime.current().cv_rate_limiter = rate_limiter.ComicVineRateLimiter(calls_per_second=1.0 / cvapi_rate)
                logger.info("ComicVine rate limiter initialized with %s second interval" % cvapi_rate)

            if runtime.current().cv_cache is None:
                from comicarr.app.metadata import cv_cache

                cache_db_path = os.path.join(runtime.current().data_dir, "cv_cache.db")
                runtime.current().cv_cache = cv_cache.CVCache(cache_db_path)
                logger.info("ComicVine cache initialized at: %s" % cache_db_path)

        initialize_cv_session()

        def initialize_metron_session():
            """Initialize Metron API session using mokkari"""
            if runtime.current().metron_api is None and runtime.current().config.USE_METRON_SEARCH:
                if runtime.current().config.METRON_USERNAME and runtime.current().config.METRON_PASSWORD:
                    try:
                        from comicarr.app.metadata import metron

                        runtime.current().metron_api = metron.initialize_metron_api()
                        if runtime.current().metron_api:
                            logger.info("Metron API session initialized successfully")
                        else:
                            logger.warn("Metron API initialization returned None - check credentials")
                    except ImportError as e:
                        logger.warn("Failed to import mokkari library for Metron API: %s" % e)
                    except Exception as e:
                        logger.error("Failed to initialize Metron API: %s" % e)
                else:
                    logger.fdebug("Metron search enabled but credentials not configured")

        initialize_metron_session()

        todaydate = datetime.datetime.today()
        runtime.current().current_weeknumber = todaydate.strftime("%U")
        runtime.current().current_year = todaydate.strftime("%Y")

        if runtime.current().search_tier_date is None:
            STD = todaydate - timedelta(days=runtime.current().config.SEARCH_TIER_CUTOFF)
            runtime.current().search_tier_date = STD.strftime("%Y-%m-%d")
            logger.fdebug("Search tier date set to : %s" % runtime.current().search_tier_date)

        runtime.current().cv_url = "https://comicvine.gamespot.com/api/"

        try:
            pub_path = os.path.join(runtime.current().config.CACHE_DIR, "imprints.json")
            update_imprints = True
            if os.path.exists(pub_path):
                filetime = max(os.path.getctime(pub_path), os.path.getmtime(pub_path))
                pub_diff = (time.time() - filetime) / 3600
                if pub_diff > 24:
                    logger.info(
                        "[IMPRINT_LOADS] Publisher imprint listing found, but possibly stale ( > 24hrs). Retrieving up-to-date listing"
                    )
                else:
                    update_imprints = False
                    logger.info("[IMPRINT_LOADS] Loading Publisher imprints data from local file.")
                    with open(pub_path) as json_file:
                        runtime.current().publisher_imprints = json.load(json_file)
            else:
                logger.info("[IMPRINT_LOADS] No data for publisher imprints locally. Retrieving up-to-date listing")

            if update_imprints is True:
                req_pub = requests.get("https://mylar3.github.io/publisher_imprints/imprints.json", verify=True)
                try:
                    json_pub = req_pub.json()
                    with open(pub_path, "w", encoding="utf-8") as outfile:
                        json.dump(json_pub, outfile, indent=4, ensure_ascii=False)
                except Exception as e:
                    logger.error("Unable to write imprints.json to %s. Error returned: %s" % (pub_path, e))
                else:
                    logger.fdebug("Successfully written imprints.json file to %s" % pub_path)
                    runtime.current().publisher_imprints = json_pub

        except requests.exceptions.RequestException as e:
            logger.warn("[IMPRINT_LOADS] Unable to retrieve publisher imprints listing at this time. Error: %s" % e)
            runtime.current().publisher_imprints = None
        except Exception as e:
            logger.warn("[IMPRINT_LOADS] Unable to load publisher -> imprint file. Error: %s" % e)
            runtime.current().publisher_imprints = None
        else:
            if runtime.current().publisher_imprints is not None:
                logger.info(
                    "[IMPRINT_LOADS] Successfully loaded imprints for %s publishers"
                    % (len(runtime.current().publisher_imprints["publishers"]))
                )

            logger.info("Remapping the sorting to allow for new additions.")
            runtime.current().comic_sort = series_service.ComicSort(sequence="startup")

        if runtime.current().config.LOCMOVE:
            series_service.updateComicLocation()

        if all([runtime.current().use_sabnzbd is True, runtime.current().config.SAB_HOST is not None]):
            s_to_the_ab = sabnzbd.SABnzbd(params=None)
            s_to_the_ab.sab_versioncheck()
            logger.info("[SAB-VERSION-CHECK] SABnzbd version detected as: %s" % runtime.current().config.SAB_VERSION)

        runtime.current().umask = os.umask(0)
        os.umask(runtime.current().umask)

        _INITIALIZED = True
        return True


def daemonize():

    if threading.active_count() != 1:
        logger.warn(
            "There are %r active threads. Daemonizing may cause \
                        strange behavior."
            % threading.enumerate()
        )

    sys.stdout.flush()
    sys.stderr.flush()

    try:
        pid = os.fork()
        if pid == 0:
            pass
        else:
            logger.debug("Forking once...")
            os._exit(0)
    except OSError as e:
        sys.exit("1st fork failed: %s [%d]" % (e.strerror, e.errno))

    os.setsid()

    prev = os.umask(0)
    os.umask(prev and int("077", 8))

    try:
        pid = os.fork()
        if pid > 0:
            logger.debug("Forking twice...")
            os._exit(0)
    except OSError as e:
        sys.exit("2nd fork failed: %s [%d]" % (e.strerror, e.errno))

    dev_null = open("/dev/null", "r")
    os.dup2(dev_null.fileno(), sys.stdin.fileno())

    si = open("/dev/null", "r")
    so = open("/dev/null", "a+")
    se = open("/dev/null", "a+")

    os.dup2(si.fileno(), sys.stdin.fileno())
    os.dup2(so.fileno(), sys.stdout.fileno())
    os.dup2(se.fileno(), sys.stderr.fileno())

    pid = os.getpid()
    logger.info("Daemonized to PID: %s" % pid)
    if runtime.current().createpid:
        logger.info("Writing PID %d to %s", pid, runtime.current().pidfile)
        with open(runtime.current().pidfile, "w") as fp:
            fp.write("%s\n" % pid)


def launch_browser(host, port, root):

    if host == "0.0.0.0":
        host = "localhost"

    try:
        webbrowser.open("http://%s:%i%s" % (host, port, root))
    except Exception as e:
        logger.error("Could not launch browser: %s" % e)


def replay_acquisition_obligations(ctx=None):
    """Restore durable search and refresh commands before workers start."""
    from comicarr.app.search.commands import replay_search_obligations
    from comicarr.app.series import add_workers

    search_queue = (ctx if ctx is not None else runtime.current()).search_queue
    search_count = replay_search_obligations(work_queue=search_queue)
    refresh_count = add_workers.replay_refresh_obligations(start_worker=True)
    if search_count or refresh_count:
        logger.info("[ACQUISITION] Replayed %s search and %s refresh obligations" % (search_count, refresh_count))
    return {"search": search_count, "refresh": refresh_count}


def resume_acquisition_runtime(config=None):
    """Replay and restart acquisition-only work after an explicit gate release.

    ``start()`` intentionally leaves the process alive but pauses producers
    and consumers when the durable reconciliation gate is closed. Releasing
    that gate from the authenticated operator flow must therefore restore the
    same narrow runtime surface without requiring an undocumented container
    restart or starting unrelated diagnostics work a second time.
    """

    from comicarr.app.acquisition.maintenance import refresh_runtime_state
    from comicarr.app.core.runtime import get_runtime_if_initialized, set_runtime_acquisition_status
    from comicarr.app.downloads.torrent import monitor as torrent_monitor

    ctx = get_runtime_if_initialized()
    config = config or (ctx.config if ctx is not None else runtime.current().config)

    def schedule(queue_name):
        if ctx is not None:
            queue_schedule(queue_name, "start", ctx=ctx)
        else:
            queue_schedule(queue_name, "start")

    with runtime.current().acquisition_resume_lock:
        gate = refresh_runtime_state(config)
        if gate.blocked:
            raise RuntimeError("acquisition remains blocked: %s" % (gate.reason or "unknown gate"))

        try:
            replayed = replay_acquisition_obligations(ctx=ctx) if ctx is not None else replay_acquisition_obligations()
        except Exception as e:
            set_runtime_acquisition_status(
                workers_blocked=True,
                block_reason="obligation_replay_failed",
            )
            raise RuntimeError("durable acquisition replay failed") from e

        queues_started = ["search_queue"]
        schedule("search_queue")
        if all(
            [
                bool(getattr(config, "ENABLE_TORRENTS", False)),
                any(
                    [
                        bool(getattr(config, "AUTO_SNATCH", False)),
                        bool(getattr(config, "LOCAL_TORRENT_PP", False)),
                    ]
                ),
                runtime.current().os_detect != "Windows",
            ]
        ) and torrent_monitor.is_monitorable_downloader(getattr(config, "TORRENT_DOWNLOADER", None)):
            schedule("snatched_queue")
            queues_started.append("snatched_queue")
        if bool(getattr(config, "POST_PROCESSING", False)) and (
            (
                getattr(config, "NZB_DOWNLOADER", None) == 0
                and bool(getattr(config, "SAB_CLIENT_POST_PROCESSING", False))
            )
            or (
                getattr(config, "NZB_DOWNLOADER", None) == 1
                and bool(getattr(config, "NZBGET_CLIENT_POST_PROCESSING", False))
            )
        ):
            schedule("nzb_queue")
            queues_started.append("nzb_queue")
        if bool(getattr(config, "POST_PROCESSING", False)):
            schedule("pp_queue")
            queues_started.append("pp_queue")
        if bool(getattr(config, "ENABLE_DDL", False)):
            schedule("ddl_queue")
            queues_started.append("ddl_queue")

        scheduler_statuses = {
            "dbupdater": runtime.current().updater_status,
            "search": runtime.current().search_status,
            "weekly": runtime.current().weekly_status,
            "rss": runtime.current().rss_status,
            "monitor": runtime.current().monitor_status,
            "importinbox": runtime.current().importinbox_status,
            "manga_sync": runtime.current().manga_sync_status,
        }
        scheduler = (ctx if ctx is not None else runtime.current()).scheduler
        resumed_jobs = []
        for job_id, status in scheduler_statuses.items():
            if status == "Paused":
                continue
            job = scheduler.get_job(job_id)
            if job is None:
                continue
            job.resume()
            resumed_jobs.append(job_id)

        logger.info(
            "[ACQUISITION] Resumed runtime: replayed %s search/%s refresh obligations; queues=%s; jobs=%s"
            % (
                replayed["search"],
                replayed["refresh"],
                ",".join(queues_started),
                ",".join(resumed_jobs) or "none",
            )
        )
        return {
            "replayed": replayed,
            "queues_started": queues_started,
            "scheduler_jobs_resumed": resumed_jobs,
        }


def start(ctx):
    """Start scheduler/workers against the pre-created canonical runtime.

    ``Comicarr.py`` creates ``ctx`` only after configuration, schema, and
    secrets are ready. Rejecting a missing or divergent context prevents a
    worker from starting against a copied queue/lock/scheduler view.
    """
    from comicarr.app.core.runtime import RuntimeNotInitializedError, set_runtime_acquisition_status, set_runtime_field
    from comicarr.app.downloads.torrent import monitor as torrent_monitor

    if ctx is None or ctx.disposed:
        raise RuntimeNotInitializedError("Workers cannot start before an active runtime context exists")
    if (
        ctx.scheduler is not runtime.current().scheduler
        or ctx.search_queue is not runtime.current().search_queue
        or ctx.ddl_queue is not runtime.current().ddl_queue
        or ctx.ddl_lock is not runtime.current().ddl_lock
        or ctx.ddl_queued is not runtime.current().ddl_queued
    ):
        raise RuntimeNotInitializedError(
            "Workers must start with the canonical runtime's shared scheduler, queues, locks, and DDL state"
        )

    global _INITIALIZED

    with runtime.current().init_lock:
        if _INITIALIZED:
            updater_job = _add_recurring_job(
                func=watchlist_refresh.run_scheduled_refresh,
                id="dbupdater",
                next_run_time=datetime.datetime.utcnow(),
                name="DB Updater",
                args=[None, True],
                trigger=IntervalTrigger(hours=0, minutes=runtime.current().config.DBUPDATE_INTERVAL, timezone="UTC"),
            )
            updater_job.pause()

            from comicarr.app.search.service import run_scheduled_search

            search_job = _add_recurring_job(
                func=run_scheduled_search,
                id="search",
                next_run_time=datetime.datetime.utcnow(),
                name="Auto-Search",
                trigger=IntervalTrigger(hours=0, minutes=runtime.current().config.SEARCH_INTERVAL, timezone="UTC"),
            )
            search_job.pause()

            ws = pull_runner.Weekly()
            weekly_job = _add_recurring_job(
                func=ws.run,
                id="weekly",
                name="Weekly Pullist",
                next_run_time=datetime.datetime.utcnow(),
                trigger=IntervalTrigger(hours=4, minutes=0, timezone="UTC"),
            )
            weekly_job.pause()

            rs = rss_runner.tehMain()
            rss_job = _add_recurring_job(
                func=rs.run,
                id="rss",
                name="RSS Feeds",
                args=[True],
                next_run_time=datetime.datetime.utcnow(),
                trigger=IntervalTrigger(
                    hours=0, minutes=int(runtime.current().config.RSS_CHECKINTERVAL), timezone="UTC"
                ),
            )
            rss_job.pause()

            vs = versioncheckit.CheckVersion()
            version_job = _add_recurring_job(
                func=vs.run,
                id="version",
                name="Check Version",
                trigger=IntervalTrigger(
                    hours=0, minutes=runtime.current().config.CHECK_GITHUB_INTERVAL, timezone="UTC"
                ),
            )
            version_job.pause()

            from comicarr.app.downloads.folder_monitor import FolderCheck

            fm = FolderCheck()
            monitor_job = _add_recurring_job(
                func=fm.run,
                id="monitor",
                name="Folder Monitor",
                trigger=IntervalTrigger(
                    hours=0, minutes=int(runtime.current().config.DOWNLOAD_SCAN_INTERVAL), timezone="UTC"
                ),
            )
            monitor_job.pause()

            from comicarr.app.imports import importinbox

            importinbox_job = _add_recurring_job(
                func=importinbox.run,
                id="importinbox",
                name="Import Inbox Scanner",
                trigger=IntervalTrigger(
                    hours=0, minutes=int(runtime.current().config.IMPORT_SCAN_INTERVAL), timezone="UTC"
                ),
            )
            importinbox_job.pause()

            from comicarr.app.manga.sync import JOB_NAME as MANGA_SYNC_JOB_NAME
            from comicarr.app.manga.sync import run_manga_sync

            manga_sync_job = _add_recurring_job(
                func=run_manga_sync,
                id="manga_sync",
                name=MANGA_SYNC_JOB_NAME,
                next_run_time=datetime.datetime.utcnow(),
                trigger=IntervalTrigger(
                    hours=0, minutes=int(runtime.current().config.DBUPDATE_INTERVAL), timezone="UTC"
                ),
            )
            manga_sync_job.pause()

            from comicarr.app.acquisition.retention import run_ledger_retention

            _add_recurring_job(
                func=run_ledger_retention,
                id="ledger_retention",
                name="Ledger Retention",
                trigger=IntervalTrigger(days=1, timezone="UTC"),
            )

            from comicarr.app.activity import retention as activity_retention

            _add_recurring_job(
                func=activity_retention.run,
                id="activity_retention",
                name=activity_retention.JOB_NAME,
                next_run_time=datetime.datetime.utcnow(),
                trigger=IntervalTrigger(hours=24, minutes=0, timezone="UTC"),
            )

            from comicarr.app.search import interactive_sessions

            _add_recurring_job(
                func=interactive_sessions.run,
                id="interactive_search_retention",
                name=interactive_sessions.JOB_NAME,
                next_run_time=datetime.datetime.utcnow(),
                trigger=IntervalTrigger(hours=24, minutes=0, timezone="UTC"),
            )

            from comicarr.app.system import connections as connection_checks

            _add_recurring_job(
                func=connection_checks.run,
                id=connection_checks.JOB_ID,
                name=connection_checks.JOB_NAME,
                next_run_time=datetime.datetime.utcnow() + datetime.timedelta(minutes=2),
                trigger=IntervalTrigger(minutes=connection_checks.CHECK_INTERVAL_MINUTES, timezone="UTC"),
            )

            try:
                from comicarr.app.acquisition.maintenance import refresh_runtime_state

                acquisition_gate = refresh_runtime_state(runtime.current().config)
            except Exception as e:
                acquisition_gate = None
                set_runtime_acquisition_status(
                    workers_blocked=True,
                    block_reason="maintenance_gate_unavailable",
                )
                logger.error("[ACQUISITION] Refusing worker startup because gate refresh failed: %s" % e)

            if ctx.acquisition_workers_blocked:
                if ctx.version_status != "Paused":
                    version_job.resume()
                logger.warn(
                    "[ACQUISITION] Background acquisition is blocked (%s); diagnostics remain available"
                    % (acquisition_gate.reason if acquisition_gate else ctx.acquisition_block_reason)
                )
                try:
                    runtime.current().scheduler.start()
                except Exception as e:
                    logger.error("[ACQUISITION] Unable to start diagnostics scheduler: %s" % e)
                set_runtime_field(ctx, "started", True)
                return

            try:
                replay_acquisition_obligations(ctx=ctx)
            except Exception as e:
                set_runtime_acquisition_status(
                    workers_blocked=True,
                    block_reason="obligation_replay_failed",
                )
                logger.error("[ACQUISITION] Durable obligation replay failed; workers remain blocked: %s" % e)
                try:
                    runtime.current().scheduler.start()
                except Exception as scheduler_error:
                    logger.error("[ACQUISITION] Unable to start diagnostics scheduler: %s" % scheduler_error)
                set_runtime_field(ctx, "started", True)
                return

            monitors = system_service.job_management(startup=True)

            sched_weekly_last = monitors["weekly"]["last"]
            sched_search_last = monitors["search"]["last"]
            sched_updater_last = monitors["updater"]["last"]
            monitors["monitor"]["last"]
            monitors["version"]["last"]
            sched_rss_last = monitors["rss"]["last"]
            sched_manga_sync_last = monitors.get("manga_sync", {}).get("last")

            if ctx.updater_status != "Paused":
                if sched_updater_last is not None:
                    updater_timestamp = float(sched_updater_last)
                    logger.fdebug(
                        "[DB UPDATER] Updater last run @ %s"
                        % common_dates.utc_date_to_local(datetime.datetime.utcfromtimestamp(updater_timestamp))
                    )
                else:
                    updater_timestamp = common_dates.utctimestamp() + (
                        int(runtime.current().config.DBUPDATE_INTERVAL) * 60
                    )

                updater_diff = (common_dates.utctimestamp() - updater_timestamp) / 60
                if updater_diff >= int(runtime.current().config.DBUPDATE_INTERVAL):
                    logger.fdebug("[DB UPDATER] DB Updater scheduled to run immediately.")
                    updater_job.modify(next_run_time=(datetime.datetime.utcnow()))
                else:
                    updater_diff = datetime.datetime.utcfromtimestamp(
                        common_dates.utctimestamp()
                        + ((int(runtime.current().config.DBUPDATE_INTERVAL) * 60) - (updater_diff * 60))
                    )
                    logger.fdebug(
                        "[DB UPDATER] Scheduling next run @ %s (every %s minutes)"
                        % (common_dates.utc_date_to_local(updater_diff), runtime.current().config.DBUPDATE_INTERVAL)
                    )
                    updater_job.modify(next_run_time=updater_diff)

            from comicarr.app.manga.sync import arm_manga_sync_job

            if ctx.manga_sync_status != "Paused":
                arm_manga_sync_job(
                    manga_sync_job,
                    ctx.manga_sync_status,
                    sched_manga_sync_last,
                    runtime.current().config.DBUPDATE_INTERVAL,
                )

            if ctx.search_status != "Paused":
                if runtime.current().config.NZB_STARTUP_SEARCH:
                    search_job.modify(next_run_time=(datetime.datetime.utcnow() + timedelta(minutes=2)))
                else:
                    if sched_search_last is not None:
                        search_timestamp = float(sched_search_last)
                        logger.fdebug(
                            "[AUTO-SEARCH] Search last run @ %s"
                            % common_dates.utc_date_to_local(datetime.datetime.utcfromtimestamp(search_timestamp))
                        )
                    else:
                        search_timestamp = common_dates.utctimestamp() + (
                            int(runtime.current().config.SEARCH_INTERVAL) * 60
                        )

                    duration_diff = (common_dates.utctimestamp() - search_timestamp) / 60
                    if duration_diff >= int(runtime.current().config.SEARCH_INTERVAL):
                        logger.fdebug(
                            "[AUTO-SEARCH]Auto-Search set to an initial delay of 2 minutes before initialization as it has been %s minutes since the last run"
                            % duration_diff
                        )
                        search_job.modify(next_run_time=(datetime.datetime.utcnow() + timedelta(minutes=2)))
                    else:
                        search_diff = datetime.datetime.utcfromtimestamp(
                            common_dates.utctimestamp()
                            + ((int(runtime.current().config.SEARCH_INTERVAL) * 60) - (duration_diff * 60))
                        )
                        logger.fdebug(
                            "[AUTO-SEARCH] Scheduling next run @ %s (every %s minutes)"
                            % (common_dates.utc_date_to_local(search_diff), runtime.current().config.SEARCH_INTERVAL)
                        )
                        search_job.modify(next_run_time=search_diff)

            queue_schedule("search_queue", "start", ctx=ctx)

            if all(
                [
                    runtime.current().config.ENABLE_TORRENTS,
                    any([runtime.current().config.AUTO_SNATCH, runtime.current().config.LOCAL_TORRENT_PP]),
                    runtime.current().os_detect != "Windows",
                ]
            ) and torrent_monitor.is_monitorable_downloader(runtime.current().config.TORRENT_DOWNLOADER):
                queue_schedule("snatched_queue", "start", ctx=ctx)

            if runtime.current().config.POST_PROCESSING is True and (
                all(
                    [
                        runtime.current().config.NZB_DOWNLOADER == 0,
                        runtime.current().config.SAB_CLIENT_POST_PROCESSING is True,
                    ]
                )
                or all(
                    [
                        runtime.current().config.NZB_DOWNLOADER == 1,
                        runtime.current().config.NZBGET_CLIENT_POST_PROCESSING is True,
                    ]
                )
            ):
                queue_schedule("nzb_queue", "start", ctx=ctx)
            ensure_sab_completed_reconcile()

            if runtime.current().config.POST_PROCESSING is True:
                queue_schedule("pp_queue", "start", ctx=ctx)

            if runtime.current().config.ENABLE_DDL is True:
                queue_schedule("ddl_queue", "start", ctx=ctx)
                _add_recurring_job(
                    func=downloads_service.ddl_health_check,
                    id="ddl_health",
                    name="DDL Health Check",
                    trigger=IntervalTrigger(
                        hours=0, minutes=int(runtime.current().config.DDL_STUCK_CHECK_INTERVAL), timezone="UTC"
                    ),
                )
                logger.info(
                    "[DDL-HEALTH] DDL health check enabled, running every %s minutes"
                    % runtime.current().config.DDL_STUCK_CHECK_INTERVAL
                )

            series_service.latestdate_fix()

            if runtime.current().config.ALT_PULL == 2:
                weektimer = 4
            else:
                weektimer = 24

            logger.info("[WEEKLY] Checking for existance of Weekly Comic listing...")

            weekly_interval = weektimer * 60 * 60
            try:
                if sched_weekly_last:
                    pass
            except:
                sched_weekly_last = None

            weektimestamp = common_dates.utctimestamp()
            if sched_weekly_last is not None:
                weekly_timestamp = float(sched_weekly_last)
            else:
                weekly_timestamp = weektimestamp + weekly_interval

            duration_diff = (weektimestamp - weekly_timestamp) / 60

            if ctx.weekly_status != "Paused":
                if abs(duration_diff) >= weekly_interval / 60:
                    logger.info(
                        "[WEEKLY] Weekly Pull-Update initializing immediately as it has been %s hours since the last run"
                        % abs(duration_diff / 60)
                    )
                    weekly_job.modify(next_run_time=datetime.datetime.utcnow())
                else:
                    weekly_diff = datetime.datetime.utcfromtimestamp(
                        weektimestamp + (weekly_interval - (duration_diff * 60))
                    )
                    logger.fdebug(
                        "[WEEKLY] Scheduling next run for @ %s every %s hours"
                        % (common_dates.utc_date_to_local(weekly_diff), weektimer)
                    )
                    weekly_job.modify(next_run_time=weekly_diff)

            if ctx.rss_status != "Paused":
                logger.info("[RSS-FEEDS] Initiating startup-RSS feed checks.")
                if sched_rss_last is not None:
                    rss_timestamp = float(sched_rss_last)
                    logger.info(
                        "[RSS-FEEDS] RSS last run @ %s"
                        % common_dates.utc_date_to_local(datetime.datetime.utcfromtimestamp(rss_timestamp))
                    )
                else:
                    rss_timestamp = common_dates.utctimestamp() + (int(runtime.current().config.RSS_CHECKINTERVAL) * 60)
                duration_diff = (common_dates.utctimestamp() - rss_timestamp) / 60
                if duration_diff >= int(runtime.current().config.RSS_CHECKINTERVAL):
                    rss_job.modify(next_run_time=datetime.datetime.utcnow())
                else:
                    rss_diff = datetime.datetime.utcfromtimestamp(
                        common_dates.utctimestamp()
                        + (int(runtime.current().config.RSS_CHECKINTERVAL) * 60)
                        - (duration_diff * 60)
                    )
                    logger.fdebug(
                        "[RSS-FEEDS] Scheduling next run for @ %s every %s minutes"
                        % (common_dates.utc_date_to_local(rss_diff), runtime.current().config.RSS_CHECKINTERVAL)
                    )
                    rss_job.modify(next_run_time=rss_diff)

            if ctx.importinbox_status != "Paused":
                if runtime.current().config.IMPORT_DIR is not None:
                    if runtime.current().config.IMPORT_SCAN_INTERVAL > 0:
                        logger.info(
                            "[IMPORT-INBOX] Enabling import inbox scanner for: "
                            + str(runtime.current().config.IMPORT_DIR)
                            + " every "
                            + str(runtime.current().config.IMPORT_SCAN_INTERVAL)
                            + " minutes."
                        )
                        importinbox_job.resume()
                    else:
                        logger.info("[IMPORT-INBOX] Import scan interval set to 0, disabling scheduled scanning")
                        importinbox_job.pause()
                else:
                    logger.fdebug("[IMPORT-INBOX] No IMPORT_DIR configured, disabling scheduled scanning")
                    importinbox_job.pause()

            if ctx.version_status != "Paused":
                version_job.resume()

            if ctx.monitor_status != "Paused":
                if runtime.current().config.CHECK_FOLDER is not None:
                    if runtime.current().config.DOWNLOAD_SCAN_INTERVAL > 0:
                        logger.info(
                            "[FOLDER MONITOR] Enabling folder monitor for : "
                            + str(runtime.current().config.CHECK_FOLDER)
                            + " every "
                            + str(runtime.current().config.DOWNLOAD_SCAN_INTERVAL)
                            + " minutes."
                        )
                        monitor_job.resume()
                    else:
                        logger.error(
                            "[FOLDER MONITOR] You need to specify a monitoring time for the check folder option to work"
                        )
                        monitor_job.pause()
                else:
                    logger.error(
                        "[FOLDER MONITOR] You need to specify a location in order to use the Folder Monitor. Disabling Folder Monitor"
                    )
                    monitor_job.pause()

            logger.info("Firing up the Background Schedulers now....")

            try:
                runtime.current().scheduler.start()
                logger.info("Background Schedulers successfully started...")
                system_service.job_management(write=True)
            except Exception as e:
                logger.info(e)
                runtime.current().scheduler.print_jobs()

        set_runtime_field(ctx, "started", True)


def queue_schedule(queuetype, mode, ctx=None):
    """Start/stop legacy workers while preserving canonical pool identity."""
    from comicarr.app.core.runtime import get_runtime_if_initialized
    from comicarr.app.downloads.torrent import monitor as torrent_monitor

    ctx = ctx or get_runtime_if_initialized()
    queues = ctx if ctx is not None else runtime.current()

    def get_pool(pool_field):
        return getattr(queues, pool_field)

    def set_pool(pool_field, pool):
        with queues.runtime_lock:
            setattr(queues, pool_field, pool)

    def start(pool_attr, target, q_arg, name, before_msg, after_msg):
        pool = get_pool(pool_attr)
        try:
            if pool.is_alive() is True:
                return
        except Exception:
            pass

        logger.info("[%s] %s" % (name, before_msg))
        thread = threading.Thread(target=target, args=(q_arg,), name=name)
        set_pool(pool_attr, thread)
        thread.start()
        logger.info("[%s] %s" % (name, after_msg))

    def shutdown(pool, comicarr_queue, thread_name):
        try:
            if pool.is_alive() is False:
                return
        except Exception:
            return

        logger.fdebug(f"Terminating the {thread_name} thread")
        try:
            comicarr_queue.put("exit")
            pool.join(5)
            logger.fdebug("Joined pool for termination -  successful")
        except KeyboardInterrupt:
            comicarr_queue.put("exit")
            pool.join(5)
        except AssertionError as e:
            logger.warn("[%s] AssertionError joining pool: %s" % (thread_name, e))

    if mode == "start":
        if queuetype == "snatched_queue":
            start(
                "sn_pool",
                downloads_service.worker_main,
                queues.snatched_queue,
                "AUTO-SNATCHER",
                "Auto-Snatch of completed torrents enabled & attempting to background load....",
                "Succesfully started Auto-Snatch add-on - will now monitor for completed torrents on client....",
            )
        elif queuetype == "nzb_queue":
            try:
                if get_pool("nzb_pool").is_alive() is True:
                    return
            except Exception:
                pass

            if runtime.current().config.NZB_DOWNLOADER == 0:
                logger.info(
                    "[SAB-MONITOR] Completed post-processing handling enabled for SABnzbd. Attempting to background load...."
                )
            elif runtime.current().config.NZB_DOWNLOADER == 1:
                logger.info(
                    "[NZBGET-MONITOR] Completed post-processing handling enabled for NZBGet. Attempting to background load...."
                )
            pool = threading.Thread(
                target=downloads_service.nzb_monitor, args=(queues.nzb_queue,), name="AUTO-COMPLETE-NZB"
            )
            set_pool("nzb_pool", pool)
            pool.start()
            if runtime.current().config.NZB_DOWNLOADER == 0:
                logger.info(
                    "[AUTO-COMPLETE-NZB] Succesfully started Completed post-processing handling for SABnzbd - will now monitor for completed nzbs within sabnzbd and post-process automatically..."
                )
            elif runtime.current().config.NZB_DOWNLOADER == 1:
                logger.info(
                    "[AUTO-COMPLETE-NZB] Succesfully started Completed post-processing handling for NZBGet - will now monitor for completed nzbs within nzbget and post-process automatically..."
                )

        elif queuetype == "search_queue":
            start(
                "search_pool",
                search_service.search_queue,
                queues.search_queue,
                "SEARCH-QUEUE",
                "Attempting to background load the search queue....",
                "Successfully started the Search Queuer...",
            )
        elif queuetype == "pp_queue":
            start(
                "pp_pool",
                downloads_service.postprocess_main,
                queues.pp_queue,
                "POST-PROCESS-QUEUE",
                "Post Process queue enabled & monitoring for api requests....",
                "Succesfully started Post-Processing Queuer....",
            )
        elif queuetype == "ddl_queue":
            try:
                if get_pool("ddl_pool").is_alive() is True:
                    return
            except Exception:
                pass
            downloads_service.recover_queued_ddl_commands(queues.ddl_queue)
            start(
                "ddl_pool",
                downloads_service.ddl_downloader,
                queues.ddl_queue,
                "DDL-QUEUE",
                "DDL Download queue enabled & monitoring for requests....",
                "Succesfully started DDL Download Queuer....",
            )
    else:
        if (queuetype == "nzb_queue") or mode == "shutdown":
            if all([mode != "shutdown", runtime.current().config.POST_PROCESSING is True]) and (
                all(
                    [
                        runtime.current().config.NZB_DOWNLOADER == 0,
                        runtime.current().config.SAB_CLIENT_POST_PROCESSING is True,
                    ]
                )
                or all(
                    [
                        runtime.current().config.NZB_DOWNLOADER == 1,
                        runtime.current().config.NZBGET_CLIENT_POST_PROCESSING is True,
                    ]
                )
            ):
                return
            shutdown(get_pool("nzb_pool"), queues.nzb_queue, "NZB auto-complete queue")

        if (queuetype == "snatched_queue") or mode == "shutdown":
            if all(
                [
                    mode != "shutdown",
                    runtime.current().config.ENABLE_TORRENTS is True,
                    any(
                        [
                            runtime.current().config.AUTO_SNATCH is True,
                            runtime.current().config.LOCAL_TORRENT_PP is True,
                        ]
                    ),
                    runtime.current().os_detect != "Windows",
                ]
            ) and torrent_monitor.is_monitorable_downloader(runtime.current().config.TORRENT_DOWNLOADER):
                return
            shutdown(get_pool("sn_pool"), queues.snatched_queue, "auto-snatch")

        if (queuetype == "search_queue") or mode == "shutdown":
            shutdown(get_pool("search_pool"), queues.search_queue, "search queue")

        if (queuetype == "pp_queue") or mode == "shutdown":
            if all([runtime.current().config.POST_PROCESSING is True, mode != "shutdown"]):
                return
            shutdown(get_pool("pp_pool"), queues.pp_queue, "post-processing queue")

        if (queuetype == "ddl_queue") or mode == "shutdown":
            if all([runtime.current().config.ENABLE_DDL is True, mode != "shutdown"]):
                return
            shutdown(get_pool("ddl_pool"), queues.ddl_queue, "DDL download queue")


def halt():
    """Idempotent shutdown signalling ONLY (U7).

    The clean ordered drain (scheduler stop -> queue 'exit' -> bounded
    worker join -> journal flush -> engine.dispose()) is owned by the
    FastAPI lifespan, which has already run by the time control returns to
    Comicarr.py and reaches here. halt() therefore does NO queue shutdown
    and NO DB work — it only flips _INITIALIZED idempotently. It must never
    block (a worker wedged in native code cannot hang termination because
    the only remaining step is the non-blocking terminal branch in
    shutdown()).
    """
    global _INITIALIZED

    with runtime.current().init_lock:
        if _INITIALIZED:
            logger.info("[SHUTDOWN] halt() — schedulers/workers already drained by the lifespan")
            _INITIALIZED = False


def shutdown(restart=False, update=False, maintenance=False):

    if maintenance is False:
        halt()

    if not restart and not update:
        logger.info("Comicarr is shutting down...")
    if update:
        logger.info("Comicarr is updating...")
        try:
            versioncheck.update()
        except Exception as e:
            logger.warn("Comicarr failed to update: %s. Restarting." % e)

    if runtime.current().createpid:
        logger.info("Removing pidfile %s" % runtime.current().pidfile)
        os.remove(runtime.current().pidfile)

    if restart:
        logger.info("Comicarr is restarting...")
        popen_list = [sys.executable, runtime.current().full_path]
        if "maintenance" not in runtime.current().args:
            popen_list += runtime.current().args
        else:
            plist = []
            for x in runtime.current().args:
                if x != "maintenance":
                    plist.append(x)
                else:
                    break
            popen_list.extend(plist)
        logger.info("Restarting Comicarr with " + str(popen_list))
        try:
            os.execv(sys.executable, popen_list)
        except Exception as e:
            logger.error("[SHUTDOWN] os.execv failed: %s — hard-exiting" % e)

    os._exit(0)
