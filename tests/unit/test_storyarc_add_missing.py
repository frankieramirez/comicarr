#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Coverage for the story-arc "add what's missing" flow (#913).

The flow has three seams: summarising which arc series are absent from the
library, resolving each to a ComicVine volume for confirmation, and the
post-import worker that links real IssueIDs and marks only the arc's issues
Wanted before queueing searches.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr.app.storyarcs import service
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, issues, metadata, storyarcs


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    metadata.create_all(get_engine())
    yield
    shutdown_engine()


def _arc_row(
    issue_arc_id,
    comic_name,
    issue_number,
    comic_id="",
    status="Added",
    arc_id="ARC1",
    arc_name="Big Event",
    issue_id="",
    reading_order=1,
):
    return {
        "StoryArcID": arc_id,
        "StoryArc": arc_name,
        "ComicName": comic_name,
        "IssueNumber": issue_number,
        "ComicID": comic_id,
        "IssueID": issue_id,
        "IssueArcID": issue_arc_id,
        "ReadingOrder": reading_order,
        "Status": status,
        "Manual": "ai",
    }


def _insert_arc_rows(rows):
    with get_engine().begin() as conn:
        for row in rows:
            conn.execute(insert(storyarcs).values(**row))


def _insert_comic(comic_id, name, status="Active", year="2020"):
    with get_engine().begin() as conn:
        conn.execute(
            insert(comics).values(
                ComicID=comic_id,
                ComicName=name,
                ComicYear=year,
                Status=status,
                Type="Print",
            )
        )


def _insert_issue(issue_id, comic_id, name, number, status="Skipped", int_number=None):
    with get_engine().begin() as conn:
        conn.execute(
            insert(issues).values(
                IssueID=issue_id,
                ComicID=comic_id,
                ComicName=name,
                Issue_Number=number,
                Int_IssueNumber=int_number,
                Status=status,
            )
        )


def _storyarc_row(issue_arc_id):
    with get_engine().connect() as conn:
        row = conn.execute(select(storyarcs).where(storyarcs.c.IssueArcID == issue_arc_id)).first()
    return dict(row._mapping) if row else None


def _issue_row(issue_id):
    with get_engine().connect() as conn:
        row = conn.execute(select(issues).where(issues.c.IssueID == issue_id)).first()
    return dict(row._mapping) if row else None


def test_missing_series_groups_unwatched_series():
    _insert_comic("C1", "Saga")
    _insert_arc_rows(
        [
            _arc_row("A1", "Saga", "1", comic_id="C1"),
            _arc_row("A2", "Flashpoint", "1", reading_order=2),
            _arc_row("A3", "Flashpoint", "2", reading_order=3),
            _arc_row("A4", "Doom", "1", comic_id="C9", reading_order=4),
        ]
    )

    missing = service.get_missing_series("ARC1")

    assert missing is not None
    by_name = {entry["series_name"]: entry for entry in missing}
    assert "Saga" not in by_name
    assert by_name["Flashpoint"]["issue_count"] == 2
    assert by_name["Flashpoint"]["issue_numbers"] == ["1", "2"]
    assert by_name["Doom"]["issue_count"] == 1
    assert by_name["Doom"]["comic_id"] == "C9"


def test_missing_series_skips_owned_arc_rows():
    _insert_arc_rows(
        [
            _arc_row("A1", "Flashpoint", "1", status="Downloaded"),
            _arc_row("A2", "Flashpoint", "2", status="Added", reading_order=2),
        ]
    )

    missing = service.get_missing_series("ARC1")

    assert missing[0]["series_name"] == "Flashpoint"
    assert missing[0]["issue_count"] == 1
    assert missing[0]["issue_numbers"] == ["2"]


def test_missing_series_unknown_arc_returns_none():
    assert service.get_missing_series("NOPE") is None
    assert service.resolve_missing_series("NOPE") is None


def test_resolve_missing_series_matches_comicvine():
    _insert_arc_rows(
        [
            _arc_row("A1", "Flashpoint", "1"),
            _arc_row("A2", "Doom", "1", comic_id="C9", reading_order=2),
        ]
    )

    def fake_find(name, mode, issue=None, **kwargs):
        assert name == "Flashpoint"
        return {
            "results": [
                {
                    "comicid": "777",
                    "name": "Flashpoint",
                    "comicyear": "2011",
                    "publisher": "DC Comics",
                    "comicimage": "https://img.example/fp.jpg",
                }
            ]
        }

    with patch("comicarr.mb.findComic", side_effect=fake_find) as finder:
        resolved = service.resolve_missing_series("ARC1")

    assert finder.call_count == 1
    by_name = {entry["series_name"]: entry for entry in resolved}
    assert by_name["Flashpoint"]["match"]["comic_id"] == "777"
    assert by_name["Flashpoint"]["match"]["year"] == "2011"
    assert by_name["Doom"]["match"]["comic_id"] == "C9"


def test_resolve_missing_series_unmatched_has_no_match():
    _insert_arc_rows([_arc_row("A1", "Obscure Thing", "1")])

    with patch("comicarr.mb.findComic", return_value={"results": []}):
        resolved = service.resolve_missing_series("ARC1")

    assert resolved[0]["match"] is None


def test_add_missing_series_requires_arc():
    result = service.add_missing_series("NOPE", [{"series_name": "X", "comic_id": "1"}])
    assert result["success"] is False


def test_add_missing_series_rejects_empty_additions():
    _insert_arc_rows([_arc_row("A1", "Flashpoint", "1")])
    assert service.add_missing_series("ARC1", [])["success"] is False
    assert service.add_missing_series("ARC1", [{"series_name": "Flashpoint"}])["success"] is False


def test_add_missing_series_stamps_queues_and_spawns_worker():
    _insert_arc_rows(
        [
            _arc_row("A1", "Flashpoint", "1"),
            _arc_row("A2", "Flashpoint", "2", reading_order=2),
            _arc_row("A3", "Saga", "1", comic_id="C1", reading_order=3),
        ]
    )

    queued = {}
    with (
        patch("comicarr.importer.importer_thread") as importer_thread,
        patch.object(service, "start_background_thread") as starter,
    ):
        importer_thread.side_effect = lambda watch: queued.setdefault("watch", watch)
        result = service.add_missing_series(
            "ARC1",
            [
                {"series_name": "Flashpoint", "comic_id": "4050-777"},
                {"series_name": "Flashpoint", "comic_id": "777"},
                {"series_name": "", "comic_id": "888"},
            ],
        )

    assert result["success"] is True
    assert result["queued"] == 1
    assert queued["watch"] == [{"comicid": "777", "comicname": None, "seriesyear": None}]
    starter.assert_called_once()
    assert starter.call_args.kwargs["args"] == ("ARC1", ["777"], "Big Event")
    assert _storyarc_row("A1")["ComicID"] == "777"
    assert _storyarc_row("A2")["ComicID"] == "777"
    assert _storyarc_row("A3")["ComicID"] == "C1"


def test_want_arc_issues_links_marks_and_enqueues():
    _insert_comic("C9", "Flashpoint")
    _insert_issue("I9", "C9", "Flashpoint", "1", int_number=1000)
    _insert_arc_rows([_arc_row("A1", "Flashpoint", "1", comic_id="C9")])

    enqueued = []
    with patch("comicarr.app.search.commands.enqueue_search_command") as enqueue:
        enqueue.side_effect = lambda payload, **kw: enqueued.append((payload, kw))
        summary = service._want_arc_issues("ARC1")

    arc_row = _storyarc_row("A1")
    assert arc_row["Status"] == "Wanted"
    assert arc_row["IssueID"] == "I9"
    assert _issue_row("I9")["Status"] == "Wanted"
    assert summary["wanted"] == 1
    assert len(enqueued) == 1
    payload, kwargs = enqueued[0]
    assert payload["issueid"] == "I9"
    assert payload["comicid"] == "C9"
    assert kwargs["trigger"] == "storyarc_wanted"


def test_want_arc_issues_mirrors_owned_status():
    _insert_comic("C9", "Flashpoint")
    _insert_issue("I9", "C9", "Flashpoint", "1", status="Downloaded", int_number=1000)
    _insert_arc_rows([_arc_row("A1", "Flashpoint", "1", comic_id="C9")])

    with patch("comicarr.app.search.commands.enqueue_search_command") as enqueue:
        summary = service._want_arc_issues("ARC1")

    assert _storyarc_row("A1")["Status"] == "Downloaded"
    assert _issue_row("I9")["Status"] == "Downloaded"
    assert summary["wanted"] == 0
    enqueue.assert_not_called()


def test_want_arc_issues_marks_unmatched_rows_wanted_without_search():
    _insert_arc_rows([_arc_row("A1", "Nowhere", "1")])

    with patch("comicarr.app.search.commands.enqueue_search_command") as enqueue:
        summary = service._want_arc_issues("ARC1")

    arc_row = _storyarc_row("A1")
    assert arc_row["Status"] == "Wanted"
    assert summary["unresolved"] == 1
    enqueue.assert_not_called()


def test_want_arc_issues_does_not_requeue_already_wanted():
    _insert_comic("C9", "Flashpoint")
    _insert_issue("I9", "C9", "Flashpoint", "1", status="Wanted", int_number=1000)
    _insert_arc_rows([_arc_row("A1", "Flashpoint", "1", comic_id="C9")])

    with patch("comicarr.app.search.commands.enqueue_search_command") as enqueue:
        summary = service._want_arc_issues("ARC1")

    assert _storyarc_row("A1")["Status"] == "Wanted"
    assert summary["wanted"] == 0
    enqueue.assert_not_called()


def test_want_issues_after_imports_waits_then_wants():
    _insert_arc_rows([_arc_row("A1", "Flashpoint", "1")])

    calls = []
    with (
        patch.object(service, "_wait_for_series_added", side_effect=lambda cid: calls.append(cid) or True),
        patch.object(service, "_want_arc_issues", return_value={"wanted": 1, "unresolved": 0}) as want,
        patch("comicarr.app.activity.producers.emit_arc_activity") as emit,
    ):
        service._want_issues_after_imports("ARC1", ["777"], "Big Event")

    assert calls == ["777"]
    want.assert_called_once_with("ARC1")
    emit.assert_called_once()
    assert emit.call_args.args[:3] == ("add", "succeeded", "ARC1")
