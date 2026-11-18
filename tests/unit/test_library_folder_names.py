#  Copyright (C) 2026 Comicarr contributors
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

"""Series folder names from FileHandlers.folder_create, pinned before the move (#1417).

Post-processing places files under these folders, so the output must not drift.
"""

from types import SimpleNamespace

import pytest

import comicarr
from comicarr.app.core import runtime
from comicarr.app.library.filers import FileHandlers


def _series(**overrides):
    series = {
        "ComicName": "Saga",
        "ComicYear": "2012",
        "ComicPublisher": "Image",
        "PublisherImprint": None,
        "ComicVersion": None,
        "Type": "Print",
        "Corrected_Type": None,
        "ComicLocation": "/comics/Saga (2012)",
    }
    series.update(overrides)
    return series


@pytest.fixture
def config(monkeypatch):
    def install(**overrides):
        values = dict(
            DESTINATION_DIR="/comics",
            FOLDER_FORMAT="$Series ($Year)",
            FORMAT_BOOKTYPE=False,
            REPLACE_SPACES=False,
            REPLACE_CHAR=".",
        )
        values.update(overrides)
        monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(**values))
        monkeypatch.setattr(comicarr, "OS_DETECT", "Linux")

    return install


def _folder(series, **kwargs):
    return FileHandlers(comic=series).folder_create(**kwargs)


def test_a_comic_gets_series_and_year(config):
    config()

    result = _folder(_series())

    assert result["comlocation"] == "/comics/Saga (2012)"
    assert result["com_parentdir"] == "/comics"


def test_publisher_and_volume_tokens(config):
    config(FOLDER_FORMAT="$Publisher/$Series $VolumeN ($Year)")

    assert _folder(_series(ComicVersion="v2"))["comlocation"] == "/comics/Image/Saga V2 (2012)"
    assert _folder(_series())["comlocation"] == "/comics/Image/Saga (2012)", "no volume drops the token"


def test_a_tpb_gets_its_type_only_when_booktype_formatting_is_on(config):
    config(FOLDER_FORMAT="$Series ($Year) [$Type]")
    assert _folder(_series(Type="TPB"))["comlocation"] == "/comics/Saga (2012)"

    config(FOLDER_FORMAT="$Series ($Year) [$Type]", FORMAT_BOOKTYPE=True)
    assert _folder(_series(Type="TPB"))["comlocation"] == "/comics/Saga (2012) [TPB]"
    assert _folder(_series(Type="Print"))["comlocation"] == "/comics/Saga (2012)", "print never shows a type"


def test_a_manga_series_uses_the_same_format(config):
    config(FOLDER_FORMAT="$Publisher/$Series ($Year)")

    result = _folder(_series(ComicName="One-Punch Man", ComicYear="2012", ComicPublisher="Viz Media"))

    assert result["comlocation"] == "/comics/Viz Media/One-Punch Man (2012)"


def test_an_imprint_fills_its_token_or_disappears(config):
    config(FOLDER_FORMAT="$Publisher/$Imprint/$Series ($Year)")

    assert _folder(_series(PublisherImprint="Vertigo"))["comlocation"] == "/comics/Image/Vertigo/Saga (2012)"
    assert _folder(_series())["comlocation"] == "/comics/Image/Saga (2012)"


def test_unsafe_names_and_replaced_spaces(config):
    config(REPLACE_SPACES=True, REPLACE_CHAR="_")

    result = _folder(_series(ComicName="Batman: Year One...", ComicPublisher="DC Comics."))

    assert result["comlocation"] == "/comics/Batman_Year_One_(2012)"


def test_a_secondary_root_replaces_the_destination(config):
    config()

    assert _folder(_series(), secondary="/more/comics")["comlocation"] == "/more/comics/Saga (2012)"
