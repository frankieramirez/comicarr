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

import os, sys, locale
import argparse
import errno
import shutil
import time
import re
import threading
import signal
import importlib

sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'lib'))

class test_the_requires(object):

    def __init__(self):
        if hasattr(sys, 'frozen'):
            full_path = os.path.abspath(sys.executable)
        else:
            full_path = os.path.abspath(__file__)

        prog_dir = os.path.dirname(full_path)
        data_dir = prog_dir
        if len(sys.argv) > 0:
            ddir = [x for x in sys.argv if 'datadir' in sys.argv]
            if ddir:
                ddir = re.sub('--datadir=', ''.join(ddir)).strip()
                data_dir = re.sub('--datadir ', ddir).strip()

        docker = False
        d_path = '/proc/self/cgroup'
        if os.path.exists('/.dockerenv') or 'KUBERNETES_SERVICE_HOST' in os.environ or os.path.isfile(d_path) and any('docker' in line for line in open(d_path)):
            print('[DOCKER-AWARE] Docker installation detected.')
            docker = True

        self.req_file_present = True
        self.reqfile = os.path.join(data_dir, 'requirements.txt')

        if any([docker, data_dir != prog_dir]) and not os.path.isfile(self.reqfile):
            self.reqfile = os.path.join(prog_dir, 'requirements.txt')

        if not os.path.isfile(self.reqfile):
            self.req_file_present = False

        self.nfo_file = os.path.join(data_dir, 'ascii_logo.nfo')
        if not self.nfo_file:
            self.nfo_file = os.path.join(prog_dir, 'ascii_logo.nfo')

        if not self.nfo_file:
            print('[WARNING] Unable to load ascii_logo. You\'re missing something cool...')
        else:
            with open(self.nfo_file, 'r') as f:
                for line in f:
                    print(line.rstrip())
            print(f'{"-":-<60}')

        self.ops = ['==', '>=', '<=']
        self.mod_list = {}
        self.mappings = {'APScheduler': 'apscheduler',
                         'beautifulsoup4': 'bs4',
                         'Pillow': 'PIL',
                         'pycryptodome': 'Crypto',
                         'pystun': 'stun',
                         'PySocks': 'socks'}

    def check_it(self):
        if not self.req_file_present:
            print('[REQUIREMENTS MISSING] Unable to locate requirements.txt in %s. Make sure it exists, or use --data-dir to specify location' % self.reqfile)
            sys.exit()

        with open(self.reqfile, 'r') as file:
            for line in file.readlines():
                operator = [x for x in self.ops if x in line]
                if operator:
                    operator = ''.join(operator)
                    lf = line.find(operator)
                    module_name = line[:lf].strip()
                    module_version = line[lf+len(operator):].strip()
                    if module_name == 'requests[socks]':
                        self.mod_list['requests'] = module_version
                        module_name = 'PySocks'
                    self.mod_list[module_name] = {'version': module_version, 'operator': operator}

        failures = {}
        for key,value in self.mod_list.items():
            try:
                module = key
                if key in self.mappings:
                    module = self.mappings[key]
                try:
                    importlib.import_module(module, package=None)
                except Exception:
                    importlib.import_module(module.lower(), package=None)
            except (ModuleNotFoundError) as e:
                failures[key] = value

        if failures:
            if 'PySocks' in failures:
                print('[MODULES UNAVAILABLE] Some modules are missing and may need to be installed via pip before proceeding. PySocks is required only if using proxies.')
            else:
                print('[MODULES UNAVAILABLE] Required modules are missing and need to be installed via pip before proceeding.')
            print('[MODULES UNAVAILABLE] Reinstall each of the listed module(s) below or reinstall the included requirements.txt file')
            print('[MODULES UNAVAILABLE] The following modules are missing:')
            for modname, modreq in failures.items():
                print('[MODULES UNAVAILABLE]  %s %s%s' % (modname, modreq['operator'], modreq['version']))
            if all(['PySocks' in failures, len(failures)>1]) or 'PySocks' not in failures:
                sys.exit()

t = test_the_requires()
t.check_it()

import comicarr

from comicarr import (
    carepackage,
    filechecker,
    logger,
    maintenance,
    dependency_check,
    versioncheck,
)

import argparse


if ( sys.platform == 'win32' and sys.executable.split( '\\' )[-1] == 'pythonw.exe'):
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")

def handler_sigterm(signum, frame):
    comicarr.SIGNAL = 'shutdown'

def check_stale_pidfile(pidfile):
    ''' Return True if pidfile doesn't hold a numeric value, or it
        does, but it doesn't correspond with a valid currently used PID.
        Only supports linux /proc fs way of getting cmdlinee by PID.
        Returns:  Unsupported, assume it's not stale (False)
                  pidfile contents aren't numeric, return True
                  On linux, if the /proc/{pid}/cmdline file doesn't
                  exist: True (this is definitive)
                  Otherwise return True if python isn't in the cmdline
    '''

    if sys.platform != 'linux' or not os.path.exists('/proc'):
        return False

    with open(pidfile, 'rt', encoding='utf-8') as fd:
        sval = fd.read()

    if not sval.isdigit():
        return True

    checkpid = int(sval, 10)
    cmdlinepath = f'/proc/{checkpid}/cmdline'
    if not os.path.exists(cmdlinepath):
        return True

# We'll simplify the check here and only verify that the word python is part
# of the commandline

    with open(cmdlinepath, 'rt', encoding='utf-8') as fd:
        cmdline = fd.read().replace('\0')

# If pytohn is in the cmdline, then we assume it's not stale.
    return ('python' not in cmdline)

def main():

    # Fixed paths to comicarr
    if hasattr(sys, 'frozen'):
        comicarr.FULL_PATH = os.path.abspath(sys.executable)
    else:
        comicarr.FULL_PATH = os.path.abspath(__file__)

    comicarr.PROG_DIR = os.path.dirname(comicarr.FULL_PATH)
    comicarr.ARGS = sys.argv[1:]

    # From sickbeard
    comicarr.SYS_ENCODING = None

    try:
        locale.setlocale(locale.LC_ALL, "")
        comicarr.SYS_ENCODING = locale.getpreferredencoding()
    except (locale.Error, IOError):
        pass

    # for OSes that are poorly configured I'll just force UTF-8
    if not comicarr.SYS_ENCODING or comicarr.SYS_ENCODING in ('ANSI_X3.4-1968', 'US-ASCII', 'ASCII'):
        comicarr.SYS_ENCODING = 'UTF-8'

    if not logger.LOG_LANG.startswith('en'):
        print('language detected as non-English (%s). Forcing specific logging module - errors WILL NOT be captured in the logs' % logger.LOG_LANG)
    else:
        print('log language set to %s' % logger.LOG_LANG)

    # Set up and gather command line arguments
    parser = argparse.ArgumentParser(description='Automated Comic Book Downloader')
    subparsers = parser.add_subparsers(title='Subcommands', dest='maintenance')

    #main parser
    parser.add_argument('-v', '--verbose', action='store_true', default=False, help='Increase console logging verbosity')
    parser.add_argument('-q', '--quiet', action='store_true', default=False, help='Turn off console logging')
    parser.add_argument('-d', '--daemon', action='store_true', default=False, help='Run as a daemon')
    parser.add_argument('-p', '--port', type=int, default=0, help='Force Comicarr to run on a specified port')
    parser.add_argument('-b', '--backup', nargs='?', const='both', help='Will automatically backup & keep the last 4 rolling copies.')
    parser.add_argument('-w', '--noweekly', action='store_true', default=False, help='Turn off weekly pull list check on startup (quicker boot sequence)')
    parser.add_argument('-iu', '--ignoreupdate', action='store_true', default=False, help='Do not update db if required (for problem bypass)')
    parser.add_argument('--datadir', default=None, help='Specify a directory where to store your data files')
    parser.add_argument('--config', default=None, help='Specify a config file to use')
    parser.add_argument('--nolaunch', action='store_true', default=False, help='Prevent browser from launching on startup')
    parser.add_argument('--pidfile', default=None, help='Create a pid file (only relevant when running as a daemon)')
    parser.add_argument('--safe', action='store_true', default=False, help='redirect the startup page to point to the Manage Comics screen on startup')

    parser_migrate = subparsers.add_parser('migrate', help='Migrate database from SQLite to PostgreSQL or MySQL')
    parser_migrate.add_argument('--from', dest='migrate_source', required=True, help='Source database URL (e.g., sqlite:///path/to/comicarr.db)')
    parser_migrate.add_argument('--to', dest='migrate_target', required=True, help='Target database URL (e.g., postgresql://user:pass@localhost/comicarr)')
    parser_migrate.add_argument('--validate-only', dest='migrate_validate', action='store_true', default=False, help='Only validate, do not migrate')
    parser_migrate.add_argument('--batch-size', dest='migrate_batch', type=int, default=5000, help='Rows per batch insert (default: 5000)')
    parser_migrate.add_argument('--yes', dest='migrate_yes', action='store_true', default=False, help='Skip confirmation prompt')

    parser_maintenance = subparsers.add_parser('maintenance', help='Enter maintenance mode (no GUI). Additional commands are available (maintenance --help)')
    parser_maintenance.add_argument('-xj', '--exportjson', default=None, action='store', help='Export existing comicarr.db to json file') #, default=argparse.SUPPRESS)
    parser_maintenance.add_argument('-id', '--importdatabase', default=None, action='store', help='Import a database into current db') # , default=argparse.SUPPRESS)
    parser_maintenance.add_argument('-ij', '--importjson', default=None, action='store', help='Import a specified json file containing just {"ComicID": "XXXXX"} into current db') #, default=argparse.SUPPRESS)
    parser_maintenance.add_argument('-st', '--importstatus', default=False, action='store_true', help='Provide current maintenance status') #, default=argparse.SUPPRESS)
    parser_maintenance.add_argument('-u', '--update', default=False, action='store_true', help='force Comicarr to perform an update as if in GUI') #, default=argparse.SUPPRESS)
    parser_maintenance.add_argument('-fs', '--fixslashes', default=False, action='store_true', help='remove double-slashes from within paths in db') #, default=argparse.SUPPRESS)
    parser_maintenance.add_argument('-cp', '--clearprovidertable', default=False, action='store_true', help='clear out the provider_searches table in db') #, default=argparse.SUPPRESS)
    parser_maintenance.add_argument('-care', '--carepackage', default=False, action='store_true', help='generate a carepackage') #, default=argparse.SUPPRESS)
    #parser_maintenance.add_argument('-it', '--importtext', action='store', help='Import a specified text file into current db')

    args = vars(parser.parse_args())

    #these need to be set for things to register
    args_exportjson = args.get('exportjson')
    args_importdatabase = args.get('importdatabase')
    args_importjson = args.get('importjson')
    args_importstatus = args.get('importstatus')
    args_update = args.get('update')
    args_fixslashes = args.get('fixslashes')
    args_clearprovidertable = args.get('clearprovidertable')
    args_carepackage = args.get('carepackage')
    args_maintenance = args.get('maintenance')
    args_verbose = args.get('verbose')
    args_quiet = args.get('quiet')
    args_ignoreupdate = args.get('ignoreupdate')
    args_daemon = args.get('daemon')
    args_pidfile = args.get('pidfile')
    args_datadir = args.get('datadir')
    args_config = args.get('config')
    args_safe = args.get('safe')
    args_noweekly = args.get('noweekly')
    args_port = args.get('port')
    args_nolaunch = args.get('nolaunch')
    args_backup = args.get('backup')
    if not any([args_backup == 'ini', args_backup == 'db', args_backup == 'both']):
        args_backup = False

    # Handle migrate subcommand (runs independently, then exits)
    if args.get('maintenance') == 'migrate' or args.get('migrate_source'):
        from comicarr.db_migrate import migrate, validate
        source = args.get('migrate_source')
        target = args.get('migrate_target')
        if not source or not target:
            print('Usage: python3 Comicarr.py migrate --from sqlite:///path/to/db --to postgresql://...')
            sys.exit(1)
        if args.get('migrate_validate'):
            ok = validate(source, target)
            sys.exit(0 if ok else 1)
        if not args.get('migrate_yes'):
            from comicarr.db_migrate import _mask_password
            print(f'This will migrate data from:')
            print(f'  Source: {_mask_password(source)}')
            print(f'  Target: {_mask_password(target)}')
            confirm = input('Proceed? [y/N] ').strip().lower()
            if confirm != 'y':
                print('Aborted.')
                sys.exit(1)
        ok = migrate(source, target, batch_size=args.get('migrate_batch', 5000))
        sys.exit(0 if ok else 1)

    if args_maintenance:
        if all([args_exportjson is None, args_importdatabase is None, args_importjson is None, args_importstatus is False, args_update is False, args_fixslashes is False, args_clearprovidertable is False, args_carepackage is False]):
            print('Expecting subcommand with the maintenance positional argumeent')
            sys.exit()
        comicarr.MAINTENANCE = True
    else:
        comicarr.MAINTENANCE = False

    if comicarr.MAINTENANCE is True and args_carepackage is True:
        print('[MAINTENANCE-MODE][CAREPACKAGE] Please wait....attempting to generate carepackage (this can take a few seconds)...')
        comicarr.LOG_LEVEL = 0
        if args_datadir:
            comicarr.DATA_DIR = args_datadir
        else:
            comicarr.DATA_DIR = comicarr.PROG_DIR
        cp = carepackage.carePackage(maintenance=True)
        resp = cp.loaders()
        if resp['status'] == 'success':
            print('%s[CAREPACKAGE] Successfully generated carepackage @ %s' % ('[MAINTENANCE-MODE]', resp['carepackage']))
        else:
            print('%s[CAREPACKAGE] Unable to generate carepackage. Error returned as : %s' % ('[MAINTENANCE-MODE]', resp['carepackage']))
        print('Exiting....')
        sys.exit()

    if args_verbose:
        print('Verbose/Debugging mode enabled...')
        comicarr.LOG_LEVEL = 2
    elif args_quiet:
        comicarr.QUIET = True
        print('Quiet logging mode enabled...')
        comicarr.LOG_LEVEL = 0
    else:
        comicarr.LOG_LEVEL = None

    if args_ignoreupdate:
        comicarr.MAINTENANCE = False

    if args_daemon:
        if sys.platform == 'win32':
            print("Daemonize not supported under Windows, starting normally")
        else:
            comicarr.DAEMON = True

    if args_pidfile:
        comicarr.PIDFILE = str(args_pidfile)

        # If the pidfile already exists, comicarr may still be running, so exit
        if os.path.exists(comicarr.PIDFILE):
            if check_stale_pidfile(comicarr.PIDFILE):
                os.unlink(comicarr.PIDFILE)
            else:
                sys.exit("PID file '" + comicarr.PIDFILE + "' already exists. Exiting.")

        # The pidfile is only useful in daemon mode, make sure we can write the file properly
        if comicarr.DAEMON:
            comicarr.CREATEPID = True
            curpid = os.getpid()
            try:
                open(comicarr.PIDFILE, 'w').write(f"{curpid}\n")
            except IOError as e:
                raise SystemExit("Unable to write PID file: %s [%d]" % (e.strerror, e.errno))
        else:
            print("Not running in daemon mode. PID file creation disabled.")

    if args_datadir:
        comicarr.DATA_DIR = args_datadir
    else:
        comicarr.DATA_DIR = comicarr.PROG_DIR

    if args_config:
        comicarr.CONFIG_FILE = args_config
    else:
        comicarr.CONFIG_FILE = os.path.join(comicarr.DATA_DIR, 'config.ini')

    if args_safe:
        comicarr.SAFESTART = True
    else:
        comicarr.SAFESTART = False

    if args_noweekly:
        comicarr.NOWEEKLY = True
    else:
        comicarr.NOWEEKLY = False

    try:
        backup = False
        backup_db = False
        backup_cfg = False
        if args_backup:
            backup = True
            if args_backup == 'ini':
                backup_cfg = True
            elif args_backup == 'db':
                backup_db = True
            elif args_backup == 'both':
                backup_cfg = True
                backup_db = True
            else:
                backup = False
    except Exception as e:
        backup = False

    # Put the database in the DATA_DIR
    comicarr.DB_FILE = os.path.join(comicarr.DATA_DIR, 'comicarr.db')

    # Read config and start logging
    if comicarr.MAINTENANCE is False:
        print('Initializing startup sequence....')

    #try:
    comicarr.initialize(comicarr.CONFIG_FILE)
    #except Exception as e:
    #    print e
    #    raise SystemExit('FATAL ERROR')


    # check for clearprovidertable value after ini load
    if comicarr.CONFIG.CLEAR_PROVIDER_TABLE is True:
        logger.info('[CLEAR_PROVIDER_TABLE] forcing over-ride value from config.ini')
        args_clearprovidertable = True
        comicarr.MAINTENANCE = True

    if comicarr.MAINTENANCE is False:
        filechecker.validateAndCreateDirectory(comicarr.DATA_DIR, True, dmode='DATA')

        # Make sure the DATA_DIR is writeable
        if not os.access(comicarr.DATA_DIR, os.W_OK):
            raise SystemExit('Cannot write to the data directory: ' + comicarr.DATA_DIR + '. Exiting...')

    # backup the db and configs before they load.
    if (backup is True and any([backup_cfg is True, backup_db is True])) or comicarr.CONFIG.BACKUP_ON_START:
        if comicarr.CONFIG.BACKUP_ON_START:
            backup_cfg = True
            backup_db = True
        if comicarr.CONFIG.BACKUP_ON_START or all([backup_cfg is True, backup_db is True]):
            logger.info('[AUTO-BACKUP] Backing up comicarr.db & config.ini files for safety.')
        elif backup_cfg is True:
            logger.info('[AUTO-BACKUP] Backing up config.ini file for safety.')
        elif backup_db is True:
            logger.info('[AUTO-BACKUP] Backing up comicarr.db file for safety.')

        mm = maintenance.Maintenance('backup')
        back_check = mm.backup_files(cfg=backup_cfg, dbs=backup_db)
        failures = [re.sub('comicarr database', 'comicarr.db', x['file']) for x in back_check if x['status'] == 'failure']
        successes = [re.sub('comicarr database', 'comicarr.db', x['file']) for x in back_check if x['status'] == 'success']
        if failures:
            logger.warn('[AUTO-BACKUP] Failure backing up %s files [%s]' % (len(failures), failures))
        if successes:
            logger.info('[AUTO-BACKUP] Successful backup of %s files [%s]' % (len(successes), successes))

    # Rename the main thread
    threading.current_thread().name = "MAIN"

    if comicarr.DAEMON:
        comicarr.daemonize()

    #print('comicarr.MAINTENANCE: %s'%  comicarr.MAINTENANCE)
    #print('comicarr.MAINTENANCE_TOTAL: %s'%  comicarr.MAINTENANCE_DB_TOTAL)
    if comicarr.MAINTENANCE is True and (comicarr.MAINTENANCE_UPDATE or any([args_exportjson, args_importjson, args_update is True, args_importstatus is True, args_fixslashes is True, args_clearprovidertable is True, args_carepackage is True])):
        # Start up a temporary maintenance server for GUI display only.
        loggermode = '[MAINTENANCE-MODE]'
        versioncheck.versionload()

        restart_method = True  #True will restart, False will shutdown.

        if comicarr.MAINTENANCE_UPDATE:
            ur = maintenance.Maintenance('db update')
            restart_method = ur.update_db()
            if restart_method is None:
                restart_method = True

        elif args_importstatus:
            cs = maintenance.Maintenance('status')
            cstat = cs.check_status()
        else:
            logger.info('%s Initializing maintenance mode' % loggermode)

            if args_update is True:
                logger.info('%s Attempting to update Comicarr so things can work again...' % loggermode)
                try:
                    comicarr.shutdown(restart=True, update=True, maintenance=True)
                except Exception as e:
                    sys.exit('%s Comicarr failed to update: %s' % (loggermode, e))

            elif args_importdatabase:
                #for attempted db import.
                maintenance_path = args_importdatabase
                logger.info('%s db path accepted as %s' % (loggermode, maintenance_path))
                di = maintenance.Maintenance('database-import', file=maintenance_path)
                d = di.database_import()
            elif args_importjson:
                #for attempted file re-import (json format)
                maintenance_path = args_importjson
                logger.info('%s file indicated as being in json format - path accepted as %s' % (loggermode, maintenance_path))
                ij = maintenance.Maintenance('json-import', file=maintenance_path)
                j = ij.json_import()
            #elif args_importtext:
            #    #for attempted file re-import (list format)
            #    maintenance_path = args_importtext
            #    logger.info('%s file indicated as being in list format - path accepted as %s' % (loggermode, maintenance_path))
            #    it = maintenance.Maintenance('list-import', file=maintenance_path)
            #    t = it.list_import()
            elif args_exportjson:
                #for export of db comicid's in json format
                maintenance_path = args_exportjson
                logger.info('%s file indicated as being written to json format - destination accepted as %s' % (loggermode, maintenance_path))
                ej = maintenance.Maintenance('json-export', output=maintenance_path)
                j = ej.json_export()
            elif args_fixslashes:
                #for running the fix slashes on the db manually
                logger.info('%s method indicated as fix slashes' % loggermode)
                fs = maintenance.Maintenance('fixslashes')
                j = fs.fix_slashes()
            elif args_clearprovidertable:
                #for running the clearprovidertable on the db manually
                logger.info('%s method indicated as fix clearprovidertable' % loggermode)
                fs = maintenance.Maintenance('clearprovidertable')
                j = fs.clear_provider_table()
            else:
                logger.info('%s Not a valid command: %s' % (loggermode, args_maintenance))
                sys.exit()
            logger.info('%s Exiting Maintenance mode' % (loggermode))

        #restart automatically after maintenance has completed...

        comicarr.shutdown(restart=restart_method, maintenance=True)

    # Force the http port if neccessary
    if args_port > 0:
        http_port = args_port
        logger.info('Starting Comicarr on forced port: %i' % http_port)
    else:
        http_port = int(comicarr.CONFIG.HTTP_PORT)

    # Generate setup token if first-run setup is needed
    if not comicarr.CONFIG.HTTP_USERNAME or not comicarr.CONFIG.HTTP_PASSWORD:
        import secrets
        comicarr.SETUP_TOKEN = secrets.token_urlsafe(32)
        logger.info('[SETUP] *** First-run setup required ***')
        logger.info('[SETUP] Setup token: %s' % comicarr.SETUP_TOKEN)
        logger.info('[SETUP] Provide this token when setting up credentials via the web interface.')

    #check for version here after web server initialized so it doesn't try to repeatidly hit github
    #for version info if it's already running
    versioncheck.versionload()

    # pip requirements check here
    r = dependency_check.Req()
    r.loaders()

    if comicarr.CONFIG.LAUNCH_BROWSER and not args_nolaunch:
        comicarr.launch_browser(comicarr.CONFIG.HTTP_HOST, http_port, comicarr.CONFIG.HTTP_ROOT)

    # Start the background threads
    comicarr.start()

    signal.signal(signal.SIGTERM, handler_sigterm)

    import uvicorn

    ssl_kwargs = {}
    if comicarr.CONFIG.ENABLE_HTTPS:
        ssl_kwargs["ssl_certfile"] = comicarr.CONFIG.HTTPS_CERT
        ssl_kwargs["ssl_keyfile"] = comicarr.CONFIG.HTTPS_KEY

    uvicorn.run(
        "comicarr.app.main:app",
        host=comicarr.CONFIG.HTTP_HOST,
        port=http_port,
        log_level="info",
        workers=1,
        **ssl_kwargs,
    )

    if comicarr.SIGNAL == 'restart':
        comicarr.shutdown(restart=True)
    elif comicarr.SIGNAL == 'update':
        comicarr.shutdown(restart=True, update=True)
    else:
        comicarr.shutdown()

    return

if __name__ == "__main__":
    main()
