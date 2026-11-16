#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The series lookup key writers store must equal the one post-processing derives."""

import re

import pytest

from comicarr import filechecker


def _post_processing_key(series_name):
    mod = filechecker.FileChecker().dynamic_replace(series_name)["mod_seriesname"]
    return re.sub(r"[\|\s]", "", mod.lower())


@pytest.mark.parametrize("name", ["Moon Garden", "Sand and Sky", "The Long Night", "Kid & Cat"])
def test_stored_key_equals_the_key_post_processing_derives(name):
    assert filechecker.dynamic_series_key(name) == _post_processing_key(name)


def test_stored_key_has_no_spaces():
    assert " " not in filechecker.dynamic_series_key("Moon Garden")
