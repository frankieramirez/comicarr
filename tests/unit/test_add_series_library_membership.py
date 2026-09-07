#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Add Series library-membership is ComicVine ID, not display title (#867).

ComicVine publishes distinct series that share a title and year. After one of
those IDs is added, search used to mark every same-named result as already
in the library because listLibrary also indexes name:title:year.
"""

from comicarr.mb import haveit_for_comicvine


def _library_with_absolute_superman_monthly():
    # Mirrors listLibrary(): ComicID plus the name:year key that previously
    # collapsed every "Absolute Superman" (2025) result onto this one row.
    return {
        "160860": {"comicid": "160860", "status": "Active"},
        "name:absolute superman:2025": {"comicid": "160860", "status": "Active"},
    }


def test_added_series_matches_only_its_comicvine_id():
    library = _library_with_absolute_superman_monthly()

    assert haveit_for_comicvine("160860", library) == library["160860"]


def test_same_title_other_comicvine_ids_are_not_added():
    library = _library_with_absolute_superman_monthly()

    # Collected edition and language editions from #867.
    for comic_id in ("168589", "166388", "168339", "169086"):
        assert haveit_for_comicvine(comic_id, library) == "No"


def test_unknown_or_empty_library_is_not_added():
    assert haveit_for_comicvine("160860", {}) == "No"
    assert haveit_for_comicvine(None, _library_with_absolute_superman_monthly()) == "No"
