#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import json
import os
from types import SimpleNamespace

import pytest

import comicarr
from comicarr import db
from comicarr.app.common import placement
from comicarr.app.imports import finalization
from comicarr.app.series import location as series_location
from comicarr.app.series import service as series_service
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import metadata

WIZARD = "18692"
OTHER = "160294"


@pytest.fixture
def library(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    comics_root = tmp_path / "Comics"
    magazines_root = tmp_path / "Magazines"
    comics_root.mkdir()
    magazines_root.mkdir()
    config = SimpleNamespace(
        DESTINATION_DIR=str(comics_root),
        MANGA_DESTINATION_DIR=None,
        COMIC_DIR=None,
        MANGA_DIR=None,
        MULTIPLE_DEST_DIRS=None,
        NEWCOM_DIR=None,
        ADDITIONAL_LIBRARY_ROOTS=str(magazines_root),
        FOLDER_FORMAT="$Series ($Year)",
        REPLACE_SPACES=False,
        FORMAT_BOOKTYPE=False,
        ANNUALS_ON=False,
    )
    monkeypatch.setattr(comicarr, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    metadata.create_all(get_engine())
    rescans = []
    monkeypatch.setattr("comicarr.updater.forceRescan", lambda comic_id, **kwargs: rescans.append(comic_id))
    yield SimpleNamespace(
        ctx=SimpleNamespace(config=config),
        config=config,
        comics=comics_root,
        magazines=magazines_root,
        rescans=rescans,
    )
    shutdown_engine()


def _add_series(comic_id, name, location, **extra):
    db.upsert(
        "comics",
        {
            "ComicName": name,
            "ComicYear": "1991",
            "ComicPublisher": "Wizard Press",
            "Type": "Print",
            "Status": "Active",
            "ComicLocation": str(location),
            **extra,
        },
        {"ComicID": comic_id},
    )


def _add_issue(comic_id, issue_id, location, status="Downloaded"):
    db.upsert(
        "issues",
        {"ComicID": comic_id, "Issue_Number": issue_id[-1], "Status": status, "Location": location},
        {"IssueID": issue_id},
    )


def _series(comic_id):
    return db.raw_select_one(
        "SELECT ComicLocation, dirlocked, RetainedLocations FROM comics WHERE ComicID = ?", [comic_id]
    )


def _issue_location(issue_id):
    return db.raw_select_one("SELECT Location FROM issues WHERE IssueID = ?", [issue_id])["Location"]


def _wizard_with_one_issue(library):
    old_folder = library.comics / "Wizard (1991)"
    old_folder.mkdir()
    (old_folder / "Wizard 001.cbz").write_text("issue one")
    _add_series(WIZARD, "Wizard", old_folder)
    _add_issue(WIZARD, "wiz-1", "Wizard 001.cbz")
    return old_folder


def test_wizard_moves_to_a_magazines_folder_and_leaves_its_files_owned_in_place(library):
    old_folder = _wizard_with_one_issue(library)
    other_folder = library.comics / "Saga (2012)"
    _add_series(OTHER, "Saga", other_folder)
    new_folder = library.magazines / "Wizard"

    result = series_location.change_series_location(library.ctx, WIZARD, str(new_folder))

    assert result["success"] is True
    assert result["comic_location"] == str(new_folder)
    assert result["previous_location"] == str(old_folder)
    assert result["override"] is True
    assert result["files_moved"] == 0
    assert result["files_left"] == 1
    assert new_folder.is_dir()
    assert (old_folder / "Wizard 001.cbz").is_file()
    assert _series(WIZARD)["ComicLocation"] == str(new_folder)
    assert _series(WIZARD)["dirlocked"] == 1
    assert json.loads(_series(WIZARD)["RetainedLocations"]) == [str(old_folder)]
    assert _issue_location("wiz-1") == str(old_folder / "Wizard 001.cbz")
    assert _series(OTHER)["ComicLocation"] == str(other_folder)
    assert library.rescans == [WIZARD]

    detail = series_service.get_comic_detail(library.ctx, WIZARD)
    assert detail["comic"][0]["LocationOverride"] == 1
    assert json.loads(detail["comic"][0]["RetainedLocations"]) == [str(old_folder)]
    assert detail["issues"][0]["physicalOwned"] is True
    assert detail["issues"][0]["displayState"] == "Downloaded"


def test_move_files_relocates_only_the_series_holdings(library):
    old_folder = _wizard_with_one_issue(library)
    (old_folder / "notes.txt").write_text("operator notes")
    new_folder = library.magazines / "Wizard"

    result = series_location.change_series_location(library.ctx, WIZARD, str(new_folder), move_files=True)

    assert result["success"] is True
    assert result["files_moved"] == 1
    assert result["files_left"] == 0
    assert (new_folder / "Wizard 001.cbz").read_text() == "issue one"
    assert not (old_folder / "Wizard 001.cbz").exists()
    assert (old_folder / "notes.txt").is_file()
    assert _issue_location("wiz-1") == "Wizard 001.cbz"
    assert _series(WIZARD)["RetainedLocations"] is None
    assert series_service.get_comic_detail(library.ctx, WIZARD)["issues"][0]["physicalOwned"] is True


def test_moving_every_file_out_removes_the_emptied_series_folder(library):
    old_folder = _wizard_with_one_issue(library)

    series_location.change_series_location(library.ctx, WIZARD, str(library.magazines / "Wizard"), move_files=True)

    assert not old_folder.exists()
    assert library.comics.is_dir()


def test_a_name_collision_refuses_the_move_before_anything_changes(library):
    old_folder = _wizard_with_one_issue(library)
    new_folder = library.magazines / "Wizard"
    new_folder.mkdir()
    (new_folder / "Wizard 001.cbz").write_text("someone else's file")

    with pytest.raises(series_location.SeriesLocationError, match="already exists"):
        series_location.change_series_location(library.ctx, WIZARD, str(new_folder), move_files=True)

    assert (new_folder / "Wizard 001.cbz").read_text() == "someone else's file"
    assert (old_folder / "Wizard 001.cbz").read_text() == "issue one"
    assert _series(WIZARD)["ComicLocation"] == str(old_folder)
    assert _issue_location("wiz-1") == "Wizard 001.cbz"


def test_a_partial_move_keeps_every_file_reachable_and_reports_failure(library, monkeypatch):
    old_folder = _wizard_with_one_issue(library)
    (old_folder / "Wizard 002.cbz").write_text("issue two")
    _add_issue(WIZARD, "wiz-2", "Wizard 002.cbz")
    new_folder = library.magazines / "Wizard"
    real_place = placement.place

    def place_then_fail(source, destination, purpose, **kwargs):
        if source.endswith("002.cbz"):
            raise placement.PlacementError("disk full")
        return real_place(source, destination, purpose, **kwargs)

    monkeypatch.setattr(placement, "place", place_then_fail)

    result = series_location.change_series_location(library.ctx, WIZARD, str(new_folder), move_files=True)

    assert result["success"] is False
    assert "disk full" in result["error"]
    assert result["files_moved"] == 1
    assert result["files_left"] == 1
    assert (new_folder / "Wizard 001.cbz").is_file()
    assert (old_folder / "Wizard 002.cbz").is_file()
    assert _issue_location("wiz-1") == "Wizard 001.cbz"
    assert _issue_location("wiz-2") == str(old_folder / "Wizard 002.cbz")
    assert json.loads(_series(WIZARD)["RetainedLocations"]) == [str(old_folder)]
    issues = series_service.get_comic_detail(library.ctx, WIZARD)["issues"]
    assert all(issue["physicalOwned"] for issue in issues)


def test_a_destination_inside_the_current_folder_cannot_take_a_move(library):
    old_folder = _wizard_with_one_issue(library)

    with pytest.raises(series_location.SeriesLocationError, match="overlap"):
        series_location.change_series_location(library.ctx, WIZARD, str(old_folder / "nested"), move_files=True)

    assert _series(WIZARD)["ComicLocation"] == str(old_folder)


def _refused(library, folder):
    with pytest.raises(series_location.SeriesLocationError) as error:
        series_location.change_series_location(library.ctx, WIZARD, folder)
    return error.value


def test_unsafe_folders_are_refused_before_anything_changes(library, tmp_path):
    old_folder = _wizard_with_one_issue(library)
    (tmp_path / "Magazines-old").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, library.magazines / "escape")
    saga_folder = library.comics / "Saga (2012)"
    saga_folder.mkdir()
    _add_series(OTHER, "Saga", saga_folder)

    refusals = {
        "relative": _refused(library, "Magazines/Wizard"),
        "traversal": _refused(library, str(library.magazines / ".." / "outside" / "Wizard")),
        "sibling prefix": _refused(library, str(tmp_path / "Magazines-old" / "Wizard")),
        "symlink escape": _refused(library, str(library.magazines / "escape" / "Wizard")),
        "unlisted root": _refused(library, str(tmp_path / "Elsewhere" / "Wizard")),
        "root itself": _refused(library, str(library.magazines)),
        "filesystem root": _refused(library, os.sep),
        "another series": _refused(library, str(saga_folder)),
        "inside another series": _refused(library, str(saga_folder / "Wizard")),
    }

    assert all(error.status == 400 for error in refusals.values())
    assert "Saga" in str(refusals["another series"])
    assert _series(WIZARD)["ComicLocation"] == str(old_folder)
    assert _series(WIZARD)["dirlocked"] is None
    assert library.rescans == []


def test_clearing_the_override_restores_the_automatic_folder(library):
    _wizard_with_one_issue(library)
    series_location.change_series_location(library.ctx, WIZARD, str(library.magazines / "Wizard"))

    result = series_location.change_series_location(library.ctx, WIZARD, None)

    assert result["success"] is True
    assert result["override"] is False
    assert result["comic_location"] == str(library.comics / "Wizard (1991)")
    assert _series(WIZARD)["dirlocked"] == 0
    assert _series(WIZARD)["RetainedLocations"] is None
    assert _issue_location("wiz-1") == "Wizard 001.cbz"


def test_a_running_post_processor_or_import_blocks_the_change(library):
    old_folder = _wizard_with_one_issue(library)
    new_folder = str(library.magazines / "Wizard")

    comicarr.APILOCK.acquire()
    try:
        with pytest.raises(series_location.SeriesLocationError) as busy_pp:
            series_location.change_series_location(library.ctx, WIZARD, new_folder)
    finally:
        comicarr.APILOCK.release()

    with finalization.finalization_paused():
        with pytest.raises(series_location.SeriesLocationError) as busy_import:
            series_location.change_series_location(library.ctx, WIZARD, new_folder)

    assert busy_pp.value.status == 409
    assert busy_import.value.status == 409
    assert _series(WIZARD)["ComicLocation"] == str(old_folder)


def test_unknown_series_is_reported_as_not_found(library):
    with pytest.raises(series_location.SeriesLocationError) as error:
        series_location.change_series_location(library.ctx, "missing", str(library.magazines / "Wizard"))

    assert error.value.status == 404


def test_a_refreshing_series_cannot_change_folder_mid_refresh(library):
    old_folder = _wizard_with_one_issue(library)
    db.upsert("comics", {"Status": "Loading"}, {"ComicID": WIZARD})

    with pytest.raises(series_location.SeriesLocationError) as error:
        series_location.change_series_location(library.ctx, WIZARD, str(library.magazines / "Wizard"))

    assert error.value.status == 409
    assert _series(WIZARD)["ComicLocation"] == str(old_folder)


def test_reclassifying_as_manga_keeps_a_chosen_folder(library, monkeypatch):
    _wizard_with_one_issue(library)
    chosen = str(library.magazines / "Wizard")
    series_location.change_series_location(library.ctx, WIZARD, chosen)
    monkeypatch.setattr(series_service, "_manga_destination", lambda: str(library.comics.parent / "Manga"))

    result = series_service.update_content_kind(library.ctx, WIZARD, "manga")
    healed, repointed = series_service.persist_manga_location_if_needed(
        db.raw_select_one("SELECT * FROM comics WHERE ComicID = ?", [WIZARD])
    )

    assert result["content_type"] == "manga"
    assert result["location_repointed"] is False
    assert (healed, repointed) == (chosen, False)
    assert _series(WIZARD)["ComicLocation"] == chosen


def test_reclassifying_a_series_without_a_chosen_folder_still_repoints_it(library, monkeypatch):
    _wizard_with_one_issue(library)
    manga_dest = library.comics.parent / "Manga"
    monkeypatch.setattr(series_service, "_manga_destination", lambda: str(manga_dest))

    result = series_service.update_content_kind(library.ctx, WIZARD, "manga")

    assert result["location_repointed"] is True
    assert _series(WIZARD)["ComicLocation"] == str(manga_dest / "Wizard")


def test_tagging_a_left_behind_file_rewrites_it_where_it_is(library, monkeypatch, tmp_path):
    from comicarr.app.metadata import service as metadata_service

    old_folder = library.comics / "Wizard (1991)"
    old_folder.mkdir()
    (old_folder / "Wizard 001.cbr").write_text("rar issue")
    _add_series(WIZARD, "Wizard", old_folder)
    _add_issue(WIZARD, "wiz-1", "Wizard 001.cbr")
    new_folder = library.magazines / "Wizard"
    series_location.change_series_location(library.ctx, WIZARD, str(new_folder))
    library.config.CMTAG_START_YEAR_AS_VOLUME = False
    cache = tmp_path / "tag-cache"
    cache.mkdir()

    def tag(dir_name, *, filename, **kwargs):
        tagged = cache / "Wizard 001.cbz"
        tagged.write_text("tagged zip issue")
        return str(tagged)

    monkeypatch.setattr("comicarr.cmtag.run", tag)

    metadata_service._do_manual_metatag("wiz-1")

    assert (old_folder / "Wizard 001.cbz").read_text() == "tagged zip issue"
    assert not (old_folder / "Wizard 001.cbr").exists()
    assert list(new_folder.iterdir()) == []
    assert _issue_location("wiz-1") == str(old_folder / "Wizard 001.cbz")


def test_a_folder_comicarr_cannot_write_to_is_refused_before_anything_changes(library):
    old_folder = _wizard_with_one_issue(library)
    locked = library.magazines / "Locked"
    locked.mkdir()
    os.chmod(locked, 0o555)
    try:
        with pytest.raises(series_location.SeriesLocationError, match="Could not create|cannot write"):
            series_location.change_series_location(library.ctx, WIZARD, str(locked / "Wizard"), move_files=True)
    finally:
        os.chmod(locked, 0o755)

    assert (old_folder / "Wizard 001.cbz").is_file()
    assert _series(WIZARD)["ComicLocation"] == str(old_folder)
    assert _issue_location("wiz-1") == "Wizard 001.cbz"
