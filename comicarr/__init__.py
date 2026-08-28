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
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MAX_INSTANCES, EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError

import comicarr.config
from comicarr import (
    helpers,
    logger,
    maintenance,
    postprocessor,
    rsscheckit,
    sabnzbd,
    searchit,
    updater,
    versioncheckit,
    weeklypullit,
)
from comicarr.app.search.queue import FairSearchQueue


class ThreadSafeLock:
    """
    Thread-safe lock that provides boolean-like interface for backwards
    compatibility while using proper threading primitives.

    Usage:
        lock = ThreadSafeLock()
        if lock:  # or lock == True or lock.locked()
            print("locked")
        lock.acquire()  # instead of lock = True
        lock.release()  # instead of lock = False
    """

    def __init__(self):
        self._lock = threading.Lock()

    def __bool__(self):
        """Allow `if lock:` syntax."""
        return self._lock.locked()

    def __eq__(self, other):
        """Allow `lock == True` or `lock is True` style comparisons."""
        if isinstance(other, bool):
            return self._lock.locked() == other
        return NotImplemented

    def acquire(self, blocking=True, timeout=-1):
        """Acquire the lock (equivalent to setting to True)."""
        return self._lock.acquire(blocking=blocking, timeout=timeout)

    def release(self):
        """
        Release the lock (equivalent to setting to False).
        Safe to call even if not locked.
        """
        try:
            self._lock.release()
        except RuntimeError:
            pass

    def locked(self):
        """Check if the lock is currently held."""
        return self._lock.locked()

    def __enter__(self):
        """Support context manager usage."""
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Support context manager usage."""
        self._lock.release()
        return False


MINIMUM_PY_VERSION = "3.8.1"
PROG_DIR = None
DATA_DIR = None
FULL_PATH = None
MAINTENANCE = False
ACQUISITION_SCHEMA_READY = False
ACQUISITION_SCHEMA_VERSION = 0
ACQUISITION_SCHEMA_ERROR = "acquisition schema has not been verified"
ACQUISITION_WORKERS_BLOCKED = True
ACQUISITION_BLOCK_REASON = "schema_unavailable"
LOG_DIR = None
LOGTYPE = "log"
LOG_LEVEL = None
LOGLIST = []
ARGS = None
SIGNAL = None
SYS_ENCODING = None
OS_DETECT = platform.system()
USER_AGENT = None
DAEMON = False
PIDFILE = None
CREATEPID = False
MAX_LOGSIZE = 5000000
SAFESTART = False
NOWEEKLY = False
INIT_LOCK = threading.Lock()
ACQUISITION_RESUME_LOCK = threading.Lock()
IMPORTLOCK = False
IMPORTBUTTON = False
DONATEBUTTON = False
IMPORT_STATUS = None
IMPORT_FILES = 0
IMPORT_TOTALFILES = 0
IMPORT_CID_COUNT = 0
IMPORT_PARSED_COUNT = 0
IMPORT_FAILURE_COUNT = 0
CHECKENABLED = False
_INITIALIZED = False
started = False
MONITOR_STATUS = "Waiting"
IMPORTINBOX_STATUS = "Waiting"
SEARCH_STATUS = "Waiting"
RSS_STATUS = "Waiting"
WEEKLY_STATUS = "Waiting"
WEEKLY_MANUAL_NEXT_RUN = None
VERSION_STATUS = "Waiting"
UPDATER_STATUS = "Waiting"
MANGA_SYNC_STATUS = "Waiting"
FORCE_STATUS = {}
RSS_SCHEDULER = None
WEEKLY_SCHEDULER = None
MONITOR_SCHEDULER = None
IMPORTINBOX_SCHEDULER = None
SEARCH_SCHEDULER = None
VERSION_SCHEDULER = None
UPDATER_SCHEDULER = None
MANGA_SYNC_SCHEDULER = None
SCHED_RSS_LAST = None
SCHED_WEEKLY_LAST = None
SCHED_MONITOR_LAST = None
SCHED_SEARCH_LAST = None
SCHED_VERSION_LAST = None
SCHED_DBUPDATE_LAST = None
SCHED_MANGA_SYNC_LAST = None
DB_BACKFILL = False
DBLOCK = False
DB_FILE = None
MAINTENANCE_UPDATE = []
MAINTENANCE_DB_TOTAL = 0
MAINTENANCE_DB_COUNT = 0
DB_EMPTY = False
MIGRATION_IN_PROGRESS = False
MIGRATION_STATUS = "idle"
MIGRATION_CURRENT_TABLE = ""
MIGRATION_TABLES_COMPLETE = 0
MIGRATION_TABLES_TOTAL = 0
MIGRATION_ERROR = None
MIGRATION_RECONCILIATION = None
UMASK = None
WANTED_TAB_OFF = False
PULLNEW = None
CONFIG = None
CONFIG_FILE = None
CV_HEADERS = None
CV_SESSION = None
CV_RATE_LIMITER = None
CV_CACHE = None
METRON_API = None
AI_CLIENT = None
AI_ASYNC_CLIENT = None
AI_CIRCUIT_BREAKER = None
AI_RATE_LIMITER = None
CV_TIMEOUT = 30
CVURL = None
EXPURL = None
DEMURL = None
WWTURL = None
WWT_CF_COOKIEVALUE = None
PROVIDER_BLOCKLIST = []
KEYS_32P = None
AUTHKEY_32P = None
FEED_32P = None
FEEDINFO_32P = None
INKDROPS_32P = None
USE_SABNZBD = False
USE_NZBGET = False
USE_BLACKHOLE = False
USE_RTORRENT = False
USE_DELUGE = False
USE_TRANSMISSION = False
USE_QBITTORRENT = False
USE_UTORRENT = False
USE_WATCHDIR = False
SNPOOL = None
NZBPOOL = None
SEARCHPOOL = None
PPPOOL = None
DDLPOOL = None
SNATCHED_QUEUE = queue.Queue()
NZB_QUEUE = queue.Queue()
PP_QUEUE = queue.Queue()
SEARCH_QUEUE = FairSearchQueue()
DDL_QUEUE = queue.Queue()
RETURN_THE_NZBQUEUE = queue.Queue()
MASS_ADD = None
ADD_LIST = queue.Queue()
ISSUE_WATCH_LIST = queue.Queue()
MASS_REFRESH = None
REFRESH_QUEUE = queue.Queue()
DDL_QUEUED = set()
DDL_STUCK_NOTIFIED = set()
DDL_HEALTH_SCHEDULER = None
PACK_ISSUEIDS_DONT_QUEUE = {}
EXT_SERVER = False
SEARCH_TIER_DATE = None
COMICSORT = None
PULLBYFILE = False
CFG = None
PUBLISHER_IMPRINTS = None
CURRENT_WEEKNUMBER = None
CURRENT_YEAR = None
INSTALL_TYPE = None
CURRENT_BRANCH = None
CURRENT_VERSION = None
CURRENT_VERSION_NAME = None
CURRENT_RELEASE_NAME = None
LATEST_VERSION = None
UPDATE_STATE = None
UPDATE_REASON = None
APILOCK = ThreadSafeLock()
SEARCHLOCK = ThreadSafeLock()
DDL_LOCK = ThreadSafeLock()
CMTAGGER_PATH = None
STATIC_COMICRN_VERSION = "1.01"
STATIC_APC_VERSION = "2.04"
ISSUE_EXCEPTIONS = [
    "DEATHS",
    "ALPHA",
    "OMEGA",
    "BLACK",
    "DARK",
    "LIGHT",
    "AU",
    "AI",
    "INH",
    "NOW",
    "BEY",
    "MU",
    "HU",
    "LR",
    "A",
    "B",
    "C",
    "X",
    "O",
    "WHITE",
    "SUMMER",
    "SPRING",
    "FALL",
    "WINTER",
    "PREVIEW",
    "DIRECTOR'S CUT",
    "(DC)",
]
SAB_PARAMS = None
PROVIDER_START_ID = 0
COMICINFO = ()
CHECK_FOLDER_CACHE = None
FOLDER_CACHE = None
SSE_KEY = None
SESSION_ID = None
SETUP_TOKEN = None
START_UP = True
UPDATE_VALUE = {}
REQS = {}
GC_URL = "https://getcomics.org"
IMPRINT_MAPPING = {
    "Homage Comics": "Homage",
    "Max Comics": "MAX",
    "Mailbu": "Malibu Comics",
    "Milestone": "Milestone Comics",
    "Skybound": "Skybound Entertainment",
    "Top Cow": "Top Cow Productions",
}
SCHED = BackgroundScheduler(
    {
        "apscheduler.executors.default": {
            "class": "apscheduler.executors.pool:ThreadPoolExecutor",
            "max_workers": "20",
        },
        "apscheduler.job_defaults.coalesce": "true",
        "apscheduler.job_defaults.max_instances": "3",
        "apscheduler.timezone": "UTC",
    }
)


def _persist_scheduler_health_event(event):
    """Late import avoids a package-initialization cycle while keeping every event durable."""
    from comicarr.app.system.service import persist_scheduler_event

    return persist_scheduler_event(event)


SCHED.add_listener(
    _persist_scheduler_health_event,
    EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED | EVENT_JOB_MAX_INSTANCES,
)
BACKENDSTATUS_WS = "up"
BACKENDSTATUS_CV = "up"
PROVIDER_STATUS = {}


def _add_recurring_job(**kwargs):
    return SCHED.add_job(max_instances=1, coalesce=True, **kwargs)


def initialize(config_file):
    with INIT_LOCK:
        global \
            CONFIG, \
            _INITIALIZED, \
            CONFIG_FILE, \
            MINIMUM_PY_VERSION, \
            OS_DETECT, \
            MAINTENANCE, \
            CURRENT_VERSION, \
            LATEST_VERSION, \
            UPDATE_STATE, \
            UPDATE_REASON, \
            INSTALL_TYPE, \
            IMPORTLOCK, \
            PULLBYFILE, \
            INKDROPS_32P, \
            DONATEBUTTON, \
            CURRENT_WEEKNUMBER, \
            CURRENT_YEAR, \
            UMASK, \
            USER_AGENT, \
            SNATCHED_QUEUE, \
            NZB_QUEUE, \
            PP_QUEUE, \
            SEARCH_QUEUE, \
            DDL_QUEUE, \
            PULLNEW, \
            COMICSORT, \
            WANTED_TAB_OFF, \
            CV_HEADERS, \
            IMPORTBUTTON, \
            IMPORT_FILES, \
            IMPORT_TOTALFILES, \
            IMPORT_CID_COUNT, \
            IMPORT_PARSED_COUNT, \
            IMPORT_FAILURE_COUNT, \
            CHECKENABLED, \
            CVURL, \
            DEMURL, \
            EXPURL, \
            WWTURL, \
            WWT_CF_COOKIEVALUE, \
            DDLPOOL, \
            NZBPOOL, \
            SNPOOL, \
            PPPOOL, \
            SEARCHPOOL, \
            RETURN_THE_NZBQUEUE, \
            MASS_ADD, \
            ADD_LIST, \
            MASS_REFRESH, \
            REFRESH_QUEUE, \
            SSE_KEY, \
            USE_SABNZBD, \
            USE_NZBGET, \
            USE_BLACKHOLE, \
            USE_RTORRENT, \
            USE_UTORRENT, \
            USE_QBITTORRENT, \
            USE_DELUGE, \
            USE_TRANSMISSION, \
            USE_WATCHDIR, \
            SAB_PARAMS, \
            PUBLISHER_IMPRINTS, \
            PROG_DIR, \
            DATA_DIR, \
            CMTAGGER_PATH, \
            STATIC_COMICRN_VERSION, \
            STATIC_APC_VERSION, \
            KEYS_32P, \
            AUTHKEY_32P, \
            FEED_32P, \
            FEEDINFO_32P, \
            MONITOR_STATUS, \
            IMPORTINBOX_STATUS, \
            SEARCH_STATUS, \
            RSS_STATUS, \
            WEEKLY_STATUS, \
            VERSION_STATUS, \
            UPDATER_STATUS, \
            MANGA_SYNC_STATUS, \
            FORCE_STATUS, \
            DB_BACKFILL, \
            APILOCK, \
            SEARCHLOCK, \
            DDL_LOCK, \
            LOG_LEVEL, \
            MONITOR_SCHEDULER, \
            SEARCH_SCHEDULER, \
            RSS_SCHEDULER, \
            WEEKLY_SCHEDULER, \
            VERSION_SCHEDULER, \
            UPDATER_SCHEDULER, \
            MANGA_SYNC_SCHEDULER, \
            START_UP, \
            SCHED_RSS_LAST, \
            SCHED_WEEKLY_LAST, \
            SCHED_MONITOR_LAST, \
            SCHED_SEARCH_LAST, \
            SCHED_VERSION_LAST, \
            SCHED_DBUPDATE_LAST, \
            SCHED_MANGA_SYNC_LAST, \
            COMICINFO, \
            SEARCH_TIER_DATE, \
            BACKENDSTATUS_CV, \
            BACKENDSTATUS_WS, \
            PROVIDER_STATUS, \
            ISSUE_EXCEPTIONS, \
            PROVIDER_START_ID, \
            CHECK_FOLDER_CACHE, \
            FOLDER_CACHE, \
            SESSION_ID, \
            MAINTENANCE_UPDATE, \
            MAINTENANCE_DB_COUNT, \
            MAINTENANCE_DB_TOTAL, \
            UPDATE_VALUE, \
            REQS, \
            IMPRINT_MAPPING, \
            GC_URL, \
            PACK_ISSUEIDS_DONT_QUEUE, \
            DDL_QUEUED, \
            DDL_STUCK_NOTIFIED, \
            DDL_HEALTH_SCHEDULER, \
            EXT_SERVER

        cc = comicarr.config.Config(config_file)
        CONFIG = cc.read(startup=True)

        assert CONFIG is not None

        if _INITIALIZED:
            return False

        logger.info("Checking to see if the database has all tables....")
        try:
            dbcheck()
        except Exception as e:
            diagnostic_error = _redact_diagnostic_error(e)
            comicarr.ACQUISITION_SCHEMA_READY = False
            comicarr.ACQUISITION_SCHEMA_ERROR = diagnostic_error
            comicarr.ACQUISITION_WORKERS_BLOCKED = True
            comicarr.ACQUISITION_BLOCK_REASON = "schema_migration_failed"
            logger.error("[SCHEMA-MIGRATION] Worker startup blocked after migration failure: %s" % diagnostic_error)
        else:
            try:
                with sql_db() as conn:
                    row = conn.execute(text("SELECT COUNT(*) FROM comics")).first()
                    comic_count = row[0] if row else 0
                    if comic_count > 0:
                        if comicarr.CONFIG.BACKUP_ON_START:
                            backup_dir = os.path.join(comicarr.DATA_DIR, "backups")
                            retention = comicarr.CONFIG.BACKUP_RETENTION if comicarr.CONFIG.BACKUP_RETENTION else 4
                            maintenance.auto_backup_db(comicarr.DB_FILE, backup_dir, retention)
                    else:
                        comicarr.DB_EMPTY = True
            except Exception as e:
                logger.warn("[STARTUP] Startup diagnostics skipped: %s" % e)

            if comicarr.MAINTENANCE is False:
                cc.provider_sequence()

            chk = maintenance.Maintenance(mode="db update")
            chk.check_failed_update()

            chk.db_update_check()

        try:
            from comicarr.app.acquisition.maintenance import refresh_runtime_state

            refresh_runtime_state(comicarr.CONFIG)
        except Exception as e:
            comicarr.ACQUISITION_WORKERS_BLOCKED = True
            comicarr.ACQUISITION_BLOCK_REASON = "maintenance_gate_unavailable"
            logger.error("[ACQUISITION] Maintenance gate unavailable; workers remain blocked: %s" % e)

        if comicarr.MAINTENANCE_UPDATE:
            comicarr.MAINTENANCE = True

        if MAINTENANCE is False:
            comicarr.config.ddl_creations()

            if LOGTYPE == "clog":
                logprog = "Concurrent Rotational Log Handler"
            else:
                logprog = "Rotational Log Handler (default)"

            logger.fdebug("Logger set to use : " + logprog)
            if LOGTYPE == "log" and OS_DETECT == "Windows":
                logger.fdebug(
                    "ConcurrentLogHandler package not installed. Using builtin log handler for Rotational logs (default)"
                )
                logger.fdebug(
                    "[Windows Users] If you are experiencing log file locking and want this auto-enabled, you need to install Python Extensions for Windows ( http://sourceforge.net/projects/pywin32/ )"
                )

            if CONFIG.SYNO_FIX:
                parsepath = os.path.join(DATA_DIR, "bs4", "builder", "_lxml.py")
                if os.path.isfile(parsepath):
                    print("found bs4...renaming appropriate file.")
                    src = os.path.join(parsepath)
                    dst = os.path.join(DATA_DIR, "bs4", "builder", "lxml.py")
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

            if comicarr.SSE_KEY is None:
                import secrets

                comicarr.SSE_KEY = secrets.token_hex(16)

            if not comicarr.CONFIG.API_KEY or len(comicarr.CONFIG.API_KEY) != 32:
                import secrets

                comicarr.CONFIG.API_KEY = secrets.token_hex(16)
                comicarr.CONFIG.API_ENABLED = True
                comicarr.CONFIG.WRITE_THE_CONFIG = True
                logger.info("[STARTUP] API key was not set - auto-generated a new API key")

            from comicarr.downloaders import external_server as des

            EXT_SERVER = des.EXT_SERVER
            logger.info("[DDL] External server configuration available to be loaded: %s" % EXT_SERVER)

        import secrets

        SESSION_ID = secrets.randbelow(990000) + 10000

        CV_HEADERS = {"User-Agent": comicarr.CONFIG.CV_USER_AGENT}

        def initialize_cv_session():
            """Initialize ComicVine API session with connection pooling"""
            global CV_SESSION, CV_RATE_LIMITER, CV_CACHE
            if CV_SESSION is None:
                CV_SESSION = requests.Session()
                CV_SESSION.headers.update(CV_HEADERS)
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=10, pool_maxsize=20, max_retries=3, pool_block=False
                )
                CV_SESSION.mount("https://", adapter)
                CV_SESSION.mount("http://", adapter)
                logger.info("ComicVine API session initialized with connection pooling")

            if CV_RATE_LIMITER is None:
                from comicarr import rate_limiter

                cvapi_rate = (
                    comicarr.CONFIG.CVAPI_RATE if comicarr.CONFIG.CVAPI_RATE and comicarr.CONFIG.CVAPI_RATE >= 2 else 2
                )
                CV_RATE_LIMITER = rate_limiter.ComicVineRateLimiter(calls_per_second=1.0 / cvapi_rate)
                logger.info("ComicVine rate limiter initialized with %s second interval" % cvapi_rate)

            if CV_CACHE is None:
                from comicarr import cv_cache

                cache_db_path = os.path.join(comicarr.DATA_DIR, "cv_cache.db")
                CV_CACHE = cv_cache.CVCache(cache_db_path)
                logger.info("ComicVine cache initialized at: %s" % cache_db_path)

        initialize_cv_session()

        def initialize_metron_session():
            """Initialize Metron API session using mokkari"""
            global METRON_API
            if METRON_API is None and CONFIG.USE_METRON_SEARCH:
                if CONFIG.METRON_USERNAME and CONFIG.METRON_PASSWORD:
                    try:
                        from comicarr import metron

                        METRON_API = metron.initialize_metron_api()
                        if METRON_API:
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
        CURRENT_WEEKNUMBER = todaydate.strftime("%U")
        CURRENT_YEAR = todaydate.strftime("%Y")

        if SEARCH_TIER_DATE is None:
            STD = todaydate - timedelta(days=comicarr.CONFIG.SEARCH_TIER_CUTOFF)
            SEARCH_TIER_DATE = STD.strftime("%Y-%m-%d")
            logger.fdebug("SEARCH_TIER_DATE set to : %s" % SEARCH_TIER_DATE)

        CVURL = "https://comicvine.gamespot.com/api/"

        WWTURL = "https://worldwidetorrents.to/"
        DEMURL = "https://www.demonoid.pw/"

        EXPURL = "https://nzbindex.nl/"

        try:
            pub_path = os.path.join(comicarr.CONFIG.CACHE_DIR, "imprints.json")
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
                        PUBLISHER_IMPRINTS = json.load(json_file)
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
                    PUBLISHER_IMPRINTS = json_pub

        except requests.exceptions.RequestException as e:
            logger.warn("[IMPRINT_LOADS] Unable to retrieve publisher imprints listing at this time. Error: %s" % e)
            PUBLISHER_IMPRINTS = None
        except Exception as e:
            logger.warn("[IMPRINT_LOADS] Unable to load publisher -> imprint file. Error: %s" % e)
            PUBLISHER_IMPRINTS = None
        else:
            if PUBLISHER_IMPRINTS is not None:
                logger.info(
                    "[IMPRINT_LOADS] Successfully loaded imprints for %s publishers"
                    % (len(PUBLISHER_IMPRINTS["publishers"]))
                )

            logger.info("Remapping the sorting to allow for new additions.")
            COMICSORT = helpers.ComicSort(sequence="startup")

        if CONFIG.LOCMOVE:
            helpers.updateComicLocation()

        if all([comicarr.USE_SABNZBD is True, comicarr.CONFIG.SAB_HOST is not None]):
            s_to_the_ab = sabnzbd.SABnzbd(params=None)
            s_to_the_ab.sab_versioncheck()
            logger.info("[SAB-VERSION-CHECK] SABnzbd version detected as: %s" % comicarr.CONFIG.SAB_VERSION)

        UMASK = os.umask(0)
        os.umask(UMASK)

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
    if CREATEPID:
        logger.info("Writing PID %d to %s", pid, PIDFILE)
        with open(PIDFILE, "w") as fp:
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
    from comicarr import importer as importer_module
    from comicarr.app.search.commands import replay_search_obligations

    search_queue = ctx.search_queue if ctx is not None else SEARCH_QUEUE
    search_count = replay_search_obligations(work_queue=search_queue)
    refresh_count = importer_module.replay_refresh_obligations(start_worker=True)
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
    from comicarr.torrent import monitor as torrent_monitor

    ctx = get_runtime_if_initialized()
    config = config or (ctx.config if ctx is not None else CONFIG)

    def schedule(queue_name):
        if ctx is not None:
            queue_schedule(queue_name, "start", ctx=ctx)
        else:
            queue_schedule(queue_name, "start")

    with ACQUISITION_RESUME_LOCK:
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
                OS_DETECT != "Windows",
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
            "dbupdater": UPDATER_STATUS,
            "search": SEARCH_STATUS,
            "weekly": WEEKLY_STATUS,
            "rss": RSS_STATUS,
            "monitor": MONITOR_STATUS,
            "importinbox": IMPORTINBOX_STATUS,
            "manga_sync": MANGA_SYNC_STATUS,
        }
        scheduler = ctx.scheduler if ctx is not None else SCHED
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
    from comicarr.torrent import monitor as torrent_monitor

    if ctx is None or ctx.disposed:
        raise RuntimeNotInitializedError("Workers cannot start before an active runtime context exists")
    if (
        ctx.scheduler is not SCHED
        or ctx.search_queue is not SEARCH_QUEUE
        or ctx.ddl_queue is not DDL_QUEUE
        or ctx.ddl_lock is not DDL_LOCK
        or ctx.ddl_queued is not DDL_QUEUED
    ):
        raise RuntimeNotInitializedError(
            "Workers must start with the canonical runtime's shared scheduler, queues, locks, and DDL state"
        )

    global _INITIALIZED, started

    with INIT_LOCK:
        if _INITIALIZED:
            UPDATER_SCHEDULER = _add_recurring_job(
                func=updater.watchlist_updater,
                id="dbupdater",
                next_run_time=datetime.datetime.utcnow(),
                name="DB Updater",
                args=[None, True],
                trigger=IntervalTrigger(hours=0, minutes=CONFIG.DBUPDATE_INTERVAL, timezone="UTC"),
            )
            UPDATER_SCHEDULER.pause()

            ss = searchit.CurrentSearcher()
            SEARCH_SCHEDULER = _add_recurring_job(
                func=ss.run,
                id="search",
                next_run_time=datetime.datetime.utcnow(),
                name="Auto-Search",
                trigger=IntervalTrigger(hours=0, minutes=CONFIG.SEARCH_INTERVAL, timezone="UTC"),
            )
            SEARCH_SCHEDULER.pause()

            ws = weeklypullit.Weekly()
            WEEKLY_SCHEDULER = _add_recurring_job(
                func=ws.run,
                id="weekly",
                name="Weekly Pullist",
                next_run_time=datetime.datetime.utcnow(),
                trigger=IntervalTrigger(hours=4, minutes=0, timezone="UTC"),
            )
            WEEKLY_SCHEDULER.pause()

            rs = rsscheckit.tehMain()
            RSS_SCHEDULER = _add_recurring_job(
                func=rs.run,
                id="rss",
                name="RSS Feeds",
                args=[True],
                next_run_time=datetime.datetime.utcnow(),
                trigger=IntervalTrigger(hours=0, minutes=int(CONFIG.RSS_CHECKINTERVAL), timezone="UTC"),
            )
            RSS_SCHEDULER.pause()

            vs = versioncheckit.CheckVersion()
            VERSION_SCHEDULER = _add_recurring_job(
                func=vs.run,
                id="version",
                name="Check Version",
                trigger=IntervalTrigger(hours=0, minutes=CONFIG.CHECK_GITHUB_INTERVAL, timezone="UTC"),
            )
            VERSION_SCHEDULER.pause()

            fm = postprocessor.FolderCheck()
            MONITOR_SCHEDULER = _add_recurring_job(
                func=fm.run,
                id="monitor",
                name="Folder Monitor",
                trigger=IntervalTrigger(hours=0, minutes=int(CONFIG.DOWNLOAD_SCAN_INTERVAL), timezone="UTC"),
            )
            MONITOR_SCHEDULER.pause()

            from comicarr import importinbox

            IMPORTINBOX_SCHEDULER = _add_recurring_job(
                func=importinbox.run,
                id="importinbox",
                name="Import Inbox Scanner",
                trigger=IntervalTrigger(hours=0, minutes=int(CONFIG.IMPORT_SCAN_INTERVAL), timezone="UTC"),
            )
            IMPORTINBOX_SCHEDULER.pause()

            from comicarr.app.manga.sync import JOB_NAME as MANGA_SYNC_JOB_NAME
            from comicarr.app.manga.sync import run_manga_sync

            MANGA_SYNC_SCHEDULER = _add_recurring_job(
                func=run_manga_sync,
                id="manga_sync",
                name=MANGA_SYNC_JOB_NAME,
                next_run_time=datetime.datetime.utcnow(),
                trigger=IntervalTrigger(hours=0, minutes=int(CONFIG.DBUPDATE_INTERVAL), timezone="UTC"),
            )
            MANGA_SYNC_SCHEDULER.pause()

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

            try:
                from comicarr.app.acquisition.maintenance import refresh_runtime_state

                acquisition_gate = refresh_runtime_state(comicarr.CONFIG)
            except Exception as e:
                acquisition_gate = None
                set_runtime_acquisition_status(
                    workers_blocked=True,
                    block_reason="maintenance_gate_unavailable",
                )
                logger.error("[ACQUISITION] Refusing worker startup because gate refresh failed: %s" % e)

            if ctx.acquisition_workers_blocked:
                if VERSION_STATUS != "Paused":
                    VERSION_SCHEDULER.resume()
                logger.warn(
                    "[ACQUISITION] Background acquisition is blocked (%s); diagnostics remain available"
                    % (acquisition_gate.reason if acquisition_gate else ctx.acquisition_block_reason)
                )
                try:
                    SCHED.start()
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
                    SCHED.start()
                except Exception as scheduler_error:
                    logger.error("[ACQUISITION] Unable to start diagnostics scheduler: %s" % scheduler_error)
                set_runtime_field(ctx, "started", True)
                return

            monitors = helpers.job_management(startup=True)

            SCHED_WEEKLY_LAST = monitors["weekly"]["last"]
            SCHED_SEARCH_LAST = monitors["search"]["last"]
            SCHED_UPDATER_LAST = monitors["updater"]["last"]
            monitors["monitor"]["last"]
            monitors["version"]["last"]
            SCHED_RSS_LAST = monitors["rss"]["last"]
            SCHED_MANGA_SYNC_LAST = monitors.get("manga_sync", {}).get("last")

            if UPDATER_STATUS != "Paused":
                if SCHED_UPDATER_LAST is not None:
                    updater_timestamp = float(SCHED_UPDATER_LAST)
                    logger.fdebug(
                        "[DB UPDATER] Updater last run @ %s"
                        % helpers.utc_date_to_local(datetime.datetime.utcfromtimestamp(updater_timestamp))
                    )
                else:
                    updater_timestamp = helpers.utctimestamp() + (int(CONFIG.DBUPDATE_INTERVAL) * 60)

                updater_diff = (helpers.utctimestamp() - updater_timestamp) / 60
                if updater_diff >= int(CONFIG.DBUPDATE_INTERVAL):
                    logger.fdebug("[DB UPDATER] DB Updater scheduled to run immediately.")
                    UPDATER_SCHEDULER.modify(next_run_time=(datetime.datetime.utcnow()))
                else:
                    updater_diff = datetime.datetime.utcfromtimestamp(
                        helpers.utctimestamp() + ((int(CONFIG.DBUPDATE_INTERVAL) * 60) - (updater_diff * 60))
                    )
                    logger.fdebug(
                        "[DB UPDATER] Scheduling next run @ %s (every %s minutes)"
                        % (helpers.utc_date_to_local(updater_diff), CONFIG.DBUPDATE_INTERVAL)
                    )
                    UPDATER_SCHEDULER.modify(next_run_time=updater_diff)

            from comicarr.app.manga.sync import arm_manga_sync_job

            if MANGA_SYNC_STATUS != "Paused":
                arm_manga_sync_job(
                    MANGA_SYNC_SCHEDULER,
                    MANGA_SYNC_STATUS,
                    SCHED_MANGA_SYNC_LAST,
                    CONFIG.DBUPDATE_INTERVAL,
                )

            if SEARCH_STATUS != "Paused":
                if CONFIG.NZB_STARTUP_SEARCH:
                    SEARCH_SCHEDULER.modify(next_run_time=(datetime.datetime.utcnow() + timedelta(minutes=2)))
                else:
                    if SCHED_SEARCH_LAST is not None:
                        search_timestamp = float(SCHED_SEARCH_LAST)
                        logger.fdebug(
                            "[AUTO-SEARCH] Search last run @ %s"
                            % helpers.utc_date_to_local(datetime.datetime.utcfromtimestamp(search_timestamp))
                        )
                    else:
                        search_timestamp = helpers.utctimestamp() + (int(CONFIG.SEARCH_INTERVAL) * 60)

                    duration_diff = (helpers.utctimestamp() - search_timestamp) / 60
                    if duration_diff >= int(CONFIG.SEARCH_INTERVAL):
                        logger.fdebug(
                            "[AUTO-SEARCH]Auto-Search set to an initial delay of 2 minutes before initialization as it has been %s minutes since the last run"
                            % duration_diff
                        )
                        SEARCH_SCHEDULER.modify(next_run_time=(datetime.datetime.utcnow() + timedelta(minutes=2)))
                    else:
                        search_diff = datetime.datetime.utcfromtimestamp(
                            helpers.utctimestamp() + ((int(CONFIG.SEARCH_INTERVAL) * 60) - (duration_diff * 60))
                        )
                        logger.fdebug(
                            "[AUTO-SEARCH] Scheduling next run @ %s (every %s minutes)"
                            % (helpers.utc_date_to_local(search_diff), CONFIG.SEARCH_INTERVAL)
                        )
                        SEARCH_SCHEDULER.modify(next_run_time=search_diff)

            queue_schedule("search_queue", "start", ctx=ctx)

            if all(
                [
                    CONFIG.ENABLE_TORRENTS,
                    any([CONFIG.AUTO_SNATCH, CONFIG.LOCAL_TORRENT_PP]),
                    OS_DETECT != "Windows",
                ]
            ) and torrent_monitor.is_monitorable_downloader(CONFIG.TORRENT_DOWNLOADER):
                queue_schedule("snatched_queue", "start", ctx=ctx)

            if CONFIG.POST_PROCESSING is True and (
                all([CONFIG.NZB_DOWNLOADER == 0, CONFIG.SAB_CLIENT_POST_PROCESSING is True])
                or all([CONFIG.NZB_DOWNLOADER == 1, CONFIG.NZBGET_CLIENT_POST_PROCESSING is True])
            ):
                queue_schedule("nzb_queue", "start", ctx=ctx)

            if CONFIG.POST_PROCESSING is True:
                queue_schedule("pp_queue", "start", ctx=ctx)

            if CONFIG.ENABLE_DDL is True:
                queue_schedule("ddl_queue", "start", ctx=ctx)
                if CONFIG.DDL_STUCK_NOTIFY is True:
                    _add_recurring_job(
                        func=helpers.ddl_health_check,
                        id="ddl_health",
                        name="DDL Health Check",
                        trigger=IntervalTrigger(hours=0, minutes=int(CONFIG.DDL_STUCK_CHECK_INTERVAL), timezone="UTC"),
                    )
                    logger.info(
                        "[DDL-HEALTH] DDL health check enabled, running every %s minutes"
                        % CONFIG.DDL_STUCK_CHECK_INTERVAL
                    )

            helpers.latestdate_fix()

            if CONFIG.ALT_PULL == 2:
                weektimer = 4
            else:
                weektimer = 24

            logger.info("[WEEKLY] Checking for existance of Weekly Comic listing...")

            weekly_interval = weektimer * 60 * 60
            try:
                if SCHED_WEEKLY_LAST:
                    pass
            except:
                SCHED_WEEKLY_LAST = None

            weektimestamp = helpers.utctimestamp()
            if SCHED_WEEKLY_LAST is not None:
                weekly_timestamp = float(SCHED_WEEKLY_LAST)
            else:
                weekly_timestamp = weektimestamp + weekly_interval

            duration_diff = (weektimestamp - weekly_timestamp) / 60

            if WEEKLY_STATUS != "Paused":
                if abs(duration_diff) >= weekly_interval / 60:
                    logger.info(
                        "[WEEKLY] Weekly Pull-Update initializing immediately as it has been %s hours since the last run"
                        % abs(duration_diff / 60)
                    )
                    WEEKLY_SCHEDULER.modify(next_run_time=datetime.datetime.utcnow())
                else:
                    weekly_diff = datetime.datetime.utcfromtimestamp(
                        weektimestamp + (weekly_interval - (duration_diff * 60))
                    )
                    logger.fdebug(
                        "[WEEKLY] Scheduling next run for @ %s every %s hours"
                        % (helpers.utc_date_to_local(weekly_diff), weektimer)
                    )
                    WEEKLY_SCHEDULER.modify(next_run_time=weekly_diff)

            if RSS_STATUS != "Paused":
                logger.info("[RSS-FEEDS] Initiating startup-RSS feed checks.")
                if SCHED_RSS_LAST is not None:
                    rss_timestamp = float(SCHED_RSS_LAST)
                    logger.info(
                        "[RSS-FEEDS] RSS last run @ %s"
                        % helpers.utc_date_to_local(datetime.datetime.utcfromtimestamp(rss_timestamp))
                    )
                else:
                    rss_timestamp = helpers.utctimestamp() + (int(CONFIG.RSS_CHECKINTERVAL) * 60)
                duration_diff = (helpers.utctimestamp() - rss_timestamp) / 60
                if duration_diff >= int(CONFIG.RSS_CHECKINTERVAL):
                    RSS_SCHEDULER.modify(next_run_time=datetime.datetime.utcnow())
                else:
                    rss_diff = datetime.datetime.utcfromtimestamp(
                        helpers.utctimestamp() + (int(CONFIG.RSS_CHECKINTERVAL) * 60) - (duration_diff * 60)
                    )
                    logger.fdebug(
                        "[RSS-FEEDS] Scheduling next run for @ %s every %s minutes"
                        % (helpers.utc_date_to_local(rss_diff), CONFIG.RSS_CHECKINTERVAL)
                    )
                    RSS_SCHEDULER.modify(next_run_time=rss_diff)

            if IMPORTINBOX_STATUS != "Paused":
                if CONFIG.IMPORT_DIR is not None:
                    if CONFIG.IMPORT_SCAN_INTERVAL > 0:
                        logger.info(
                            "[IMPORT-INBOX] Enabling import inbox scanner for: "
                            + str(CONFIG.IMPORT_DIR)
                            + " every "
                            + str(CONFIG.IMPORT_SCAN_INTERVAL)
                            + " minutes."
                        )
                        IMPORTINBOX_SCHEDULER.resume()
                    else:
                        logger.info("[IMPORT-INBOX] Import scan interval set to 0, disabling scheduled scanning")
                        IMPORTINBOX_SCHEDULER.pause()
                else:
                    logger.fdebug("[IMPORT-INBOX] No IMPORT_DIR configured, disabling scheduled scanning")
                    IMPORTINBOX_SCHEDULER.pause()

            if VERSION_STATUS != "Paused":
                VERSION_SCHEDULER.resume()

            if MONITOR_STATUS != "Paused":
                if CONFIG.CHECK_FOLDER is not None:
                    if CONFIG.DOWNLOAD_SCAN_INTERVAL > 0:
                        logger.info(
                            "[FOLDER MONITOR] Enabling folder monitor for : "
                            + str(CONFIG.CHECK_FOLDER)
                            + " every "
                            + str(CONFIG.DOWNLOAD_SCAN_INTERVAL)
                            + " minutes."
                        )
                        MONITOR_SCHEDULER.resume()
                    else:
                        logger.error(
                            "[FOLDER MONITOR] You need to specify a monitoring time for the check folder option to work"
                        )
                        MONITOR_SCHEDULER.pause()
                else:
                    logger.error(
                        "[FOLDER MONITOR] You need to specify a location in order to use the Folder Monitor. Disabling Folder Monitor"
                    )
                    MONITOR_SCHEDULER.pause()

            logger.info("Firing up the Background Schedulers now....")

            try:
                SCHED.start()
                logger.info("Background Schedulers successfully started...")
                helpers.job_management(write=True)
            except Exception as e:
                logger.info(e)
                SCHED.print_jobs()

        set_runtime_field(ctx, "started", True)


def queue_schedule(queuetype, mode, ctx=None):
    """Start/stop legacy workers while preserving canonical pool identity."""
    from comicarr.app.core.runtime import POOL_CONTEXT_FIELDS, get_runtime_if_initialized, set_runtime_field
    from comicarr.torrent import monitor as torrent_monitor

    ctx = ctx or get_runtime_if_initialized()

    def get_pool(pool_attr):
        if ctx is not None:
            return getattr(ctx, POOL_CONTEXT_FIELDS[pool_attr])
        return getattr(comicarr, pool_attr)

    def set_pool(pool_attr, pool):
        if ctx is not None:
            set_runtime_field(ctx, POOL_CONTEXT_FIELDS[pool_attr], pool)
        else:
            setattr(comicarr, pool_attr, pool)

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
                "SNPOOL",
                helpers.worker_main,
                SNATCHED_QUEUE,
                "AUTO-SNATCHER",
                "Auto-Snatch of completed torrents enabled & attempting to background load....",
                "Succesfully started Auto-Snatch add-on - will now monitor for completed torrents on client....",
            )
        elif queuetype == "nzb_queue":
            try:
                if get_pool("NZBPOOL").is_alive() is True:
                    return
            except Exception:
                pass

            if CONFIG.NZB_DOWNLOADER == 0:
                logger.info(
                    "[SAB-MONITOR] Completed post-processing handling enabled for SABnzbd. Attempting to background load...."
                )
            elif CONFIG.NZB_DOWNLOADER == 1:
                logger.info(
                    "[NZBGET-MONITOR] Completed post-processing handling enabled for NZBGet. Attempting to background load...."
                )
            pool = threading.Thread(target=helpers.nzb_monitor, args=(NZB_QUEUE,), name="AUTO-COMPLETE-NZB")
            set_pool("NZBPOOL", pool)
            pool.start()
            if CONFIG.NZB_DOWNLOADER == 0:
                logger.info(
                    "[AUTO-COMPLETE-NZB] Succesfully started Completed post-processing handling for SABnzbd - will now monitor for completed nzbs within sabnzbd and post-process automatically..."
                )
            elif CONFIG.NZB_DOWNLOADER == 1:
                logger.info(
                    "[AUTO-COMPLETE-NZB] Succesfully started Completed post-processing handling for NZBGet - will now monitor for completed nzbs within nzbget and post-process automatically..."
                )

        elif queuetype == "search_queue":
            start(
                "SEARCHPOOL",
                helpers.search_queue,
                SEARCH_QUEUE,
                "SEARCH-QUEUE",
                "Attempting to background load the search queue....",
                "Successfully started the Search Queuer...",
            )
        elif queuetype == "pp_queue":
            start(
                "PPPOOL",
                helpers.postprocess_main,
                PP_QUEUE,
                "POST-PROCESS-QUEUE",
                "Post Process queue enabled & monitoring for api requests....",
                "Succesfully started Post-Processing Queuer....",
            )
        elif queuetype == "ddl_queue":
            try:
                if get_pool("DDLPOOL").is_alive() is True:
                    return
            except Exception:
                pass
            helpers.recover_queued_ddl_commands(DDL_QUEUE)
            start(
                "DDLPOOL",
                helpers.ddl_downloader,
                DDL_QUEUE,
                "DDL-QUEUE",
                "DDL Download queue enabled & monitoring for requests....",
                "Succesfully started DDL Download Queuer....",
            )
    else:
        if (queuetype == "nzb_queue") or mode == "shutdown":
            if all([mode != "shutdown", comicarr.CONFIG.POST_PROCESSING is True]) and (
                all([comicarr.CONFIG.NZB_DOWNLOADER == 0, comicarr.CONFIG.SAB_CLIENT_POST_PROCESSING is True])
                or all([comicarr.CONFIG.NZB_DOWNLOADER == 1, comicarr.CONFIG.NZBGET_CLIENT_POST_PROCESSING is True])
            ):
                return
            shutdown(get_pool("NZBPOOL"), comicarr.NZB_QUEUE, "NZB auto-complete queue")

        if (queuetype == "snatched_queue") or mode == "shutdown":
            if all(
                [
                    mode != "shutdown",
                    comicarr.CONFIG.ENABLE_TORRENTS is True,
                    any([comicarr.CONFIG.AUTO_SNATCH is True, comicarr.CONFIG.LOCAL_TORRENT_PP is True]),
                    OS_DETECT != "Windows",
                ]
            ) and torrent_monitor.is_monitorable_downloader(comicarr.CONFIG.TORRENT_DOWNLOADER):
                return
            shutdown(get_pool("SNPOOL"), comicarr.SNATCHED_QUEUE, "auto-snatch")

        if (queuetype == "search_queue") or mode == "shutdown":
            shutdown(get_pool("SEARCHPOOL"), comicarr.SEARCH_QUEUE, "search queue")

        if (queuetype == "pp_queue") or mode == "shutdown":
            if all([comicarr.CONFIG.POST_PROCESSING is True, mode != "shutdown"]):
                return
            shutdown(get_pool("PPPOOL"), comicarr.PP_QUEUE, "post-processing queue")

        if (queuetype == "ddl_queue") or mode == "shutdown":
            if all([comicarr.CONFIG.ENABLE_DDL is True, mode != "shutdown"]):
                return
            shutdown(get_pool("DDLPOOL"), comicarr.DDL_QUEUE, "DDL download queue")


def sql_db():
    """Return a SQLAlchemy connection (replaces raw sqlite3).

    Callers must use SQLAlchemy text() for raw SQL and call .close()
    when finished, or preferably use this as a context manager.
    """
    from comicarr.db import get_engine

    return get_engine().connect()


def _ensure_columns(engine, table_name, required_columns):
    """Add missing columns to an existing table.

    Uses SQLAlchemy inspect() for portable column detection.
    Each ALTER TABLE runs in its own transaction.

    Args:
        engine: SQLAlchemy Engine
        table_name: Name of the table to check
        required_columns: List of (column_name, column_type_sql) tuples
    """
    inspector = inspect(engine)
    try:
        existing = {c["name"] for c in inspector.get_columns(table_name)}
    except Exception:
        return

    for col_name, col_type in required_columns:
        if col_name not in existing:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))
            except (OperationalError, ProgrammingError) as e:
                logger.warn("Could not add column %s.%s: %s", table_name, col_name, e)


def dbcheck():
    """Compatibility wrapper for the application-owned Alembic runner.

    Normal startup must never run ad-hoc DDL or data cleanup outside Alembic
    revision state.
    """

    from comicarr.app.core.schema import upgrade_database

    return upgrade_database()


def _redact_diagnostic_error(error):
    """Remove credentials from errors returned by authenticated diagnostics."""

    message = re.sub(r"\s+", " ", str(error or "")).strip()
    message = re.sub(
        r"(?i)(api[ _-]?key|authorization|password|token|passkey)\s*[=:]\s*[^\s,;]+",
        r"\1=[redacted]",
        message,
    )
    message = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s]+@", r"\1[redacted]@", message)
    message = re.sub(r"(?i)([?&](?:apikey|api_key|token|password|passkey)=)[^&\s]+", r"\1[redacted]", message)
    return message[:1000]


_UPSERT_UNIQUE_CONSTRAINT_NAMES = {
    "issues": "uq_issues_issueid",
    "annuals": "uq_annuals_issueid",
    "storyarcs": "uq_storyarcs_issuearcid",
    "readlist": "uq_readlist_issueid",
    "failed": "uq_failed_id_provider_nzbname",
    "upcoming": "uq_upcoming_comicid_issuenum",
    "nzblog": "uq_nzblog_issueid_provider",
    "importresults": "uq_importresults_impid",
    "jobhistory": "uq_jobhistory_jobname",
    "snatched": "uq_snatched_issue_status_provider",
    "oneoffhistory": "uq_oneoffhistory_comicid_issueid",
    "weekly": "uq_weekly_comicid_issueid",
}

_PRE_UNIQUE_MIGRATION_BACKUP = "comicarr.db.pre-unique-migration.bak"


def _build_upsert_unique_constraints():
    """Map allowlisted tables to (key_cols from UPSERT_KEYS, constraint name)."""
    from comicarr.tables import UPSERT_KEYS

    constraints = {}
    for table_name, constraint_name in _UPSERT_UNIQUE_CONSTRAINT_NAMES.items():
        key_cols = UPSERT_KEYS.get(table_name)
        if not key_cols:
            raise RuntimeError("[UNIQUE-MIGRATION] UPSERT_KEYS has no entry for allowlisted table %s" % table_name)
        constraints[table_name] = (list(key_cols), constraint_name)
    return constraints


_UPSERT_UNIQUE_CONSTRAINTS = _build_upsert_unique_constraints()


def _index_has_partial_predicate(index):
    dialect_options = index.get("dialect_options") or {}
    if any(name.endswith("_where") and value is not None for name, value in dialect_options.items()):
        return True
    return any(index.get(name) is not None for name in ("filter_definition", "predicate", "where"))


def _has_unique_enforcement(bind, table_name, key_cols):
    """Return whether a table has a unique constraint or index on ``key_cols``."""
    inspector = inspect(bind)
    expected_columns = tuple(sorted(key_cols))
    constraints = inspector.get_unique_constraints(table_name)
    constraint_columns = {tuple(sorted(constraint.get("column_names") or [])) for constraint in constraints}
    if expected_columns in constraint_columns:
        return True

    for index in inspector.get_indexes(table_name):
        index_columns = tuple(sorted(index.get("column_names") or []))
        if not index.get("unique") or index_columns != expected_columns:
            continue
        if bind.dialect.name != "sqlite":
            if not _index_has_partial_predicate(index):
                return True
            continue

        sqlite_where = (index.get("dialect_options") or {}).get("sqlite_where")
        if sqlite_where is None:
            if not _index_has_partial_predicate(index):
                return True
        elif _sqlite_valid_key_predicate_matches(sqlite_where, key_cols):
            return True

    return False


def _valid_key_predicate(columns):
    return " AND ".join(f"{column} IS NOT NULL AND {column} != ''" for column in columns)


def _canonical_sqlite_predicate(predicate):
    predicate_sql = re.sub(r'["`\[\]]', "", str(predicate))
    predicate_sql = predicate_sql.replace("<>", "!=")
    predicate_sql = re.sub(r"[()]", "", predicate_sql)
    predicate_sql = re.sub(r"\s*!=\s*", " != ", predicate_sql)
    return re.sub(r"\s+", " ", predicate_sql).strip().casefold()


def _sqlite_valid_key_predicate_matches(predicate, key_cols):
    expected_predicate = _valid_key_predicate(key_cols)
    return _canonical_sqlite_predicate(predicate) == _canonical_sqlite_predicate(expected_predicate)


def _sqlite_unique_index_sql(engine, table_name, key_cols, constraint_name):
    """Build a safely quoted partial UNIQUE index for valid legacy keys."""
    quote = engine.dialect.identifier_preparer.quote_identifier
    quoted_columns = [quote(column) for column in key_cols]
    valid_key_predicate = _valid_key_predicate(quoted_columns)
    return (
        f"CREATE UNIQUE INDEX {quote(constraint_name)} ON {quote(table_name)} "
        f"({', '.join(quoted_columns)}) WHERE {valid_key_predicate}"
    )


def _sqlite_database_path(engine, connection=None):
    database = engine.url.database
    database_name = str(database).casefold() if database else ""
    if not database or database_name == ":memory:":
        return None

    uri = engine.url.query.get("uri")
    uri_values = uri if isinstance(uri, (tuple, list)) else (uri,)
    uri_mode_enabled = any(
        value is not None and str(value).casefold() in {"1", "true", "yes", "on"} for value in uri_values
    )
    if not uri_mode_enabled:
        return os.path.abspath(os.path.expanduser(str(database)))

    if database_name.startswith("file:"):
        mode = engine.url.query.get("mode")
        mode_values = mode if isinstance(mode, (tuple, list)) else (mode,)
        if any(value is not None and str(value).casefold() == "memory" for value in mode_values):
            return None

        if database_name.startswith("file::memory:"):
            return None

    if connection is not None:
        for _sequence, schema_name, database_path in connection.exec_driver_sql("PRAGMA database_list"):
            if schema_name == "main" and database_path:
                return os.path.abspath(os.path.expanduser(database_path))
    else:
        with engine.connect() as conn:
            for _sequence, schema_name, database_path in conn.exec_driver_sql("PRAGMA database_list"):
                if schema_name == "main" and database_path:
                    return os.path.abspath(os.path.expanduser(database_path))
    return os.path.abspath(os.path.expanduser(str(database)))


def _row_identity_column(dialect):
    """Return the dialect-native physical row identity used for deduplication."""
    if dialect == "sqlite":
        return "rowid"
    if dialect == "postgresql":
        return "ctid"
    return None


_LIBRARY_QUALITY_DEDUP_TABLES = frozenset({"issues", "annuals", "readlist", "storyarcs"})


def _status_rank_sql(quoted_status_column):
    """Higher is better — prefer completed/on-disk states over Wanted stubs."""
    return (
        f"CASE {quoted_status_column} "
        f"WHEN 'Downloaded' THEN 50 "
        f"WHEN 'Archived' THEN 50 "
        f"WHEN 'Snatched' THEN 40 "
        f"WHEN 'Failed' THEN 20 "
        f"WHEN 'Wanted' THEN 10 "
        f"WHEN 'Skipped' THEN 10 "
        f"ELSE 15 END"
    )


def _library_quality_order_sql(quote, column_names, row_identity):
    """ORDER BY clause for library-quality survivor selection (DESC ranks first)."""
    columns = {name.casefold() for name in column_names}
    order_parts = []
    if "location" in columns:
        loc = quote("Location")
        order_parts.append(f"CASE WHEN {loc} IS NOT NULL AND {loc} != '' THEN 1 ELSE 0 END DESC")
    if "status" in columns:
        order_parts.append(f"{_status_rank_sql(quote('Status'))} DESC")
    order_parts.append(f"{row_identity} DESC")
    return ", ".join(order_parts)


def _dedup_delete_sql(
    dialect,
    quoted_table,
    quoted_keys,
    valid_key_predicate,
    table_name=None,
    column_names=None,
    quote=None,
):
    """Build DELETE that keeps one row per valid key group.

    Default is MAX(rowid/ctid). For library tables with Status/Location columns,
    prefer non-empty Location and stronger Status, then row identity.
    """
    row_identity = _row_identity_column(dialect)
    if row_identity is None:
        return None

    use_quality = (
        table_name in _LIBRARY_QUALITY_DEDUP_TABLES
        and column_names is not None
        and quote is not None
        and ({name.casefold() for name in column_names} & {"location", "status"})
    )
    if not use_quality:
        group_by = ", ".join(quoted_keys)
        return (
            f"DELETE FROM {quoted_table} WHERE {row_identity} NOT IN ("
            f"SELECT MAX({row_identity}) FROM {quoted_table} WHERE {valid_key_predicate} "
            f"GROUP BY {group_by}"
            f") AND {valid_key_predicate}"
        )

    partition = ", ".join(quoted_keys)
    order_by = _library_quality_order_sql(quote, column_names, row_identity)
    return (
        f"DELETE FROM {quoted_table} WHERE {row_identity} IN ("
        f"SELECT {row_identity} FROM ("
        f"SELECT {row_identity}, ROW_NUMBER() OVER ("
        f"PARTITION BY {partition} ORDER BY {order_by}"
        f") AS _comicarr_rn FROM {quoted_table} WHERE {valid_key_predicate}"
        f") AS _comicarr_ranked WHERE _comicarr_rn > 1"
        f")"
    )


def _mysql_dedup_valid_keys(conn, table_name, key_cols):
    """Remove duplicate valid-key rows on MySQL/MariaDB primary-less tables.

    Legacy Comicarr tables often lack a primary key, so MySQL has no rowid/ctid.
    For each valid key group with count C > 1, DELETE ... LIMIT C-1 keeps one
    arbitrary survivor. Must run in the same connection/transaction as ADD CONSTRAINT
    where the engine allows (MySQL DDL may still implicitly commit).
    """
    quote = conn.dialect.identifier_preparer.quote_identifier
    quoted_table = quote(table_name)
    quoted_keys = [quote(column) for column in key_cols]
    valid_key_predicate = _valid_key_predicate(quoted_keys)
    group_by = ", ".join(quoted_keys)

    dup_rows = (
        conn.execute(
            text(
                f"SELECT {group_by}, COUNT(*) AS _comicarr_cnt FROM {quoted_table} "
                f"WHERE {valid_key_predicate} "
                f"GROUP BY {group_by} HAVING COUNT(*) > 1"
            )
        )
        .mappings()
        .all()
    )

    for row in dup_rows:
        cnt = int(row["_comicarr_cnt"])
        if cnt < 2:
            continue
        predicates = []
        params = {}
        for index, column in enumerate(key_cols):
            param = f"k{index}"
            predicates.append(f"{quote(column)} = :{param}")
            params[param] = row[column]
        where_clause = " AND ".join(predicates) + " AND " + valid_key_predicate
        conn.execute(
            text(f"DELETE FROM {quoted_table} WHERE {where_clause} LIMIT {cnt - 1}"),
            params,
        )


def _add_unique_constraint_sql(quoted_table, quoted_constraint, quoted_keys):
    return f"ALTER TABLE {quoted_table} ADD CONSTRAINT {quoted_constraint} UNIQUE ({', '.join(quoted_keys)})"


def _backup_sqlite_unique_migration(engine, backup_func=None, connection=None):
    """Create the mandatory WAL-safe backup for a destructive SQLite migration.

    Backups are co-located with the live database file under
    ``<db-dir>/backups/migrations/``. A fixed-name pin
    (``comicarr.db.pre-unique-migration.bak``) is written once and preserved
    across retention rotation of timestamped backups.
    """
    source_path = _sqlite_database_path(engine, connection=connection)
    if source_path is None:
        return

    backup_dir = os.path.join(os.path.dirname(source_path), "backups", "migrations")
    pin_path = os.path.join(backup_dir, _PRE_UNIQUE_MIGRATION_BACKUP)
    abs_source = os.path.abspath(source_path)
    abs_backup_dir = os.path.abspath(backup_dir)
    abs_pin = os.path.abspath(pin_path)

    logger.info(
        "[UNIQUE-MIGRATION] Pre-migration backup source=%s dest_dir=%s pin=%s",
        abs_source,
        abs_backup_dir,
        abs_pin,
    )

    if os.path.isfile(pin_path):
        logger.info(
            "[UNIQUE-MIGRATION] Reusing existing pre-unique-migration pin backup at %s",
            abs_pin,
        )
        return

    config = getattr(comicarr, "CONFIG", None)
    retention = getattr(config, "BACKUP_RETENTION", 4) if config is not None else 4
    retention = retention or 4
    backup = backup_func or maintenance.auto_backup_db

    try:
        backup_succeeded = backup(source_path, backup_dir, retention)
    except Exception as e:
        message = "SQLite unique-constraint backup failed before migration"
        logger.error("[UNIQUE-MIGRATION] %s: %s", message, e)
        raise RuntimeError(message) from e

    if not backup_succeeded:
        message = "SQLite unique-constraint backup failed; migration was not started"
        logger.error("[UNIQUE-MIGRATION] %s", message)
        raise RuntimeError(message)

    if not os.path.isfile(pin_path):
        timestamped = sorted(
            path
            for path in glob.glob(os.path.join(backup_dir, "comicarr.db.*.bak"))
            if re.match(r"^comicarr\.db\.\d{8}_\d{6}\.bak$", os.path.basename(path))
        )
        if timestamped:
            try:
                shutil.copy2(timestamped[-1], pin_path)
                logger.info("[UNIQUE-MIGRATION] Wrote pre-unique-migration pin backup to %s", abs_pin)
            except OSError as e:
                message = "SQLite unique-constraint pin backup failed before migration"
                logger.error("[UNIQUE-MIGRATION] %s: %s", message, e)
                raise RuntimeError(message) from e


def _pending_unique_constraints(bind):
    pending = []
    inspector = inspect(bind)
    for table_name, (key_cols, constraint_name) in _UPSERT_UNIQUE_CONSTRAINTS.items():
        try:
            if not inspector.has_table(table_name):
                continue
            if not _has_unique_enforcement(bind, table_name, key_cols):
                pending.append((table_name, key_cols, constraint_name))
        except SQLAlchemyError as e:
            logger.warn("[UNIQUE-MIGRATION] Could not inspect UNIQUE enforcement for %s: %s", table_name, e)
    return pending


def _remaining_unenforced_tables(bind, pending_constraints):
    """Return allowlisted table names from ``pending_constraints`` still lacking enforcement."""
    remaining = []
    for table_name, key_cols, _constraint_name in pending_constraints:
        try:
            if not inspect(bind).has_table(table_name):
                continue
            if not _has_unique_enforcement(bind, table_name, key_cols):
                remaining.append(table_name)
        except SQLAlchemyError as e:
            logger.warn(
                "[UNIQUE-MIGRATION] Could not verify UNIQUE enforcement for %s after migration: %s",
                table_name,
                e,
            )
            remaining.append(table_name)
    return remaining


def _bounded_alternate_index_name(engine, constraint_name, table_name, key_cols, attempt):
    max_length = max(int(getattr(engine.dialect, "max_identifier_length", 128) or 128), 1)
    identity = f"{table_name}|{','.join(key_cols)}|{attempt}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    suffix = f"_ca_{digest}"
    if len(suffix) >= max_length:
        return digest[:max_length]
    return f"{constraint_name[: max_length - len(suffix)]}{suffix}"


def _sqlite_available_index_name(engine, constraint_name, table_name, key_cols, connection=None):
    if connection is not None:
        existing_names = {
            str(name).casefold()
            for name in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'index' AND name IS NOT NULL")
            ).scalars()
        }
    else:
        with engine.connect() as conn:
            existing_names = {
                str(name).casefold()
                for name in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'index' AND name IS NOT NULL")
                ).scalars()
            }

    max_length = max(int(getattr(engine.dialect, "max_identifier_length", 128) or 128), 1)
    if len(constraint_name) <= max_length and constraint_name.casefold() not in existing_names:
        return constraint_name

    for attempt in range(100):
        candidate = _bounded_alternate_index_name(engine, constraint_name, table_name, key_cols, attempt)
        if candidate.casefold() not in existing_names:
            return candidate
    raise RuntimeError(f"Could not allocate a unique index name for {table_name}")


def _migrate_unique_constraints(engine_or_connection, backup_func=None):
    """Install the unique enforcement required by atomic upserts.

    Legacy SQLite databases receive partial unique indexes so duplicate null or
    empty keys remain valid. File-backed databases are backed up once after
    preflight and before the first deduplication. Each table's deterministic
    deduplication and index creation share one transaction, ensuring a failed
    DDL statement restores the rows deleted by that attempt.

    After the per-table loop, any still-pending tables cause a RuntimeError so
    startup fails closed rather than soft-succeeding without enforcement.
    """
    connection = engine_or_connection if hasattr(engine_or_connection, "exec_driver_sql") else None
    engine = connection.engine if connection is not None else engine_or_connection
    bind = connection or engine
    dialect = bind.dialect.name

    pending_constraints = _pending_unique_constraints(bind)
    if not pending_constraints:
        return

    if dialect == "sqlite":
        _backup_sqlite_unique_migration(engine, backup_func, connection=connection)

    for table_name, key_cols, constraint_name in pending_constraints:
        try:
            if _has_unique_enforcement(bind, table_name, key_cols):
                continue
        except SQLAlchemyError as e:
            logger.warn(
                "[UNIQUE-MIGRATION] Could not recheck UNIQUE enforcement for %s; proceeding with migration: %s",
                table_name,
                e,
            )

        quote = bind.dialect.identifier_preparer.quote_identifier
        quoted_table = quote(table_name)
        quoted_keys = [quote(column) for column in key_cols]
        valid_key_predicate = _valid_key_predicate(quoted_keys)
        try:
            column_names = [col["name"] for col in inspect(bind).get_columns(table_name)]
        except SQLAlchemyError:
            column_names = []
        dedup_sql = _dedup_delete_sql(
            dialect,
            quoted_table,
            quoted_keys,
            valid_key_predicate,
            table_name=table_name,
            column_names=column_names,
            quote=quote,
        )
        constraint_sql = _add_unique_constraint_sql(quoted_table, quote(constraint_name), quoted_keys)
        index_name = constraint_name
        index_sql = None

        if dialect == "sqlite":
            index_name = _sqlite_available_index_name(
                engine,
                constraint_name,
                table_name,
                key_cols,
                connection=connection,
            )
            index_sql = _sqlite_unique_index_sql(engine, table_name, key_cols, index_name)

        def install_unique_enforcement(
            active_connection,
            dialect=dialect,
            dedup_sql=dedup_sql,
            index_sql=index_sql,
            constraint_sql=constraint_sql,
            table_name=table_name,
            key_cols=key_cols,
        ):
            if dialect == "sqlite":
                active_connection.execute(text(dedup_sql))
                active_connection.execute(text(index_sql))
            elif dialect == "postgresql":
                active_connection.execute(text(dedup_sql))
                active_connection.execute(text(constraint_sql))
            elif dialect == "mysql":
                _mysql_dedup_valid_keys(active_connection, table_name, key_cols)
                active_connection.execute(text(constraint_sql))

        if dialect not in {"sqlite", "postgresql", "mysql"}:
            logger.warn(
                "[UNIQUE-MIGRATION] Unsupported dialect %s for unique-constraint migration on %s",
                dialect,
                table_name,
            )
            continue

        if connection is not None:
            try:
                install_unique_enforcement(connection)
            except SQLAlchemyError as e:
                message = "Could not add UNIQUE enforcement %s on %s" % (constraint_name, table_name)
                logger.error(
                    "[UNIQUE-MIGRATION] %s using the active Alembic connection: %s",
                    message,
                    e,
                )
                raise RuntimeError(message) from e
        else:
            try:
                with engine.begin() as active_connection:
                    install_unique_enforcement(active_connection)
            except SQLAlchemyError as e:
                logger.warn(
                    "[UNIQUE-MIGRATION] Could not add UNIQUE enforcement %s on %s; changes rolled back: %s",
                    index_name,
                    table_name,
                    e,
                )
                continue

        try:
            constraint_installed = _has_unique_enforcement(bind, table_name, key_cols)
        except SQLAlchemyError as e:
            logger.warn("[UNIQUE-MIGRATION] Could not verify UNIQUE enforcement for %s: %s", table_name, e)
            continue

        if constraint_installed:
            logger.info(
                "[UNIQUE-MIGRATION] Added UNIQUE enforcement %s on %s(%s)",
                index_name,
                table_name,
                ", ".join(key_cols),
            )
        else:
            logger.warn(
                "[UNIQUE-MIGRATION] UNIQUE enforcement %s on %s was not installed",
                constraint_name,
                table_name,
            )

    remaining = _remaining_unenforced_tables(bind, pending_constraints)
    if remaining:
        message = "Unique-constraint migration incomplete for: %s" % ", ".join(remaining)
        logger.error("[UNIQUE-MIGRATION] %s", message)
        raise RuntimeError(message)


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
    global _INITIALIZED, started

    with INIT_LOCK:
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

    if CREATEPID:
        logger.info("Removing pidfile %s" % PIDFILE)
        os.remove(PIDFILE)

    if restart:
        logger.info("Comicarr is restarting...")
        popen_list = [sys.executable, FULL_PATH]
        if "maintenance" not in ARGS:
            popen_list += ARGS
        else:
            plist = []
            for x in ARGS:
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
