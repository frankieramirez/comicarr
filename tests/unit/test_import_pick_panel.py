#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The Import pick panel: candidate series, why a group stopped, and folder memory."""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db, importinbox
from comicarr.app.imports import candidates, finalization, folder_memory
from comicarr.tables import comics, importresults, metadata


@pytest.fixture
def pick_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    config = SimpleNamespace(IMPORT_DIR=str(tmp_path / "inbox"), AUTO_IMPORT_CONFIDENCE=80, AUTO_IMPORT_ENABLED=True)
    monkeypatch.setattr(comicarr, "CONFIG", config)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield SimpleNamespace(engine=engine, ctx=SimpleNamespace(config=config), root=tmp_path / "inbox")
    db.shutdown_engine()


def _series(engine, comic_id, name, year, publisher="Kodansha", total=10, have=0):
    with engine.begin() as conn:
        conn.execute(
            insert(comics).values(
                ComicID=comic_id,
                ComicName=name,
                ComicSortName=name,
                ComicYear=year,
                ComicPublisher=publisher,
                Total=total,
                Have=have,
                DynamicComicName=name.lower(),
            )
        )


def _group(pick, folder, names, *, suggested=None, confidence=0, sizes=None):
    folder_path = pick.root / folder
    folder_path.mkdir(parents=True, exist_ok=True)
    key = "folder:%s" % importinbox._filepath_to_impid(str(folder_path))
    ids = []
    with pick.engine.begin() as conn:
        for index, name in enumerate(names):
            path = folder_path / name
            path.write_bytes(b"x" * ((sizes or {}).get(name, 10)))
            imp_id = importinbox._filepath_to_impid(str(path))
            ids.append(imp_id)
            conn.execute(
                insert(importresults).values(
                    impID=imp_id,
                    ComicName=folder,
                    DynamicName=key,
                    ComicFilename=name,
                    ComicLocation=str(path),
                    Status="Not Imported",
                    ImportDate="2026-11-12 08:00:0%d" % index,
                    MatchConfidence=confidence,
                    SuggestedComicID=suggested,
                    MatchSource="inbox",
                )
            )
    return key, ids


def test_candidates_rank_library_series_and_explain_a_tie(pick_db):
    _series(pick_db.engine, "cv-2016", "BLAME!", "2016", publisher="Vertical", total=6, have=6)
    _series(pick_db.engine, "cv-1998", "BLAME!", "1998", total=10)
    _series(pick_db.engine, "cv-batman", "Batman", "2016")
    _, ids = _group(
        pick_db,
        "BLAME!",
        ["BLAME! v01.cbz", "BLAME! v02.cbz"],
        suggested="cv-2016",
        confidence=100,
        sizes={"BLAME! v01.cbz": 248, "BLAME! v02.cbz": 236},
    )

    panel = candidates.group_candidates(pick_db.ctx, ids)

    assert [c["comic_id"] for c in panel["candidates"]] == ["cv-2016", "cv-1998", "cv-batman"]
    assert panel["reason"] == "tied"
    assert panel["tied"] == 2
    assert panel["pick"] == "cv-2016"
    assert panel["candidates"][0] | {"score": 0} == {
        "comic_id": "cv-2016",
        "name": "BLAME!",
        "year": "2016",
        "publisher": "Vertical",
        "issues": 6,
        "have": 6,
        "in_library": True,
        "image": None,
        "score": 0,
    }
    assert panel["source"] == "inbox"
    assert panel["folder"] == "inbox/BLAME!/"
    assert panel["total_bytes"] == 484
    assert [f["bytes"] for f in panel["files"]] == [248, 236]
    assert panel["found_at"].startswith("2026-11-12T08:00:00")
    assert panel["remembers"] is True
    assert panel["remembered"] is None


def test_candidates_say_when_the_best_guess_is_under_the_bar(pick_db):
    _series(pick_db.engine, "cv-magi", "Magi: The Labyrinth of Magic", "2009")
    _, ids = _group(pick_db, "Magi Labyrinth", ["Magi Labyrinth 01.cbz"], suggested="cv-magi", confidence=60)
    panel = candidates.group_candidates(pick_db.ctx, ids)
    assert panel["reason"] == "below_bar"
    assert panel["confidence_bar"] == 80
    assert panel["candidates"][0]["comic_id"] == "cv-magi"
    assert 40 <= panel["candidates"][0]["score"] < 80


def test_a_series_from_an_earlier_year_is_offered_below_the_bar(pick_db):
    # Files carry the issue's cover year; Saga began in 2012. A series that
    # began after the files' year cannot hold them and stays out.
    _series(pick_db.engine, "cv-saga", "Saga", "2012", publisher="Image")
    _series(pick_db.engine, "cv-saga-later", "Saga", "2030", publisher="Image")
    _, ids = _group(pick_db, "Saga (2026)", ["Saga 055 (2026).cbz", "Saga 056 (2026).cbz"])

    panel = candidates.group_candidates(pick_db.ctx, ids)

    assert [c["comic_id"] for c in panel["candidates"]] == ["cv-saga"]
    assert panel["candidates"][0]["score"] == 70
    assert panel["pick"] == "cv-saga"
    assert panel["reason"] == "other_year"
    # Auto-import keeps the strict rule.
    assert importinbox.score_series("Saga", {"2026"}, {"ComicName": "Saga", "ComicYear": "2012"}) == 0.0


def test_candidates_with_nothing_close_say_no_match(pick_db):
    _series(pick_db.engine, "cv-batman", "Batman", "2016")
    _, ids = _group(pick_db, "Scan_0042", ["Scan_0042.pdf"])
    panel = candidates.group_candidates(pick_db.ctx, ids)
    assert panel["reason"] == "no_match"
    assert panel["candidates"] == []
    assert panel["pick"] is None
    assert candidates.group_candidates(pick_db.ctx, ["missing"]) is None


def test_remote_candidates_are_scored_and_trimmed(pick_db):
    _, ids = _group(pick_db, "Ashita no Joe (1968)", ["Ashita no Joe 01.cbz"])
    found = {
        "results": [
            {
                "comicid": "4050-1",
                "name": "Ashita no Joe",
                "comicyear": "1968",
                "publisher": "Kodansha",
                "issues": "20",
            },
            {"comicid": "4050-2", "name": "Ashita no Joe", "comicyear": "2011", "issues": "1"},
            {"comicid": "4050-3", "name": "Nothing Alike", "comicyear": "1968"},
            {"name": "No id"},
        ]
    }
    with patch("comicarr.app.search.service.find_comic", return_value=found) as find:
        result = candidates.remote_candidates(pick_db.ctx, ids)
    assert find.call_args.kwargs["name"] == "Ashita no Joe"
    assert [c["comic_id"] for c in result["candidates"]] == ["4050-1"]
    assert result["candidates"][0]["issues"] == 20
    assert result["candidates"][0]["in_library"] is False


def test_remote_candidates_report_a_provider_error(pick_db):
    _, ids = _group(pick_db, "Magi", ["Magi 01.cbz"])
    with patch("comicarr.app.search.service.find_comic", return_value={"error": "ComicVine is down"}):
        result = candidates.remote_candidates(pick_db.ctx, ids)
    assert result == {"candidates": [], "query": "Magi", "error": "ComicVine is down"}


def test_a_folder_pick_is_remembered_and_reused_by_the_next_scan(pick_db):
    _series(pick_db.engine, "cv-2016", "BLAME!", "2016")
    key, ids = _group(pick_db, "BLAME! Master Edition", ["BLAME! Master Edition v01.cbz"])
    folder = folder_memory.folder_of(ids)
    assert folder == (key, "BLAME! Master Edition")
    assert folder_memory.remember(folder, "cv-2016", "BLAME!") is True
    assert folder_memory.recall(key)["comic_id"] == "cv-2016"

    panel = candidates.group_candidates(pick_db.ctx, ids)
    assert panel["reason"] == "remembered"
    assert panel["pick"] == "cv-2016"

    new_file = os.path.join(str(pick_db.root / "BLAME! Master Edition"), "BLAME! Master Edition v02.cbz")
    series_list = importinbox._load_library_series()
    with (
        patch("comicarr.app.imports.queries.get_issue_id", return_value="issue-2"),
        patch.object(importinbox, "_finalize_auto_import_group", return_value=True) as finalize,
    ):
        result = importinbox._match_group(
            key, {"group_name": "BLAME! Master Edition", "files": [new_file]}, series_list
        )
    assert result == {"auto_imported": 1, "queued_for_review": 0}
    assert finalize.call_args.args[1]["ComicID"] == "cv-2016"
    assert finalize.call_args.args[2] == 100


def test_loose_inbox_files_are_never_remembered(pick_db):
    assert folder_memory.recall("file:abc") is None
    with pick_db.engine.begin() as conn:
        conn.execute(insert(importresults).values(impID="loose", DynamicName="file:abc", ComicName="x"))
    assert folder_memory.folder_of(["loose"]) is None
    assert folder_memory.remember(None, "cv-1") is False


def test_import_confident_imports_each_group_and_keeps_going(pick_db):
    _series(pick_db.engine, "cv-a", "Alpha", "2020")
    _series(pick_db.engine, "cv-b", "Beta", "2020")
    key_a, ids_a = _group(pick_db, "Alpha", ["Alpha 01.cbz"], suggested="cv-a", confidence=95)
    _, ids_b = _group(pick_db, "Beta", ["Beta 01.cbz"], suggested="cv-b", confidence=90)
    _group(pick_db, "Gamma", ["Gamma 01.cbz"], suggested="cv-a", confidence=40)

    def finalize(ctx, imp_ids, comic_id, series_name=None):
        if comic_id == "cv-b":
            raise finalization.ImportFinalizationError("disk full", phase="move")
        return finalization.ImportFinalizationResult(
            matched=len(imp_ids), series_id=comic_id, series_name=series_name or "", moved=1, archived=0
        )

    with patch.object(finalization, "finalize_manual_match", side_effect=finalize) as called:
        result = candidates.import_confident(pick_db.ctx)

    assert sorted(call.args[1][0] for call in called.call_args_list) == sorted([ids_a[0], ids_b[0]])
    assert result["groups"] == 2
    assert result["imported"] == 1
    # The page gets a phrase for the phase, never the raw exception text.
    assert result["failed"] == [{"name": "Beta", "error": "the files could not be moved"}]
    assert folder_memory.recall(key_a)["comic_id"] == "cv-a"


def test_a_manual_match_remembers_the_folder(pick_db):
    from comicarr.app.series import router

    key, ids = _group(pick_db, "Blame Folder", ["Blame 01.cbz"])
    done = finalization.ImportFinalizationResult(
        matched=1, series_id="cv-2016", series_name="BLAME!", moved=1, archived=0
    )
    with patch.object(router.import_finalization, "finalize_manual_match", return_value=done):
        response = router.match_import({"imp_ids": ids, "comic_id": "cv-2016"}, ctx=pick_db.ctx)
    assert response["matched"] == 1
    assert folder_memory.recall(key) | {"chosen_at": None} == {
        "comic_id": "cv-2016",
        "comic_name": "BLAME!",
        "folder_name": "Blame Folder",
        "chosen_at": None,
    }


def test_candidate_routes_validate_their_input(pick_db):
    from comicarr.app.series import router

    assert router.import_candidates({}, ctx=pick_db.ctx).status_code == 400
    assert router.import_candidates({"imp_ids": ["gone"]}, ctx=pick_db.ctx).status_code == 404
    assert router.import_remote_candidates({"imp_ids": []}, ctx=pick_db.ctx).status_code == 400
    _, ids = _group(pick_db, "Scan", ["Scan.pdf"])
    assert router.import_candidates({"imp_ids": ",".join(ids)}, ctx=pick_db.ctx)["reason"] == "no_match"
