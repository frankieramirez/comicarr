#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The cached cover path for a series stays inside the cache folder."""

import os
from types import SimpleNamespace

import pytest

from comicarr.app.core import runtime
from comicarr.app.series import comic_add


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(CACHE_DIR=str(cache)), raising=False)
    return cache


def test_a_series_id_maps_to_its_cover_in_the_cache_folder(cache_dir):
    assert comic_add.cover_cache_path("4050") == os.path.join(os.path.realpath(cache_dir), "4050.jpg")
    assert comic_add.cover_cache_path(4050) == os.path.join(os.path.realpath(cache_dir), "4050.jpg")


@pytest.mark.parametrize("comicid", ["../escape", "../../etc/passwd", "/tmp/abs", "sub/../../out"])
def test_a_series_id_that_escapes_the_cache_folder_is_refused(cache_dir, comicid):
    with pytest.raises(ValueError):
        comic_add.cover_cache_path(comicid)


def test_a_sibling_folder_sharing_the_cache_prefix_is_refused(cache_dir):
    (cache_dir.parent / "cache-other").mkdir()
    with pytest.raises(ValueError):
        comic_add.cover_cache_path("../cache-other/x")
