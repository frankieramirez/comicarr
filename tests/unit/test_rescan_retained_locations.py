#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import json
from types import SimpleNamespace

from sqlalchemy import create_engine, select

import comicarr
from comicarr import updater
from comicarr.tables import comics, issues, metadata


def _config():
    return SimpleNamespace(
        ANNUALS_ON=False,
        MULTIPLE_DEST_DIRS=None,
        DUPECONSTRAINT="filesize",
        IGNORE_HAVETOTAL=False,
        IGNORE_TOTAL=False,
        SNATCHED_HAVETOTAL=False,
        ENFORCE_PERMS=False,
        AUTOWANT_ALL=False,
    )


def test_rescan_keeps_left_behind_files_and_still_archives_missing_ones(monkeypatch, tmp_path):
    old_folder = tmp_path / "Comics" / "Wizard (1991)"
    old_folder.mkdir(parents=True)
    left_behind = old_folder / "Wizard 001 (1991).cbz"
    left_behind.write_bytes(b"issue one")
    new_folder = tmp_path / "Magazines" / "Wizard"
    new_folder.mkdir(parents=True)

    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            comics.insert(),
            {
                "ComicID": "18692",
                "ComicName": "Wizard",
                "ComicPublisher": "Wizard Press",
                "ComicYear": "1991",
                "ComicLocation": str(new_folder),
                "RetainedLocations": json.dumps([str(old_folder)]),
                "dirlocked": 1,
                "Type": "Print",
                "Status": "Active",
            },
        )
        for issue_id, number, location in (
            ("wiz-1", "1", str(left_behind)),
            ("wiz-2", "2", "Wizard 002 (1991).cbz"),
        ):
            conn.execute(
                issues.insert(),
                {
                    "IssueID": issue_id,
                    "ComicID": "18692",
                    "Issue_Number": number,
                    "Int_IssueNumber": int(number) * 1000,
                    "IssueDate": "1991-0%s-01" % number,
                    "Status": "Downloaded",
                    "Location": location,
                },
            )

    monkeypatch.setattr(updater.db, "get_engine", lambda: engine)
    monkeypatch.setattr(comicarr, "CONFIG", _config(), raising=False)
    monkeypatch.setattr(
        updater.filechecker,
        "FileChecker",
        lambda **kwargs: SimpleNamespace(listFiles=lambda: {"comiccount": 0, "comiclist": []}),
    )

    updater.forceRescan("18692")

    with engine.connect() as conn:
        rows = {
            row["IssueID"]: row for row in conn.execute(select(issues).where(issues.c.ComicID == "18692")).mappings()
        }
    assert rows["wiz-1"]["Status"] == "Downloaded"
    assert rows["wiz-1"]["Location"] == str(left_behind)
    assert rows["wiz-2"]["Status"] == "Archived"
    with engine.connect() as conn:
        have = conn.execute(select(comics.c.Have).where(comics.c.ComicID == "18692")).scalar_one()
    assert have == 2
