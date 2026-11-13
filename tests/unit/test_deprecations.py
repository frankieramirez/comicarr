#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The deprecation registry, its startup warning and its system route (ADR-0006)."""

from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.app.system import deprecations
from comicarr.app.system import router as system_router
from comicarr.tables import annuals, issues, metadata, storyarcs


def _entry(in_use):
    return deprecations.Deprecation(
        id="fake-feature",
        name="Fake feature",
        announced_in="0.52.0",
        removable_from="1.0.0",
        replacement="Real feature",
        docs_url="https://comicarr.com/docs/deprecations#fake-feature",
        in_use=in_use,
    )


@pytest.fixture
def logged(monkeypatch):
    lines = {"warn": [], "error": []}
    monkeypatch.setattr(deprecations.logger, "warn", lambda message: lines["warn"].append(message))
    monkeypatch.setattr(deprecations.logger, "error", lambda message: lines["error"].append(message))
    return lines


def _register(monkeypatch, *entries):
    monkeypatch.setattr(deprecations, "REGISTRY", list(entries))


def _boom():
    raise RuntimeError("database is locked")


def test_an_entry_in_use_is_returned_and_warned_about_once(monkeypatch, logged):
    _register(monkeypatch, _entry(lambda: True))

    deprecations.warn_deprecations_in_use()

    assert system_router.get_deprecations() == {
        "deprecations": [
            {
                "id": "fake-feature",
                "name": "Fake feature",
                "announced_in": "0.52.0",
                "removable_from": "1.0.0",
                "replacement": "Real feature",
                "docs_url": "https://comicarr.com/docs/deprecations#fake-feature",
            }
        ]
    }
    assert len(logged["warn"]) == 1
    assert "Fake feature" in logged["warn"][0]


def test_an_entry_not_in_use_is_silent(monkeypatch, logged):
    _register(monkeypatch, _entry(lambda: False))

    deprecations.warn_deprecations_in_use()

    assert system_router.get_deprecations() == {"deprecations": []}
    assert logged == {"warn": [], "error": []}


def test_a_predicate_that_raises_counts_as_not_in_use(monkeypatch, logged):
    _register(monkeypatch, _entry(_boom), _entry(lambda: True))

    deprecations.warn_deprecations_in_use()

    assert [entry.id for entry in deprecations.deprecations_in_use()] == ["fake-feature"]
    assert len(logged["warn"]) == 1
    assert "database is locked" in logged["error"][0]


@pytest.fixture
def arc_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(STORYARCDIR=False))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _arc_row(engine, issue_id, status):
    with engine.begin() as conn:
        conn.execute(
            insert(storyarcs).values(
                StoryArcID="arc-1",
                StoryArc="Civil War",
                IssueArcID="arc-1-%s" % issue_id,
                IssueID=issue_id,
                ComicID="c-%s" % issue_id,
                Status=status,
            )
        )


def _library_issue(engine, issue_id, table=issues):
    with engine.begin() as conn:
        conn.execute(insert(table).values(IssueID=issue_id, ComicID="c-%s" % issue_id, Status="Wanted"))


def _in_use(entry_id):
    return next(entry for entry in deprecations.REGISTRY if entry.id == entry_id).in_use()


def test_both_story_arc_paths_are_registered_with_their_docs_anchor():
    assert {entry.id: entry.docs_url for entry in deprecations.REGISTRY} == {
        "storyarc-oneoff": "https://comicarr.com/docs/deprecations#storyarc-oneoff",
        "storyarc-folder-match": "https://comicarr.com/docs/deprecations#storyarc-folder-match",
    }
    for entry in deprecations.REGISTRY:
        assert entry.removable_from == "1.0.0"
        assert entry.replacement.startswith("Add what's missing")


@pytest.mark.parametrize("status", ["Wanted", "Snatched"])
def test_oneoff_is_in_use_for_an_arc_issue_wanted_without_a_library_issue(arc_db, status):
    _arc_row(arc_db, "iss-1", status)

    assert _in_use("storyarc-oneoff") is True


def test_oneoff_is_not_in_use_when_the_issue_is_in_the_library(arc_db):
    _arc_row(arc_db, "iss-1", "Wanted")
    _library_issue(arc_db, "iss-1")
    _arc_row(arc_db, "iss-2", "Snatched")
    _library_issue(arc_db, "iss-2", table=annuals)

    assert _in_use("storyarc-oneoff") is False


def test_oneoff_is_not_in_use_for_arc_issues_already_downloaded_or_skipped(arc_db):
    _arc_row(arc_db, "iss-1", "Downloaded")
    _arc_row(arc_db, "iss-2", "Skipped")

    assert _in_use("storyarc-oneoff") is False


def test_folder_match_needs_the_arc_folder_setting_and_a_watched_arc(arc_db, monkeypatch):
    assert _in_use("storyarc-folder-match") is False

    _arc_row(arc_db, "iss-1", "Downloaded")
    assert _in_use("storyarc-folder-match") is False

    monkeypatch.setattr(comicarr.CONFIG, "STORYARCDIR", True)
    assert _in_use("storyarc-folder-match") is True


def test_folder_match_is_not_in_use_with_the_setting_on_and_no_arcs(arc_db, monkeypatch):
    monkeypatch.setattr(comicarr.CONFIG, "STORYARCDIR", True)

    assert _in_use("storyarc-folder-match") is False


def test_an_arc_only_wanted_row_warns_once_at_startup_and_shows_in_the_route(arc_db, logged):
    _arc_row(arc_db, "iss-1", "Wanted")

    deprecations.warn_deprecations_in_use()

    assert [entry["id"] for entry in system_router.get_deprecations()["deprecations"]] == ["storyarc-oneoff"]
    assert len(logged["warn"]) == 1
    assert "story-arc issues whose series is not in your library" in logged["warn"][0]
