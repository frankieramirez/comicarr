#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Downloads domain service — history, post-processing, DDL queue.

Module-level functions wrapping postprocessor.py (~5k lines) and
download client interactions.
"""

import datetime
import os
import re
import time
import zipfile

import rarfile

import comicarr
from comicarr import db, getcomics, logger, nzbget, process, sabnzbd
from comicarr.app.attention import BATCH_CAP, PROBLEM_STATUS, Failure, ManualReview, record
from comicarr.app.downloads import queries as dl_queries
from comicarr.app.downloads.completed_path import resolve_completed_download_file
from comicarr.app.downloads.ddl_commands import DDLCommand, DDLCommandError
from comicarr.app.downloads.pp_commands import PostProcessCommandError, configured_roots, validate_postprocess_item
from comicarr.downloaders import mediafire, mega, pixeldrain
from comicarr.tables import annuals, comics, ddl_info, issues, storyarcs, weekly

# ids handed to DDL_QUEUE but not yet claimed by the worker thread (#784).
_DDL_PENDING_HANDOFF = set()
