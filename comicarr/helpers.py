#  Copyright (C) 2012-2024 Mylar3 contributors
#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Originally based on Mylar3 (https://github.com/mylar3/mylar3).
# -*- coding: utf-8 -*-
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

"""
Re-export shim.

All function implementations have been extracted to comicarr/app/ domain
modules. This file re-exports them so existing callers continue to work.
"""

import comicarr
from comicarr import db
from comicarr.app.common.dates import (  # noqa: F401
    convert_milliseconds,
    convert_seconds,
    date_conversion,
    fullmonth,
    humanize_time,
    now,
    today,
    utc_date_to_local,
    utctimestamp,
)
from comicarr.app.common.dates import weekly_info as _weekly_info_impl
from comicarr.app.common.filesystem import checkFolder as _checkFolder_impl
from comicarr.app.common.filesystem import file_ops as _file_ops_impl
from comicarr.app.common.filesystem import (  # noqa: F401
    is_path_within_allowed_dirs,
    urlretrieve,
)
from comicarr.app.common.numbers import (  # noqa: F401
    bytes_to_mb,
    decimal_issue,
    human2bytes,
    human_size,
    is_number,
    sizeof_fmt,
)
from comicarr.app.common.numbers import issuedigits as _issuedigits_impl

# --- common/ re-exports ---
from comicarr.app.common.strings import (  # noqa: F401
    clean_url,
    cleanHost,
    cleanhtml,
    cleanName,
    cleanTitle,
    filesafe,
    latinToAscii,
    replace_all,
    replacetheslash,
)
from comicarr.app.common.utilities import (  # noqa: F401
    checked,
    chunker,
    conversion,
    extract_logline,
    get_the_hash,
    int_num,
    multikeysort,
    radio,
)
from comicarr.app.common.utilities import crc as _crc_impl
from comicarr.app.common.utilities import log_that_exception as _log_that_exception_impl

# --- core/ re-exports ---
from comicarr.app.core.security import (  # noqa: F401
    apiremove,
    create_https_certificates,
    remove_apikey,
)

# --- domain service re-exports ---
from comicarr.app.downloads.service import (  # noqa: F401
    cdh_monitor,
    check_file_condition,
    ddl_cleanup,
    ddl_downloader,
    ddl_health_check,
    duplicate_filecheck,
    issue_find_ids,
    lookupthebitches,
    nzb_monitor,
    postprocess_main,
    rename_param,
    renamefile_readingorder,
    reverse_the_pack_snatch,
    worker_main,
)
from comicarr.app.metadata.service import (  # noqa: F401
    IssueDetails,
    getImage,
    publisherImages,
)
from comicarr.app.search.service import (  # noqa: F401
    LoadAlternateSearchNames,
    block_provider_check,
    checkthe_id,
    disable_provider,
    ignored_publisher_check,
    newznab_test,
    parse_32pfeed,
    search_queue,
    torrent_create,
    torrentinfo,
    torznab_test,
)
from comicarr.app.series.service import (  # noqa: F401
    ComicSort,
    DateAddedFix,
    annual_update,
    checkthepub,
    get_issue_title,
    havetotals,
    incr_snatched,
    issue_status,
    latestdate_fix,
    latestdate_update,
    latestissue_update,
    listIssues,
    listLibrary,
    listoneoffs,
    listPull,
    statusChange,
    updateComicLocation,
)
from comicarr.app.storyarcs.service import (  # noqa: F401
    arcformat,
    listStoryArcs,
    manualArc,
    spantheyears,
    updatearc_locs,
)
from comicarr.app.system.service import (  # noqa: F401
    QueueInfo,
    get_free_space,
    job_management,
    notify_ddl_stuck,
    queue_info,
    script_env,
    stupidchk,
    tail_that_log,
    upgrade_dynamic,
)

from . import logger

# --- Thin wrappers for functions that need comicarr globals ---


def issuedigits(issnum):
    return _issuedigits_impl(issnum, issue_exceptions=comicarr.ISSUE_EXCEPTIONS, log=logger)


def checkFolder(folderpath=None):
    from comicarr import postprocessor

    return _checkFolder_impl(
        folderpath=folderpath,
        check_folder=comicarr.CONFIG.CHECK_FOLDER,
        postprocessor=postprocessor,
    )


def weekly_info(week=None, year=None, current=None):
    return _weekly_info_impl(
        week=week,
        year=year,
        current=current,
        weekfolder_loc=comicarr.CONFIG.WEEKFOLDER_LOC,
        destination_dir=comicarr.CONFIG.DESTINATION_DIR,
        weekfolder_format=comicarr.CONFIG.WEEKFOLDER_FORMAT,
        sched_weekly_last=comicarr.SCHED_WEEKLY_LAST,
    )


def file_ops(path, dst, arc=False, one_off=False, multiple=False):
    return _file_ops_impl(
        path,
        dst,
        arc=arc,
        one_off=one_off,
        multiple=multiple,
        file_opts=comicarr.CONFIG.FILE_OPTS,
        arc_fileops=comicarr.CONFIG.ARC_FILEOPS,
        arc_fileops_softlink_relative=comicarr.CONFIG.ARC_FILEOPS_SOFTLINK_RELATIVE,
        os_detect=comicarr.OS_DETECT,
    )


def crc(filename):
    return _crc_impl(filename, sys_encoding=comicarr.SYS_ENCODING)


def log_that_exception(except_info):
    return _log_that_exception_impl(
        except_info,
        db=db,
        now_func=now,
        log_dir=comicarr.CONFIG.LOG_DIR,
        tail_func=tail_that_log,
    )
