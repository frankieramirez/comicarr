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

import argparse
import locale
import os
import re
import signal
import sys
import threading

from comicarr.app.core import runtime

try:
    import comicarr  # noqa: E402
    from comicarr.app.config import log_level as log_level_source  # noqa: E402
    from comicarr.app.core import logger
    from comicarr.app.core.pidfile import check_stale_pidfile  # noqa: E402
    from comicarr.app.library import filechecker
    from comicarr.app.system import carepackage, maintenance, versioncheck  # noqa: E402
except ModuleNotFoundError as e:
    missing_dependency = e.name or "an application dependency"
    print(
        f"Comicarr could not import {missing_dependency}. Run 'uv sync' "
        "to install the locked application dependencies, then try again.",
        file=sys.stderr,
    )
    raise SystemExit(1) from e

if sys.platform == "win32" and sys.executable.split("\\")[-1] == "pythonw.exe":
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")


def handler_sigterm(signum, frame):
    # Guard the write (documented prior regression): the shutdown/restart
    # API endpoints set runtime.current().signal *before* sending SIGTERM. An
    # unconditional write here clobbers a pending 'restart'/'update'/
    # 'maintenance' intent, degrading a restart to a plain stop.
    if not runtime.current().signal:
        runtime.current().signal = "shutdown"


def main():

    # Fixed paths to comicarr
    if hasattr(sys, "frozen"):
        runtime.current().full_path = os.path.abspath(sys.executable)
    else:
        runtime.current().full_path = os.path.abspath(__file__)

    runtime.current().prog_dir = os.path.dirname(runtime.current().full_path)
    runtime.current().args = sys.argv[1:]

    # From sickbeard
    runtime.current().sys_encoding = None

    try:
        locale.setlocale(locale.LC_ALL, "")
        runtime.current().sys_encoding = locale.getpreferredencoding()
    except (locale.Error, IOError):
        pass

    # for OSes that are poorly configured I'll just force UTF-8
    if not runtime.current().sys_encoding or runtime.current().sys_encoding in ("ANSI_X3.4-1968", "US-ASCII", "ASCII"):
        runtime.current().sys_encoding = "UTF-8"

    # Set up and gather command line arguments
    parser = argparse.ArgumentParser(description="Automated Comic Book Downloader")
    subparsers = parser.add_subparsers(title="Subcommands", dest="maintenance")

    # main parser
    parser.add_argument(
        "--log-level",
        dest="log_level",
        default=None,
        metavar="{0,1,2|warning,info,debug}",
        help=(
            "Logging verbosity: 0/warning warnings and errors, 1/info normal, 2/debug everything. "
            "Overrides COMICARR_LOG_LEVEL and the config file; omit it and those apply."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Deprecated alias for --log-level debug (everything)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Deprecated alias for --log-level warning (warnings and errors only)",
    )
    parser.add_argument("-d", "--daemon", action="store_true", default=False, help="Run as a daemon")
    parser.add_argument("-p", "--port", type=int, default=0, help="Force Comicarr to run on a specified port")
    parser.add_argument(
        "-b", "--backup", nargs="?", const="both", help="Will automatically backup & keep the last 4 rolling copies."
    )
    parser.add_argument(
        "-w",
        "--noweekly",
        action="store_true",
        default=False,
        help="Turn off weekly pull list check on startup (quicker boot sequence)",
    )
    parser.add_argument(
        "-iu",
        "--ignoreupdate",
        action="store_true",
        default=False,
        help="Do not update db if required (for problem bypass)",
    )
    parser.add_argument("--datadir", default=None, help="Specify a directory where to store your data files")
    parser.add_argument("--config", default=None, help="Specify a config file to use")
    parser.add_argument(
        "--nolaunch", action="store_true", default=False, help="Prevent browser from launching on startup"
    )
    parser.add_argument("--pidfile", default=None, help="Create a pid file (only relevant when running as a daemon)")
    parser.add_argument(
        "--safe",
        action="store_true",
        default=False,
        help="redirect the startup page to point to the Manage Comics screen on startup",
    )

    parser_migrate = subparsers.add_parser("migrate", help="Migrate database from SQLite to PostgreSQL or MySQL")
    parser_migrate.add_argument(
        "--from", dest="migrate_source", required=True, help="Source database URL (e.g., sqlite:///path/to/comicarr.db)"
    )
    parser_migrate.add_argument(
        "--to",
        dest="migrate_target",
        required=True,
        help="Target database URL (e.g., postgresql://user:pass@localhost/comicarr)",
    )
    parser_migrate.add_argument(
        "--validate-only",
        dest="migrate_validate",
        action="store_true",
        default=False,
        help="Only validate, do not migrate",
    )
    parser_migrate.add_argument(
        "--batch-size", dest="migrate_batch", type=int, default=5000, help="Rows per batch insert (default: 5000)"
    )
    parser_migrate.add_argument(
        "--yes", dest="migrate_yes", action="store_true", default=False, help="Skip confirmation prompt"
    )

    parser_maintenance = subparsers.add_parser(
        "maintenance", help="Enter maintenance mode (no GUI). Additional commands are available (maintenance --help)"
    )
    parser_maintenance.add_argument(
        "-xj", "--exportjson", default=None, action="store", help="Export existing comicarr.db to json file"
    )  # , default=argparse.SUPPRESS)
    parser_maintenance.add_argument(
        "-id", "--importdatabase", default=None, action="store", help="Import a database into current db"
    )  # , default=argparse.SUPPRESS)
    parser_maintenance.add_argument(
        "-ij",
        "--importjson",
        default=None,
        action="store",
        help='Import a specified json file containing just {"ComicID": "XXXXX"} into current db',
    )  # , default=argparse.SUPPRESS)
    parser_maintenance.add_argument(
        "-st", "--importstatus", default=False, action="store_true", help="Provide current maintenance status"
    )  # , default=argparse.SUPPRESS)
    parser_maintenance.add_argument(
        "-u", "--update", default=False, action="store_true", help="force Comicarr to perform an update as if in GUI"
    )  # , default=argparse.SUPPRESS)
    parser_maintenance.add_argument(
        "-fs", "--fixslashes", default=False, action="store_true", help="remove double-slashes from within paths in db"
    )  # , default=argparse.SUPPRESS)
    parser_maintenance.add_argument(
        "-cp",
        "--clearprovidertable",
        default=False,
        action="store_true",
        help="clear out the provider_searches table in db",
    )  # , default=argparse.SUPPRESS)
    parser_maintenance.add_argument(
        "-care", "--carepackage", default=False, action="store_true", help="generate a carepackage"
    )  # , default=argparse.SUPPRESS)
    # parser_maintenance.add_argument('-it', '--importtext', action='store', help='Import a specified text file into current db')

    args = vars(parser.parse_args())

    # these need to be set for things to register
    args_exportjson = args.get("exportjson")
    args_importdatabase = args.get("importdatabase")
    args_importjson = args.get("importjson")
    args_importstatus = args.get("importstatus")
    args_update = args.get("update")
    args_fixslashes = args.get("fixslashes")
    args_clearprovidertable = args.get("clearprovidertable")
    args_carepackage = args.get("carepackage")
    args_maintenance = args.get("maintenance")
    args_verbose = args.get("verbose")
    args_quiet = args.get("quiet")
    args_log_level = args.get("log_level")
    args_ignoreupdate = args.get("ignoreupdate")
    args_daemon = args.get("daemon")
    args_pidfile = args.get("pidfile")
    args_datadir = args.get("datadir")
    args_config = args.get("config")
    args_port = args.get("port")
    args_nolaunch = args.get("nolaunch")
    args_backup = args.get("backup")
    if not any([args_backup == "ini", args_backup == "db", args_backup == "both"]):
        args_backup = False

    # Handle migrate subcommand (runs independently, then exits)
    if args.get("maintenance") == "migrate" or args.get("migrate_source"):
        from comicarr.app.system.db_migrate import migrate, validate

        source = args.get("migrate_source")
        target = args.get("migrate_target")
        if not source or not target:
            print("Usage: python3 Comicarr.py migrate --from sqlite:///path/to/db --to postgresql://...")
            sys.exit(1)
        if args.get("migrate_validate"):
            ok = validate(source, target)
            sys.exit(0 if ok else 1)
        if not args.get("migrate_yes"):
            from comicarr.app.system.db_migrate import _mask_password

            print("This will migrate data from:")
            print(f"  Source: {_mask_password(source)}")
            print(f"  Target: {_mask_password(target)}")
            confirm = input("Proceed? [y/N] ").strip().lower()
            if confirm != "y":
                print("Aborted.")
                sys.exit(1)
        ok = migrate(source, target, batch_size=args.get("migrate_batch", 5000))
        sys.exit(0 if ok else 1)

    if args_maintenance:
        if all(
            [
                args_exportjson is None,
                args_importdatabase is None,
                args_importjson is None,
                args_importstatus is False,
                args_update is False,
                args_fixslashes is False,
                args_clearprovidertable is False,
                args_carepackage is False,
            ]
        ):
            print("Expecting subcommand with the maintenance positional argumeent")
            sys.exit()
        runtime.current().maintenance = True
    else:
        runtime.current().maintenance = False

    if runtime.current().maintenance is True and args_carepackage is True:
        print(
            "[MAINTENANCE-MODE][CAREPACKAGE] Please wait....attempting to generate carepackage (this can take a few seconds)..."
        )
        runtime.current().log_level = 0
        if args_datadir:
            runtime.current().data_dir = args_datadir
        else:
            runtime.current().data_dir = runtime.current().prog_dir
        cp = carepackage.carePackage(maintenance=True)
        resp = cp.loaders()
        if resp["status"] == "success":
            print(
                "%s[CAREPACKAGE] Successfully generated carepackage @ %s" % ("[MAINTENANCE-MODE]", resp["carepackage"])
            )
        else:
            print(
                "%s[CAREPACKAGE] Unable to generate carepackage. Error returned as : %s"
                % ("[MAINTENANCE-MODE]", resp["carepackage"])
            )
        print("Exiting....")
        sys.exit()

    # Startup args are the top of the precedence chain (args > COMICARR_LOG_LEVEL
    # > config), but only when one was actually passed: leaving this None is what
    # lets the environment and the config file be heard at all.
    #
    # `--log-level` accepts a number or a name; an unusable value supplies
    # nothing, so it falls through to the aliases and then to the layers below
    # rather than blocking the boot over a typo.
    runtime.current().log_level = None
    if args_log_level is not None:
        argument_level, argument_notices = log_level_source.parse_level(
            args_log_level, log_level_source.SOURCE_ARGUMENT
        )
        for notice in argument_notices:
            print(notice)
        if argument_level is not None:
            runtime.current().log_level = argument_level
            print("Log level set to %s by startup argument." % log_level_source.describe_level(argument_level))
    if runtime.current().log_level is None and args_verbose:
        print("--verbose is deprecated; use --log-level debug. Log level set to 2 (debug).")
        runtime.current().log_level = 2
    if runtime.current().log_level is None and args_quiet:
        print("--quiet is deprecated; use --log-level warning. Log level set to 0 (warning).")
        runtime.current().log_level = 0

    if args_ignoreupdate:
        runtime.current().maintenance = False

    if args_daemon:
        if sys.platform == "win32":
            print("Daemonize not supported under Windows, starting normally")
        else:
            runtime.current().daemon = True

    if args_pidfile:
        runtime.current().pidfile = str(args_pidfile)

        # If the pidfile already exists, comicarr may still be running, so exit
        if os.path.exists(runtime.current().pidfile):
            if check_stale_pidfile(runtime.current().pidfile):
                os.unlink(runtime.current().pidfile)
            else:
                sys.exit("PID file '" + runtime.current().pidfile + "' already exists. Exiting.")

        # The pidfile is only useful in daemon mode, make sure we can write the file properly
        if runtime.current().daemon:
            runtime.current().createpid = True
            curpid = os.getpid()
            try:
                open(runtime.current().pidfile, "w").write(f"{curpid}\n")
            except IOError as e:
                raise SystemExit("Unable to write PID file: %s [%d]" % (e.strerror, e.errno)) from e
        else:
            print("Not running in daemon mode. PID file creation disabled.")

    if args_datadir:
        runtime.current().data_dir = args_datadir
    else:
        runtime.current().data_dir = runtime.current().prog_dir

    if args_config:
        runtime.current().config_file = args_config
    else:
        runtime.current().config_file = os.path.join(runtime.current().data_dir, "config.ini")

    try:
        backup = False
        backup_db = False
        backup_cfg = False
        if args_backup:
            backup = True
            if args_backup == "ini":
                backup_cfg = True
            elif args_backup == "db":
                backup_db = True
            elif args_backup == "both":
                backup_cfg = True
                backup_db = True
            else:
                backup = False
    except Exception:
        backup = False

    # Put the database in the data directory
    runtime.current().db_file = os.path.join(runtime.current().data_dir, "comicarr.db")

    # Read config and start logging
    if runtime.current().maintenance is False:
        print("Initializing startup sequence....")

    # try:
    comicarr.initialize(runtime.current().config_file)
    # except Exception as e:
    #    print e
    #    raise SystemExit('FATAL ERROR')

    # check for clearprovidertable value after ini load
    if runtime.current().config.CLEAR_PROVIDER_TABLE is True:
        logger.info("[CLEAR_PROVIDER_TABLE] forcing over-ride value from config.ini")
        args_clearprovidertable = True
        runtime.current().maintenance = True

    if runtime.current().maintenance is False:
        filechecker.validateAndCreateDirectory(runtime.current().data_dir, True, dmode="DATA")

        # Make sure the data directory is writeable
        if not os.access(runtime.current().data_dir, os.W_OK):
            raise SystemExit("Cannot write to the data directory: " + runtime.current().data_dir + ". Exiting...")

    # backup the db and configs before they load.
    if (backup is True and any([backup_cfg is True, backup_db is True])) or runtime.current().config.BACKUP_ON_START:
        if runtime.current().config.BACKUP_ON_START:
            backup_cfg = True
            backup_db = True
        if runtime.current().config.BACKUP_ON_START or all([backup_cfg is True, backup_db is True]):
            logger.info("[AUTO-BACKUP] Backing up comicarr.db & config.ini files for safety.")
        elif backup_cfg is True:
            logger.info("[AUTO-BACKUP] Backing up config.ini file for safety.")
        elif backup_db is True:
            logger.info("[AUTO-BACKUP] Backing up comicarr.db file for safety.")

        mm = maintenance.Maintenance("backup")
        back_check = mm.backup_files(cfg=backup_cfg, dbs=backup_db)
        failures = [
            re.sub("comicarr database", "comicarr.db", x["file"]) for x in back_check if x["status"] == "failure"
        ]
        successes = [
            re.sub("comicarr database", "comicarr.db", x["file"]) for x in back_check if x["status"] == "success"
        ]
        if failures:
            logger.warn("[AUTO-BACKUP] Failure backing up %s files [%s]" % (len(failures), failures))
        if successes:
            logger.info("[AUTO-BACKUP] Successful backup of %s files [%s]" % (len(successes), successes))

    # Rename the main thread
    threading.current_thread().name = "MAIN"

    if runtime.current().daemon:
        comicarr.daemonize()

    if runtime.current().maintenance is True and (
        runtime.current().maintenance_update
        or any(
            [
                args_exportjson,
                args_importjson,
                args_update is True,
                args_importstatus is True,
                args_fixslashes is True,
                args_clearprovidertable is True,
                args_carepackage is True,
            ]
        )
    ):
        # Start up a temporary maintenance server for GUI display only.
        loggermode = "[MAINTENANCE-MODE]"
        versioncheck.versionload()

        restart_method = True  # True will restart, False will shutdown.

        if runtime.current().maintenance_update:
            ur = maintenance.Maintenance("db update")
            restart_method = ur.update_db()
            if restart_method is None:
                restart_method = True

        elif args_importstatus:
            cs = maintenance.Maintenance("status")
            cs.check_status()
        else:
            logger.info("%s Initializing maintenance mode" % loggermode)

            if args_update is True:
                logger.info("%s Attempting to update Comicarr so things can work again..." % loggermode)
                try:
                    comicarr.shutdown(restart=True, update=True, maintenance=True)
                except Exception as e:
                    sys.exit("%s Comicarr failed to update: %s" % (loggermode, e))

            elif args_importdatabase:
                # for attempted db import.
                maintenance_path = args_importdatabase
                logger.info("%s db path accepted as %s" % (loggermode, maintenance_path))
                di = maintenance.Maintenance("database-import", file=maintenance_path)
                di.database_import()
            elif args_importjson:
                # for attempted file re-import (json format)
                maintenance_path = args_importjson
                logger.info(
                    "%s file indicated as being in json format - path accepted as %s" % (loggermode, maintenance_path)
                )
                ij = maintenance.Maintenance("json-import", file=maintenance_path)
                ij.json_import()
            # elif args_importtext:
            #    #for attempted file re-import (list format)
            #    maintenance_path = args_importtext
            #    logger.info('%s file indicated as being in list format - path accepted as %s' % (loggermode, maintenance_path))
            #    it = maintenance.Maintenance('list-import', file=maintenance_path)
            #    t = it.list_import()
            elif args_exportjson:
                # for export of db comicid's in json format
                maintenance_path = args_exportjson
                logger.info(
                    "%s file indicated as being written to json format - destination accepted as %s"
                    % (loggermode, maintenance_path)
                )
                ej = maintenance.Maintenance("json-export", output=maintenance_path)
                ej.json_export()
            elif args_fixslashes:
                # for running the fix slashes on the db manually
                logger.info("%s method indicated as fix slashes" % loggermode)
                fs = maintenance.Maintenance("fixslashes")
                fs.fix_slashes()
            elif args_clearprovidertable:
                # for running the clearprovidertable on the db manually
                logger.info("%s method indicated as fix clearprovidertable" % loggermode)
                fs = maintenance.Maintenance("clearprovidertable")
                fs.clear_provider_table()
            else:
                logger.info("%s Not a valid command: %s" % (loggermode, args_maintenance))
                sys.exit()
            logger.info("%s Exiting Maintenance mode" % (loggermode))

        # restart automatically after maintenance has completed...

        comicarr.shutdown(restart=restart_method, maintenance=True)

    # Force the http port if neccessary
    if args_port > 0:
        http_port = args_port
        logger.info("Starting Comicarr on forced port: %i" % http_port)
    else:
        http_port = int(runtime.current().config.HTTP_PORT)

    # Generate setup token if first-run setup is needed
    if not runtime.current().config.HTTP_USERNAME or not runtime.current().config.HTTP_PASSWORD:
        import secrets

        from comicarr.app.system import service as system_service

        runtime.current().setup_token = secrets.token_urlsafe(32)
        system_service.announce_setup_token(runtime.current().setup_token)

    # check for version here after web server initialized so it doesn't try to repeatidly hit github
    # for version info if it's already running
    versioncheck.versionload()

    from comicarr.app.system.dependency_check import RuntimeCapabilityDiagnostics

    RuntimeCapabilityDiagnostics().loaders()

    # Configuration, schema readiness, encrypted secrets, setup token, and
    # version metadata are now available. Create the one canonical runtime
    # before any scheduler or worker can observe mutable queue/lock state.
    from comicarr.app.core.runtime import create_runtime

    ctx = create_runtime()

    if runtime.current().config.LAUNCH_BROWSER and not args_nolaunch:
        comicarr.launch_browser(runtime.current().config.HTTP_HOST, http_port, runtime.current().config.HTTP_ROOT)

    # Start the background threads
    comicarr.start(ctx)

    # Register the SIGTERM handler before startup replay: replay_pipeline()
    # below can spend real time probing downloaders and inline-redriving PP,
    # so a SIGTERM during that window must be caught here to preserve any
    # pending restart/update intent (handler_sigterm guards runtime.current().signal).
    signal.signal(signal.SIGTERM, handler_sigterm)

    # Startup recovery replay (U6). MUST run here: after comicarr.start()
    # returns (start() is one unbroken `with init_lock:` block, so the lock is
    # now released — replay never acquires init_lock and cannot starve a
    # concurrent SIGTERM halt()), and after credential decryption (encrypt_items
    # ran inside comicarr.initialize() above, so downloader-client creds are no
    # longer ciphertext), and before uvicorn.run() (workers are already running
    # so re-enqueued/STILL items are picked up by the live monitors). Idempotent
    # and re-runnable; a per-row failure is logged and skipped, never fatal.
    try:
        from comicarr.app.downloads import recovery

        if runtime.current().acquisition_workers_blocked:
            logger.warn(
                "[RECOVERY] Startup replay skipped because acquisition workers are blocked: %s"
                % runtime.current().acquisition_block_reason
            )
        else:
            recovery.replay_pipeline()
    except Exception as e:
        logger.error("[RECOVERY] Startup replay raised — continuing startup (resumable next start): %s" % e)

    import uvicorn

    ssl_kwargs = {}
    if runtime.current().config.ENABLE_HTTPS:
        ssl_kwargs["ssl_certfile"] = runtime.current().config.HTTPS_CERT
        ssl_kwargs["ssl_keyfile"] = runtime.current().config.HTTPS_KEY

    uvicorn.run(
        "comicarr.app.main:app",
        host=runtime.current().config.HTTP_HOST,
        port=http_port,
        log_level="info",
        workers=1,
        **ssl_kwargs,
    )

    if runtime.current().signal == "restart":
        comicarr.shutdown(restart=True)
    elif runtime.current().signal == "update":
        comicarr.shutdown(restart=True, update=True)
    else:
        comicarr.shutdown()

    return


if __name__ == "__main__":
    main()
