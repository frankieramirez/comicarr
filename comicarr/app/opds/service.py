#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""OPDS calls into legacy modules, so the router imports no root module (ADR-0005)."""

from comicarr import logger
from comicarr.getimage import comic_pages, open_archive, page_count, scale_image

__all__ = ["comic_pages", "mark_issue_read", "open_archive", "page_count", "scale_image"]


def mark_issue_read(issue_id: str, filename: str) -> None:
    """Mark a downloaded issue read on the reading list, if it is on one."""
    try:
        from comicarr import readinglist

        logger.fdebug("OPDS is attempting to markasRead filename %s aka issue_id %s" % (filename, issue_id))
        readinglist.Readinglist().markasRead(IssueID=issue_id)
    except Exception:
        logger.fdebug("No reading list found to update.")
