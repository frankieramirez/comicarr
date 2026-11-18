#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Owned and grabbed manga volumes (#1278)."""

import pytest

from comicarr.app.core import runtime
from comicarr.app.core.db import get_engine, shutdown_engine
from comicarr.app.core.tables import metadata
from comicarr.app.manga import volumes


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "data_dir", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if runtime.current().log_level is None:
        monkeypatch.setattr(runtime.current(), "log_level", 0, raising=False)
    metadata.create_all(get_engine())
    yield
    shutdown_engine()


def test_a_grab_then_the_file_landing_owns_the_volume():
    assert volumes.record_volume("md-x", "01", volumes.SNATCHED) == "md-x-v1"
    assert volumes.volume_states("md-x") == {"1": "Snatched"}
    assert volumes.covering_volumes(volumes.volume_states("md-x")) == set()

    volumes.record_volume("md-x", "1", volumes.DOWNLOADED, location="X v01.cbz")

    assert volumes.volume_states("md-x") == {"1": "Downloaded"}
    assert volumes.covering_volumes(volumes.volume_states("md-x")) == {"1"}


def test_a_later_grab_does_not_unown_a_downloaded_volume():
    volumes.record_volume("md-x", "1", volumes.DOWNLOADED, location="X v01.cbz")
    volumes.record_volume("md-x", "1", volumes.SNATCHED)
    assert volumes.volume_states("md-x") == {"1": "Downloaded"}


def test_no_volume_number_records_nothing():
    assert volumes.record_volume("md-x", None, volumes.SNATCHED) is None
    assert volumes.record_volume("md-x", "none", volumes.SNATCHED) is None
    assert volumes.volume_states("md-x") == {}
    assert volumes.volume_states(None) == {}


def test_volumes_are_kept_per_series():
    volumes.record_volume("md-x", "1", volumes.DOWNLOADED)
    volumes.record_volume("md-y", "2", volumes.SNATCHED)
    assert volumes.volume_states("md-x") == {"1": "Downloaded"}
    assert volumes.volume_states("md-y") == {"2": "Snatched"}


def test_a_snatched_update_never_overwrites_a_row_that_became_downloaded(monkeypatch):
    """The guard sits in the UPDATE itself, not only in a read before it."""
    from sqlalchemy import update

    from comicarr.app.core.tables import manga_volumes

    volumes.record_volume("md-x", "1", volumes.SNATCHED)
    # Simulate a concurrent post-process landing between any read and the write.
    with get_engine().begin() as conn:
        conn.execute(update(manga_volumes).values(Status=volumes.DOWNLOADED))
    volumes.record_volume("md-x", "1", volumes.SNATCHED)
    assert volumes.volume_states("md-x") == {"1": "Downloaded"}


def test_recording_an_existing_volume_does_not_raise_on_its_key():
    volumes.record_volume("md-x", "1", volumes.SNATCHED)
    volumes.record_volume("md-x", "1", volumes.SNATCHED)
    volumes.record_volume("md-x", "1", volumes.DOWNLOADED, location="X v01.cbz")
    assert volumes.volume_states("md-x") == {"1": "Downloaded"}


def _seed_chapters(comic_id, chapters, *, have=0):
    """``chapters`` is ``[(number, volume tag or None, status)]``."""
    from comicarr.app.core.tables import comics, issues

    with get_engine().begin() as conn:
        conn.execute(comics.insert().values(ComicID=comic_id, ComicName="Example", Have=have, Total=len(chapters)))
        for number, volume, status in chapters:
            conn.execute(
                issues.insert().values(
                    IssueID="%s-ch%s" % (comic_id, number),
                    ComicID=comic_id,
                    Issue_Number=str(number),
                    ChapterNumber=str(number),
                    VolumeNumber=volume,
                    Status=status,
                )
            )


def _stored_have(comic_id):
    from sqlalchemy import select

    from comicarr.app.core.tables import comics

    with get_engine().connect() as conn:
        return conn.execute(select(comics.c.Have).where(comics.c.ComicID == comic_id)).scalar_one()


def test_owned_volumes_count_every_chapter_they_hold_tagged_or_not():
    # Chapters 1-4 in vol 1, 5-8 in vol 2; MangaDex left 3 and 7 untagged.
    tags = {1: "1", 2: "1", 4: "1", 5: "2", 6: "2", 8: "2"}
    _seed_chapters("md-x", [(n, tags.get(n), "Skipped") for n in range(1, 9)] + [(9, None, "Downloaded")])
    volumes.record_volume("md-x", "1", volumes.DOWNLOADED, location="X v01.cbz")
    volumes.record_volume("md-x", "2", volumes.DOWNLOADED, location="X v02.cbz")

    assert volumes.owned_chapter_count("md-x") == 9


def test_a_grabbed_volume_does_not_count_until_its_file_lands():
    _seed_chapters("md-x", [(1, "1", "Skipped"), (2, "1", "Skipped")])
    volumes.record_volume("md-x", "1", volumes.SNATCHED)
    assert volumes.owned_chapter_count("md-x") == 0


def test_recount_have_stores_the_count_the_library_list_shows():
    _seed_chapters("md-x", [(1, "1", "Skipped"), (2, "1", "Skipped"), (3, None, "Downloaded")], have=1)
    volumes.record_volume("md-x", "1", volumes.DOWNLOADED, location="X v01.cbz")

    assert volumes.recount_have("md-x") == 3
    assert _stored_have("md-x") == 3


def test_a_rescan_of_volumes_already_on_record_restores_a_zeroed_have():
    """A refresh stores Have 0; a rescan that finds no new file must still recount it."""
    from comicarr.app.manga.rescan import mark_parsed_files_downloaded

    _seed_chapters("md-x", [(1, "1", "Skipped"), (2, "1", "Skipped")], have=0)
    volumes.record_volume("md-x", "1", volumes.DOWNLOADED, location="X v01.cbz")

    count = mark_parsed_files_downloaded(
        "md-x", [("/library/X v01.cbz", {"chapter_number": None, "volume_number": "1"})]
    )

    assert count == 0
    assert _stored_have("md-x") == 2


def test_a_grab_under_way_and_an_explicit_skip_stay_on_the_chapter():
    """The same exceptions the series page makes, so the two counts agree."""
    from sqlalchemy import update

    from comicarr.app.core.tables import issues

    _seed_chapters("md-x", [(1, "1", "Skipped"), (2, "1", "Snatched"), (3, "1", "Skipped"), (4, "1", "Archived")])
    with get_engine().begin() as conn:
        conn.execute(update(issues).where(issues.c.IssueID == "md-x-ch3").values(AcquisitionIntent="skipped"))
    volumes.record_volume("md-x", "1", volumes.DOWNLOADED, location="X v01.cbz")

    # Chapter 1 is covered and chapter 4 has its own file; 2 and 3 are not held.
    assert volumes.owned_chapter_count("md-x") == 2


def test_the_startup_recount_corrects_only_series_that_hold_a_volume():
    _seed_chapters("md-x", [(1, "1", "Skipped"), (2, "1", "Skipped")], have=0)
    _seed_chapters("md-y", [(1, "1", "Skipped")], have=7)
    volumes.record_volume("md-x", "1", volumes.DOWNLOADED, location="X v01.cbz")
    volumes.record_volume("md-y", "1", volumes.SNATCHED)

    assert volumes.recount_series_with_volumes() == 1
    assert _stored_have("md-x") == 2
    assert _stored_have("md-y") == 7
