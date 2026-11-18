#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""cmtag.run against real archives, with ComicVine faked (#1414)."""

import json
import xml.etree.ElementTree as ET
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from comicarr.app.core import runtime
from comicarr.app.metadata import comicinfo
from comicarr.app.metadata import tagging as cmtag

ISSUE = {
    "id": 4242,
    "name": "Chapter One",
    "issue_number": "001",
    "cover_date": "2012-03-01",
    "volume": {"id": 43, "name": "Saga"},
    "description": "<p>The war.</p>",
    "site_detail_url": "https://comicvine.example/issue/4000-4242/",
    "person_credits": [
        {"name": "Brian K. Vaughan", "role": "writer"},
        {"name": "Fiona Staples", "role": "artist, cover"},
    ],
    "character_credits": [{"name": "Alana"}, {"name": "Marko"}],
    "team_credits": [],
    "location_credits": [],
    "story_arc_credits": [],
}


def _config(tmp_path, **overrides):
    values = dict(
        CACHE_DIR=str(tmp_path / "cache"),
        FILE_OPTS="copy",
        CBR2CBZ_ONLY=False,
        CT_TAG_CR=True,
        CT_TAG_CBL=False,
        CT_CBZ_OVERWRITE=False,
        CT_NOTES_FORMAT="Issue ID",
        CMTAG_VOLUME=True,
        CMTAG_START_YEAR_AS_VOLUME=False,
        SETDEFAULTVOLUME=False,
        ENFORCE_PERMS=False,
    )
    values.update(overrides)
    (tmp_path / "cache").mkdir(exist_ok=True)
    return SimpleNamespace(**values)


def _cbz(path, comicinfo_xml=None, comment=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("page01.jpg", b"one")
        archive.writestr("page02.jpg", b"two")
        if comicinfo_xml is not None:
            archive.writestr("ComicInfo.xml", comicinfo_xml)
        if comment is not None:
            archive.comment = comment
    return path


def _tags(path):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("ComicInfo.xml"))
    return {element.tag: (element.text or "").strip() for element in root}


def _run(tmp_path, source, *, issueid="4242", issue=ISSUE, manga_volume=None, comversion="v2012", **config):
    fetches = []

    def comicvine_issue(requested):
        fetches.append(requested)
        return (issue, "Image") if issue else (None, None)

    with (
        patch.object(runtime.current(), "config", _config(tmp_path, **config)),
        patch.object(cmtag, "comicvine_issue", side_effect=comicvine_issue),
        patch.object(cmtag, "manga_volume_for_issue", return_value=manga_volume),
        patch.object(cmtag, "sendnotify"),
    ):
        result = cmtag.run(
            str(source.parent),
            issueid=issueid,
            comversion=comversion,
            filename=str(source),
            readingorder=[("Saga Arc", 3)],
            agerating="Mature",
        )
    return result, fetches


def test_a_comicvine_issue_is_tagged_from_comicvine_and_comicarr(tmp_path):
    source = _cbz(tmp_path / "library" / "Saga 001.cbz")

    result, fetches = _run(tmp_path, source)

    assert fetches == ["4242"]
    assert result.startswith(str(tmp_path / "cache")) and result.endswith("Saga 001.cbz")
    tags = _tags(result)
    assert tags["Series"] == "Saga"
    assert tags["Number"] == "1"
    assert tags["Title"] == "Chapter One"
    assert tags["Volume"] == "2012"
    assert tags["Publisher"] == "Image"
    assert (tags["Year"], tags["Month"], tags["Day"]) == ("2012", "3", "1")
    assert tags["Writer"] == "Brian K. Vaughan"
    assert tags["Penciller"] == "Fiona Staples" and tags["CoverArtist"] == "Fiona Staples"
    assert tags["Characters"] == "Alana, Marko"
    assert tags["StoryArc"] == "Saga Arc" and tags["StoryArcNumber"] == "3"
    assert tags["AgeRating"] == "Mature"
    assert tags["Notes"].endswith("[Issue ID 4242]")
    with zipfile.ZipFile(result) as archive:
        assert archive.namelist() == ["page01.jpg", "page02.jpg", "ComicInfo.xml"]
    with zipfile.ZipFile(source) as archive:
        assert "ComicInfo.xml" not in archive.namelist(), "the library file itself is not touched"


def test_existing_cbz_tags_are_kept_unless_overwrite_is_on(tmp_path):
    original = "<ComicInfo><Series>Mine</Series></ComicInfo>"
    source = _cbz(tmp_path / "library" / "Saga 001.cbz", comicinfo_xml=original)

    kept, _ = _run(tmp_path, source)
    replaced, _ = _run(tmp_path, source, CT_CBZ_OVERWRITE=True)

    assert _tags(kept) == {"Series": "Mine"}
    assert _tags(replaced)["Series"] == "Saga"


def test_overwriting_keeps_fields_comicarr_does_not_manage(tmp_path):
    original = "<ComicInfo><Series>Mine</Series><GTIN>9781607066019</GTIN><Writer>Old Name</Writer></ComicInfo>"
    source = _cbz(tmp_path / "library" / "Saga 001.cbz", comicinfo_xml=original)

    result, _ = _run(tmp_path, source, CT_CBZ_OVERWRITE=True)

    tags = _tags(result)
    assert tags["GTIN"] == "9781607066019"
    assert tags["Writer"] == "Old Name, Brian K. Vaughan"


def test_a_manga_volume_is_tagged_as_a_volume_with_no_issue_number(tmp_path):
    source = _cbz(tmp_path / "library" / "One-Punch Man v07.cbz")

    result, _ = _run(tmp_path, source, manga_volume="7")

    tags = _tags(result)
    assert tags["Volume"] == "7"
    assert "Number" not in tags, "ComicVine numbers the volume; the tag must not"


@pytest.mark.parametrize("issueid", ["md-csm-ch165", None])
def test_an_issue_without_a_comicvine_id_is_tagged_locally(tmp_path, issueid):
    source = _cbz(tmp_path / "library" / "Chainsaw Man 165.cbz")

    result, fetches = _run(tmp_path, source, issueid=issueid)

    assert fetches == []
    tags = _tags(result)
    assert tags["Volume"] == "2012"
    assert "Series" not in tags


def test_comicvine_failure_leaves_the_file_untagged(tmp_path):
    source = _cbz(tmp_path / "library" / "Saga 001.cbz")

    result, _ = _run(tmp_path, source, issue=None)

    assert result == "fail"


def test_a_file_that_is_not_an_archive_is_reported_as_not_found(tmp_path):
    source = tmp_path / "library" / "Saga 001.cbz"
    source.parent.mkdir()
    source.write_bytes(b"not a zip")

    result, _ = _run(tmp_path, source)

    assert result == "file not found||Saga 001.cbz"


def test_comicbooklover_tags_go_in_the_zip_comment(tmp_path):
    source = _cbz(tmp_path / "library" / "Saga 001.cbz")

    result, _ = _run(tmp_path, source, CT_TAG_CR=False, CT_TAG_CBL=True)

    with zipfile.ZipFile(result) as archive:
        assert "ComicInfo.xml" not in archive.namelist()
        block = json.loads(archive.comment)["ComicBookInfo/1.0"]
    assert block["series"] == "Saga"
    assert block["publicationYear"] == 2012
    assert {"person": "Brian K. Vaughan", "role": "Writer"} in block["credits"]


def test_no_tag_style_selected_fails(tmp_path):
    source = _cbz(tmp_path / "library" / "Saga 001.cbz")

    result, _ = _run(tmp_path, source, CT_TAG_CR=False)

    assert result == "fail"


class _FakeRar:
    """A rarfile.RarFile stand-in: the test host has no rar tool to build one."""

    members = {"page01.jpg": b"one", "page02.jpg": b"two"}
    fail = False

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def infolist(self):
        return [SimpleNamespace(filename=name, is_dir=lambda: False) for name in self.members]

    def read(self, member):
        if self.fail:
            raise comicinfo.rarfile.BadRarFile("CRC error")
        return self.members[member.filename]


@pytest.fixture
def rar(monkeypatch):
    monkeypatch.setattr(comicinfo, "archive_kind", lambda path: "rar" if path.endswith(".cbr") else "zip")
    monkeypatch.setattr(comicinfo.rarfile, "RarFile", _FakeRar)
    _FakeRar.fail = False
    return _FakeRar


def test_a_cbr_becomes_a_tagged_cbz(tmp_path, rar):
    source = tmp_path / "library" / "Saga 001.cbr"
    source.parent.mkdir()
    source.write_bytes(b"rar")

    result, _ = _run(tmp_path, source)

    assert result.endswith("Saga 001.cbz")
    assert _tags(result)["Series"] == "Saga"
    assert source.exists(), "the library .cbr stays until the caller places the .cbz"


def test_conversion_only_converts_and_writes_no_tags(tmp_path, rar):
    source = tmp_path / "library" / "Saga 001.cbr"
    source.parent.mkdir()
    source.write_bytes(b"rar")

    result, fetches = _run(tmp_path, source, CBR2CBZ_ONLY=True)

    assert result.endswith("Saga 001.cbz")
    assert fetches == []
    with zipfile.ZipFile(result) as archive:
        assert archive.namelist() == ["page01.jpg", "page02.jpg"]


def test_an_unreadable_cbr_is_corrupt(tmp_path, rar):
    rar.fail = True
    source = tmp_path / "library" / "Saga 001.cbr"
    source.parent.mkdir()
    source.write_bytes(b"rar")

    result, _ = _run(tmp_path, source)

    assert result == "corrupt"


def test_the_tagged_copy_keeps_the_library_file_mode(tmp_path):
    source = _cbz(tmp_path / "library" / "Saga 001.cbz")
    source.chmod(0o644)

    result, _ = _run(tmp_path, source)

    assert cmtag.current_file_mode(result) == 0o644
