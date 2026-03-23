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

import cherrypy
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError, ProgrammingError

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
            # Lock was not held - this is fine for backwards compatibility
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


# these are the globals that are runtime-based (ie. not config-valued at all)
# they are referenced in other modules just as comicarr.VARIABLE (instead of comicarr.CONFIG.VARIABLE)
MINIMUM_PY_VERSION = "3.8.1"
PROG_DIR = None
DATA_DIR = None
FULL_PATH = None
MAINTENANCE = False
LOG_DIR = None
LOGTYPE = "log"
LOG_LANG = "en"
LOG_CHARSET = "UTF-8"
LOG_LEVEL = None
LOGLIST = []
ARGS = None
SIGNAL = None
SYS_ENCODING = None
OS_DETECT = platform.system()
USER_AGENT = None
# VERBOSE = False
DAEMON = False
PIDFILE = None
CREATEPID = False
QUIET = False
MAX_LOGSIZE = 5000000
SAFESTART = False
NOWEEKLY = False
INIT_LOCK = threading.Lock()
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
SEARCH_STATUS = "Waiting"
RSS_STATUS = "Waiting"
WEEKLY_STATUS = "Waiting"
VERSION_STATUS = "Waiting"
UPDATER_STATUS = "Waiting"
FORCE_STATUS = {}
RSS_SCHEDULER = None
WEEKLY_SCHEDULER = None
MONITOR_SCHEDULER = None
SEARCH_SCHEDULER = None
VERSION_SCHEDULER = None
UPDATER_SCHEDULER = None
SCHED_RSS_LAST = None
SCHED_WEEKLY_LAST = None
SCHED_MONITOR_LAST = None
SCHED_SEARCH_LAST = None
SCHED_VERSION_LAST = None
SCHED_DBUPDATE_LAST = None
DBUPDATE_INTERVAL = 1440  # 24hrs
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
SEARCH_QUEUE = queue.Queue()
DDL_QUEUE = queue.Queue()
RETURN_THE_NZBQUEUE = queue.Queue()
MASS_ADD = None
ADD_LIST = queue.Queue()
ISSUE_WATCH_LIST = queue.Queue()
MASS_REFRESH = None
REFRESH_QUEUE = queue.Queue()
DDL_QUEUED = []
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
COMMITS_BEHIND = None
LOCAL_IP = None
DOWNLOAD_APIKEY = None
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
EXT_IP = None
PROVIDER_START_ID = 0
COMICINFO = ()
CHECK_FOLDER_CACHE = None
FOLDER_CACHE = None
GLOBAL_MESSAGES = None
SSE_KEY = None
SESSION_ID = None
SETUP_TOKEN = None
START_UP = True
UPDATE_VALUE = {}
REQS = {}
GC_URL = "https://getcomics.org"
IMPRINT_MAPPING = {
    # ComicVine: imprint.json
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
BACKENDSTATUS_WS = "up"
BACKENDSTATUS_CV = "up"
PROVIDER_STATUS = {}


def initialize(config_file):
    with INIT_LOCK:
        global \
            CONFIG, \
            _INITIALIZED, \
            QUIET, \
            CONFIG_FILE, \
            MINIMUM_PY_VERSION, \
            OS_DETECT, \
            MAINTENANCE, \
            CURRENT_VERSION, \
            LATEST_VERSION, \
            COMMITS_BEHIND, \
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
            DOWNLOAD_APIKEY, \
            LOCAL_IP, \
            STATIC_COMICRN_VERSION, \
            STATIC_APC_VERSION, \
            KEYS_32P, \
            AUTHKEY_32P, \
            FEED_32P, \
            FEEDINFO_32P, \
            MONITOR_STATUS, \
            SEARCH_STATUS, \
            RSS_STATUS, \
            WEEKLY_STATUS, \
            VERSION_STATUS, \
            UPDATER_STATUS, \
            FORCE_STATUS, \
            DBUPDATE_INTERVAL, \
            DB_BACKFILL, \
            LOG_LANG, \
            LOG_CHARSET, \
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
            START_UP, \
            SCHED_RSS_LAST, \
            SCHED_WEEKLY_LAST, \
            SCHED_MONITOR_LAST, \
            SCHED_SEARCH_LAST, \
            SCHED_VERSION_LAST, \
            SCHED_DBUPDATE_LAST, \
            COMICINFO, \
            SEARCH_TIER_DATE, \
            BACKENDSTATUS_CV, \
            BACKENDSTATUS_WS, \
            PROVIDER_STATUS, \
            EXT_IP, \
            ISSUE_EXCEPTIONS, \
            PROVIDER_START_ID, \
            GLOBAL_MESSAGES, \
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

        # Initialize the database
        logger.info("Checking to see if the database has all tables....")
        try:
            dbcheck()
        except Exception as e:
            logger.error("Cannot connect to the database: %s" % e)
        else:
            # Check if database is empty and set startup flags
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

            # quick check here to see if a previous db update failed.
            chk = maintenance.Maintenance(mode="db update")
            chk.check_failed_update()

            # check to see if any db updates are required / new.
            chk.db_update_check()

        # set the flag here whether to start it up in maintenance mode or not.
        # usually it will be based on if a field is present in the db or not.
        if comicarr.MAINTENANCE_UPDATE:
            comicarr.MAINTENANCE = True

        if MAINTENANCE is False:
            comicarr.config.ddl_creations()

            # try to get the local IP using socket. Get this on every startup so it's at least current for existing session.
            import socket

            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                LOCAL_IP = s.getsockname()[0]
                s.close()
                logger.info("Successfully discovered local IP and locking it in as : " + str(LOCAL_IP))
            except:
                logger.warn(
                    "Unable to determine local IP - this might cause problems when downloading (maybe use host_return in the config.ini)"
                )
                LOCAL_IP = CONFIG.HTTP_HOST

            # verbatim back the logger being used since it's now started.
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

            # check for syno_fix here
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

        # Initialize ComicVine API session with connection pooling
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

            # Initialize rate limiter
            if CV_RATE_LIMITER is None:
                from comicarr import rate_limiter

                # Default to 1 call per 2 seconds (0.5 calls/sec)
                cvapi_rate = (
                    comicarr.CONFIG.CVAPI_RATE if comicarr.CONFIG.CVAPI_RATE and comicarr.CONFIG.CVAPI_RATE >= 2 else 2
                )
                CV_RATE_LIMITER = rate_limiter.ComicVineRateLimiter(calls_per_second=1.0 / cvapi_rate)
                logger.info("ComicVine rate limiter initialized with %s second interval" % cvapi_rate)

            # Initialize ComicVine cache
            if CV_CACHE is None:
                from comicarr import cv_cache

                cache_db_path = os.path.join(comicarr.DATA_DIR, "cv_cache.db")
                CV_CACHE = cv_cache.CVCache(cache_db_path)
                logger.info("ComicVine cache initialized at: %s" % cache_db_path)

        initialize_cv_session()

        # Initialize Metron API session if configured
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

        # set the current week for the pull-list
        todaydate = datetime.datetime.today()
        CURRENT_WEEKNUMBER = todaydate.strftime("%U")
        CURRENT_YEAR = todaydate.strftime("%Y")

        if SEARCH_TIER_DATE is None:
            # tier the wanted listed so anything older than SEARCH_TIER_CUTOFF (default 14 days)
            # won't trigger the API during searches.
            # utc_date = datetime.datetime.utcnow()
            STD = todaydate - timedelta(days=comicarr.CONFIG.SEARCH_TIER_CUTOFF)
            SEARCH_TIER_DATE = STD.strftime("%Y-%m-%d")
            logger.fdebug("SEARCH_TIER_DATE set to : %s" % SEARCH_TIER_DATE)

        # set the default URL for ComicVine API here.
        CVURL = "https://comicvine.gamespot.com/api/"

        # set default URL for Public trackers (just in case it changes more frequently)
        WWTURL = "https://worldwidetorrents.to/"
        DEMURL = "https://www.demonoid.pw/"

        # set the default URL for nzbindex
        EXPURL = "https://nzbindex.nl/"

        # load in the imprint json here.
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
                # TODO: Host on Comicarr domain
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

        # startup check(s) here so that the config values are already loaded against.
        if all([comicarr.USE_SABNZBD is True, comicarr.CONFIG.SAB_HOST is not None]):
            s_to_the_ab = sabnzbd.SABnzbd(params=None)
            s_to_the_ab.sab_versioncheck()
            logger.info("[SAB-VERSION-CHECK] SABnzbd version detected as: %s" % comicarr.CONFIG.SAB_VERSION)

        # make sure the intLatestIssue field is populated with values...
        # ??helpers.latestissue_update()

        # Store the original umask
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

    # Do first fork
    try:
        pid = os.fork()
        if pid == 0:
            pass
        else:
            # Exit the parent process
            logger.debug("Forking once...")
            os._exit(0)
    except OSError as e:
        sys.exit("1st fork failed: %s [%d]" % (e.strerror, e.errno))

    os.setsid()

    # Make sure I can read my own files and shut out others
    prev = os.umask(0)  # @UndefinedVariable - only available in UNIX
    os.umask(prev and int("077", 8))

    # Do second fork
    try:
        pid = os.fork()
        if pid > 0:
            logger.debug("Forking twice...")
            os._exit(0)  # Exit second parent process
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


def start():

    global _INITIALIZED, started

    with INIT_LOCK:
        if _INITIALIZED:
            # scheduler jobs - add them all in a paused state initially
            UPDATER_SCHEDULER = SCHED.add_job(
                func=updater.watchlist_updater,
                id="dbupdater",
                next_run_time=datetime.datetime.utcnow(),
                name="DB Updater",
                args=[None, True],
                trigger=IntervalTrigger(hours=0, minutes=DBUPDATE_INTERVAL, timezone="UTC"),
            )
            UPDATER_SCHEDULER.pause()

            ss = searchit.CurrentSearcher()
            SEARCH_SCHEDULER = SCHED.add_job(
                func=ss.run,
                id="search",
                next_run_time=datetime.datetime.utcnow(),
                name="Auto-Search",
                trigger=IntervalTrigger(hours=0, minutes=CONFIG.SEARCH_INTERVAL, timezone="UTC"),
            )
            SEARCH_SCHEDULER.pause()

            ws = weeklypullit.Weekly()
            WEEKLY_SCHEDULER = SCHED.add_job(
                func=ws.run,
                id="weekly",
                name="Weekly Pullist",
                next_run_time=datetime.datetime.utcnow(),
                trigger=IntervalTrigger(hours=4, minutes=0, timezone="UTC"),
            )
            WEEKLY_SCHEDULER.pause()

            rs = rsscheckit.tehMain()
            RSS_SCHEDULER = SCHED.add_job(
                func=rs.run,
                id="rss",
                name="RSS Feeds",
                args=[True],
                next_run_time=datetime.datetime.utcnow(),
                trigger=IntervalTrigger(hours=0, minutes=int(CONFIG.RSS_CHECKINTERVAL), timezone="UTC"),
            )
            RSS_SCHEDULER.pause()

            vs = versioncheckit.CheckVersion()
            VERSION_SCHEDULER = SCHED.add_job(
                func=vs.run,
                id="version",
                name="Check Version",
                trigger=IntervalTrigger(hours=0, minutes=CONFIG.CHECK_GITHUB_INTERVAL, timezone="UTC"),
            )
            VERSION_SCHEDULER.pause()

            fm = postprocessor.FolderCheck()
            MONITOR_SCHEDULER = SCHED.add_job(
                func=fm.run,
                id="monitor",
                name="Folder Monitor",
                trigger=IntervalTrigger(hours=0, minutes=int(CONFIG.DOWNLOAD_SCAN_INTERVAL), timezone="UTC"),
            )
            MONITOR_SCHEDULER.pause()

            # load up the previous runs from the job sql table so we know stuff...
            monitors = helpers.job_management(startup=True)

            # logger.fdebug('monitors: %s' % (monitors,))

            SCHED_WEEKLY_LAST = monitors["weekly"]["last"]
            SCHED_SEARCH_LAST = monitors["search"]["last"]
            SCHED_UPDATER_LAST = monitors["updater"]["last"]
            monitors["monitor"]["last"]
            monitors["version"]["last"]
            SCHED_RSS_LAST = monitors["rss"]["last"]

            # Start our scheduled background tasks
            if UPDATER_STATUS != "Paused":
                # we want to run the db updater on every startup regardless of last run
                # this will ensure we get better coverage, and if nothing has updated it
                # will just return to the normal dbupdater_interval duration.
                if SCHED_UPDATER_LAST is not None:
                    updater_timestamp = float(SCHED_UPDATER_LAST)
                    logger.fdebug(
                        "[DB UPDATER] Updater last run @ %s"
                        % helpers.utc_date_to_local(datetime.datetime.utcfromtimestamp(updater_timestamp))
                    )
                else:
                    updater_timestamp = helpers.utctimestamp() + (int(DBUPDATE_INTERVAL) * 60)

                updater_diff = (helpers.utctimestamp() - updater_timestamp) / 60
                if updater_diff >= int(DBUPDATE_INTERVAL):
                    logger.fdebug("[DB UPDATER] DB Updater scheduled to run immediately.")
                    UPDATER_SCHEDULER.modify(next_run_time=(datetime.datetime.utcnow()))
                else:
                    updater_diff = datetime.datetime.utcfromtimestamp(
                        helpers.utctimestamp() + ((int(DBUPDATE_INTERVAL) * 60) - (updater_diff * 60))
                    )
                    logger.fdebug(
                        "[DB UPDATER] Scheduling next run @ %s (every %s minutes)"
                        % (helpers.utc_date_to_local(updater_diff), DBUPDATE_INTERVAL)
                    )
                    UPDATER_SCHEDULER.modify(next_run_time=updater_diff)

            # let's do a run at the Wanted issues here (on startup) if enabled.
            if SEARCH_STATUS != "Paused":
                if CONFIG.NZB_STARTUP_SEARCH:
                    # now + 2 minute startup delay
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

            # thread queue control..
            queue_schedule("search_queue", "start")

            if all([CONFIG.ENABLE_TORRENTS, CONFIG.AUTO_SNATCH, OS_DETECT != "Windows"]) and any(
                [CONFIG.TORRENT_DOWNLOADER == 2, CONFIG.TORRENT_DOWNLOADER == 4]
            ):
                queue_schedule("snatched_queue", "start")

            if CONFIG.POST_PROCESSING is True and (
                all([CONFIG.NZB_DOWNLOADER == 0, CONFIG.SAB_CLIENT_POST_PROCESSING is True])
                or all([CONFIG.NZB_DOWNLOADER == 1, CONFIG.NZBGET_CLIENT_POST_PROCESSING is True])
            ):
                queue_schedule("nzb_queue", "start")

            if CONFIG.POST_PROCESSING is True:
                queue_schedule("pp_queue", "start")

            if CONFIG.ENABLE_DDL is True:
                queue_schedule("ddl_queue", "start")
                if CONFIG.DDL_STUCK_NOTIFY is True:
                    SCHED.add_job(
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

            # weekly pull list gets messed up if it's not populated first, so let's populate it then set the scheduler.
            logger.info("[WEEKLY] Checking for existance of Weekly Comic listing...")

            # now the scheduler (check every 24 hours)
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

            # initiate startup rss feeds for torrents/nzbs here...
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

            if VERSION_STATUS != "Paused":
                VERSION_SCHEDULER.resume()

            ##run checkFolder every X minutes (basically Manual Run Post-Processing)
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
                # update the job db here
                logger.info("Background Schedulers successfully started...")
                helpers.job_management(write=True)
            except Exception as e:
                logger.info(e)
                SCHED.print_jobs()

        started = True


def queue_schedule(queuetype, mode):
    def start(pool_attr, target, q_arg, name, before_msg, after_msg):
        pool = getattr(comicarr, pool_attr)
        try:
            if pool.is_alive() is True:
                return
        except Exception:
            pass

        logger.info("[%s] %s" % (name, before_msg))
        thread = threading.Thread(target=target, args=(q_arg,), name=name)
        setattr(comicarr, pool_attr, thread)
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
        except AssertionError:
            if mode == "shutdown":
                os._exit(0)

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
                if comicarr.NZBPOOL.is_alive() is True:
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
            comicarr.NZBPOOL = threading.Thread(target=helpers.nzb_monitor, args=(NZB_QUEUE,), name="AUTO-COMPLETE-NZB")
            comicarr.NZBPOOL.start()
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
            shutdown(comicarr.NZBPOOL, comicarr.NZB_QUEUE, "NZB auto-complete queue")

        if (queuetype == "snatched_queue") or mode == "shutdown":
            if all(
                [
                    mode != "shutdown",
                    comicarr.CONFIG.ENABLE_TORRENTS is True,
                    comicarr.CONFIG.AUTO_SNATCH is True,
                    OS_DETECT != "Windows",
                ]
            ) and any([comicarr.CONFIG.TORRENT_DOWNLOADER == 2, comicarr.CONFIG.TORRENT_DOWNLOADER == 4]):
                return
            shutdown(comicarr.SNPOOL, comicarr.SNATCHED_QUEUE, "auto-snatch")

        if (queuetype == "search_queue") or mode == "shutdown":
            shutdown(comicarr.SEARCHPOOL, comicarr.SEARCH_QUEUE, "search queue")

        if (queuetype == "pp_queue") or mode == "shutdown":
            if all([comicarr.CONFIG.POST_PROCESSING is True, mode != "shutdown"]):
                return
            shutdown(comicarr.PPPOOL, comicarr.PP_QUEUE, "post-processing queue")

        if (queuetype == "ddl_queue") or mode == "shutdown":
            if all([comicarr.CONFIG.ENABLE_DDL is True, mode != "shutdown"]):
                return
            shutdown(comicarr.DDLPOOL, comicarr.DDL_QUEUE, "DDL download queue")


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
        return  # Table doesn't exist yet (will be created by metadata.create_all)

    for col_name, col_type in required_columns:
        if col_name not in existing:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))
            except (OperationalError, ProgrammingError) as e:
                logger.warn("Could not add column %s.%s: %s", table_name, col_name, e)


def dbcheck():
    from comicarr.db import get_engine
    from comicarr.tables import metadata as sa_metadata

    engine = get_engine()

    # --- Legacy readinglist -> storyarcs migration (very old databases) ---
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "readinglist" in existing_tables and "storyarcs" not in existing_tables:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS storyarcs(StoryArcID TEXT, ComicName TEXT, "
                        "IssueNumber TEXT, SeriesYear TEXT, IssueYEAR TEXT, StoryArc TEXT, "
                        "TotalIssues TEXT, Status TEXT, inCacheDir TEXT, Location TEXT, "
                        "IssueArcID TEXT, ReadingOrder INT, IssueID TEXT, ComicID TEXT, "
                        "ReleaseDate TEXT, IssueDate TEXT, Publisher TEXT, IssuePublisher TEXT, "
                        "IssueName TEXT, CV_ArcID TEXT, Int_IssueNumber INT, DynamicComicName TEXT, "
                        "Volume TEXT, Manual TEXT, DateAdded TEXT, DigitalDate TEXT, Type TEXT, "
                        "Aliases TEXT, ArcImage TEXT, StoreDate TEXT)"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO storyarcs(StoryArcID, ComicName, IssueNumber, SeriesYear, "
                        "IssueYEAR, StoryArc, TotalIssues, Status, inCacheDir, Location, "
                        "IssueArcID, ReadingOrder, IssueID, ComicID, ReleaseDate, IssueDate, "
                        "Publisher, IssuePublisher, IssueName, CV_ArcID, Int_IssueNumber, "
                        "DynamicComicName, Volume, Manual) SELECT StoryArcID, ComicName, "
                        "IssueNumber, SeriesYear, IssueYEAR, StoryArc, TotalIssues, Status, "
                        "inCacheDir, Location, IssueArcID, ReadingOrder, IssueID, ComicID, "
                        "StoreDate, IssueDate, Publisher, IssuePublisher, IssueName, CV_ArcID, "
                        "Int_IssueNumber, DynamicComicName, Volume, Manual FROM readinglist"
                    )
                )
                conn.execute(text("DROP TABLE readinglist"))
        except (OperationalError, ProgrammingError):
            logger.warn("Unable to update readinglist table to new storyarc table format.")

    # --- Create all tables and indexes from SQLAlchemy metadata ---
    sa_metadata.create_all(engine)

    # --- Schema migrations: add columns missing from older databases ---
    # For new installations, create_all() creates tables with all columns.
    # For upgrades, these ensure missing columns are added.

    dynamic_upgrade = False

    # -- Comics Table --
    comics_cols = [
        ("LastUpdated", "TEXT"),
        ("QUALalt_vers", "TEXT"),
        ("QUALtype", "TEXT"),
        ("QUALscanner", "TEXT"),
        ("QUALquality", "TEXT"),
        ("AlternateSearch", "TEXT"),
        ("ComicVersion", "TEXT"),
        ("SortOrder", "INTEGER"),
        ("UseFuzzy", "TEXT"),
        ("DetailURL", "TEXT"),
        ("ForceContinuing", "INTEGER"),
        ("intLatestIssue", "INTEGER"),
        ("ComicName_Filesafe", "TEXT"),
        ("AlternateFileName", "TEXT"),
        ("ComicImageURL", "TEXT"),
        ("ComicImageALTURL", "TEXT"),
        ("NewPublish", "TEXT"),
        ("AllowPacks", "TEXT"),
        ("Type", "TEXT"),
        ("Corrected_SeriesYear", "TEXT"),
        ("Corrected_Type", "TEXT"),
        ("TorrentID_32P", "TEXT"),
        ("LatestIssueID", "TEXT"),
        ("Collects", "TEXT"),
        ("IgnoreType", "INTEGER"),
        ("FirstImageSize", "INTEGER"),
        ("AgeRating", "TEXT"),
        ("PublisherImprint", "TEXT"),
        ("DescriptionEdit", "TEXT"),
        ("FilesUpdated", "TEXT"),
        ("dirlocked", "INTEGER"),
        ("seriesjsonPresent", "INT"),
        ("cv_removed", "INT"),
        ("ContentType", "TEXT DEFAULT 'comic'"),
        ("ReadingDirection", "TEXT DEFAULT 'ltr'"),
        ("MetadataSource", "TEXT"),
        ("ExternalID", "TEXT"),
        ("not_updated_db", "TEXT"),
    ]
    _ensure_columns(engine, "comics", comics_cols)

    # Check DynamicComicName separately (has side effect)
    inspector = inspect(engine)
    comics_existing = {c["name"] for c in inspector.get_columns("comics")}
    if "DynamicComicName" not in comics_existing:
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE comics ADD COLUMN DynamicComicName TEXT"))
        except (OperationalError, ProgrammingError):
            pass
        dynamic_upgrade = True
    elif CONFIG.DYNAMIC_UPDATE < 3:
        dynamic_upgrade = True

    # -- Issues Table --
    issues_cols = [
        ("ComicSize", "TEXT"),
        ("inCacheDIR", "TEXT"),
        ("AltIssueNumber", "TEXT"),
        ("IssueDate_Edit", "TEXT"),
        ("ImageURL", "TEXT"),
        ("ImageURL_ALT", "TEXT"),
        ("DigitalDate", "TEXT"),
        ("forced_file", "INT"),
        ("ChapterNumber", "TEXT"),
        ("VolumeNumber", "TEXT"),
    ]
    _ensure_columns(engine, "issues", issues_cols)

    # -- ImportResults Table --
    importresults_cols = [
        ("WatchMatch", "TEXT"),
        ("IssueCount", "TEXT"),
        ("ComicLocation", "TEXT"),
        ("ComicFilename", "TEXT"),
        ("impID", "TEXT"),
        ("implog", "TEXT"),
        ("DisplayName", "TEXT"),
        ("SRID", "TEXT"),
        ("ComicID", "TEXT"),
        ("IssueID", "TEXT"),
        ("Volume", "TEXT"),
        ("IssueNumber", "TEXT"),
        ("DynamicName", "TEXT"),
        ("MatchConfidence", "INTEGER"),
        ("SuggestedComicID", "TEXT"),
        ("SuggestedComicName", "TEXT"),
        ("SuggestedIssueID", "TEXT"),
        ("IgnoreFile", "INTEGER DEFAULT 0"),
        ("MatchSource", "TEXT"),
    ]
    _ensure_columns(engine, "importresults", importresults_cols)

    # -- Readlist Table --
    readlist_cols = [
        ("inCacheDIR", "TEXT"),
        ("Location", "TEXT"),
        ("IssueDate", "TEXT"),
        ("SeriesYear", "TEXT"),
        ("ComicID", "TEXT"),
        ("StatusChange", "TEXT"),
    ]
    _ensure_columns(engine, "readlist", readlist_cols)

    # -- Weekly Table --
    weekly_cols = [
        ("ComicID", "TEXT"),
        ("IssueID", "TEXT"),
        ("DynamicName", "TEXT"),
        ("CV_Last_Update", "TEXT"),
        ("weeknumber", "TEXT"),
        ("year", "TEXT"),
        ("volume", "TEXT"),
        ("seriesyear", "TEXT"),
        ("annuallink", "TEXT"),
        ("format", "TEXT"),
    ]
    _ensure_columns(engine, "weekly", weekly_cols)

    # -- Nzblog Table --
    nzblog_cols = [
        ("SARC", "TEXT"),
        ("PROVIDER", "TEXT"),
        ("ID", "TEXT"),
        ("AltNZBName", "TEXT"),
        ("OneOff", "TEXT"),
    ]
    _ensure_columns(engine, "nzblog", nzblog_cols)

    # -- Annuals Table --
    annuals_cols = [
        ("Location", "TEXT"),
        ("ComicSize", "TEXT"),
        ("Int_IssueNumber", "INT"),
        ("ReleaseDate", "TEXT"),
        ("ReleaseComicID", "TEXT"),
        ("ReleaseComicName", "TEXT"),
        ("IssueDate_Edit", "TEXT"),
        ("DateAdded", "TEXT"),
        ("DigitalDate", "TEXT"),
        ("Deleted", "INT DEFAULT 0"),
    ]
    _ensure_columns(engine, "annuals", annuals_cols)

    # Check ComicName in annuals separately (has side effect)
    annuals_existing = {c["name"] for c in inspect(engine).get_columns("annuals")}
    annual_update = "no"
    if "ComicName" not in annuals_existing:
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE annuals ADD COLUMN ComicName TEXT"))
        except (OperationalError, ProgrammingError):
            pass
        annual_update = "yes"

    if annual_update == "yes":
        logger.info("Updating Annuals table for new fields - one-time update.")
        helpers.annual_update()

    # -- Snatched Table --
    snatched_cols = [("Provider", "TEXT"), ("Hash", "TEXT"), ("crc", "TEXT")]
    _ensure_columns(engine, "snatched", snatched_cols)

    # -- Upcoming Table --
    _ensure_columns(engine, "upcoming", [("DisplayComicName", "TEXT")])

    # -- StoryArcs Table --
    storyarcs_cols = [
        ("ComicID", "TEXT"),
        ("StoreDate", "TEXT"),
        ("IssueDate", "TEXT"),
        ("Publisher", "TEXT"),
        ("IssuePublisher", "TEXT"),
        ("IssueName", "TEXT"),
        ("CV_ArcID", "TEXT"),
        ("Int_IssueNumber", "INT"),
        ("Volume", "TEXT"),
        ("Manual", "TEXT"),
        ("DateAdded", "TEXT"),
        ("DigitalDate", "TEXT"),
        ("Type", "TEXT"),
        ("Aliases", "TEXT"),
        ("ArcImage", "TEXT"),
    ]
    _ensure_columns(engine, "storyarcs", storyarcs_cols)

    # Check DynamicComicName in storyarcs separately (has side effect)
    storyarcs_existing = {c["name"] for c in inspect(engine).get_columns("storyarcs")}
    if "DynamicComicName" not in storyarcs_existing:
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE storyarcs ADD COLUMN DynamicComicName TEXT"))
        except (OperationalError, ProgrammingError):
            pass
        dynamic_upgrade = True
    elif CONFIG.DYNAMIC_UPDATE < 4:
        dynamic_upgrade = True

    # -- SearchResults Table --
    searchresults_cols = [
        ("SRID", "TEXT"),
        ("Series", "TEXT"),
        ("sresults", "TEXT"),
        ("ogcname", "TEXT"),
    ]
    _ensure_columns(engine, "searchresults", searchresults_cols)

    # -- FutureUpcoming Table --
    _ensure_columns(engine, "futureupcoming", [("weeknumber", "TEXT"), ("year", "TEXT")])

    # -- Failed Table --
    _ensure_columns(engine, "failed", [("DateFailed", "TEXT")])

    # -- Ref32p Table --
    _ensure_columns(engine, "ref32p", [("Updated", "TEXT")])

    # -- Jobhistory Table --
    _ensure_columns(engine, "jobhistory", [("status", "TEXT")])

    # last date — used by db Updater for staggering requests
    jobhistory_existing = {c["name"] for c in inspect(engine).get_columns("jobhistory")}
    if "last_date" not in jobhistory_existing:
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE jobhistory ADD COLUMN last_date timestamp"))
            comicarr.DB_BACKFILL = True
        except (OperationalError, ProgrammingError):
            comicarr.DB_BACKFILL = False
    else:
        comicarr.DB_BACKFILL = False

    # -- DDL_info Table --
    ddl_cols = [
        ("remote_filesize", "TEXT"),
        ("updated_date", "TEXT"),
        ("mainlink", "TEXT"),
        ("issues", "TEXT"),
        ("site", "TEXT"),
        ("submit_date", "TEXT"),
        ("pack", "INTEGER"),
        ("link_type", "TEXT"),
        ("tmp_filename", "TEXT"),
    ]
    _ensure_columns(engine, "ddl_info", ddl_cols)

    # -- Provider_searches Table --
    _ensure_columns(engine, "provider_searches", [("id", "INTEGER"), ("hits", "INTEGER DEFAULT 0")])

    # -- mylar_info bootstrap --
    with engine.begin() as conn:
        try:
            result = conn.execute(text("SELECT DatabaseVersion FROM mylar_info"))
            row = result.fetchone()
            if row is None:
                conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES(0)"))
        except (OperationalError, ProgrammingError):
            try:
                conn.execute(text("ALTER TABLE mylar_info ADD COLUMN DatabaseVersion INTEGER PRIMARY KEY"))
                conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES(0)"))
            except (OperationalError, ProgrammingError):
                pass

    # --- Data integrity cleanup ---
    logger.info("Ensuring DB integrity - Removing all Erroneous Comics (ie. named None)")
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM comics WHERE ComicName='None' OR ComicName LIKE 'Comic ID%' "
                "OR ComicName IS NULL OR ComicName LIKE '%Fetch%failed%'"
            )
        )
        conn.execute(
            text("DELETE FROM issues WHERE ComicName='None' OR ComicName LIKE 'Comic ID%' OR ComicName IS NULL")
        )
        conn.execute(text("DELETE FROM issues WHERE ComicID IS NULL"))
        conn.execute(text("DELETE FROM annuals WHERE ComicName='None' OR ComicName IS NULL OR Issue_Number IS NULL"))
        conn.execute(text("DELETE FROM upcoming WHERE ComicName='None' OR ComicName IS NULL OR IssueNumber IS NULL"))
        conn.execute(text("DELETE FROM importresults WHERE ComicName='None' OR ComicName IS NULL"))
        conn.execute(text("DELETE FROM storyarcs WHERE StoryArcID IS NULL OR StoryArc IS NULL"))
        conn.execute(text("DELETE FROM failed WHERE ComicName='None' OR ComicName IS NULL OR ID IS NULL"))

        logger.info("Correcting Null entries that make the main page break on startup.")
        conn.execute(text("UPDATE comics SET LatestDate='Unknown' WHERE LatestDate='None' OR LatestDate IS NULL"))

        try:
            conn.execute(text("DELETE FROM weekly WHERE Publisher IS NULL AND COMIC IS NOT NULL"))
        except Exception:
            pass

    # --- Config-version-based data migrations ---
    logger.info(
        "[%s]oldconfig_version: %s" % (type(comicarr.CONFIG.OLDCONFIG_VERSION), comicarr.CONFIG.OLDCONFIG_VERSION)
    )
    if comicarr.CONFIG.OLDCONFIG_VERSION is not None:
        if int(comicarr.CONFIG.OLDCONFIG_VERSION) < 12:
            logger.info("now updating table data to ensure DDL is properly populated with correct data.")
            with engine.begin() as conn:
                conn.execute(text("UPDATE snatched SET Provider = 'DDL(GetComics)' WHERE Provider = 'ddl'"))
                conn.execute(text("UPDATE nzblog SET PROVIDER = 'DDL(GetComics)' WHERE PROVIDER = 'ddl'"))
                conn.execute(text("UPDATE rssdb SET site = 'DDL(GetComics)' WHERE site = 'DDL'"))
                conn.execute(text("UPDATE ddl_info SET site = 'DDL(GetComics)' WHERE site IS NULL"))

    # --- Deduplicate and add UNIQUE constraints for upsert tables ---
    _migrate_unique_constraints(engine)

    if dynamic_upgrade is True:
        logger.info("Updating db to include some important changes.")
        helpers.upgrade_dynamic()


def _migrate_unique_constraints(engine):
    """Add UNIQUE constraints to tables that need them for atomic upserts.

    For SQLite, this requires table recreation (cannot ALTER TABLE ADD CONSTRAINT).
    For PostgreSQL/MySQL, uses ALTER TABLE ADD CONSTRAINT directly.

    Only runs once — skips if constraints already exist.
    """
    from comicarr.db import get_dialect

    dialect = get_dialect()

    # Tables needing UNIQUE constraints and their key columns
    # Tables that already have them (comics, rssdb, ref32p, ddl_info, exceptions_log,
    # tmp_searches, notifs, provider_searches, mylar_info) are skipped.
    constraint_map = {
        "issues": (["IssueID"], "uq_issues_issueid"),
        "annuals": (["IssueID"], "uq_annuals_issueid"),
        "storyarcs": (["IssueArcID"], "uq_storyarcs_issuearcid"),
        "readlist": (["IssueID"], "uq_readlist_issueid"),
        "failed": (["ID", "Provider", "NZBName"], "uq_failed_id_provider_nzbname"),
        "upcoming": (["ComicID", "IssueNumber"], "uq_upcoming_comicid_issuenum"),
        "nzblog": (["IssueID", "PROVIDER"], "uq_nzblog_issueid_provider"),
        "importresults": (["impID"], "uq_importresults_impid"),
        "jobhistory": (["JobName"], "uq_jobhistory_jobname"),
        "snatched": (["IssueID", "Status", "Provider"], "uq_snatched_issue_status_provider"),
        "oneoffhistory": (["ComicID", "IssueID"], "uq_oneoffhistory_comicid_issueid"),
        "weekly": (["ComicID", "IssueID"], "uq_weekly_comicid_issueid"),
    }

    inspector = inspect(engine)

    for table_name, (key_cols, constraint_name) in constraint_map.items():
        # Check if constraint already exists
        try:
            existing_uq = inspector.get_unique_constraints(table_name)
            existing_uq_names = {u.get("name") for u in existing_uq}
            if constraint_name in existing_uq_names:
                continue
            # Also check if columns already have unique constraints by column set
            existing_col_sets = {tuple(sorted(u.get("column_names", []))) for u in existing_uq}
            if tuple(sorted(key_cols)) in existing_col_sets:
                continue
        except Exception:
            continue

        logger.info("Adding UNIQUE constraint %s on %s(%s)", constraint_name, table_name, ", ".join(key_cols))

        # Deduplicate first — keep row with highest rowid
        null_checks = " AND ".join(f"{k} IS NOT NULL AND {k} != ''" for k in key_cols)
        dedup_sql = (
            f"DELETE FROM {table_name} WHERE rowid NOT IN ("
            f"SELECT MAX(rowid) FROM {table_name} WHERE {null_checks} GROUP BY {', '.join(key_cols)}"
            f") AND {null_checks}"
        )
        try:
            with engine.begin() as conn:
                conn.execute(text(dedup_sql))
        except (OperationalError, ProgrammingError) as e:
            logger.warn("Dedup on %s failed (non-fatal): %s", table_name, e)

        if dialect == "sqlite":
            # SQLite cannot ALTER TABLE ADD CONSTRAINT — must recreate table
            # Skip for now; the constraint exists in tables.py for new databases.
            # Existing SQLite databases will use the non-atomic upsert fallback
            # until the user runs the migration tool.
            logger.info(
                "SQLite: UNIQUE constraint %s defined in schema for new databases. "
                "Existing database will use legacy upsert until migration.",
                constraint_name,
            )
        else:
            # PostgreSQL / MySQL: add constraint directly
            cols = ", ".join(key_cols)
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} UNIQUE ({cols})"))
            except (OperationalError, ProgrammingError) as e:
                logger.warn("Could not add constraint %s: %s", constraint_name, e)

    # if to_the_rss_update is True:
    #    comicarr.MAINTENANCE = True
    #    comicarr.MAINTENANCE_DB_TOTAL = 1 # set this to 1 to kick it.


def halt():
    global _INITIALIZED, started

    with INIT_LOCK:
        if _INITIALIZED:
            logger.info("Shutting down the background schedulers...")
            SCHED.shutdown(wait=False)

            queue_schedule("all", "shutdown")
            # if NZBPOOL is not None:
            #    queue_schedule('nzb_queue', 'shutdown')
            # if SNPOOL is not None:
            #    queue_schedule('snatched_queue', 'shutdown')

            # if SEARCHPOOL is not None:
            #    queue_schedule('search_queue', 'shutdown')

            # if PPPOOL is not None:
            #    queue_schedule('pp_queue', 'shutdown')

            # if DDLPOOL is not None:
            #    queue_schedule('ddl_queue', 'shutdown')

            _INITIALIZED = False


def shutdown(restart=False, update=False, maintenance=False):

    if maintenance is False:
        cherrypy.engine.exit()
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
        os.execv(sys.executable, popen_list)

    os._exit(0)
