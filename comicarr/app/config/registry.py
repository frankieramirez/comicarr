#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The config key registry: one entry type, one definition per key.

Today `comicarr/config.py` holds `_CONFIG_DEFINITIONS`, and four more places
repeat slices of the same knowledge: `get_safe_config`'s `safe_keys` list and
`WRITABLE_CONFIG_KEYS` in `comicarr/app/system/service.py`, plus that module's
`SCHEDULER_JOB_INTERVALS` and `SCHEDULER_JOB_REQUIRED_CONFIG`. A key added in
one and forgotten in another is the failure mode. `ConfigKey` puts all of it on
one entry so the other four derive.

This module currently holds a deliberately awkward *sample* of the 411 keys --
the ones that would break a naive entry type. The bulk migration is separate.
"""

from __future__ import annotations

import copy
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

COERCIBLE_TYPES = (str, int, bool)


@dataclass(frozen=True, slots=True)
class ConfigKey:
    """One config key, in every dimension the running system needs.

    `name` is the attribute name on the `Config` object and the uppercase key in
    `_CONFIG_DEFINITIONS`. Both the ini option and the name the frontend sees
    are `name.lower()` -- see `ini_key` / `wire_name`, and the module docstring
    of the sibling prototype for why those are derived rather than stored.

    `readable` and `writable` are independent and default-deny: 15 keys are
    write-only secrets and 10 are read-only, so a single "exposed" flag would
    leak the secrets onto the API.
    """

    name: str
    type: type
    section: str
    default: Any

    readable: bool = False
    writable: bool = False

    interval_for: str | None = None
    gates: str | None = None

    provider_extra: bool = False

    note: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not self.name.isupper():
            raise ValueError("config key name must be uppercase: %r" % self.name)
        if self.type not in COERCIBLE_TYPES:
            raise ValueError("%s: type must be one of str/int/bool, got %r" % (self.name, self.type))
        if not self.section:
            raise ValueError("%s: section is required" % self.name)
        if self.provider_extra and self.type is not str:
            raise ValueError("%s: provider extras are declared str" % self.name)

    @property
    def ini_key(self) -> str:
        """The option name written into the ini file."""
        return self.name.lower()

    @property
    def wire_name(self) -> str:
        """The name the settings API and the frontend see."""
        return self.name.lower()

    @property
    def as_definition(self) -> tuple[type, str, Any]:
        """This key as a legacy `_CONFIG_DEFINITIONS` value.

        The default is copied. `frozen=True` stops the field being rebound but
        not a list default being mutated in place, and `check_setting` hands
        `v[2]` straight to `setattr`, so without this every `Config` built in
        the process would share one `IGNORE_SEARCH_WORDS` list -- and an
        `.append` anywhere would edit the registry's own default.
        """
        return (self.type, self.section, copy.copy(self.default))


_KEYS: tuple[ConfigKey, ...] = (
    ConfigKey("CONFIG_VERSION", int, "General", 18),
    ConfigKey("MINIMAL_INI", bool, "General", False),
    ConfigKey("CACHE_DIR", str, "General", None, readable=True),
    ConfigKey("DYNAMIC_UPDATE", int, "General", 0),
    ConfigKey("REFRESH_CACHE", int, "General", 7),
    ConfigKey("ANNUALS_ON", bool, "General", False, readable=True, writable=True),
    ConfigKey("SYNO_FIX", bool, "General", False),
    ConfigKey("LAUNCH_BROWSER", bool, "General", False, readable=True, writable=True),
    ConfigKey("WANTED_TAB_OFF", bool, "General", False),
    ConfigKey("ENABLE_RSS", bool, "General", False),
    ConfigKey("SEARCH_DELAY", int, "General", 1, readable=True, writable=True),
    ConfigKey("GRABBAG_DIR", str, "General", None),
    ConfigKey("HIGHCOUNT", int, "General", 0),
    ConfigKey("MAINTAINSERIESFOLDER", bool, "General", False),
    ConfigKey("DESTINATION_DIR", str, "General", None, readable=True, writable=True),
    ConfigKey("MULTIPLE_DEST_DIRS", str, "General", None, readable=True, writable=True),
    ConfigKey("CREATE_FOLDERS", bool, "General", True, readable=True, writable=True),
    ConfigKey("DELETE_REMOVE_DIR", bool, "General", False),
    ConfigKey("UPCOMING_SNATCHED", bool, "General", True),
    ConfigKey("UPDATE_ENDED", bool, "General", False),
    ConfigKey("NEWCOM_DIR", str, "Update", None),
    ConfigKey("FFTONEWCOM_DIR", bool, "Update", False),
    ConfigKey("INTERFACE", str, "General", "carbon"),
    ConfigKey("CORRECT_METADATA", bool, "General", False),
    ConfigKey("MOVE_FILES", bool, "General", False),
    ConfigKey("RENAME_FILES", bool, "General", False),
    ConfigKey("FOLDER_FORMAT", str, "General", "$Series ($Year)", readable=True, writable=True),
    ConfigKey("FILE_FORMAT", str, "General", "$Series $Annual $Issue ($Year)", readable=True, writable=True),
    ConfigKey("REPLACE_SPACES", bool, "General", False, readable=True, writable=True),
    ConfigKey("REPLACE_CHAR", str, "General", None),
    ConfigKey("ZERO_LEVEL", bool, "General", False, readable=True, writable=True),
    ConfigKey("ZERO_LEVEL_N", str, "General", None, readable=True, writable=True),
    ConfigKey("LOWERCASE_FILENAMES", bool, "General", False, readable=True, writable=True),
    ConfigKey("IGNORE_HAVETOTAL", bool, "General", False),
    ConfigKey("IGNORE_TOTAL", bool, "General", False),
    ConfigKey("IGNORE_COVERS", bool, "General", True),
    ConfigKey("SNATCHED_HAVETOTAL", bool, "General", False),
    ConfigKey("FAILED_DOWNLOAD_HANDLING", bool, "General", False),
    ConfigKey("FAILED_AUTO", bool, "General", False),
    ConfigKey("PREFERRED_QUALITY", int, "General", 0, readable=True, writable=True),
    ConfigKey("IGNORE_SEARCH_WORDS", str, "General", []),
    ConfigKey("USE_MINSIZE", bool, "General", False, readable=True, writable=True),
    ConfigKey("MINSIZE", str, "General", None, readable=True, writable=True),
    ConfigKey("USE_MAXSIZE", bool, "General", False, readable=True, writable=True),
    ConfigKey("MAXSIZE", str, "General", None, readable=True, writable=True),
    ConfigKey("AUTOWANT_UPCOMING", bool, "General", True),
    ConfigKey("AUTOWANT_ALL", bool, "General", False),
    ConfigKey("COMIC_COVER_LOCAL", bool, "General", False),
    ConfigKey("SERIES_METADATA_LOCAL", bool, "General", False),
    ConfigKey("SERIESJSON_FILE_PRIORITY", bool, "General", False),
    ConfigKey("COVER_FOLDER_LOCAL", bool, "General", False),
    ConfigKey("ADD_TO_CSV", bool, "General", True),
    ConfigKey("SKIPPED2WANTED", bool, "General", False),
    ConfigKey("READ2FILENAME", bool, "General", False),
    ConfigKey("SEND2READ", bool, "General", False),
    ConfigKey("NZB_STARTUP_SEARCH", bool, "General", False, readable=True, writable=True),
    ConfigKey("UNICODE_ISSUENUMBER", bool, "General", False),
    ConfigKey("ALTERNATE_LATEST_SERIES_COVERS", bool, "General", False),
    ConfigKey("SHOW_ICONS", bool, "General", False),
    ConfigKey("FORMAT_BOOKTYPE", bool, "General", True),
    ConfigKey("CLEANUP_CACHE", bool, "General", True),
    ConfigKey("CLEANUP_STRAYS", bool, "General", False),
    ConfigKey("SECURE_DIR", str, "General", None),
    ConfigKey("DATABASE_URL", str, "Database", None),
    ConfigKey("ENCRYPT_PASSWORDS", bool, "General", False),
    ConfigKey("BACKUP_ON_START", bool, "General", False),
    ConfigKey("BACKUP_LOCATION", str, "General", None),
    ConfigKey("BACKUP_RETENTION", int, "General", 4),
    ConfigKey("MIGRATION_DISMISSED", bool, "General", False),
    ConfigKey("ACQUISITION_MAINTENANCE", bool, "General", False),
    ConfigKey("BACKFILL_LENGTH", int, "General", 8),
    ConfigKey("BACKFILL_TIMESPAN", int, "General", 10),
    ConfigKey("PROBLEM_DATES", str, "General", []),
    ConfigKey("PROBLEM_DATES_SECONDS", int, "General", 60),
    ConfigKey("DEFAULT_DATES", str, "General", "store_date"),
    ConfigKey("FOLDER_CACHE_LOCATION", str, "PostProcess", None),
    ConfigKey("SCAN_ON_SERIES_CHANGES", bool, "General", True),
    ConfigKey("CLEAR_PROVIDER_TABLE", bool, "General", False),
    ConfigKey("SEARCH_TIER_CUTOFF", int, "General", 14),
    ConfigKey("RSS_CHECKINTERVAL", int, "Scheduler", 20, readable=True, writable=True, interval_for="rss"),
    ConfigKey("SEARCH_INTERVAL", int, "Scheduler", 1440, readable=True, writable=True, interval_for="search"),
    ConfigKey("DOWNLOAD_SCAN_INTERVAL", int, "Scheduler", 5, readable=True, writable=True, interval_for="monitor"),
    ConfigKey("DBUPDATE_INTERVAL", int, "Scheduler", 1440, readable=True, writable=True, interval_for="dbupdater"),
    ConfigKey("CHECK_GITHUB_INTERVAL", int, "Scheduler", 360),
    ConfigKey("BLOCKLIST_TIMER", int, "Scheduler", 3600),
    ConfigKey("IMPORT_SCAN_INTERVAL", int, "Scheduler", 30, readable=True, interval_for="importinbox"),
    ConfigKey("ALT_PULL", int, "Weekly", 2),
    ConfigKey("PULL_REFRESH", str, "Weekly", None),
    ConfigKey("WEEKFOLDER", bool, "Weekly", False, readable=True, writable=True),
    ConfigKey("WEEKFOLDER_LOC", str, "Weekly", None),
    ConfigKey("WEEKFOLDER_FORMAT", int, "Weekly", 0),
    ConfigKey("INDIE_PUB", int, "Weekly", 75),
    ConfigKey("BIGGIE_PUB", int, "Weekly", 55),
    ConfigKey("PACK_0DAY_WATCHLIST_ONLY", bool, "Weekly", True),
    ConfigKey("RESET_PULLIST_PAGINATION", bool, "Weekly", True),
    ConfigKey("MASS_PUBLISHERS", str, "Weekly", []),
    ConfigKey("AUTO_MASS_ADD", bool, "Weekly", False),
    ConfigKey("HTTP_PORT", int, "Interface", 8090, readable=True, writable=True),
    ConfigKey("HTTP_HOST", str, "Interface", "0.0.0.0", readable=True, writable=True),
    ConfigKey("HTTP_USERNAME", str, "Interface", None, readable=True),
    ConfigKey("HTTP_PASSWORD", str, "Interface", None),
    ConfigKey("HTTP_ROOT", str, "Interface", "/", readable=True, writable=True),
    ConfigKey("ENABLE_HTTPS", bool, "Interface", False, readable=True, writable=True),
    ConfigKey("HTTPS_CERT", str, "Interface", None),
    ConfigKey("HTTPS_KEY", str, "Interface", None),
    ConfigKey("HTTPS_CHAIN", str, "Interface", None),
    ConfigKey("HTTPS_FORCE_ON", bool, "Interface", False),
    ConfigKey("AUTHENTICATION", int, "Interface", 2, readable=True),
    ConfigKey("LOGIN_TIMEOUT", int, "Interface", 43800),
    ConfigKey("ALPHAINDEX", bool, "Interface", True),
    ConfigKey("API_ENABLED", bool, "API", False),
    ConfigKey("API_KEY", str, "API", None),
    ConfigKey("CALENDAR_DEFAULT_DAYS", int, "API", 90),
    ConfigKey("COMICVINE_ENABLED", bool, "CV", True, readable=True, writable=True),
    ConfigKey("CVAPI_RATE", int, "CV", 2),
    ConfigKey("COMICVINE_API", str, "CV", None, writable=True),
    ConfigKey("IGNORED_PUBLISHERS", str, "CV", ""),
    ConfigKey("CV_VERIFY", bool, "CV", True, readable=True, writable=True),
    ConfigKey("CV_TIMEOUT", int, "CV", 30),
    ConfigKey("CV_ONLY", bool, "CV", True, readable=True, writable=True),
    ConfigKey("CV_ONETIMER", bool, "CV", True),
    ConfigKey("CVINFO", bool, "CV", False),
    ConfigKey(
        "CV_USER_AGENT",
        str,
        "CV",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    ),
    ConfigKey("CV_CACHE_ENABLED", bool, "CV", True),
    ConfigKey("CV_CACHE_TTL_SEARCH", int, "CV", 86400),
    ConfigKey("CV_CACHE_TTL_METADATA", int, "CV", 604800),
    ConfigKey("CV_CACHE_TTL_ARC", int, "CV", 259200),
    ConfigKey("CV_SKIP_IMPRINT_VALIDATION", bool, "CV", False),
    ConfigKey("CV_PARALLEL_PAGINATION", bool, "CV", True),
    ConfigKey("CV_MAX_PARALLEL_REQUESTS", int, "CV", 3),
    ConfigKey("IMPRINT_MAPPING_TYPE", str, "CV", "CV"),
    ConfigKey("METRON_USERNAME", str, "Metron", None, readable=True, writable=True),
    ConfigKey("METRON_PASSWORD", str, "Metron", None, writable=True),
    ConfigKey("USE_METRON_SEARCH", bool, "Metron", False, readable=True, writable=True),
    ConfigKey("MANGADEX_ENABLED", bool, "MangaDex", True, readable=True, writable=True),
    ConfigKey("MANGADEX_LANGUAGES", str, "MangaDex", "en", readable=True, writable=True),
    ConfigKey("MANGADEX_CONTENT_RATING", str, "MangaDex", "safe,suggestive", readable=True, writable=True),
    ConfigKey("MAL_ENABLED", bool, "MAL", False, readable=True, writable=True),
    ConfigKey("MAL_CLIENT_ID", str, "MAL", None, writable=True),
    ConfigKey("LOG_DIR", str, "Logs", None, readable=True),
    ConfigKey("MAX_LOGSIZE", int, "Logs", 10000000, readable=True),
    ConfigKey("MAX_LOGFILES", int, "Logs", 5, readable=True),
    ConfigKey("LOG_LEVEL", int, "Logs", 1, readable=True, writable=True),
    ConfigKey("GIT_PATH", str, "Git", None),
    ConfigKey("GIT_USER", str, "Git", "frankieramirez"),
    ConfigKey("GIT_TOKEN", str, "Git", None),
    ConfigKey("GIT_BRANCH", str, "Git", None),
    ConfigKey("CHECK_GITHUB", bool, "Git", True, readable=True, writable=True),
    ConfigKey("ANNOUNCE_RELEASES", bool, "Git", False, readable=True, writable=True),
    ConfigKey("LAST_ANNOUNCED_VERSION", str, "Git", None),
    ConfigKey("LAST_SEEN_VERSION", str, "Git", None),
    ConfigKey("ENFORCE_PERMS", bool, "Perms", False),
    ConfigKey("CHMOD_DIR", str, "Perms", "0777"),
    ConfigKey("CHMOD_FILE", str, "Perms", "0660"),
    ConfigKey("CHOWNER", str, "Perms", None),
    ConfigKey("CHGROUP", str, "Perms", None),
    ConfigKey("ADD_COMICS", bool, "Import", False),
    ConfigKey("COMIC_DIR", str, "Import", None, readable=True, writable=True),
    ConfigKey("MANGA_DIR", str, "Import", None, readable=True),
    ConfigKey("MANGA_DESTINATION_DIR", str, "General", None, readable=True),
    ConfigKey("IMP_MOVE", bool, "Import", False, readable=True, writable=True),
    ConfigKey("IMP_PATHS", bool, "Import", False),
    ConfigKey("IMP_RENAME", bool, "Import", False, readable=True, writable=True),
    ConfigKey("IMP_METADATA", bool, "Import", False, readable=True, writable=True),
    ConfigKey("IMP_SERIESFOLDERS", bool, "Import", True, readable=True, writable=True),
    ConfigKey("IMPORT_DIR", str, "Import", None, readable=True, gates="importinbox"),
    ConfigKey("DUPECONSTRAINT", str, "Duplicates", None),
    ConfigKey("DDUMP", bool, "Duplicates", False),
    ConfigKey("DUPLICATE_DUMP", str, "Duplicates", None),
    ConfigKey("DUPLICATE_DATED_FOLDERS", bool, "Duplicates", False),
    ConfigKey("PROWL_ENABLED", bool, "Prowl", False, readable=True, writable=True),
    ConfigKey("PROWL_PRIORITY", int, "Prowl", 0, readable=True, writable=True),
    ConfigKey("PROWL_KEYS", str, "Prowl", None, writable=True),
    ConfigKey("PROWL_ONSNATCH", bool, "Prowl", False, readable=True, writable=True),
    ConfigKey("PUSHOVER_ENABLED", bool, "PUSHOVER", False, readable=True, writable=True),
    ConfigKey("PUSHOVER_PRIORITY", int, "PUSHOVER", 0, readable=True, writable=True),
    ConfigKey("PUSHOVER_APIKEY", str, "PUSHOVER", None, writable=True),
    ConfigKey("PUSHOVER_DEVICE", str, "PUSHOVER", None, readable=True, writable=True),
    ConfigKey("PUSHOVER_USERKEY", str, "PUSHOVER", None, writable=True),
    ConfigKey("PUSHOVER_ONSNATCH", bool, "PUSHOVER", False, readable=True, writable=True),
    ConfigKey("PUSHOVER_IMAGE", bool, "PUSHOVER", False, readable=True, writable=True),
    ConfigKey("BOXCAR_ENABLED", bool, "BOXCAR", False, readable=True, writable=True),
    ConfigKey("BOXCAR_ONSNATCH", bool, "BOXCAR", False, readable=True, writable=True),
    ConfigKey("BOXCAR_TOKEN", str, "BOXCAR", None, writable=True),
    ConfigKey("PUSHBULLET_ENABLED", bool, "PUSHBULLET", False, readable=True, writable=True),
    ConfigKey("PUSHBULLET_APIKEY", str, "PUSHBULLET", None, writable=True),
    ConfigKey("PUSHBULLET_DEVICEID", str, "PUSHBULLET", None, readable=True, writable=True),
    ConfigKey("PUSHBULLET_CHANNEL_TAG", str, "PUSHBULLET", None, readable=True, writable=True),
    ConfigKey("PUSHBULLET_ONSNATCH", bool, "PUSHBULLET", False, readable=True, writable=True),
    ConfigKey("TELEGRAM_ENABLED", bool, "TELEGRAM", False, readable=True, writable=True),
    ConfigKey("TELEGRAM_TOKEN", str, "TELEGRAM", None, writable=True),
    ConfigKey("TELEGRAM_USERID", str, "TELEGRAM", None, readable=True, writable=True),
    ConfigKey("TELEGRAM_ONSNATCH", bool, "TELEGRAM", False, readable=True, writable=True),
    ConfigKey("TELEGRAM_IMAGE", bool, "TELEGRAM", False, readable=True, writable=True),
    ConfigKey("SLACK_ENABLED", bool, "SLACK", False, readable=True, writable=True),
    ConfigKey("SLACK_WEBHOOK_URL", str, "SLACK", None, writable=True),
    ConfigKey("SLACK_ONSNATCH", bool, "SLACK", False, readable=True, writable=True),
    ConfigKey("MATTERMOST_ENABLED", bool, "MATTERMOST", False, readable=True, writable=True),
    ConfigKey("MATTERMOST_WEBHOOK_URL", str, "MATTERMOST", None, writable=True),
    ConfigKey("MATTERMOST_ONSNATCH", bool, "MATTERMOST", False, readable=True, writable=True),
    ConfigKey("DISCORD_ENABLED", bool, "DISCORD", False, readable=True, writable=True),
    ConfigKey("DISCORD_WEBHOOK_URL", str, "DISCORD", None, writable=True),
    ConfigKey("DISCORD_ONSNATCH", bool, "DISCORD", False, readable=True, writable=True),
    ConfigKey("EMAIL_ENABLED", bool, "Email", False, readable=True, writable=True),
    ConfigKey("EMAIL_FROM", str, "Email", "", readable=True, writable=True),
    ConfigKey("EMAIL_TO", str, "Email", "", readable=True, writable=True),
    ConfigKey("EMAIL_SERVER", str, "Email", "", readable=True, writable=True),
    ConfigKey("EMAIL_USER", str, "Email", "", readable=True, writable=True),
    ConfigKey("EMAIL_PASSWORD", str, "Email", "", writable=True),
    ConfigKey("EMAIL_PORT", int, "Email", 25, readable=True, writable=True),
    ConfigKey("EMAIL_ENC", int, "Email", 0, readable=True, writable=True),
    ConfigKey("EMAIL_ONGRAB", bool, "Email", True, readable=True, writable=True),
    ConfigKey("EMAIL_ONPOST", bool, "Email", True, readable=True, writable=True),
    ConfigKey("GOTIFY_ENABLED", bool, "GOTIFY", False, readable=True, writable=True),
    ConfigKey("GOTIFY_SERVER_URL", str, "GOTIFY", None, readable=True, writable=True),
    ConfigKey("GOTIFY_TOKEN", str, "GOTIFY", None, writable=True),
    ConfigKey("GOTIFY_ONSNATCH", bool, "GOTIFY", False, readable=True, writable=True),
    ConfigKey("MATRIX_ENABLED", bool, "MATRIX", False, readable=True, writable=True),
    ConfigKey("MATRIX_HOMESERVER", str, "MATRIX", None, readable=True, writable=True),
    ConfigKey("MATRIX_ACCESS_TOKEN", str, "MATRIX", None, writable=True),
    ConfigKey("MATRIX_ROOM_ID", str, "MATRIX", None, readable=True, writable=True),
    ConfigKey("MATRIX_ONSNATCH", bool, "MATRIX", False, readable=True, writable=True),
    ConfigKey("POST_PROCESSING", bool, "PostProcess", True),
    ConfigKey("FILE_OPTS", str, "PostProcess", "move"),
    ConfigKey("SNATCHEDTORRENT_NOTIFY", bool, "PostProcess", False),
    ConfigKey("LOCAL_TORRENT_PP", bool, "PostProcess", False),
    ConfigKey("POST_PROCESSING_SCRIPT", str, "PostProcess", None),
    ConfigKey("PP_SHELL_LOCATION", str, "PostProcess", None),
    ConfigKey("ENABLE_EXTRA_SCRIPTS", bool, "PostProcess", False),
    ConfigKey("ES_SHELL_LOCATION", str, "PostProcess", None),
    ConfigKey("EXTRA_SCRIPTS", str, "PostProcess", None),
    ConfigKey("ENABLE_SNATCH_SCRIPT", bool, "PostProcess", False),
    ConfigKey("SNATCH_SHELL_LOCATION", str, "PostProcess", None),
    ConfigKey("SNATCH_SCRIPT", str, "PostProcess", None),
    ConfigKey("ENABLE_PRE_SCRIPTS", bool, "PostProcess", False),
    ConfigKey("PRE_SHELL_LOCATION", str, "PostProcess", None),
    ConfigKey("PRE_SCRIPTS", str, "PostProcess", None),
    ConfigKey("ENABLE_CHECK_FOLDER", bool, "PostProcess", False),
    ConfigKey("CHECK_FOLDER", str, "PostProcess", None, readable=True, writable=True, gates="monitor"),
    ConfigKey("MANUAL_PP_FOLDER", str, "PostProcess", None),
    ConfigKey("PROVIDER_ORDER", str, "Providers", None),
    ConfigKey("USENET_RETENTION", int, "Providers", 3500),
    ConfigKey("NZB_DOWNLOADER", int, "Client", 3, readable=True, writable=True),
    ConfigKey("TORRENT_DOWNLOADER", int, "Client", 0, readable=True),
    ConfigKey("SAB_HOST", str, "SABnzbd", None, readable=True, writable=True),
    ConfigKey("SAB_USERNAME", str, "SABnzbd", None),
    ConfigKey("SAB_PASSWORD", str, "SABnzbd", None),
    ConfigKey("SAB_APIKEY", str, "SABnzbd", None, writable=True),
    ConfigKey("SAB_CATEGORY", str, "SABnzbd", None, readable=True, writable=True),
    ConfigKey("SAB_PRIORITY", str, "SABnzbd", "Default"),
    ConfigKey("SAB_DIRECT_UNPACK", bool, "SABnzbd", False),
    ConfigKey("SAB_DIRECTORY", str, "SABnzbd", None, readable=True, writable=True),
    ConfigKey("SAB_VERSION", str, "SABnzbd", None),
    ConfigKey("SAB_MOVING_DELAY", int, "SABnzbd", 5),
    ConfigKey("SAB_CLIENT_POST_PROCESSING", bool, "SABnzbd", False),
    ConfigKey("SAB_REMOVE_COMPLETED", bool, "SABnzbd", False),
    ConfigKey("SAB_REMOVE_FAILED", bool, "SABnzbd", False),
    ConfigKey("SAB_VERIFY", bool, "SABnzbd", False, readable=True, writable=True),
    ConfigKey("NZBGET_HOST", str, "NZBGet", None),
    ConfigKey("NZBGET_SUB", str, "NZBGet", None),
    ConfigKey("NZBGET_PORT", str, "NZBGet", None),
    ConfigKey("NZBGET_USERNAME", str, "NZBGet", None),
    ConfigKey("NZBGET_PASSWORD", str, "NZBGet", None),
    ConfigKey("NZBGET_VERIFY", bool, "NZBGet", False),
    ConfigKey("NZBGET_PRIORITY", str, "NZBGet", None),
    ConfigKey("NZBGET_CATEGORY", str, "NZBGet", None),
    ConfigKey("NZBGET_DIRECTORY", str, "NZBGet", None),
    ConfigKey("NZBGET_CLIENT_POST_PROCESSING", bool, "NZBGet", False),
    ConfigKey("BLACKHOLE_DIR", str, "Blackhole", None),
    ConfigKey("NEWZNAB", bool, "Newznab", False),
    ConfigKey("EXTRA_NEWZNABS", str, "Newznab", "", provider_extra=True),
    ConfigKey("ENABLE_TORZNAB", bool, "Torznab", False),
    ConfigKey("EXTRA_TORZNABS", str, "Torznab", "", provider_extra=True),
    ConfigKey("TORZNAB_NAME", str, "Torznab", None),
    ConfigKey("TORZNAB_HOST", str, "Torznab", None),
    ConfigKey("TORZNAB_APIKEY", str, "Torznab", None),
    ConfigKey("TORZNAB_CATEGORY", str, "Torznab", None),
    ConfigKey("TORZNAB_VERIFY", bool, "Torznab", True),
    ConfigKey("EXPERIMENTAL", bool, "Experimental", False),
    ConfigKey("ALTEXPERIMENTAL", bool, "Experimental", False),
    ConfigKey("TAB_ENABLE", bool, "Tablet", False),
    ConfigKey("TAB_HOST", str, "Tablet", None),
    ConfigKey("TAB_USER", str, "Tablet", None),
    ConfigKey("TAB_PASS", str, "Tablet", None),
    ConfigKey("TAB_DIRECTORY", str, "Tablet", None),
    ConfigKey("STORYARCDIR", bool, "StoryArc", False),
    ConfigKey("STORYARC_LOCATION", str, "StoryArc", None, readable=True, writable=True),
    ConfigKey("COPY2ARCDIR", bool, "StoryArc", False),
    ConfigKey("ARC_FOLDERFORMAT", str, "StoryArc", "$arc ($spanyears)"),
    ConfigKey("ARC_FILEOPS", str, "StoryArc", "copy"),
    ConfigKey("ARC_FILEOPS_SOFTLINK_RELATIVE", bool, "StoryArc", False),
    ConfigKey("UPCOMING_STORYARCS", bool, "StoryArc", False),
    ConfigKey("SEARCH_STORYARCS", bool, "StoryArc", False),
    ConfigKey("LOCMOVE", bool, "Update", False),
    ConfigKey("ENABLE_META", bool, "Metatagging", False, readable=True, writable=True),
    ConfigKey("CMTAGGER_PATH", str, "Metatagging", None),
    ConfigKey("CBR2CBZ_ONLY", bool, "Metatagging", False),
    ConfigKey("CT_TAG_CR", bool, "Metatagging", True),
    ConfigKey("CT_TAG_CBL", bool, "Metatagging", False),
    ConfigKey("CT_CBZ_OVERWRITE", bool, "Metatagging", False),
    ConfigKey("UNRAR_CMD", str, "Metatagging", None),
    ConfigKey("CT_NOTES_FORMAT", str, "Metatagging", "Issue ID"),
    ConfigKey("CT_SETTINGSPATH", str, "Metatagging", None),
    ConfigKey("CMTAG_VOLUME", bool, "Metatagging", True),
    ConfigKey("CMTAG_START_YEAR_AS_VOLUME", bool, "Metatagging", True),
    ConfigKey("SETDEFAULTVOLUME", bool, "Metatagging", False),
    ConfigKey("CV_BATCH_LIMIT_PROTECTION", bool, "Metatagging", True),
    ConfigKey("CV_BATCH_LIMIT_THRESHOLD", int, "Metatagging", 200),
    ConfigKey("ENABLE_TORRENTS", bool, "Torrents", False),
    ConfigKey("ENABLE_TORRENT_SEARCH", bool, "Torrents", False),
    ConfigKey("MINSEEDS", int, "Torrents", 0),
    ConfigKey("ENABLE_PUBLIC", bool, "Torrents", False),
    ConfigKey("PUBLIC_VERIFY", bool, "Torrents", True),
    ConfigKey("ENABLE_DDL", bool, "DDL", False),
    ConfigKey("ENABLE_GETCOMICS", bool, "DDL", False),
    ConfigKey("ENABLE_EXTERNAL_SERVER", bool, "DDL", False),
    ConfigKey("EXTERNAL_SERVER", str, "DDL", None),
    ConfigKey("EXTERNAL_USERNAME", str, "DDL", None),
    ConfigKey("EXTERNAL_APIKEY", str, "DDL", None),
    ConfigKey("PACK_PRIORITY", bool, "DDL", False),
    ConfigKey("DDL_QUERY_DELAY", int, "DDL", 15),
    ConfigKey("DDL_LOCATION", str, "DDL", None),
    ConfigKey("DDL_AUTORESUME", bool, "DDL", True),
    ConfigKey("DDL_PREFER_UPSCALED", bool, "DDL", True),
    ConfigKey("DDL_PRIORITY_ORDER", str, "DDL", []),
    ConfigKey("DDL_STUCK_NOTIFY", bool, "DDL", True),
    ConfigKey("DDL_STUCK_THRESHOLD", int, "DDL", 30),
    ConfigKey("DDL_STUCK_CHECK_INTERVAL", int, "DDL", 10),
    ConfigKey("ENABLE_FLARESOLVERR", bool, "DDL", False),
    ConfigKey("FLARESOLVERR_URL", str, "DDL", None),
    ConfigKey("ENABLE_PROXY", bool, "DDL", False),
    ConfigKey("HTTP_PROXY", str, "DDL", None),
    ConfigKey("HTTPS_PROXY", str, "DDL", None),
    ConfigKey("AUTO_SNATCH", bool, "AutoSnatch", False),
    ConfigKey("AUTO_SNATCH_SCRIPT", str, "AutoSnatch", None),
    ConfigKey("PP_SSHHOST", str, "AutoSnatch", None),
    ConfigKey("PP_SSHPORT", str, "AutoSnatch", 22),
    ConfigKey("PP_SSHUSER", str, "AutoSnatch", None),
    ConfigKey("PP_SSHPASSWD", str, "AutoSnatch", None),
    ConfigKey("PP_SSHLOCALCD", str, "AutoSnatch", None),
    ConfigKey("PP_SSHKEYFILE", str, "AutoSnatch", None),
    ConfigKey("TORRENT_LOCAL", bool, "Watchdir", False),
    ConfigKey("LOCAL_WATCHDIR", str, "Watchdir", None),
    ConfigKey("TORRENT_SEEDBOX", bool, "Seedbox", False),
    ConfigKey("SEEDBOX_HOST", str, "Seedbox", None),
    ConfigKey("SEEDBOX_PORT", str, "Seedbox", None),
    ConfigKey("SEEDBOX_USER", str, "Seedbox", None),
    ConfigKey("SEEDBOX_PASS", str, "Seedbox", None),
    ConfigKey("SEEDBOX_WATCHDIR", str, "Seedbox", None),
    ConfigKey("ENABLE_32P", bool, "32P", False),
    ConfigKey("SEARCH_32P", bool, "32P", False),
    ConfigKey("DEEP_SEARCH_32P", bool, "32P", False),
    ConfigKey("MODE_32P", bool, "32P", False),
    ConfigKey("RSSFEED_32P", str, "32P", None),
    ConfigKey("PASSKEY_32P", str, "32P", None),
    ConfigKey("USERNAME_32P", str, "32P", None),
    ConfigKey("PASSWORD_32P", str, "32P", None),
    ConfigKey("VERIFY_32P", bool, "32P", True),
    ConfigKey("RTORRENT_HOST", str, "Rtorrent", None),
    ConfigKey("RTORRENT_AUTHENTICATION", str, "Rtorrent", "basic"),
    ConfigKey("RTORRENT_RPC_URL", str, "Rtorrent", None),
    ConfigKey("RTORRENT_SSL", bool, "Rtorrent", False),
    ConfigKey("RTORRENT_VERIFY", bool, "Rtorrent", False),
    ConfigKey("RTORRENT_CA_BUNDLE", str, "Rtorrent", None),
    ConfigKey("RTORRENT_USERNAME", str, "Rtorrent", None),
    ConfigKey("RTORRENT_PASSWORD", str, "Rtorrent", None),
    ConfigKey("RTORRENT_STARTONLOAD", bool, "Rtorrent", False),
    ConfigKey("RTORRENT_LABEL", str, "Rtorrent", None),
    ConfigKey("RTORRENT_DIRECTORY", str, "Rtorrent", None),
    ConfigKey("UTORRENT_HOST", str, "uTorrent", None),
    ConfigKey("UTORRENT_USERNAME", str, "uTorrent", None),
    ConfigKey("UTORRENT_PASSWORD", str, "uTorrent", None),
    ConfigKey("UTORRENT_LABEL", str, "uTorrent", None),
    ConfigKey("TRANSMISSION_HOST", str, "Transmission", None),
    ConfigKey("TRANSMISSION_USERNAME", str, "Transmission", None),
    ConfigKey("TRANSMISSION_PASSWORD", str, "Transmission", None),
    ConfigKey("TRANSMISSION_DIRECTORY", str, "Transmission", None),
    ConfigKey("DELUGE_HOST", str, "Deluge", None),
    ConfigKey("DELUGE_USERNAME", str, "Deluge", None),
    ConfigKey("DELUGE_PASSWORD", str, "Deluge", None),
    ConfigKey("DELUGE_LABEL", str, "Deluge", None),
    ConfigKey("DELUGE_PAUSE", bool, "Deluge", False),
    ConfigKey("DELUGE_DOWNLOAD_DIRECTORY", str, "Deluge", ""),
    ConfigKey("DELUGE_DONE_DIRECTORY", str, "Deluge", ""),
    ConfigKey("QBITTORRENT_HOST", str, "qBittorrent", None),
    ConfigKey("QBITTORRENT_USERNAME", str, "qBittorrent", None),
    ConfigKey("QBITTORRENT_PASSWORD", str, "qBittorrent", None),
    ConfigKey("QBITTORRENT_LABEL", str, "qBittorrent", None),
    ConfigKey("QBITTORRENT_FOLDER", str, "qBittorrent", None),
    ConfigKey("QBITTORRENT_LOADACTION", str, "qBittorrent", "default"),
    ConfigKey("OPDS_ENABLE", bool, "OPDS", False, readable=True, writable=True),
    ConfigKey("OPDS_AUTHENTICATION", bool, "OPDS", False),
    ConfigKey("OPDS_ENDPOINT", str, "OPDS", "opds"),
    ConfigKey("OPDS_USERNAME", str, "OPDS", None),
    ConfigKey("OPDS_PASSWORD", str, "OPDS", None),
    ConfigKey("OPDS_METAINFO", bool, "OPDS", False),
    ConfigKey("OPDS_PAGESIZE", int, "OPDS", 30, readable=True, writable=True),
    ConfigKey("CBL_IMPORT_ISSUESONLY", bool, "CBLImport", True),
    ConfigKey("CBL_IMPORT_IGNOREARCHIVED", bool, "CBLImport", False),
    ConfigKey("AI_BASE_URL", str, "AI", None, readable=True, writable=True),
    ConfigKey("AI_API_KEY", str, "AI", None, writable=True),
    ConfigKey("AI_MODEL", str, "AI", None, readable=True, writable=True),
    ConfigKey("AI_TIMEOUT", int, "AI", 30, readable=True, writable=True),
    ConfigKey("AI_RPM_LIMIT", int, "AI", 20, readable=True, writable=True),
    ConfigKey("AI_DAILY_TOKEN_LIMIT", int, "AI", 100000, readable=True, writable=True),
    ConfigKey("AI_CIRCUIT_THRESHOLD", int, "AI", 5, readable=True, writable=True),
    ConfigKey("AI_CIRCUIT_COOLDOWN", int, "AI", 300, readable=True, writable=True),
)


def _build(keys: tuple[ConfigKey, ...]) -> OrderedDict[str, ConfigKey]:
    """Index the keys, refusing any collision.

    Building the dict straight from a comprehension would let a duplicate name
    silently drop a definition, and a duplicate `interval_for` / `gates` would
    silently rebind a scheduler job to whichever entry happened to come last.
    The bulk migration emits these 411 entries from a script, so a typo there
    has to fail at import rather than quietly lose a key.
    """
    registry: OrderedDict[str, ConfigKey] = OrderedDict()
    bindings: dict[str, dict[str, str]] = {"interval_for": {}, "gates": {}}

    for key in keys:
        if key.name in registry:
            raise ValueError("duplicate config key: %s" % key.name)
        registry[key.name] = key

        for attr, claimed in bindings.items():
            job = getattr(key, attr)
            if job is None:
                continue
            if job in claimed:
                raise ValueError("%s job %r claimed by both %s and %s" % (attr, job, claimed[job], key.name))
            claimed[job] = key.name

    return registry


REGISTRY: OrderedDict[str, ConfigKey] = _build(_KEYS)


def as_legacy_definitions() -> OrderedDict[str, tuple[type, str, Any]]:
    """`_CONFIG_DEFINITIONS` rebuilt from the registry.

    `Config.check_setting`, `Config._define` and `comicarr/migration.py:426`
    index these tuples positionally, so the shape is fixed at 3 elements.
    """
    return OrderedDict((k.name, k.as_definition) for k in REGISTRY.values())


def readable_keys() -> set[str]:
    """Replaces the `safe_keys` literal in `get_safe_config`."""
    return {k.name for k in REGISTRY.values() if k.readable}


def writable_keys() -> set[str]:
    """Replaces the `WRITABLE_CONFIG_KEYS` literal."""
    return {k.name for k in REGISTRY.values() if k.writable}


def scheduler_job_intervals() -> dict[str, str]:
    """Replaces `SCHEDULER_JOB_INTERVALS` — job id to the key driving its cadence."""
    return {k.interval_for: k.name for k in REGISTRY.values() if k.interval_for}


def scheduler_job_required_config() -> dict[str, str]:
    """Replaces `SCHEDULER_JOB_REQUIRED_CONFIG` — job id to the key gating it."""
    return {k.gates: k.name for k in REGISTRY.values() if k.gates}


def provider_extra_fields() -> tuple[str, ...]:
    """Replaces `_PROVIDER_EXTRA_FIELDS`."""
    return tuple(k.name for k in REGISTRY.values() if k.provider_extra)
