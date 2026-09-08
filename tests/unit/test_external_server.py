#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""DDL(External) search imports MegaNZ from downloaders.external_server."""

from types import SimpleNamespace

import comicarr
from comicarr import search
from comicarr.app.search import progress
from comicarr.downloaders import external_server as exs


def test_search_imports_external_server_meganz():
    assert search.exs is exs
    assert hasattr(exs, "MegaNZ")
    assert exs.MegaNZ is not None


def test_ddl_external_search_constructor_matches_search_py():
    provider_stat = {"id": 201, "type": "DDL(External)", "lastrun": 0, "active": True, "hits": 0}
    client = search.exs.MegaNZ(query="Batman", provider_stat=provider_stat)

    assert client.ddl_search(is_info={"chktpb": 0}) == "no results"


def test_ddl_external_search_reports_unavailable_provider_to_interactive_collector():
    failures = []

    with progress.report_progress(
        on_provider_complete=lambda _provider: None,
        on_provider_failure=lambda provider, code, detail: failures.append((provider, code, detail)),
    ):
        result = exs.MegaNZ(query="Batman", provider_stat={"id": 201}).ddl_search(is_info={"chktpb": 0})

    assert result == "no results"
    assert failures == [("DDL(External)", "provider_unavailable", "External search server client is not installed")]


def test_ddl_external_search_outside_interactive_collection_does_not_raise():
    assert exs.MegaNZ(query="Batman").ddl_search() == "no results"


def test_ddl_external_warns_once_per_process_then_debugs(monkeypatch):
    calls = []
    monkeypatch.setattr(exs, "_warned", False)
    monkeypatch.setattr(
        exs,
        "logger",
        SimpleNamespace(warn=lambda m: calls.append(("warn", m)), fdebug=lambda m: calls.append(("fdebug", m))),
    )

    client = exs.MegaNZ(query="Batman")
    client.ddl_search()
    client.ddl_search()
    client.queue_the_download({"id": "nzb-1"})

    assert [level for level, _ in calls] == ["warn", "fdebug", "fdebug"]
    assert all("[DDL(External)]" in message for _, message in calls)


def test_ddl_external_snatch_constructor_matches_search_py():
    client = search.exs.MegaNZ(provider_stat={"id": 201, "type": "DDL(External)"})
    result = client.queue_the_download(
        {"id": "nzb-1", "link": "https://example.test/file", "site": "DDL(External)"},
        [{"ComicName": "Batman"}],
        {"pack": False},
    )

    assert result["success"] is False


def test_nzb_search_ddl_external_does_not_raise_missing_meganz(monkeypatch):
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(ENABLE_TORRENT_SEARCH=False),
        raising=False,
    )

    result = search.NZB_SEARCH(
        "Batman",
        "1",
        "2024",
        "2024",
        None,
        "2024-01-01",
        "2024-01-01",
        {"DDL(External)": {"id": 201, "type": "DDL(External)", "lastrun": 0, "active": True, "hits": 0}},
        1,
        "no",
        "issue-1",
        "0",
        RSS="no",
        ComicID="comic-1",
        cmloopit=1,
        manual=True,
        digitaldate="0000-00-00",
        booktype="Print",
        chktpb=0,
    )

    assert result["status"] is False
    assert result["provider"] == "DDL(External)"
