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

import codecs
import configparser
import copy
import errno
import glob
import json
import os
import re
import shutil
import stat
import tempfile
import threading
from collections import OrderedDict
from operator import itemgetter
from pathlib import Path

import comicarr
from comicarr import db, encrypted, filechecker, helpers, logger, maintenance
from comicarr.app.config.registry import as_legacy_definitions

config = configparser.ConfigParser()
_CONFIG_TRANSACTION_LOCK = threading.RLock()
_CONFIG_TEMP_PREFIX = ".comicarr-config-"
_CONFIG_TEMP_SUFFIX = ".tmp"
_PROVIDER_EXTRA_FIELDS = ("EXTRA_NEWZNABS", "EXTRA_TORZNABS")
_PROVIDER_EXTRA_WIDTHS = (6, 7)
_PROVIDER_CREDENTIAL_INDEX = 3
_PROVIDER_BOOLEAN_VALUES = {"0", "1", "false", "true", "no", "yes", "off", "on"}


def _provider_entry_is_structurally_valid(entry):
    """Distinguish historical six- and seven-field provider records safely."""
    if len(entry) not in _PROVIDER_EXTRA_WIDTHS:
        return False
    if str(entry[2]).strip().lower() not in _PROVIDER_BOOLEAN_VALUES:
        return False
    if str(entry[5]).strip().lower() not in _PROVIDER_BOOLEAN_VALUES:
        return False
    if len(entry) == 7:
        try:
            int(entry[6])
        except (TypeError, ValueError):
            return False
    return True


def parse_provider_extras(value, config_version=15):
    """Parse provider extras without assuming one historical tuple width."""
    if value in (None, "", "None"):
        return []

    if isinstance(value, (list, tuple)):
        entries = value
    elif isinstance(value, str):
        parts = value.split(", ")
        candidates = []
        for width in _PROVIDER_EXTRA_WIDTHS:
            if len(parts) % width:
                continue
            candidate = [parts[index : index + width] for index in range(0, len(parts), width)]
            if all(_provider_entry_is_structurally_valid(entry) for entry in candidate):
                candidates.append(candidate)
        if len(candidates) != 1:
            raise ValueError("Provider configuration has an invalid field count")
        entries = candidates[0]
    else:
        raise ValueError("Provider configuration must be a list of entries")

    parsed = []
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or not _provider_entry_is_structurally_valid(entry):
            raise ValueError("Provider entries must contain six or seven fields")
        parsed.append(tuple(entry))
    return parsed


def serialize_provider_extras(entries):
    """Serialize validated provider entries using the legacy flat INI format."""
    flattened = []
    for entry in parse_provider_extras(entries):
        for index, value in enumerate(entry):
            field = "" if value is None else str(value)
            if index == 4:
                field = field.replace(",", "#")
            elif ", " in field:
                raise ValueError("Provider fields cannot contain the INI delimiter")
            flattened.append(field)
    return ", ".join(flattened)


def decrypt_provider_credential(value, secure_dir):
    """Return a runtime provider credential and its reusable Fernet token."""
    if value in (None, "", "None"):
        return value, None, False
    if not isinstance(value, str):
        value = str(value)
    if not value.startswith(("gAAAAA", "^~$z$")):
        return value, None, True

    result = encrypted.Encryptor(value, secure_dir=secure_dir).decrypt_it()
    if not result.get("status"):
        raise ValueError("Unable to decrypt provider credential")
    token = value if value.startswith("gAAAAA") else None
    return result["password"], token, token is None


# Derived from the registry -- comicarr/app/config/registry.py is the single
# definition of every key. Kept as a name and a 3-tuple shape because
# check_setting, _define and migration.py all index these positionally.
_CONFIG_DEFINITIONS = as_legacy_definitions()

_BAD_DEFINITIONS = OrderedDict(
    {
        # for those items that were in wrong sections previously, or sections that are no longer present...
        # using this method, old values are able to be transfered to the new config items properly.
        # keyname, section, oldkeyname
        # ie. 'TEST_VALUE': ('TEST', 'TESTVALUE')
        "SAB_CLIENT_POST_PROCESSING": ("SABnbzd", None),
        "ENABLE_PUBLIC": ("Torrents", "ENABLE_TPSE"),
        "PUBLIC_VERIFY": ("Torrents", "TPSE_VERIFY"),
        "IGNORED_PUBLISHERS": ("CV", "BLACKLISTED_PUBLISHERS"),
        # NZBsu and DOGnzb entries were removed here. They remapped onto keys
        # Comicarr does not define, and migrate_mylar3_config reads this dict
        # independently of _CONFIG_DEFINITIONS -- so migrating a Mylar3 config
        # that used either provider handed writeconfig an undefined key,
        # process_kwargs raised KeyError, and every setting was discarded.
        "SAB_DIRECT_UNPACK": ("SABnzbd", "SAB_TO_MYLAR"),
    }
)

# section/key only — no live values. Used by encrypt_items and carepackage redaction.
# HTTP_PASSWORD excluded — it uses bcrypt (one-way hash), not Fernet.
ENCRYPTED_CONFIG_ITEMS = OrderedDict(
    {
        "SAB_PASSWORD": ("SABnzbd", "sab_password"),
        "SAB_APIKEY": ("SABnzbd", "sab_apikey"),
        "NZBGET_PASSWORD": ("NZBGet", "nzbget_password"),
        "UTORRENT_PASSWORD": ("uTorrent", "utorrent_password"),
        "TRANSMISSION_PASSWORD": ("Transmission", "transmission_password"),
        "DELUGE_PASSWORD": ("Deluge", "deluge_password"),
        "QBITTORRENT_PASSWORD": ("qBittorrent", "qbittorrent_password"),
        "RTORRENT_PASSWORD": ("Rtorrent", "rtorrent_password"),
        "PROWL_KEYS": ("Prowl", "prowl_keys"),
        "PUSHOVER_APIKEY": ("PUSHOVER", "pushover_apikey"),
        "PUSHOVER_USERKEY": ("PUSHOVER", "pushover_userkey"),
        "BOXCAR_TOKEN": ("BOXCAR", "boxcar_token"),
        "PUSHBULLET_APIKEY": ("PUSHBULLET", "pushbullet_apikey"),
        "TELEGRAM_TOKEN": ("TELEGRAM", "telegram_token"),
        "COMICVINE_API": ("CV", "comicvine_api"),
        "PASSWORD_32P": ("32P", "password_32p"),
        "PASSKEY_32P": ("32P", "passkey_32p"),
        "USERNAME_32P": ("32P", "username_32p"),
        "SEEDBOX_PASS": ("Seedbox", "seedbox_pass"),
        "TAB_PASS": ("Tablet", "tab_pass"),
        "API_KEY": ("API", "api_key"),
        "OPDS_PASSWORD": ("OPDS", "opds_password"),
        "PP_SSHPASSWD": ("AutoSnatch", "pp_sshpasswd"),
        "EMAIL_PASSWORD": ("Email", "email_password"),
        "GIT_TOKEN": ("Git", "git_token"),
        "METRON_PASSWORD": ("Metron", "metron_password"),
        "GOTIFY_TOKEN": ("GOTIFY", "gotify_token"),
        "MATRIX_ACCESS_TOKEN": ("MATRIX", "matrix_access_token"),
        "EXTERNAL_APIKEY": ("DDL", "external_apikey"),
        "SLACK_WEBHOOK_URL": ("SLACK", "slack_webhook_url"),
        "MATTERMOST_WEBHOOK_URL": ("MATTERMOST", "mattermost_webhook_url"),
        "DISCORD_WEBHOOK_URL": ("DISCORD", "discord_webhook_url"),
        "DATABASE_URL": ("Database", "database_url"),
        "AI_API_KEY": ("AI", "ai_api_key"),
    }
)

# Lower bound, in minutes, for the intervals that are handed to an
# IntervalTrigger and whose job is then resumed regardless of the value. A
# non-positive one builds a negative-length interval whose next fire time is
# always in the past, so the job re-fires back to back forever.
#
# DOWNLOAD_SCAN_INTERVAL and IMPORT_SCAN_INTERVAL are deliberately absent: for
# those, 0 is the documented way to disable the job, and comicarr.start() keeps
# them paused rather than scheduling them.
SCHEDULER_INTERVAL_MINIMUMS = {
    "SEARCH_INTERVAL": (360, "Search interval too low. Resetting to 6 hour minimum"),
    "RSS_CHECKINTERVAL": (20, "Minimum RSS Interval Check delay set for 20 minutes to avoid hammering."),
    "DBUPDATE_INTERVAL": (60, "Minimum DB update interval set for 60 minutes to avoid hammering."),
}


def clamp_scheduler_intervals(cfg):
    """Raise any scheduler interval that sits below its safe minimum.

    Returns the keys that were clamped. Called from Config.configure(), which
    apply_transaction() runs on every settings save, so this is the boundary a
    value typed into the settings form has to cross.

    A value that cannot be compared raises, as it did when these were three
    inline checks: apply_transaction() rolls the save back rather than storing
    an interval nothing downstream can use.
    """
    clamped = []
    for key, (minimum, message) in SCHEDULER_INTERVAL_MINIMUMS.items():
        if getattr(cfg, key) < minimum:
            logger.fdebug(message)
            setattr(cfg, key, minimum)
            clamped.append(key)
    return clamped


class Config(object):
    def __init__(self, config_file):
        # initalize the config...
        self._config_file = config_file
        self.WRITE_THE_CONFIG = False
        self._provider_credential_tokens = {}

    def config_vals(self, update=False):
        if update is False:
            if os.path.isfile(self._config_file):
                self.config = config.read_file(codecs.open(self._config_file, "r", "utf8"))  # read(self._config_file)
                # check for empty config / new config
                count = sum(1 for line in open(self._config_file))
            else:
                count = 0

            # this is the current version at this particular point in time.
            self.newconfig = 15

            OLDCONFIG_VERSION = 0
            if count == 0:
                CONFIG_VERSION = 0
                MINIMALINI = False
            else:
                # get the config version first, since we need to know.
                try:
                    CONFIG_VERSION = config.getint("General", "config_version")
                    OLDCONFIG_VERSION = CONFIG_VERSION
                except:
                    CONFIG_VERSION = 0
                    OLDCONFIG_VERSION = 0
                try:
                    MINIMALINI = config.getboolean("General", "minimal_ini")
                except:
                    MINIMALINI = False

        self.CONFIG_VERSION = CONFIG_VERSION
        self.OLDCONFIG_VERSION = OLDCONFIG_VERSION
        self.MINIMAL_INI = MINIMALINI

        for k, v in _CONFIG_DEFINITIONS.items():
            xv = []
            xv.append(k)
            for x in v:
                if x is None:
                    x = "None"
                xv.append(x)
            value = self.check_setting(xv)

            for b, bv in _BAD_DEFINITIONS.items():
                try:
                    if all([config.has_section(bv[0]), any([b == k, bv[1] is None])]) and not config.has_option(
                        xv[2], xv[0]
                    ):
                        cvs = xv
                        if bv[1] is None:
                            ckey = k
                        else:
                            ckey = bv[1]
                        corevalues = [ckey if x == 0 else x for x in cvs]
                        corevalues = [bv[1] if x == b else x for x in cvs]
                        value = self.check_setting(corevalues)
                        if config.has_section(bv[0]):
                            if bv[1] is None:
                                config.remove_option(bv[0], ckey.lower())
                                config.remove_section(bv[0])
                            else:
                                config.remove_option(bv[0], bv[1].lower())
                            self.WRITE_THE_CONFIG = True
                        break
                except:
                    pass

            if all([k != "CONFIG_VERSION", k != "MINIMAL_INI"]):
                try:
                    if v[0] == str and any([value == "", value is None, len(value) == 0, value == "None"]):
                        value = v[2]
                except:
                    value = v[2]

                try:
                    if v[0] == bool:
                        value = self.argToBool(value)
                except:
                    value = self.argToBool(v[2])
                try:
                    if all([v[0] == int, str(value).isdigit()]):
                        value = int(value)
                except:
                    value = v[2]

                setattr(self, k, value)

                try:
                    # make sure interpolation isn't being used, so we can just escape the % character
                    if v[0] == str:
                        value = value.replace("%", "%%")
                except Exception:
                    pass

                # just to ensure defaults are properly set...
                if any([value is None, value == "None"]):
                    value = v[0](v[2])

                if all([self.MINIMAL_INI is True, str(value) != str(v[2])]) or self.MINIMAL_INI is False:
                    try:
                        config.add_section(v[1])
                    except configparser.DuplicateSectionError:
                        pass
                else:
                    try:
                        if config.has_section(v[1]):
                            config.remove_option(v[1], k.lower())
                    except configparser.NoSectionError:
                        continue

                if all([config.has_section(v[1]), self.MINIMAL_INI is False]) or all(
                    [self.MINIMAL_INI is True, str(value) != str(v[2]), config.has_section(v[1])]
                ):
                    config.set(v[1], k.lower(), str(value))
                else:
                    try:
                        if config.has_section(v[1]):
                            config.remove_option(v[1], k.lower())
                        if len(dict(config.items(v[1]))) == 0:
                            config.remove_section(v[1])
                    except configparser.NoSectionError:
                        continue
            else:
                if self.CONFIG_VERSION != 0:
                    if k == "CONFIG_VERSION":
                        config.remove_option("General", "dbuser")
                        config.remove_option("General", "dbpass")
                        config.remove_option("General", "dbchoice")
                        config.remove_option("General", "dbname")
                    elif k == "MINIMAL_INI":
                        config.set(v[1], k.lower(), str(self.MINIMAL_INI))

        # this section retains values of variables that are no longer being saved to the ini
        # in case they are needed prior to wiping out things
        self.OLD_VALUES = {}
        for b, bv in _BAD_DEFINITIONS.items():
            if len(bv) == 4:  # removal of option...
                if bv[1] not in self.OLD_VALUES:
                    try:
                        if bv[2] == bool:
                            self.OLD_VALUES[bv[1]] = config.getboolean(bv[0], bv[1])
                        elif bv[2] == str:
                            self.OLD_VALUES[bv[1]] = config.get(bv[0], bv[1])
                        elif bv[2] == int:
                            self.OLD_VALUES[bv[1]] = config.getint(bv[0], bv[1])
                    except (configparser.NoSectionError, configparser.NoOptionError):
                        pass

    def read(self, startup=False):
        self.config_vals()
        self._ensure_secure_directory()
        self._validate_existing_encryption_authority()

        if startup is True:
            if self.LOG_DIR is None:
                self.LOG_DIR = os.path.join(comicarr.DATA_DIR, "logs")

            if not os.path.exists(self.LOG_DIR):
                try:
                    os.makedirs(self.LOG_DIR)
                except OSError:
                    if not comicarr.QUIET:
                        self.LOG_DIR = None
                        print("Unable to create the log directory. Logging to screen only.")

            # Start the logger, silence console logging if we need to
            # quick check to make sure log_level isn't just blank in the config
            if self.LOG_LEVEL is None:
                self.LOG_LEVEL = 1  # default it to INFO level (1) if not set.

            log_level = self.LOG_LEVEL
            if comicarr.LOG_LEVEL is not None:
                log_level = comicarr.LOG_LEVEL
                print("Logging level in config over-ridden by startup value. Logging level set to : %s" % (log_level))

            comicarr.LOG_LEVEL = (
                log_level  # set this to the calculated log_leve value so that logs display fine in the GUI
            )
            if logger.LOG_LANG.startswith("en"):
                logger.initLogger(
                    console=not comicarr.QUIET,
                    log_dir=self.LOG_DIR,
                    max_logsize=self.MAX_LOGSIZE,
                    max_logfiles=self.MAX_LOGFILES,
                    loglevel=log_level,
                )
            else:
                logger.comicarr_log.initLogger(
                    loglevel=log_level,
                    log_dir=self.LOG_DIR,
                    max_logsize=self.MAX_LOGSIZE,
                    max_logfiles=self.MAX_LOGFILES,
                )

        # Validate the live provider authority before backup maintenance is
        # allowed to encrypt historical plaintext with that same authority.
        self.EXTRA_NEWZNABS, self.EXTRA_TORZNABS = self.get_extras()
        provider_migration_needed = self._load_provider_extra_credentials()
        self._validate_loaded_provider_extras()
        if provider_migration_needed and self.writeconfig(startup=True) is False:
            raise OSError("Unable to persist encrypted provider credentials")
        self._sanitize_provider_backup_credentials()

        if any([self.CONFIG_VERSION == 0, self.CONFIG_VERSION < self.newconfig]):
            if not self.BACKUP_LOCATION:
                # this is needed here since the configuration hasn't run to check the location value yet.
                self.BACKUP_LOCATION = os.path.join(comicarr.DATA_DIR, "backup")

            backupinfo = {
                "location": self.BACKUP_LOCATION,
                "config_version": self.CONFIG_VERSION,
                "backup_retention": self.BACKUP_RETENTION,
            }
            cc = maintenance.Maintenance("backup")
            cc.backup_files(cfg=True, dbs=False, backupinfo=backupinfo)

            if self.CONFIG_VERSION < 14:
                print("Attempting to update configuration..")
                # 8-torznab multiple entries merged into extra_torznabs value
                # 9-remote rtorrent ssl option
                # 10-encryption of all keys/passwords.
                # 11-provider ids
                # 12-ddl seperation into multiple providers, new keys, update tables
                # 13-remove dognzb and nzbsu as independent options (throw them under newznabs if present)
                self.config_update()
            self.OLDCONFIG_VERSION = str(self.CONFIG_VERSION)
            self.CONFIG_VERSION = self.newconfig
            config.set("General", "CONFIG_VERSION", str(self.newconfig))
            self.writeconfig(startup=startup)
        else:
            if self.OLDCONFIG_VERSION != self.CONFIG_VERSION:
                self.OLDCONFIG_VERSION = str(self.CONFIG_VERSION)

        extra_newznabs, extra_torznabs = self.get_extras()
        self.EXTRA_NEWZNABS = extra_newznabs
        self.EXTRA_TORZNABS = extra_torznabs
        self.IGNORED_PUBLISHERS = self.get_ignored_pubs()

        provider_migration_needed = self._load_provider_extra_credentials()
        self._validate_loaded_provider_extras()
        if provider_migration_needed and self.writeconfig(startup=True) is False:
            raise OSError("Unable to persist encrypted provider credentials")

        if startup is False:
            # need to do provider sequence AFTER db check
            self.provider_sequence()
        self.configure(startup=startup)
        if self.WRITE_THE_CONFIG is True or startup is True:
            if self.writeconfig(startup=startup) is False:
                raise OSError("Unable to persist configuration")
        return self

    def config_update(self):
        logger.info("Updating Configuration from %s to %s" % (self.CONFIG_VERSION, self.newconfig))
        if self.CONFIG_VERSION < 8:
            logger.info("Checking for existing torznab configuration...")
            if not any(
                [
                    self.TORZNAB_NAME is None,
                    self.TORZNAB_HOST is None,
                    self.TORZNAB_APIKEY is None,
                    self.TORZNAB_CATEGORY is None,
                ]
            ):
                torznabs = [
                    (
                        self.TORZNAB_NAME,
                        self.TORZNAB_HOST,
                        self.TORZNAB_VERIFY,
                        self.TORZNAB_APIKEY,
                        self.TORZNAB_CATEGORY,
                        str(int(self.ENABLE_TORZNAB)),
                    )
                ]
                self.EXTRA_TORZNABS = torznabs
                config.set("Torznab", "EXTRA_TORZNABS", str(torznabs))
                logger.info(
                    "Successfully converted existing torznab for multiple configuration allowance. Removing old references."
                )
            else:
                logger.info(
                    "No existing torznab configuration found. Just removing old config references at this point.."
                )
            config.remove_option("Torznab", "torznab_name")
            config.remove_option("Torznab", "torznab_host")
            config.remove_option("Torznab", "torznab_verify")
            config.remove_option("Torznab", "torznab_apikey")
            config.remove_option("Torznab", "torznab_category")
            config.remove_option("Torznab", "torznab_verify")
            logger.info("Successfully removed outdated config entries.")
        if self.newconfig < 9:
            # rejig rtorrent settings due to change.
            try:
                if all([self.RTORRENT_SSL is True, not self.RTORRENT_HOST.startswith("http")]):
                    self.RTORRENT_HOST = "https://" + self.RTORRENT_HOST
                    config.set("Rtorrent", "rtorrent_host", self.RTORRENT_HOST)
            except:
                pass
            config.remove_option("Rtorrent", "rtorrent_ssl")
            logger.info("Successfully removed oudated config entries.")
        if self.newconfig < 10:
            # encrypt all passwords / apikeys / usernames in ini file.
            # leave non-ini items (ie. memory) as un-encrypted items.
            try:
                if self.ENCRYPT_PASSWORDS is True:
                    self.encrypt_items(mode="encrypt", updateconfig=True)
            except Exception as e:
                logger.error("Error: %s" % e)
            logger.info("Successfully updated config to version 10 ( password / apikey - .ini encryption )")
        # if self.CONFIG_VERSION < 11:
        # add ID to all providers as a way to better identify them
        # tmp_newznabs = self.EXTRA_NEWZNABS
        # n_cnt = 0
        # a_list = []
        # if len(tmp_newznabs) > 0:
        #    for i in tmp_newznabs:
        #        tmp_i = list(i)
        #        tmp_i.append(n_cnt)
        #        a_list.append(tuple(tmp_i))
        #        n_cnt +=1
        # setattr(self, 'EXTRA_NEWZNABS', a_list)
        # tmp_torznabs = self.EXTRA_TORZNABS
        # b_cnt = 0
        # b_list = []
        # if len(tmp_torznabs) > 0:
        #    for i in tmp_torznabs:
        #        tmp_i = list(i)
        #        tmp_i.append(b_cnt)
        #        b_list.append(tuple(tmp_i))
        #        b_cnt +=1
        # setattr(self, 'EXTRA_TORZNABS', b_list)

        if self.newconfig < 12:
            # change enable_ddl to be a true/false for multiple ddl providers
            # set enable_getcomics to True by default if that's the case.
            if self.ENABLE_DDL is True:
                self.ENABLE_GETCOMICS = True
                config.set("DDL", "enable_getcomics", self.ENABLE_GETCOMICS)
            # tables will be updated by checking the OLDCONFIG_VERSION in __init__
            logger.info("Successfully updated config to version 12 ( multiple DDL provider option )")
        if self.newconfig < 15:
            # remove nzbsu and dognzb as individual options
            # if data exists already, add them as newznab options (if not already there or via Prowlarr)
            try:
                for chk_e in [self.OLD_VALUES["nzbsu_apikey"], self.OLD_VALUES["dognzb_apikey"]]:
                    if chk_e is not None:
                        if chk_e[:5] == "^~$z$":
                            nz = encrypted.Encryptor(chk_e, secure_dir=self.SECURE_DIR)
                            nz_stat = nz.decrypt_it()
                            if nz_stat["status"] is True:
                                if chk_e == self.OLD_VALUES["nzbsu_apikey"]:
                                    self.OLD_VALUES["nzbsu_apikey"] = nz_stat["password"]
                                else:
                                    self.OLD_VALUES["dognzb_apikey"] = nz_stat["password"]
            except Exception:
                pass

            extra_newznabs, extra_torznabs = self.get_extras()
            enz = []
            dogs = []
            nzbsus = []
            try:
                ncnt = 0
                for en in extra_newznabs:
                    dognzb_found = nzbsu_found = False
                    ben = list(en)
                    if ben[1] is not None:
                        n_name = ben[0].lower()
                        if n_name is None:
                            n_name = ""
                        if ben[3][:5] == "^~$z$":
                            nz = encrypted.Encryptor(ben[3], secure_dir=self.SECURE_DIR)
                            nz_stat = nz.decrypt_it()
                            if nz_stat["status"] is True:
                                ben[3] = nz_stat["password"]

                        # prowlarr's url does not contain the actual url, hope the name contains it...
                        if "nzb.su" in ben[1].lower() or (
                            any(["nzb.su" in n_name.lower(), "nzbsu" in re.sub(r"\s", "", n_name).lower()])
                            and "prowlarr" in n_name.lower()
                        ):
                            nzbsus.append(tuple(ben))
                            nzbsu_found = True
                        elif "dognzb" in ben[1].lower() or all(
                            ["dognzb" in re.sub(r"\s", "", n_name).lower(), "prowlarr" in n_name.lower()]
                        ):
                            dogs.append(tuple(ben))
                            dognzb_found = True
                        if not any([dognzb_found, nzbsu_found]):
                            enz.append(tuple(ben))
                    ncnt += 1
            except Exception as e:
                logger.warn("error: %s" % e)

            try:
                if self.OLD_VALUES["nzbsu"]:
                    comicarr.PROVIDER_START_ID += 1
                    tsnzbsu = "" if self.OLD_VALUES["nzbsu_uid"] is None else self.OLD_VALUES["nzbsu_uid"]
                    nzbsus.append(
                        (
                            "nzb.su",
                            "https://api.nzb.su",
                            "1",
                            self.OLD_VALUES["nzbsu_apikey"],
                            tsnzbsu,
                            str(int(self.OLD_VALUES["nzbsu"])),
                            comicarr.PROVIDER_START_ID,
                        )
                    )
            except Exception:
                pass

            try:
                if self.OLD_VALUES["dognzb"]:
                    comicarr.PROVIDER_START_ID += 1
                    dogs.append(
                        (
                            "DOGnzb",
                            "https://api.dognzb.cr",
                            "1",
                            self.OLD_VALUES["dognzb_apikey"],
                            "",
                            str(int(self.OLD_VALUES["dognzb"])),
                            comicarr.PROVIDER_START_ID,
                        )
                    )
            except Exception:
                pass

            # loop thru nzbsus and dogs entries and only keep one (in order of priority): Enabled, Prowlarr, newznab
            keep_it = None
            kcnt = 0
            for ggg in [nzbsus, dogs]:
                for gg in sorted(ggg, key=itemgetter(5), reverse=True):
                    try:
                        if gg[5] == "1":
                            if gg[0] is not None:
                                if "Prowlarr" in gg[0]:
                                    keep_it = gg
                        if keep_it is None and gg[0] is not None:
                            if "Prowlarr" in gg[0]:
                                keep_it = gg
                        if keep_it is None:
                            keep_it = gg
                    except Exception as e:
                        logger.error("error: %s" % e)

                if kcnt == 0 and keep_it is not None:
                    enz.append(keep_it)
                elif kcnt == 1 and keep_it is not None:
                    enz.append(keep_it)
                keep_it = None
                kcnt += 1

            try:
                config.remove_option("NZBsu", "nzbsu")
                config.remove_option("NZBsu", "nzbsu_uid")
                config.remove_option("NZBsu", "nzbsu_apikey")
                config.remove_option("NZBsu", "nzbsu_verify")
            except configparser.NoSectionError:
                pass
            else:
                config.remove_section("NZBsu")
            try:
                config.remove_option("DOGnzb", "dognzb")
                config.remove_option("DOGnzb", "dognzb_verify")
                config.remove_option("DOGnzb", "dognzb_apikey")
            except configparser.NoSectionError:
                pass
            else:
                config.remove_section("DOGnzb")

            self.EXTRA_NEWZNABS = enz
            self.EXTRA_TORZNABS = extra_torznabs
            try:
                from sqlalchemy import delete
                from sqlalchemy import inspect as sa_inspect

                from comicarr.tables import provider_searches

                inspector = sa_inspect(db.get_engine())
                cols = inspector.get_columns("provider_searches")
                if cols:
                    stmt = delete(provider_searches).where(provider_searches.c.id.in_([102, 103]))
                    with db.get_engine().begin() as conn:
                        conn.execute(stmt)
            except Exception:
                # if the table doesn't exist yet, it'll get created after the config loads on new installs.
                pass

        logger.info("Configuration upgraded to version %s" % self.newconfig)

    def check_section(self, section, key):
        """Check if INI section exists, if not create it"""
        if config.has_section(section):
            return True
        else:
            return False

    def argToBool(self, argument):
        _arg = argument.strip().lower() if isinstance(argument, str) else argument
        if _arg in (1, "1", "on", "true", True):
            return True
        elif _arg in (0, "0", "off", "false", False):
            return False
        return argument

    def check_setting(self, key):
        """Cast any value in the config to the right type or use the default"""
        key[0].upper()
        inikey = key[0].lower()
        definition_type = key[1]
        section = key[2]
        default = key[3]
        myval = self.check_config(definition_type, section, inikey, default)
        if myval["status"] is False:
            if self.CONFIG_VERSION == 6 or (
                config.has_section("Torrents") and any([inikey == "auto_snatch", inikey == "auto_snatch_script"])
            ):
                chkstatus = False
                if config.has_section("Torrents"):
                    myval = self.check_config(definition_type, "Torrents", inikey, default)
                    if myval["status"] is True:
                        chkstatus = True
                        try:
                            config.remove_option("Torrents", inikey)
                        except configparser.NoSectionError:
                            pass
                if all([chkstatus is False, config.has_section("General")]):
                    myval = self.check_config(definition_type, "General", inikey, default)
                    if myval["status"] is True:
                        config.remove_option("General", inikey)

                    else:
                        # print 'no key found in ini - setting to default value of %s' % definition_type(default)
                        # myval = {'value': definition_type(default)}
                        pass
            else:
                myval = {"value": definition_type(default)}
        # if all([myval['value'] is not None, myval['value'] != '', myval['value'] != 'None']):
        # if default != myval['value']:
        #    print '%s : %s' % (keyname, myval['value'])
        # else:
        #    print 'NEW CONFIGURATION SETTING %s : %s' % (keyname, myval['value'])
        return myval["value"]

    def check_config(self, definition_type, section, inikey, default):
        try:
            if definition_type == str:
                myval = {"status": True, "value": config.get(section, inikey)}
            elif definition_type == int:
                myval = {"status": True, "value": config.getint(section, inikey)}
            elif definition_type == bool:
                myval = {"status": True, "value": config.getboolean(section, inikey)}
        except Exception:
            if definition_type == str:
                try:
                    myval = {"status": True, "value": config.get(section, inikey, raw=True)}
                except (configparser.NoSectionError, configparser.NoOptionError):
                    myval = {"status": False, "value": None}
            else:
                myval = {"status": False, "value": None}
        return myval

    def _define(self, name):
        key = name.upper()
        ini_key = name.lower()
        definition_type, section, default = _CONFIG_DEFINITIONS[key]
        return key, definition_type, section, ini_key, default

    def _provider_max_id(self):
        provider_ids = [getattr(comicarr, "PROVIDER_START_ID", 0)]
        for attr_name in _PROVIDER_EXTRA_FIELDS:
            try:
                entries = parse_provider_extras(getattr(self, attr_name, []), self.CONFIG_VERSION)
            except ValueError:
                continue
            for entry in entries:
                if len(entry) == 7:
                    try:
                        provider_ids.append(int(entry[6]))
                    except (TypeError, ValueError):
                        pass
        return max(provider_ids)

    def _reserved_provider_ids(self):
        reserved = set()
        if self.EXPERIMENTAL:
            reserved.add(101)
        if self.ENABLE_DDL and self.ENABLE_GETCOMICS:
            reserved.add(200)
        if self.ENABLE_DDL and self.ENABLE_EXTERNAL_SERVER:
            reserved.add(201)
        return reserved

    def _validate_existing_encryption_authority(self):
        """Fail before any write when a live Fernet secret lacks its authority."""
        for attr_name in ENCRYPTED_CONFIG_ITEMS:
            value = getattr(self, attr_name, None)
            if isinstance(value, (tuple, list)) and value:
                value = value[0]
            if not isinstance(value, str) or not value.startswith("gAAAAA"):
                continue
            result = encrypted.Encryptor(value, secure_dir=self.SECURE_DIR).decrypt_it()
            if not result.get("status"):
                raise ValueError("Unable to validate encrypted configuration authority")

    def _reserved_provider_names(self):
        reserved = set()
        if self.ENABLE_TORRENT_SEARCH and self.ENABLE_32P:
            reserved.add("32p")
        if self.EXPERIMENTAL:
            reserved.add("experimental")
        if self.ENABLE_DDL and self.ENABLE_GETCOMICS:
            reserved.add("ddl(getcomics)")
        if self.ENABLE_DDL and self.ENABLE_EXTERNAL_SERVER:
            reserved.add("ddl(external)")
        return reserved

    @staticmethod
    def _validate_provider_names(entries, seen_names):
        for entry in entries:
            canonical_name = str(entry[0] or entry[1]).strip().casefold()
            if not canonical_name:
                raise ValueError("Provider name or host is required")
            if canonical_name in seen_names:
                raise ValueError("Provider names must be unique across enabled providers")
            seen_names.add(canonical_name)

    def _validate_loaded_provider_extras(self):
        """Validate persisted provider identities before projection or backup work."""
        seen_ids = self._reserved_provider_ids()
        seen_names = self._reserved_provider_names()
        next_id = self._provider_max_id()
        for attr_name in _PROVIDER_EXTRA_FIELDS:
            entries = parse_provider_extras(getattr(self, attr_name, []), self.CONFIG_VERSION)
            normalized, next_id = self._assign_provider_ids(entries, next_id, seen_ids)
            self._validate_provider_names(normalized, seen_names)

    def _decode_provider_entries(self, entries, token_cache=None):
        decoded = []
        cache = dict(self._provider_credential_tokens if token_cache is None else token_cache)
        migration_needed = False
        for entry in entries:
            runtime_entry = list(entry)
            credential, token, migrate = decrypt_provider_credential(
                runtime_entry[_PROVIDER_CREDENTIAL_INDEX],
                self.SECURE_DIR,
            )
            runtime_entry[_PROVIDER_CREDENTIAL_INDEX] = credential
            if token:
                cache[credential] = token
            elif migrate and credential in cache:
                migrate = False
            migration_needed = migration_needed or migrate
            decoded.append(tuple(runtime_entry))
        return decoded, cache, migration_needed

    def _assign_provider_ids(self, entries, next_id=None, seen_ids=None):
        """Normalize legacy widths and reject duplicate current provider IDs."""
        next_id = self._provider_max_id() if next_id is None else next_id
        normalized = []
        seen_ids = set() if seen_ids is None else seen_ids
        for entry in entries:
            values = list(entry)
            if len(values) == 6:
                next_id += 1
                while next_id in seen_ids:
                    next_id += 1
                values.append(next_id)
            else:
                try:
                    values[6] = int(values[6])
                except (TypeError, ValueError) as e:
                    raise ValueError("Provider ID must be an integer") from e
            if values[6] in seen_ids:
                raise ValueError("Provider IDs must be unique across enabled providers")
            seen_ids.add(values[6])
            normalized.append(tuple(values))
        return normalized, next_id

    def _normalize_provider_extra_value(self, value):
        entries = parse_provider_extras(value, self.CONFIG_VERSION)
        decoded, token_cache, _migration_needed = self._decode_provider_entries(entries)
        normalized, _next_id = self._assign_provider_ids(decoded, seen_ids=self._reserved_provider_ids())
        self._validate_provider_names(normalized, self._reserved_provider_names())
        self._provider_credential_tokens = token_cache
        return normalized

    def _load_provider_extra_credentials(self):
        """Decrypt provider keys after secure-directory authority is available."""
        decoded_fields = {}
        token_cache = dict(self._provider_credential_tokens)
        migration_needed = False
        for attr_name in _PROVIDER_EXTRA_FIELDS:
            entries = parse_provider_extras(getattr(self, attr_name, []), self.CONFIG_VERSION)
            decoded, token_cache, migrate = self._decode_provider_entries(entries, token_cache)
            decoded_fields[attr_name] = decoded
            migration_needed = migration_needed or migrate

        for attr_name, entries in decoded_fields.items():
            setattr(self, attr_name, entries)
        self._provider_credential_tokens = token_cache
        if migration_needed:
            self.ENCRYPT_PASSWORDS = True
            if not config.has_section("General"):
                config.add_section("General")
            config.set("General", "encrypt_passwords", "True")
            self.WRITE_THE_CONFIG = True
        return migration_needed

    def _sanitize_provider_backup_credentials(self):
        """Encrypt provider keys retained in historical config backups."""
        backup_dir = self.BACKUP_LOCATION
        if backup_dir in (None, "", "None"):
            backup_dir = os.path.join(comicarr.DATA_DIR, "backup")

        for backup_name in glob.glob(os.path.join(backup_dir, "config.ini-v*.backup*")):
            backup_path = Path(backup_name)
            if backup_path.is_symlink():
                raise OSError("Refusing to rewrite a symlinked config backup")
            if not backup_path.is_file():
                continue
            backup_config = configparser.ConfigParser()
            backup_config.read(backup_path)
            config_version = backup_config.getint("General", "config_version", fallback=15)
            changed = False

            for section, option in (("Newznab", "extra_newznabs"), ("Torznab", "extra_torznabs")):
                raw_value = backup_config.get(section, option, raw=True, fallback="")
                if raw_value in ("", "None"):
                    continue
                section_changed = False
                try:
                    entries = parse_provider_extras(raw_value, config_version)
                except ValueError:
                    backup_config.set(section, option, "")
                    changed = True
                    continue

                sanitized = []
                for entry in entries:
                    values = list(entry)
                    credential = values[_PROVIDER_CREDENTIAL_INDEX]
                    if credential not in (None, "", "None") and not str(credential).startswith("gAAAAA"):
                        try:
                            runtime_credential, _token, _migration = decrypt_provider_credential(
                                credential,
                                self.SECURE_DIR,
                            )
                        except ValueError:
                            runtime_credential = None
                        if runtime_credential in (None, "", "None"):
                            values[_PROVIDER_CREDENTIAL_INDEX] = ""
                        else:
                            encrypted_value = encrypted.Encryptor(
                                str(runtime_credential),
                                secure_dir=self.SECURE_DIR,
                            ).encrypt_it()
                            if not encrypted_value.get("status"):
                                raise OSError("Unable to sanitize provider credential backup")
                            values[_PROVIDER_CREDENTIAL_INDEX] = encrypted_value["password"]
                        section_changed = True
                    sanitized.append(tuple(values))

                if section_changed:
                    backup_config.set(section, option, serialize_provider_extras(sanitized))
                    changed = True

            if changed:
                backup_mode = stat.S_IMODE(backup_path.stat().st_mode)
                self._atomic_replace_file(backup_path, backup_mode, backup_config.write)

    def validate_provider_extra_value(self, attr_name, value):
        """Validate an API provider payload without publishing it to readers."""
        if attr_name not in _PROVIDER_EXTRA_FIELDS:
            raise ValueError("Unknown provider configuration field")
        seen_ids = self._reserved_provider_ids()
        seen_names = self._reserved_provider_names()
        next_id = self._provider_max_id()
        for other_attr in _PROVIDER_EXTRA_FIELDS:
            if other_attr == attr_name:
                continue
            other_entries = parse_provider_extras(getattr(self, other_attr, []), self.CONFIG_VERSION)
            decoded_other, _token_cache, _migration_needed = self._decode_provider_entries(other_entries)
            normalized_other, next_id = self._assign_provider_ids(decoded_other, next_id, seen_ids)
            self._validate_provider_names(normalized_other, seen_names)
        entries = parse_provider_extras(value, self.CONFIG_VERSION)
        decoded, _token_cache, _migration_needed = self._decode_provider_entries(entries)
        normalized, _next_id = self._assign_provider_ids(decoded, next_id, seen_ids)
        self._validate_provider_names(normalized, seen_names)

    def _prepare_provider_extras_for_write(self, overrides=None):
        """Build encrypted storage copies while leaving runtime credentials plaintext."""
        overrides = overrides or {}
        storage = {}
        runtime = {}
        token_cache = dict(self._provider_credential_tokens)
        next_id = self._provider_max_id()
        seen_ids = self._reserved_provider_ids()
        seen_names = self._reserved_provider_names()
        has_credentials = False

        for attr_name in _PROVIDER_EXTRA_FIELDS:
            value = overrides.get(attr_name, getattr(self, attr_name, []))
            entries = parse_provider_extras(value, self.CONFIG_VERSION)
            decoded, token_cache, _migration_needed = self._decode_provider_entries(entries, token_cache)
            normalized, next_id = self._assign_provider_ids(decoded, next_id, seen_ids)
            self._validate_provider_names(normalized, seen_names)
            encrypted_entries = []
            for entry in normalized:
                stored_values = list(entry)
                credential = entry[_PROVIDER_CREDENTIAL_INDEX]
                if credential not in (None, "", "None"):
                    has_credentials = True
                    token = token_cache.get(credential)
                    if token is None:
                        encrypted_value = encrypted.Encryptor(
                            str(credential),
                            secure_dir=self.SECURE_DIR,
                        ).encrypt_it()
                        if not encrypted_value.get("status"):
                            raise ValueError("Unable to encrypt provider credential")
                        token = encrypted_value["password"]
                        token_cache[credential] = token
                    stored_values[_PROVIDER_CREDENTIAL_INDEX] = token
                encrypted_entries.append(tuple(stored_values))

            runtime[attr_name] = normalized
            storage[attr_name] = serialize_provider_extras(encrypted_entries)

        active_credentials = {
            entry[_PROVIDER_CREDENTIAL_INDEX]
            for entries in runtime.values()
            for entry in entries
            if entry[_PROVIDER_CREDENTIAL_INDEX] not in (None, "", "None")
        }
        active_token_cache = {
            credential: token_cache[credential] for credential in active_credentials if credential in token_cache
        }
        return storage, runtime, active_token_cache, has_credentials

    def process_kwargs(self, kwargs):
        """
        Given a big bunch of key value pairs, apply them to the ini.
        """
        for name, value in list(kwargs.items()):
            if not any(
                [
                    (name.startswith("newznab") and name[-1].isdigit()),
                    name.startswith("torznab") and name[-1].isdigit(),
                    name == "ignore_search_words[]",
                ]
            ):
                key, definition_type, section, ini_key, default = self._define(name)
                if key in _PROVIDER_EXTRA_FIELDS:
                    setattr(self, key, self._normalize_provider_extra_value(value))
                    continue
                if definition_type == str:
                    try:
                        if any([value == "", value is None, len(value) == 0]):
                            value = default
                        else:
                            value = str(value)
                    except:
                        value = default
                try:
                    if definition_type == bool:
                        value = self.argToBool(value)
                except:
                    value = self.argToBool(default)
                try:
                    if all([definition_type == int, str(value).isdigit()]):
                        value = int(value)
                except:
                    value = default

                # just to ensure defaults are properly set...
                if any([value is None, value == "None"]):
                    value = definition_type(default)

                if key != "MINIMAL_INI":
                    if value == "None":
                        nv = None
                    else:
                        nv = definition_type(value)
                    setattr(self, key, nv)

                    # print('writing config value...[%s][%s] key: %s / ini_key: %s / value: %s [%s]' % (definition_type, section, key, ini_key, value, default))
                    if (
                        all([self.MINIMAL_INI is True, definition_type(value) != definition_type(default)])
                        or self.MINIMAL_INI is False
                    ):
                        try:
                            config.add_section(section)
                        except configparser.DuplicateSectionError:
                            pass
                    else:
                        try:
                            if config.has_section(section):
                                config.remove_option(section, ini_key)
                            if len(dict(config.items(section))) == 0:
                                config.remove_section(section)
                        except configparser.NoSectionError:
                            continue

                    if any([value is None, value == ""]):
                        value = definition_type(default)
                    if config.has_section(section) and (
                        all([self.MINIMAL_INI is True, definition_type(value) != definition_type(default)])
                        or self.MINIMAL_INI is False
                    ):
                        try:
                            if definition_type == str:
                                value = value.replace("%", "%%")
                        except Exception:
                            pass
                        config.set(section, ini_key, str(value))
                else:
                    config.set(section, ini_key, str(self.MINIMAL_INI))

            else:
                pass

    def apply_transaction(self, values, configure=True):
        """Apply, encrypt, and persist config values as one recoverable update."""
        with _CONFIG_TRANSACTION_LOCK:
            if getattr(self, "_config_write_halted", False):
                logger.error("[CONFIG] Refusing config write: a previous transactional rollback was incomplete")
                return False

            try:
                config_path = self._config_write_target()
            except (OSError, RuntimeError) as e:
                logger.error("[CONFIG] Refusing unsafe config write target: %s" % e)
                return False

            runtime_snapshot = self._snapshot_runtime_state()
            parser_defaults = copy.deepcopy(config._defaults)
            parser_sections = copy.deepcopy(config._sections)
            file_existed = config_path.is_file()
            file_contents = config_path.read_bytes() if file_existed else None
            file_mode = config_path.stat().st_mode if file_existed else None
            provider_start_id = comicarr.PROVIDER_START_ID

            try:
                provider_values = {key: value for key, value in values.items() if key in _PROVIDER_EXTRA_FIELDS}
                scalar_values = {key: value for key, value in values.items() if key not in _PROVIDER_EXTRA_FIELDS}
                if provider_values and scalar_values:
                    raise ValueError("Provider and scalar settings require separate transactions")
                if provider_values:
                    # Provider values are fully normalized and published by
                    # _writeconfig; the broad legacy configure pass adds no
                    # provider state and cannot be rolled back safely.
                    configure = False
                if scalar_values:
                    self.process_kwargs(scalar_values)
                self._encrypt_config_for_write()
                if provider_values:
                    persisted = self._writeconfig(provider_values=provider_values)
                else:
                    persisted = self.writeconfig()
                if persisted is False:
                    raise OSError("config write failed")
                if configure:
                    # configure() still owns legacy filesystem and queue side effects.
                    # Running it after the durable write prevents those effects on write
                    # failure; config state can be rolled back if configure itself fails,
                    # but already-completed external effects are not reversible here.
                    self.configure(update=True, startup=False)
                return True
            # BaseException is deliberate: rollback must run even for
            # interpreter-exiting exceptions (a torn config.ini is worse than a
            # cancelled save); the isinstance re-raise below preserves their
            # propagation once state is restored.
            except BaseException as e:
                comicarr.PROVIDER_START_ID = provider_start_id
                durable_write_happened = self._durable_write_changed(config_path, file_existed, file_contents)
                runtime_ok = False
                file_ok = False
                try:
                    self._restore_transaction_state(runtime_snapshot, parser_defaults, parser_sections)
                    runtime_ok = True
                except Exception as rollback_error:
                    logger.error("[CONFIG] Failed to restore runtime state after update failure: %s" % rollback_error)
                try:
                    self._restore_config_file(config_path, file_existed, file_contents, file_mode)
                    file_ok = True
                except Exception as rollback_error:
                    logger.error(
                        "[CONFIG] Failed to restore configuration file after update failure: %s" % rollback_error
                    )
                if durable_write_happened and not (runtime_ok and file_ok):
                    self._config_write_halted = True
                    logger.error(
                        "[CONFIG] CRITICAL: transactional rollback incomplete "
                        "(runtime_restored=%s, file_restored=%s). "
                        "Further config writes are refused until the process restarts or config is repaired."
                        % (runtime_ok, file_ok)
                    )
                logger.error("[CONFIG] Transactional update failed: %s" % e)
                if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                    raise
                return False

    def _snapshot_runtime_state(self):
        """Copy mutable runtime state while retaining references to opaque helpers."""
        snapshot = {}
        for key, value in self.__dict__.items():
            try:
                snapshot[key] = copy.deepcopy(value)
            except Exception:
                snapshot[key] = value
        return snapshot

    @staticmethod
    def _durable_write_changed(config_path, file_existed, file_contents):
        """Return True when the on-disk config differs from the pre-transaction snapshot."""
        try:
            if file_existed:
                current_contents = config_path.read_bytes() if config_path.is_file() else None
                return current_contents != file_contents
            return config_path.exists()
        except Exception:
            # If we cannot inspect disk state, assume a durable write may have landed.
            return True

    def _encrypt_config_for_write(self):
        """Encrypt every configured secret in the parser without changing runtime values."""
        configured_secrets = []
        for attr_name, (section, ini_key) in ENCRYPTED_CONFIG_ITEMS.items():
            value = getattr(self, attr_name, None)
            if isinstance(value, (tuple, list)):
                value = value[0] if value else None
            if value not in (None, "", "None"):
                configured_secrets.append((section, ini_key))

        if not configured_secrets:
            return

        self.ENCRYPT_PASSWORDS = True
        if not config.has_section("General"):
            config.add_section("General")
        config.set("General", "encrypt_passwords", "True")
        self.encrypt_items(mode="encrypt")

        for section, ini_key in configured_secrets:
            encrypted_value = config.get(section, ini_key, raw=True, fallback=None)
            if not encrypted_value or not encrypted_value.startswith("gAAAAA"):
                raise ValueError("Unable to encrypt configured secret: %s.%s" % (section, ini_key))

    def _restore_transaction_state(self, runtime_snapshot, parser_defaults, parser_sections):
        """Restore the Config object and shared parser to their pre-update state."""
        self.__dict__.clear()
        self.__dict__.update(runtime_snapshot)

        config.clear()
        config._defaults.clear()
        config._defaults.update(copy.deepcopy(parser_defaults))
        for section, options in parser_sections.items():
            config.add_section(section)
            for option, value in options.items():
                config.set(section, option, value)

    def _restore_config_file(self, config_path, file_existed, file_contents, file_mode):
        """Restore the last durable config only when the transaction changed it."""
        if file_existed:
            current_contents = config_path.read_bytes() if config_path.is_file() else None
            if current_contents == file_contents:
                return
            self._atomic_replace_file(
                config_path,
                stat.S_IMODE(file_mode),
                lambda rollback_file: rollback_file.write(file_contents),
                binary=True,
            )
        elif config_path.exists():
            config_path.unlink()
            self._fsync_directory(config_path.parent)

    def _config_write_target(self):
        """Resolve a configured symlink target without replacing the link itself."""
        configured_path = Path(self._config_file).absolute()
        if configured_path.is_symlink():
            target_path = configured_path.resolve(strict=False)
            if target_path.exists() and not target_path.is_file():
                raise OSError("config symlink target is not a regular file")
            return target_path
        if configured_path.exists() and not configured_path.is_file():
            raise OSError("config path is not a regular file")
        return configured_path

    @staticmethod
    def _apply_file_mode(file_descriptor, temp_path, mode):
        """Apply POSIX permissions with a safe Windows fallback."""
        fchmod = getattr(os, "fchmod", None)
        if callable(fchmod):
            try:
                fchmod(file_descriptor, mode)
                return
            except (AttributeError, NotImplementedError):
                pass
            except OSError:
                if os.name != "nt":
                    raise

        chmod = getattr(os, "chmod", None)
        if callable(chmod):
            try:
                chmod(temp_path, mode)
                return
            except (AttributeError, NotImplementedError):
                pass
            except OSError:
                if os.name != "nt":
                    raise

        if os.name != "nt":
            raise OSError("platform cannot apply config file permissions")

    @classmethod
    def _atomic_replace_file(cls, target_path, mode, write_content, binary=False):
        """Write through an exclusive same-directory temp and atomically replace."""
        temp_fd = None
        temp_path = None
        try:
            temp_fd, temp_name = tempfile.mkstemp(
                prefix=_CONFIG_TEMP_PREFIX,
                suffix=_CONFIG_TEMP_SUFFIX,
                dir=str(target_path.parent),
            )
            temp_path = Path(temp_name)
            cls._apply_file_mode(temp_fd, temp_path, mode)
            open_mode = "wb" if binary else "w"
            open_kwargs = {} if binary else {"encoding": "utf8"}
            with os.fdopen(temp_fd, mode=open_mode, **open_kwargs) as temp_file:
                temp_fd = None
                write_content(temp_file)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, target_path)
            temp_path = None
            cls._fsync_directory(target_path.parent)
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError as cleanup_error:
                    logger.warn("[CONFIG] Unable to remove config temp file %s: %s" % (temp_path, cleanup_error))

    @staticmethod
    def _fsync_directory(directory):
        """Make a replaced config directory entry crash-durable on POSIX."""
        if os.name == "nt":
            return
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def writeconfig(self, values=None, startup=False):
        """Serialize every parser mutation and atomic config-file replacement."""
        with _CONFIG_TRANSACTION_LOCK:
            if getattr(self, "_config_write_halted", False):
                logger.error("[CONFIG] Refusing config write: a previous transactional rollback was incomplete")
                return False
            return self._writeconfig(values=values, startup=startup)

    def writeconfig_values(self, values, startup=False):
        """Process values before provider sequencing under the shared write lock.

        Runtime and parser state are restored when the durable write fails so
        callers do not keep dirty in-memory values after a failed persist.
        """
        with _CONFIG_TRANSACTION_LOCK:
            if getattr(self, "_config_write_halted", False):
                logger.error("[CONFIG] Refusing config write: a previous transactional rollback was incomplete")
                return False

            runtime_snapshot = self._snapshot_runtime_state()
            parser_defaults = copy.deepcopy(config._defaults)
            parser_sections = copy.deepcopy(config._sections)
            try:
                provider_values = {key: value for key, value in values.items() if key in _PROVIDER_EXTRA_FIELDS}
                scalar_values = {key: value for key, value in values.items() if key not in _PROVIDER_EXTRA_FIELDS}
                if scalar_values:
                    self.process_kwargs(scalar_values)
                if self._writeconfig(startup=startup, provider_values=provider_values) is False:
                    raise OSError("config write failed")
                return True
            except Exception as e:
                try:
                    self._restore_transaction_state(runtime_snapshot, parser_defaults, parser_sections)
                except Exception as rollback_error:
                    logger.error(
                        "[CONFIG] Failed to restore runtime state after writeconfig_values failure: %s" % rollback_error
                    )
                logger.error("[CONFIG] writeconfig_values failed: %s" % e)
                return False

    def _writeconfig(self, values=None, startup=False, provider_values=None):
        try:
            config_path = self._config_write_target()
        except (OSError, RuntimeError) as e:
            logger.warn("[CONFIG] Refusing unsafe configuration write target: %s" % e)
            return False

        if values is not None:
            value_providers = {key: value for key, value in values.items() if key in _PROVIDER_EXTRA_FIELDS}
            provider_values = {**(provider_values or {}), **value_providers}
            scalar_values = {key: value for key, value in values.items() if key not in _PROVIDER_EXTRA_FIELDS}
            if scalar_values:
                self.process_kwargs(scalar_values)

        logger.fdebug("Writing configuration to file")
        parser_defaults = copy.deepcopy(config._defaults)
        parser_sections = copy.deepcopy(config._sections)
        try:
            provider_storage, provider_runtime, token_cache, has_provider_credentials = (
                self._prepare_provider_extras_for_write(provider_values)
            )
        except Exception as e:
            logger.warn("Unable to serialize provider configuration: %s" % type(e).__name__)
            return False

        config.set("Newznab", "extra_newznabs", provider_storage["EXTRA_NEWZNABS"])
        config.set("Torznab", "extra_torznabs", provider_storage["EXTRA_TORZNABS"])
        if has_provider_credentials:
            self.ENCRYPT_PASSWORDS = True
            config.set("General", "encrypt_passwords", "True")

        provider_order = None
        if startup is False and provider_values:
            provider_order, serialized_order = self._calculate_provider_order(
                provider_runtime["EXTRA_NEWZNABS"],
                provider_runtime["EXTRA_TORZNABS"],
            )
            if not config.has_section("Providers"):
                config.add_section("Providers")
            config.set("Providers", "PROVIDER_ORDER", serialized_order)

        ###this should be moved elsewhere...
        if type(self.IGNORED_PUBLISHERS) != list:
            if self.IGNORED_PUBLISHERS is None:
                bp = "None"
            else:
                if ",," in self.IGNORED_PUBLISHERS:
                    bp = "None"
                else:
                    bp = ", ".join(self.IGNORED_PUBLISHERS)
            config.set("CV", "ignored_publishers", bp)
        else:
            config.set("CV", "ignored_publishers", ", ".join(self.IGNORED_PUBLISHERS))
        ###
        config.set("General", "dynamic_update", str(self.DYNAMIC_UPDATE))

        # Atomic write: restrict the temporary file before making it visible.
        target_mode = 0o600
        try:
            target_mode = stat.S_IMODE(config_path.stat().st_mode)
        except FileNotFoundError:
            pass

        file_existed = config_path.is_file()
        original_file = config_path.read_bytes() if file_existed else None
        original_mode = config_path.stat().st_mode if file_existed else None
        durable_write_happened = False
        try:
            self._atomic_replace_file(config_path, target_mode, config.write)
            durable_write_happened = True
            if startup is False and provider_values:
                self.write_out_provider_searches(
                    provider_order=provider_order,
                    extra_newznabs=provider_runtime["EXTRA_NEWZNABS"],
                    extra_torznabs=provider_runtime["EXTRA_TORZNABS"],
                )
            self.EXTRA_NEWZNABS = provider_runtime["EXTRA_NEWZNABS"]
            self.EXTRA_TORZNABS = provider_runtime["EXTRA_TORZNABS"]
            self._provider_credential_tokens = token_cache
            for entries in provider_runtime.values():
                for entry in entries:
                    comicarr.PROVIDER_START_ID = max(comicarr.PROVIDER_START_ID, int(entry[6]))
            if provider_order is not None:
                self.PROVIDER_ORDER = provider_order
            logger.fdebug("Configuration written to disk.")
            return True
        except Exception as e:
            config._defaults = parser_defaults
            config._sections = parser_sections
            if durable_write_happened:
                try:
                    self._restore_config_file(config_path, file_existed, original_file, original_mode)
                except Exception as rollback_error:
                    logger.error(
                        "[CONFIG] Failed to restore configuration after provider projection: %s" % rollback_error
                    )
            logger.warn("Error writing configuration file: %s", e)
            return False

    def encrypt_items(self, mode="encrypt", updateconfig=False):
        # HTTP_PASSWORD excluded — it uses bcrypt (one-way hash), not Fernet
        encryption_list = OrderedDict()
        for attr_name, (section, ini_key) in ENCRYPTED_CONFIG_ITEMS.items():
            encryption_list[attr_name] = (section, ini_key, getattr(self, attr_name, None))

        new_encrypted = 0
        for k, v in encryption_list.items():
            section, ini_key, current_value = v

            if current_value is None:
                continue

            # configure() rewrites GIT_TOKEN to (token, "x-oauth-basic") for requests
            # Basic auth before encrypt_items() may run. Encrypt/decrypt the string
            # token only; never call str methods on the auth tuple.
            if isinstance(current_value, (tuple, list)) and current_value:
                current_value = current_value[0]
            if not isinstance(current_value, str):
                logger.warn(
                    "Skipping encryption for %s: expected string, got %s" % (ini_key, type(current_value).__name__)
                )
                continue

            # Skip values already encrypted with Fernet
            if current_value.startswith("gAAAAA"):
                if mode == "decrypt":
                    hp = encrypted.Encryptor(current_value, secure_dir=self.SECURE_DIR)
                    decrypted = hp.decrypt_it()
                    if decrypted["status"]:
                        setattr(self, k, decrypted["password"])
                        if updateconfig:
                            config.set(section, ini_key, decrypted["password"])
                continue

            # Legacy base64 encrypted values
            if current_value.startswith("^~$z$"):
                if mode == "decrypt":
                    hp = encrypted.Encryptor(current_value, secure_dir=self.SECURE_DIR)
                    decrypted = hp.decrypt_it()
                    if decrypted["status"]:
                        setattr(self, k, decrypted["password"])
                        if updateconfig:
                            config.set(section, ini_key, decrypted["password"])
                    else:
                        logger.warn(
                            "Password unable to decrypt - you might have to manually edit the ini for %s to reset the value"
                            % ini_key
                        )
                else:
                    # Re-encrypt legacy base64 → Fernet
                    hp = encrypted.Encryptor(current_value, secure_dir=self.SECURE_DIR)
                    decrypted = hp.decrypt_it()
                    if decrypted["status"]:
                        re_enc = encrypted.Encryptor(decrypted["password"], secure_dir=self.SECURE_DIR)
                        encrypted_password = re_enc.encrypt_it()
                        if encrypted_password["status"]:
                            config.set(section, ini_key, encrypted_password["password"])
                            new_encrypted += 1
                continue

            # Plaintext — encrypt with Fernet
            if mode == "encrypt":
                hp = encrypted.Encryptor(current_value, secure_dir=self.SECURE_DIR)
                encrypted_password = hp.encrypt_it()
                if encrypted_password["status"]:
                    config.set(section, ini_key, encrypted_password["password"])
                    new_encrypted += 1
                else:
                    logger.warn(
                        "Unable to encrypt password for %s - it has not been encrypted. Keeping it as it is." % ini_key
                    )

        if new_encrypted > 0:
            self.WRITE_THE_CONFIG = True

    def _normalize_git_token_auth(self):
        """Keep the requests Basic-auth token tuple flat across reconfiguration."""
        token = self.GIT_TOKEN
        while isinstance(token, (tuple, list)) and token:
            token = token[0]
        if token:
            self.GIT_TOKEN = (token, "x-oauth-basic")

    def _ensure_secure_directory(self):
        """Establish encryption authority before any configuration persistence."""
        if not self.SECURE_DIR:
            self.SECURE_DIR = os.path.join(comicarr.DATA_DIR, ".secure")

        try:
            if os.path.exists(self.SECURE_DIR):
                if os.name != "nt":
                    os.chmod(self.SECURE_DIR, 0o700)
                return
            os.makedirs(self.SECURE_DIR, mode=0o700)
            if os.name != "nt":
                os.chmod(self.SECURE_DIR, 0o700)
        except OSError:
            logger.error(
                "[FATAL] Could not create secure directory at %s. "
                "Credential encryption will not work. Fix permissions and restart." % self.SECURE_DIR
            )
            raise SystemExit(1)

    def configure(self, update=False, startup=False):

        if all([self.CLEAR_PROVIDER_TABLE is True, startup is True]):
            comicarr.MAINTENANCE = True

        # force alt_pull = 2 on restarts regardless of settings
        if self.ALT_PULL != 2:
            self.ALT_PULL = 2
            config.set("Weekly", "alt_pull", str(self.ALT_PULL))

        # force off public torrents usage as currently broken.
        self.ENABLE_PUBLIC = False

        if self.GIT_TOKEN:
            self._normalize_git_token_auth()
            # logger.info('git_token set to %s' % (self.GIT_TOKEN,))

        try:
            if not any(
                [
                    self.SAB_HOST is None,
                    self.SAB_HOST == "",
                    "http://" in self.SAB_HOST[:7],
                    "https://" in self.SAB_HOST[:8],
                ]
            ):
                self.SAB_HOST = "http://" + self.SAB_HOST
            if self.SAB_HOST.endswith("/"):
                logger.fdebug("Auto-correcting trailing slash in SABnzbd url (not required)")
                self.SAB_HOST = self.SAB_HOST[:-1]
        except:
            pass

        if any([self.HTTP_ROOT is None, self.HTTP_ROOT == "/"]):
            self.HTTP_ROOT = "/"
        else:
            if not self.HTTP_ROOT.endswith("/"):
                self.HTTP_ROOT += "/"

        if not update:
            logger.fdebug("Log dir: %s" % self.LOG_DIR)

        if self.LOG_DIR is None:
            self.LOG_DIR = os.path.join(comicarr.DATA_DIR, "logs")

        if not os.path.exists(self.LOG_DIR):
            try:
                os.makedirs(self.LOG_DIR)
            except OSError:
                if not comicarr.QUIET:
                    logger.warn("Unable to create the log directory. Logging to screen only.")

        # if not update:
        #     logger.fdebug('[Cache Check] Cache directory currently set to : ' + self.CACHE_DIR)

        # Put the cache dir in the data dir for now
        if not self.CACHE_DIR:
            self.CACHE_DIR = os.path.join(str(comicarr.DATA_DIR), "cache")
            if not update:
                logger.fdebug(
                    "[Cache Check] Cache directory not found in configuration. Defaulting location to : "
                    + self.CACHE_DIR
                )

        if not os.path.exists(self.CACHE_DIR):
            try:
                os.makedirs(self.CACHE_DIR)
            except OSError:
                logger.error(
                    "[Cache Check] Could not create cache dir. Check permissions of datadir: %s" % comicarr.DATA_DIR
                )

        self._ensure_secure_directory()

        # Encrypt plaintext credentials now that SECURE_DIR is available
        if self.ENCRYPT_PASSWORDS is True:
            self.encrypt_items(mode="encrypt")

        # Migrate login password to bcrypt on startup (handles all three states)
        if self.HTTP_PASSWORD and not (self.HTTP_PASSWORD.startswith("$2b$") or self.HTTP_PASSWORD.startswith("$2a$")):
            # Backup config before credential migration
            backup_path = os.path.join(self.SECURE_DIR, "config.ini.pre-security-migration.bak")
            if not os.path.exists(backup_path):
                try:
                    shutil.copy2(self._config_file, backup_path)
                    logger.info("[SECURITY] Pre-migration backup saved to %s" % backup_path)
                except Exception as e:
                    logger.error("[SECURITY] Failed to create pre-migration backup: %s" % e)

            new_hash = encrypted.migrate_password(self.HTTP_PASSWORD)
            if new_hash:
                self.HTTP_PASSWORD = new_hash
                config.set("Interface", "http_password", new_hash)
                self.ENCRYPT_PASSWORDS = True
                config.set("General", "encrypt_passwords", "True")
                self.WRITE_THE_CONFIG = True
                logger.info("[SECURITY] Login password migrated to bcrypt")

        # Startup security permission checks
        if startup and not update:
            try:
                config_mode = os.stat(self._config_file).st_mode
                if config_mode & 0o044:
                    logger.warn(
                        "[SECURITY] config.ini is world-readable (mode %o). "
                        "Run: chmod 600 %s" % (config_mode & 0o777, self._config_file)
                    )
            except Exception:
                pass

            master_key_path = os.path.join(self.SECURE_DIR, "master.key")
            if os.path.exists(master_key_path):
                try:
                    key_mode = os.stat(master_key_path).st_mode
                    if key_mode & 0o044:
                        logger.warn(
                            "[SECURITY] master.key is world-readable (mode %o). "
                            "Run: chmod 600 %s" % (key_mode & 0o777, master_key_path)
                        )
                except Exception:
                    pass

        if not self.BACKUP_LOCATION:
            self.BACKUP_LOCATION = os.path.join(comicarr.DATA_DIR, "backup")

        if not os.path.exists(self.BACKUP_LOCATION):
            try:
                os.makedirs(self.BACKUP_LOCATION)
            except OSError:
                logger.error(
                    "[Backup Location Check] Could not create backup directory. Check permissions for creation of : %s"
                    % self.BACKUP_LOCATION
                )

        if self.IMPORT_DIR:
            if not os.path.isdir(self.IMPORT_DIR):
                logger.warning("[CONFIG] Import directory does not exist: %s" % self.IMPORT_DIR)
            else:
                overlap_dirs = {
                    "COMIC_DIR": self.COMIC_DIR,
                    "MANGA_DIR": self.MANGA_DIR,
                    "DESTINATION_DIR": self.DESTINATION_DIR,
                    "CHECK_FOLDER": self.CHECK_FOLDER if hasattr(self, "CHECK_FOLDER") else None,
                }
                real_import = os.path.realpath(self.IMPORT_DIR)
                for name, path in overlap_dirs.items():
                    if not path:
                        continue
                    real_other = os.path.realpath(path)
                    if (
                        real_import == real_other
                        or real_import.startswith(real_other + os.sep)
                        or real_other.startswith(real_import + os.sep)
                    ):
                        logger.warning(
                            "[CONFIG] IMPORT_DIR overlaps with %s (%s). Import Inbox disabled." % (name, path)
                        )
                        self.IMPORT_DIR = None
                        break

        if all([self.STORYARCDIR is True, self.DESTINATION_DIR is not None]):
            if os.path.exists(self.DESTINATION_DIR):
                if not self.STORYARC_LOCATION:
                    self.STORYARC_LOCATION = os.path.join(self.DESTINATION_DIR, "StoryArcs")

                if not os.path.exists(self.STORYARC_LOCATION):
                    try:
                        os.makedirs(self.STORYARC_LOCATION)
                    except OSError as e:
                        logger.error(
                            "[STORYARC LOCATION] Could not create storyarcs directory @ %s. Error returned: %s"
                            % (self.STORYARC_LOCATION, e)
                        )

                logger.info(
                    "[STORYARC LOCATION] Storyarc Base directory location set to: %s" % (self.STORYARC_LOCATION)
                )

        # make sure the cookies.dat file is not in cache
        for f in glob.glob(os.path.join(self.CACHE_DIR, ".32p_cookies.dat")):
            try:
                if os.path.isfile(f):
                    shutil.move(f, os.path.join(self.SECURE_DIR, ".32p_cookies.dat"))
            except Exception:
                logger.error(
                    "SECURE-DIR-MOVE] Unable to move cookies file into secure location. This is a fatal error."
                )
                sys.exit()

        if self.CLEANUP_CACHE:
            logger.fdebug(
                "[Cache Cleanup] Cache Cleanup initiated. Will delete items from cache that are no longer needed."
            )
            cache_types = ["*.nzb", "*.torrent", "*.html", "mylar_*", "html_cache"]
            dir_locations = []
            dir_locations.append(self.CACHE_DIR)
            if self.CLEANUP_STRAYS:
                logger.fdebug(
                    "[Cache Cleanup] cbr/cbz cache cleanup option detected. Will remove any detected cbr & cbz files from cache/ddl location."
                )
                cache_types.extend(("*.zip", "*.cbr", "*.cbz", "[__*__]"))
                if all(
                    [
                        self.DDL_LOCATION is not None,
                        self.DESTINATION_DIR is not None,
                        self.CACHE_DIR != self.DDL_LOCATION,
                        self.DDL_LOCATION != self.DESTINATION_DIR,
                    ]
                ):
                    dir_locations.append(self.DDL_LOCATION)
            cntr = 0
            pathlimiter = "**"
            for y in dir_locations:
                for x in cache_types:
                    tmp_path = os.path.join(y, pathlimiter, x)
                    if x == "[__*__]":
                        tmp_path = os.path.join(y, pathlimiter, "*" + glob.escape("[__") + "*" + glob.escape("__]"))
                    for f in glob.glob(tmp_path, recursive=True):
                        ff = Path(f)
                        try:
                            if os.path.isdir(f):
                                if all([ff.stem != "html_cache", ff.stem != "mega"]):
                                    shutil.rmtree(f)
                            else:
                                os.remove(f)
                        except Exception as e:
                            logger.warn("[ERROR] Unable to remove %s from cache. [%s]" % (f, e))
                        cntr += 1

            if cntr > 1:
                logger.fdebug("[Cache Cleanup] Cache Cleanup finished. Cleaned %s items" % cntr)
            else:
                logger.fdebug("[Cache Cleanup] Cache Cleanup finished. Nothing to clean!")

        d_path = "/proc/self/cgroup"
        if (
            os.path.exists("/.dockerenv")
            or "KUBERNETES_SERVICE_HOST" in os.environ
            or os.path.isfile(d_path)
            and any("docker" in line for line in open(d_path))
        ):
            logger.info("[DOCKER-AWARE] Docker installation detected.")
            comicarr.INSTALL_TYPE = "docker"
            if any([self.DESTINATION_DIR is None, self.DESTINATION_DIR == ""]):
                logger.info("[DOCKER-AWARE] Setting default comic location path to /comics")
                self.DESTINATION_DIR = "/comics"
            if any([self.MANGA_DESTINATION_DIR is None, self.MANGA_DESTINATION_DIR == ""]):
                logger.info("[DOCKER-AWARE] Setting default manga location path to /manga")
                self.MANGA_DESTINATION_DIR = "/manga"
            if all([self.NZB_DOWNLOADER == 0, self.SAB_DIRECTORY is None, self.SAB_DIRECT_UNPACK is False]):
                logger.info("[DOCKER-AWARE] Setting default sabnzbd download directory location to /downloads")
                self.SAB_DIRECT_UNPACK = True
                self.SAB_DIRECTORY = "/downloads"

        if all([self.GRABBAG_DIR is None, self.DESTINATION_DIR is not None]):
            self.GRABBAG_DIR = os.path.join(self.DESTINATION_DIR, "Grabbag")
            logger.fdebug("[Grabbag Directory] Setting One-Off directory to default location: %s" % self.GRABBAG_DIR)

        if self.ARC_FOLDERFORMAT is None:
            self.ARC_FOLDERFORMAT = "$arc ($spanyears)"

        ## Sanity checking
        if any([self.COMICVINE_API is None, self.COMICVINE_API == "None", self.COMICVINE_API == ""]):
            logger.error(
                "No User Comicvine API key specified. I will not work very well due to api limits - http://api.comicvine.com/ and get your own free key."
            )
            self.COMICVINE_API = None
        # Check if Comicvine API key starts with None, thus making it invalid
        elif self.COMICVINE_API[:4] == "None":
            # Notify user of what's going on
            logger.warn("Comicvine API key starts with a None, working around for now, please fix")
            # Set the actual API key, so comicarr does not appear broken from the start
            self.COMICVINE_API = self.COMICVINE_API[4:]

        clamp_scheduler_intervals(self)

        if self.SEARCH_DELAY < 1:
            logger.fdebug("Minimum search delay set for 1 minute to avoid hammering.")
            self.SEARCH_DELAY = 1

        if self.ENABLE_RSS is True and comicarr.RSS_STATUS == "Paused":
            comicarr.RSS_STATUS = "Waiting"
        elif self.ENABLE_RSS is False and comicarr.RSS_STATUS == "Waiting":
            comicarr.RSS_STATUS = "Paused"

        if self.DUPECONSTRAINT is None:
            # default dupecontraint to filesize
            self.DUPECONSTRAINT = "filesize"
            config.set("Duplicates", "dupeconstraint", "filesize")

        if self.MINSIZE is not None:
            self.MINSIZE = re.sub(r"[^0-9]", "", self.MINSIZE).strip()

        if self.MAXSIZE is not None:
            self.MAXSIZE = re.sub(r"[^0-9]", "", self.MAXSIZE).strip()

        if not helpers.is_number(self.CHMOD_DIR):
            logger.fdebug("CHMOD Directory value is not a valid numeric - please correct. Defaulting to 0777")
            self.CHMOD_DIR = "0777"

        if not helpers.is_number(self.CHMOD_FILE):
            logger.fdebug("CHMOD File value is not a valid numeric - please correct. Defaulting to 0660")
            self.CHMOD_FILE = "0660"

        if self.FILE_OPTS is None:
            self.FILE_OPTS = "move"

        if any([self.FILE_OPTS == "hardlink", self.FILE_OPTS == "softlink"]):
            # we can't have metatagging enabled with hard/soft linking. Forcibly disable it here just in case it's set on load.
            self.ENABLE_META = False

        if all([self.IGNORED_PUBLISHERS is not None, self.IGNORED_PUBLISHERS != ""]):
            logger.info("Ignored Publishers: %s" % self.IGNORED_PUBLISHERS)
            if type(self.IGNORED_PUBLISHERS) == str:
                self.ignored_PUBLISHERS = self.IGNORED_PUBLISHERS.split(", ")

        if all([self.AUTHENTICATION == 0, self.HTTP_USERNAME is not None, self.HTTP_PASSWORD is not None]):
            # set it to the default login prompt if nothing selected.
            self.AUTHENTICATION = 1
        elif all([self.HTTP_USERNAME is None, self.HTTP_PASSWORD is None]):
            self.AUTHENTICATION = 0

        if self.ENCRYPT_PASSWORDS is True:
            self.encrypt_items(mode="decrypt")
        self._load_provider_extra_credentials()
        if all([self.IGNORE_TOTAL is True, self.IGNORE_HAVETOTAL is True]):
            self.IGNORE_TOTAL = False
            self.IGNORE_HAVETOTAL = False
            logger.warn(
                "You cannot have both ignore_total and ignore_havetotal enabled in the config.ini at the same time. Set only ONE to true - disabling both until this is resolved."
            )

        if len(self.MASS_PUBLISHERS) > 0 and self.MASS_PUBLISHERS != "[]":
            if type(self.MASS_PUBLISHERS) != list:
                try:
                    self.MASS_PUBLISHERS = json.loads(self.MASS_PUBLISHERS)
                except Exception:
                    try:
                        tmp_publishers = json.dumps(self.MASS_PUBLISHERS)
                        self.MASS_PUBLISHERS = json.loads(tmp_publishers)
                    except Exception as e:
                        logger.warn(
                            "[MASS_PUBLISHERS] Unable to convert publishers [%s]. Error returned: %s"
                            % (self.MASS_PUBLISHERS, e)
                        )
        logger.info("[MASS_PUBLISHERS] Auto-add for weekly publishers set to: %s" % (self.MASS_PUBLISHERS,))

        if len(self.IGNORE_SEARCH_WORDS) > 0 and self.IGNORE_SEARCH_WORDS != "[]":
            if type(self.IGNORE_SEARCH_WORDS) != list:
                try:
                    self.IGNORE_SEARCH_WORDS = json.loads(self.IGNORE_SEARCH_WORDS)
                except Exception:
                    logger.warn("unable to load ignored search words")
        else:
            self.IGNORE_SEARCH_WORDS = [".exe", ".iso", "pdf-xpost", "pdf", "ebook"]
            config.set("General", "ignore_search_words", json.dumps(self.IGNORE_SEARCH_WORDS))

        logger.fdebug("[IGNORE_SEARCH_WORDS] Words to flag search result as invalid: %s" % (self.IGNORE_SEARCH_WORDS,))

        if len(self.PROBLEM_DATES) > 0 and self.PROBLEM_DATES != "[]":
            if type(self.PROBLEM_DATES) != list:
                try:
                    self.PROBLEM_DATES = json.loads(self.PROBLEM_DATES)
                except Exception:
                    logger.warn("unable to load problem dates")
        else:
            self.PROBLEM_DATES = ["2021-07-14 04:00:34"]
            config.set("General", "problem_dates", json.dumps(self.PROBLEM_DATES))

        logger.info("[PROBLEM_DATES] Problem dates loaded: %s" % (self.PROBLEM_DATES,))

        # default opds endpoint check
        if any([self.OPDS_ENDPOINT is None, len(self.OPDS_ENDPOINT) == 0]):
            self.OPDS_ENDPOINT = "opds"
        else:
            if self.OPDS_ENDPOINT.startswith("/"):
                self.OPDS_ENDPOINT = self.OPDS_ENDPOINT[1:]
            elif self.OPDS_ENDPOINT.endswith("/"):
                self.OPDS_ENDPOINT = self.OPDS_ENDPOINT[:-1]
            config.set("OPDS", "opds_endpoint", self.OPDS_ENDPOINT.strip())

        # comictagger - force to use included version if option is enabled.
        from comicarr._vendor.comictaggerlib import ctversion

        logger.info("[COMICTAGGER] Version detected: %s" % ctversion.version)
        # if any([self.ENABLE_META, self.CBR2CBZ_ONLY]):
        comicarr.CMTAGGER_PATH = comicarr.PROG_DIR

        if not ([self.CT_NOTES_FORMAT == "CVDB", self.CT_NOTES_FORMAT == "Issue ID"]):
            self.CT_NOTES_FORMAT = "Issue ID"
            config.set("Metatagging", "ct_notes_format", self.CT_NOTES_FORMAT)

        # we need to make sure the default folder setting for the comictagger settings exists so things don't error out
        if self.CT_SETTINGSPATH is None:
            chkpass = False

            # windows won't be able to create in ~, so force it to DATA_DIR
            if comicarr.OS_DETECT == "Windows":
                ct_path = comicarr.DATA_DIR
                chkpass = True
            else:
                ct_path = str(Path(os.path.expanduser("~")))
                try:
                    os.mkdir(os.path.join(ct_path, ".ComicTagger"))
                    chkpass = True
                except OSError as e:
                    if e.errno != errno.EEXIST:
                        logger.error(
                            "Unable to create .ComicTagger directory in %s. Setting up to default location of %s"
                            % (ct_path, os.path.join(comicarr.DATA_DIR, ".ComicTagger"))
                        )
                        ct_path = comicarr.DATA_DIR
                        chkpass = True
                    elif e.errno == 17:  # file_already_exists
                        chkpass = True
                except exception:
                    logger.error(
                        "Unable to create setting directory for ComicTagger. This WILL cause problems when tagging."
                    )
                    ct_path = comicarr.DATA_DIR
                    chkpass = True

            if chkpass is True:
                self.CT_SETTINGSPATH = os.path.join(ct_path, ".ComicTagger")
                config.set("Metatagging", "ct_settingspath", self.CT_SETTINGSPATH)

        if not update:
            logger.fdebug("[COMICTAGGER] Setting ComicTagger settings default path to : %s" % self.CT_SETTINGSPATH)

        if not os.path.exists(self.CT_SETTINGSPATH):
            try:
                os.mkdir(self.CT_SETTINGSPATH)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    logger.error(
                        "Unable to create setting directory for ComicTagger. This WILL cause problems when tagging."
                    )
            else:
                logger.fdebug("Successfully created ComicTagger Settings location.")

        # make sure the user_agent is running a current version and write it to the .ComicTagger file for use with CT
        if "42.0.2311.135" in self.CV_USER_AGENT:
            self.CV_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

        ct_settingsfile = os.path.join(self.CT_SETTINGSPATH, "settings")
        if os.path.exists(ct_settingsfile):
            ct_config = configparser.ConfigParser()

            def readline_generator(f):
                line = f.readline()
                while line:
                    yield line
                    line = f.readline()

            ct_config.read_file(readline_generator(codecs.open(ct_settingsfile, "r", "utf8")))

            tmp_agent = None
            if ct_config.has_option("comicvine", "cv_user_agent"):
                tmp_agent = ct_config.get("comicvine", "cv_user_agent")

            if tmp_agent != self.CV_USER_AGENT:
                # update
                try:
                    with codecs.open(ct_settingsfile, "r", "utf8") as ct_read:
                        ct_lines = ct_read.readlines()

                    process_next = False
                    cv_line = "cv_user_agent = %s" % self.CV_USER_AGENT
                    with codecs.open(ct_settingsfile, encoding="utf8", mode="w+") as ct_file:
                        for line in ct_lines:
                            if "cv_user_agent" in line:
                                line = cv_line

                            elif "[comicvine]" not in line and process_next:
                                ct_file.write(cv_line + "\n")
                                process_next = False

                            if tmp_agent is None and "[comicvine]" in line:
                                process_next = True

                            ct_file.write(line)

                    logger.fdebug("Updated CT Settings with new CV user agent string.")
                except IOError as e:
                    logger.warn("Error writing configuration file: %s" % e)
            else:
                logger.info("[CV_USER_AGENT] Agent already identical in comictagger session.")

        # make sure queues are running here...
        if startup is False:
            if self.POST_PROCESSING is True and (
                all([self.NZB_DOWNLOADER == 0, self.SAB_CLIENT_POST_PROCESSING is True])
                or all([self.NZB_DOWNLOADER == 1, self.NZBGET_CLIENT_POST_PROCESSING is True])
            ):
                comicarr.queue_schedule("nzb_queue", "start")
            elif self.POST_PROCESSING is True and (
                all([self.NZB_DOWNLOADER == 0, self.SAB_CLIENT_POST_PROCESSING is False])
                or all([self.NZB_DOWNLOADER == 1, self.NZBGET_CLIENT_POST_PROCESSING is False])
                or self.NZB_DOWNLOADER == 3
            ):
                comicarr.queue_schedule("nzb_queue", "stop")

            if self.ENABLE_DDL is True:
                comicarr.queue_schedule("ddl_queue", "start")
            elif self.ENABLE_DDL is False:
                comicarr.queue_schedule("ddl_queue", "stop")

        if self.FOLDER_FORMAT is None:
            self.FOLDER_FORMAT = "$Series ($Year)"

        if "$Annual" in self.FOLDER_FORMAT:
            logger.fdebug(
                "$Annual has been depreciated as a folder format option. Auto-removing from your folder format scheme."
            )
            ann_removed = re.sub(r"\$annual", "", self.FOLDER_FORMAT, flags=re.I).strip()
            ann_remove = re.sub(r"\s+", " ", ann_removed).strip()
            self.FOLDER_FORMAT = ann_remove
            config.set("General", "folder_format", ann_remove)

        if len(self.DDL_PRIORITY_ORDER) > 0 and self.DDL_PRIORITY_ORDER != "[]":
            if type(self.DDL_PRIORITY_ORDER) != list:
                try:
                    self.DDL_PRIORITY_ORDER = json.loads(self.DDL_PRIORITY_ORDER)
                except Exception:
                    logger.warn("[DDL PRIORITY ORDER] Unable to load DDL priority order from setting to default")
                    self.DDL_PRIORITY_ORDER = ["mega", "mediafire", "pixeldrain", "main"]

            # validate entries
            ddl_pros = ["mega", "mediafire", "pixeldrain", "main"]
            for dpo in self.DDL_PRIORITY_ORDER:
                if dpo.lower() not in ddl_pros:
                    logger.warn("[DDL PRIORITY ORDER] Invalid value detected - removing %s" % dpo)
                    self.DDL_PRIORITY_ORDER.pop(self.DDL_PRIORITY_ORDER.index(dpo))

        else:
            self.DDL_PRIORITY_ORDER = ["mega", "mediafire", "pixeldrain", "main"]  # default order
            config.set("DDL", "ddl_priority_order", json.dumps(self.DDL_PRIORITY_ORDER))

        logger.info(
            "[DDL PRIORITY ORDER] DDL will attempt to use the following 3rd party sites in this specific download order: %s"
            % self.DDL_PRIORITY_ORDER
        )

        if self.SEARCH_TIER_CUTOFF is None:
            self.SEARCH_TIER_CUTOFF = 14
            config.set("General", "search_tier_cutoff", str(self.SEARCH_TIER_CUTOFF))
        else:
            if not str(self.SEARCH_TIER_CUTOFF).isdigit():
                self.SEARCH_TIER_CUTOFF = 14
                config.set("General", "search_tier_cutoff", str(self.SEARCH_TIER_CUTOFF))
        logger.info("[Search Tier Cutoff] Setting Tier-1 cutoff point to %s days" % self.SEARCH_TIER_CUTOFF)

        if all([self.GOTIFY_ENABLED, self.GOTIFY_SERVER_URL is not None]):
            if not self.GOTIFY_SERVER_URL.endswith("/"):
                self.GOTIFY_SERVER_URL += "/"
                config.set("GOTIFY", "gotify_server_url", self.GOTIFY_SERVER_URL)

        if self.MODE_32P is False and self.RSSFEED_32P is not None:
            comicarr.KEYS_32P = self.parse_32pfeed(self.RSSFEED_32P)

        if self.AUTO_SNATCH is True and self.AUTO_SNATCH_SCRIPT is None:
            self.AUTO_SNATCH_SCRIPT = os.path.join(
                comicarr.PROG_DIR, "post-processing", "torrent-auto-snatch", "getlftp.sh"
            )
            config.set("AutoSnatch", "auto_snatch_script", self.AUTO_SNATCH_SCRIPT)
        comicarr.USE_SABNZBD = False
        comicarr.USE_NZBGET = False
        comicarr.USE_BLACKHOLE = False

        if (
            all([self.NZB_DOWNLOADER == 0, self.SAB_HOST is None])
            or all([self.NZB_DOWNLOADER == 1, self.NZBGET_HOST is None])
            or all([self.NZB_DOWNLOADER == 2, self.BLACKHOLE_DIR is None])
        ):
            logger.info("NZB Downloader detected as invalid entry - defaulting to None")
            self.NZB_DOWNLOADER = 3

        if self.NZB_DOWNLOADER == 0:
            comicarr.USE_SABNZBD = True
        elif self.NZB_DOWNLOADER == 1:
            comicarr.USE_NZBGET = True
        elif self.NZB_DOWNLOADER == 2:
            comicarr.USE_BLACKHOLE = True

        if self.SAB_PRIORITY.isdigit():
            if self.SAB_PRIORITY == "0":
                self.SAB_PRIORITY = "Default"
            elif self.SAB_PRIORITY == "1":
                self.SAB_PRIORITY = "Low"
            elif self.SAB_PRIORITY == "2":
                self.SAB_PRIORITY = "Normal"
            elif self.SAB_PRIORITY == "3":
                self.SAB_PRIORITY = "High"
            elif self.SAB_PRIORITY == "4":
                self.SAB_PRIORITY = "Paused"
            else:
                self.SAB_PRIORITY = "Default"

        comicarr.USE_WATCHDIR = False
        comicarr.USE_UTORRENT = False
        comicarr.USE_RTORRENT = False
        comicarr.USE_TRANSMISSION = False
        comicarr.USE_DELUGE = False
        comicarr.USE_QBITTORRENT = False
        if self.TORRENT_DOWNLOADER == 0:
            comicarr.USE_WATCHDIR = True
        elif self.TORRENT_DOWNLOADER == 1:
            comicarr.USE_UTORRENT = True
        elif self.TORRENT_DOWNLOADER == 2:
            comicarr.USE_RTORRENT = True
        elif self.TORRENT_DOWNLOADER == 3:
            comicarr.USE_TRANSMISSION = True
        elif self.TORRENT_DOWNLOADER == 4:
            comicarr.USE_DELUGE = True
        elif self.TORRENT_DOWNLOADER == 5:
            comicarr.USE_QBITTORRENT = True
        else:
            self.TORRENT_DOWNLOADER = 0
            comicarr.USE_WATCHDIR = True

    def parse_32pfeed(self, rssfeedline):
        KEYS_32P = {}
        if self.ENABLE_32P and len(rssfeedline) > 1:
            userid_st = rssfeedline.find("&user")
            userid_en = rssfeedline.find("&", userid_st + 1)
            if userid_en == -1:
                userid_32p = rssfeedline[userid_st + 6 :]
            else:
                userid_32p = rssfeedline[userid_st + 6 : userid_en]

            auth_st = rssfeedline.find("&auth")
            auth_en = rssfeedline.find("&", auth_st + 1)
            if auth_en == -1:
                auth_32p = rssfeedline[auth_st + 6 :]
            else:
                auth_32p = rssfeedline[auth_st + 6 : auth_en]

            authkey_st = rssfeedline.find("&authkey")
            authkey_en = rssfeedline.find("&", authkey_st + 1)
            if authkey_en == -1:
                authkey_32p = rssfeedline[authkey_st + 9 :]
            else:
                authkey_32p = rssfeedline[authkey_st + 9 : authkey_en]

            KEYS_32P = {"user": userid_32p, "auth": auth_32p, "authkey": authkey_32p, "passkey": self.PASSKEY_32P}

        return KEYS_32P

    def get_extras(self):
        extra_newznabs = parse_provider_extras(self.EXTRA_NEWZNABS, self.CONFIG_VERSION)
        extra_torznabs = parse_provider_extras(self.EXTRA_TORZNABS, self.CONFIG_VERSION)

        x_newzcat = []
        x_torzcat = []
        cnt = 0
        while cnt < 2:
            if cnt == 0:
                ex = extra_newznabs
            else:
                ex = extra_torznabs

            for x in ex:
                x_cat = x[4]
                if x_cat:
                    if "#" in x_cat:
                        x_t = x[4].split("#")
                        x_cat = ",".join(x_t)
                        if x_cat[0] == ",":
                            x_cat = re.sub(",", "#", x_cat, 1)
                try:
                    if cnt == 0:
                        x_newzcat.append((x[0], x[1], x[2], x[3], x_cat, x[5], int(x[6])))
                    else:
                        x_torzcat.append((x[0], x[1], x[2], x[3], x_cat, x[5], int(x[6])))
                    if int(x[6]) > comicarr.PROVIDER_START_ID:
                        comicarr.PROVIDER_START_ID = int(x[6])
                except Exception:
                    if cnt == 0:
                        x_newzcat.append((x[0], x[1], x[2], x[3], x_cat, x[5]))
                    else:
                        x_torzcat.append((x[0], x[1], x[2], x[3], x_cat, x[5]))
            cnt += 1

        # had to loop thru entire set above in order to get the highest id to start at
        xx_newzcat = []
        xx_torzcat = []
        cnt = 0
        while cnt < 2:
            if cnt == 0:
                ex = x_newzcat
            else:
                ex = x_torzcat

            for xn in ex:
                try:
                    if cnt == 0:
                        xx_newzcat.append((xn[0], xn[1], xn[2], xn[3], xn[4], xn[5], xn[6]))
                    else:
                        xx_torzcat.append((xn[0], xn[1], xn[2], xn[3], xn[4], xn[5], xn[6]))
                except Exception:
                    comicarr.PROVIDER_START_ID += 1
                    if cnt == 0:
                        xx_newzcat.append((xn[0], xn[1], xn[2], xn[3], xn[4], xn[5], comicarr.PROVIDER_START_ID))
                    else:
                        xx_torzcat.append((xn[0], xn[1], xn[2], xn[3], xn[4], xn[5], comicarr.PROVIDER_START_ID))
            cnt += 1
        # logger.fdebug('xx_newzcat: %s' % (xx_newzcat,))
        # logger.fdebug('xx_torzcat: %s' % (xx_torzcat,))
        return xx_newzcat, xx_torzcat

    def get_extra_torznabs(self):
        extra_torznabs = parse_provider_extras(self.EXTRA_TORZNABS, self.CONFIG_VERSION)
        x_torcat = []
        for x in extra_torznabs:
            x_cat = x[4]
            if "#" in x_cat:
                x_t = x[4].split("#")
                x_cat = ",".join(x_t)
            try:
                x_torcat.append((x[0], x[1], x[2], x[3], x_cat, x[5], int(x[6])))
                if int(x[6]) > comicarr.PROVIDER_START_ID:
                    comicarr.PROVIDER_START_ID = int(x[6])
            except Exception:
                x_torcat.append((x[0], x[1], x[2], x[3], x_cat, x[5]))

        # had to loop thru entire set above in order to get the highest id to start at
        xx_torcat = []
        for xn in x_torcat:
            try:
                xx_torcat.append((xn[0], xn[1], xn[2], xn[3], xn[4], xn[5], xn[6]))
            except Exception:
                comicarr.PROVIDER_START_ID += 1
                xx_torcat.append((xn[0], xn[1], xn[2], xn[3], xn[4], xn[5], comicarr.PROVIDER_START_ID))

        extra_torznabs = xx_torcat
        return extra_torznabs

    def get_ignored_pubs(self):
        if all([self.IGNORED_PUBLISHERS is not None, self.IGNORED_PUBLISHERS != "", len(self.IGNORED_PUBLISHERS) != 0]):
            if ",," not in self.IGNORED_PUBLISHERS:
                ignored_pubs = [x.strip() for x in self.IGNORED_PUBLISHERS.split(",")]
            else:
                ignored_pubs = []
        else:
            ignored_pubs = []
        return ignored_pubs

    def _calculate_provider_order(self, extra_newznabs=None, extra_torznabs=None):
        """Calculate provider ordering without mutating runtime, disk, or the database."""
        extra_newznabs = self.EXTRA_NEWZNABS if extra_newznabs is None else extra_newznabs
        extra_torznabs = self.EXTRA_TORZNABS if extra_torznabs is None else extra_torznabs
        PR = []
        PR_NUM = 0
        if self.ENABLE_TORRENT_SEARCH:
            if self.ENABLE_32P:
                PR.append("32p")
                PR_NUM += 1
            # if self.ENABLE_PUBLIC:
            #    PR.append('public torrents')
            #    PR_NUM +=1
        if self.EXPERIMENTAL:
            PR.append("Experimental")
            PR_NUM += 1

        if self.ENABLE_DDL:
            if self.ENABLE_GETCOMICS:
                PR.append("DDL(GetComics)")
                PR_NUM += 1
            if self.ENABLE_EXTERNAL_SERVER:
                PR.append("DDL(External)")
                PR_NUM += 1

        PPR = ["Experimental", "DDL(GetComics)", "DDL(External)"]
        if self.NEWZNAB:
            for ens in extra_newznabs:
                if str(ens[5]) == "1":  # if newznabs are enabled
                    if ens[0] == "":
                        en_name = ens[1]
                    else:
                        en_name = ens[0]
                    if en_name.endswith('"'):
                        en_name = re.sub('"', "", str(en_name)).strip()
                    PR.append(en_name)
                    PPR.append(en_name)
                    PR_NUM += 1

        if self.ENABLE_TORZNAB and self.ENABLE_TORRENT_SEARCH:
            for ets in extra_torznabs:
                if str(ets[5]) == "1":  # if torznabs are enabled
                    if ets[0] == "":
                        et_name = ets[1]
                    else:
                        et_name = ets[0]
                    if et_name.endswith('"'):
                        et_name = re.sub('"', "", str(et_name)).strip()
                    PR.append(et_name)
                    PPR.append(et_name)
                    PR_NUM += 1

        if self.PROVIDER_ORDER is not None:
            try:
                PRO_ORDER = list(zip(*[iter(self.PROVIDER_ORDER.split(", "))] * 2, strict=False))
            except:
                PO = []
                for k, v in self.PROVIDER_ORDER.items():
                    PO.append(k)
                    PO.append(v)
                POR = ", ".join(PO)
                PRO_ORDER = list(zip(*[iter(POR.split(", "))] * 2, strict=False))

            logger.fdebug("Original provider_order sequence: %s" % self.PROVIDER_ORDER)

            # if provider order exists already, load it and then append to end any NEW entries.
            logger.fdebug("Provider sequence already pre-exists. Re-loading and adding/remove any new entries")
            TMPPR_NUM = 0
            PROV_ORDER = []
            # load original sequence
            for PRO in PRO_ORDER:
                PROV_ORDER.append({"order_seq": PRO[0], "provider": str(PRO[1])})
                TMPPR_NUM += 1

            # calculate original sequence to current sequence for discrepancies
            # print('TMPPR_NUM: %s --- PR_NUM: %s' % (TMPPR_NUM, PR_NUM))
            if PR_NUM != TMPPR_NUM:
                logger.fdebug("existing Order count does not match New Order count")
                if PR_NUM > TMPPR_NUM:
                    logger.fdebug("%s New entries exist, appending to end as default ordering" % (PR_NUM - TMPPR_NUM))
                    (TMPPR_NUM + PR_NUM)
                else:
                    logger.fdebug("%s Disabled entries exist, removing from ordering sequence" % (TMPPR_NUM - PR_NUM))
                if PR_NUM > 0:
                    logger.fdebug("%s entries are enabled." % PR_NUM)

            NEW_PROV_ORDER = []
            i = len(PR) - 1
            # this should loop over ALL possible entries
            while i >= 0:
                found = False
                for d in PPR:
                    # logger.fdebug('checking entry %s against %s' % (PR[i], d) #d['provider'])
                    if d == PR[i]:
                        x = [p["order_seq"] for p in PROV_ORDER if p["provider"].lower() == PR[i].lower()]
                        if x:
                            ord = x[0]
                        else:
                            # if x isn't found, the provider was not in the OG list. So we add it to the end.
                            ord = len(PR)
                        found = {"provider": PR[i], "order": ord}
                        break
                    else:
                        found = False

                if found is not False:
                    new_order_seqnum = len(NEW_PROV_ORDER)
                    if new_order_seqnum != int(found["order"]):
                        seqnum = int(found["order"])
                    else:
                        seqnum = new_order_seqnum
                    NEW_PROV_ORDER.append(
                        {"order_seq": int(seqnum), "provider": found["provider"], "orig_seq": int(seqnum)}
                    )
                i -= 1

            # now we reorder based on priority of orig_seq, but use a new_order seq
            xa = 0
            NPROV = []
            for x in sorted(NEW_PROV_ORDER, key=itemgetter("orig_seq"), reverse=False):
                NPROV.append(str(xa))
                NPROV.append(x["provider"])
                xa += 1
            PROVIDER_ORDER = NPROV

        else:
            # priority provider sequence in order#, ProviderName
            logger.fdebug("creating provider sequence order now...")
            TMPPR_NUM = 0
            PROV_ORDER = []
            while TMPPR_NUM < PR_NUM:
                PROV_ORDER.append(str(TMPPR_NUM))
                PROV_ORDER.append(PR[TMPPR_NUM])
                # {"order_seq":  TMPPR_NUM,
                # "provider":   str(PR[TMPPR_NUM])})
                TMPPR_NUM += 1
            PROVIDER_ORDER = PROV_ORDER

        serialized_order = ", ".join(PROVIDER_ORDER)
        provider_order = dict(list(zip(*[PROVIDER_ORDER[i::2] for i in range(2)], strict=False)))
        return provider_order, serialized_order

    def provider_sequence(self):
        """Publish the current provider order and reconcile its database projection."""
        provider_order, serialized_order = self._calculate_provider_order()
        if not config.has_section("Providers"):
            config.add_section("Providers")
        config.set("Providers", "PROVIDER_ORDER", serialized_order)
        self.PROVIDER_ORDER = provider_order
        logger.fdebug("Provider Order is now set : %s " % self.PROVIDER_ORDER)

        self.write_out_provider_searches()

    @staticmethod
    def _provider_search_identity(provider, extra_newznabs, extra_torznabs):
        """Return the canonical database identity for a configured provider."""
        if provider == "DDL(GetComics)":
            return provider, "DDL", 200
        if provider == "DDL(External)":
            return provider, "DDL(External)", 201
        if provider.lower() == "experimental":
            return "experimental", "experimental", 101
        for provider_type, entries in (("newznab", extra_newznabs), ("torznab", extra_torznabs)):
            for entry in entries:
                entry_name = entry[0] or entry[1]
                if entry_name.lower() == provider.lower():
                    return entry_name, provider_type, int(entry[6])
        raise ValueError("Provider order contains an unknown provider")

    def write_out_provider_searches(self, provider_order=None, extra_newznabs=None, extra_torznabs=None):
        """Reconcile the provider-search projection in one database transaction."""
        from sqlalchemy import select, update

        from comicarr.tables import provider_searches

        provider_order = self.PROVIDER_ORDER if provider_order is None else provider_order
        extra_newznabs = self.EXTRA_NEWZNABS if extra_newznabs is None else extra_newznabs
        extra_torznabs = self.EXTRA_TORZNABS if extra_torznabs is None else extra_torznabs

        with db.get_engine().begin() as conn:
            rows = [dict(row._mapping) for row in conn.execute(select(provider_searches))]
            existing = {}
            existing_by_id = {}
            for row in rows:
                hits = row["hits"] or 0
                provider = row["provider"]
                provider_id = row["id"]
                provider_type = row["type"]
                if provider_id in (0, None):
                    try:
                        canonical, provider_type, provider_id = self._provider_search_identity(
                            provider,
                            extra_newznabs,
                            extra_torznabs,
                        )
                    except ValueError:
                        existing[provider.lower()] = {
                            "id": provider_id,
                            "provider": provider,
                            "active": row["active"],
                            "lastrun": row["lastrun"],
                            "type": provider_type,
                            "hits": hits,
                        }
                        if provider_id not in (0, None):
                            existing_by_id[provider_id] = existing[provider.lower()]
                        continue
                    conn.execute(
                        update(provider_searches)
                        .where(provider_searches.c.provider == row["provider"])
                        .values(id=provider_id, provider=canonical, type=provider_type, hits=hits)
                    )
                    provider = canonical
                existing[provider.lower()] = {
                    "id": provider_id,
                    "provider": provider,
                    "active": row["active"],
                    "lastrun": row["lastrun"],
                    "type": provider_type,
                    "hits": hits,
                }
                if provider_id not in (0, None):
                    existing_by_id[provider_id] = existing[provider.lower()]

            for provider in provider_order.values():
                try:
                    canonical, provider_type, provider_id = self._provider_search_identity(
                        provider,
                        extra_newznabs,
                        extra_torznabs,
                    )
                except ValueError:
                    if provider.lower() in {"32p", "public torrents"}:
                        # Legacy torrent providers do not use provider_searches.
                        continue
                    raise
                current = existing.get(canonical.lower())
                if current:
                    if current["id"] != provider_id or current["type"] != provider_type:
                        previous_id = current["id"]
                        conn.execute(
                            update(provider_searches)
                            .where(provider_searches.c.provider == current["provider"])
                            .values(id=provider_id, provider=canonical, type=provider_type)
                        )
                        existing_by_id.pop(previous_id, None)
                        current.update({"id": provider_id, "provider": canonical, "type": provider_type})
                        existing_by_id[provider_id] = current
                    continue
                controls = {"id": provider_id, "provider": canonical}
                values = {"active": False, "lastrun": 0, "type": provider_type, "hits": 0}
                logger.fdebug("writing: keys - %s: vals - %s" % (values, controls))
                id_collision = existing_by_id.get(provider_id)
                if id_collision:
                    conn.execute(
                        update(provider_searches)
                        .where(provider_searches.c.id == provider_id)
                        .values(provider=canonical, **values)
                    )
                    existing.pop(id_collision["provider"].lower(), None)
                    current = {"id": provider_id, "provider": canonical, **values}
                    existing[canonical.lower()] = current
                    existing_by_id[provider_id] = current
                else:
                    db.upsert_conn(conn, "provider_searches", values, controls)


def get_manga_destination():
    """Return the manga destination directory using the fallback chain.

    Fallback order: MANGA_DESTINATION_DIR -> MANGA_DIR -> DESTINATION_DIR.
    MANGA_DIR is included in the fallback because users who only configure a
    scan source directory expect downloads to land alongside existing files.
    """
    return comicarr.CONFIG.MANGA_DESTINATION_DIR or comicarr.CONFIG.MANGA_DIR or comicarr.CONFIG.DESTINATION_DIR


def ddl_creations():
    if not comicarr.CONFIG.DDL_LOCATION:
        comicarr.CONFIG.DDL_LOCATION = comicarr.CONFIG.CACHE_DIR
        if comicarr.CONFIG.ENABLE_DDL is True:
            logger.info("Setting DDL Location set to : %s" % comicarr.CONFIG.DDL_LOCATION)
    else:
        dcreate = filechecker.validateAndCreateDirectory(
            comicarr.CONFIG.DDL_LOCATION, create=True, dmode="ddl location"
        )
        if all([dcreate is False, comicarr.CONFIG.ENABLE_DDL is True]):
            logger.warn(
                "Unable to create ddl_location specified in config: %s. Reverting to default cache location."
                % comicarr.CONFIG.DDL_LOCATION
            )
            comicarr.CONFIG.DDL_LOCATION = comicarr.CONFIG.CACHE_DIR

    if comicarr.CONFIG.ENABLE_DDL:
        # make sure directory for mega downloads is created...
        mega_ddl_path = os.path.join(comicarr.CONFIG.DDL_LOCATION, "mega")
        html_cache_path = os.path.join(comicarr.CONFIG.CACHE_DIR, "html_cache")
        mdp_create = filechecker.validateAndCreateDirectory(mega_ddl_path, create=True, dmode="ddl-mega location")
        if mdp_create is False:
            logger.error(
                "Unable to create temp download directory [%s] for DDL-External. You will not be able to view the progress of the download."
                % mega_ddl_path
            )

        hcp_create = filechecker.validateAndCreateDirectory(html_cache_path, create=True, dmode="html cache")
        if hcp_create is False:
            logger.error(
                "Unable to create html_cache folder within the cache folder location [%s]. DDL will not work until this is corrected."
                % html_cache_path
            )
