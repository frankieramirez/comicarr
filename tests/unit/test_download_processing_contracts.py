#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import queue
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests
from sqlalchemy import insert, select

import comicarr
from comicarr import db, getcomics
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.downloads import pp_commands, recovery, router, service
from comicarr.app.downloads.ddl_commands import DDLCommand
from comicarr.downloaders import mediafire
from comicarr.tables import ddl_info, metadata


@pytest.fixture(autouse=True)
def _reset_ddl_process_ownership(monkeypatch):
    monkeypatch.setattr(comicarr, "DDL_QUEUED", set(), raising=False)


def _complete_ddl_payload(**overrides):
    payload = {
        "id": "ddl-1",
        "link": "https://downloads.invalid/issue.cbz",
        "site": "DDL(GetComics)",
        "series": "Saga",
        "year": "2026",
        "size": "10 MB",
        "comicid": "comic-1",
        "issueid": "issue-1",
        "oneoff": False,
        "link_type": "GC-Main",
        "filename": "Saga 001.cbz",
        "mainlink": "https://getcomics.invalid/saga",
        "comicinfo": [{"pack": False, "IssueID": "issue-1"}],
        "packinfo": None,
        "remote_filesize": 10_485_760,
        "resume": None,
        "issues": "1",
        "pack": False,
    }
    payload.update(overrides)
    return payload


# ... truncated for brevity in tool call - NEED FULL CONTENT
