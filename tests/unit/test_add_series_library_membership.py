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

from types import SimpleNamespace
from unittest.mock import Mock
from xml.dom.minidom import parseString

import comicarr
from comicarr import mb
from comicarr.app.search.service import find_comic
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


def test_search_marks_only_matching_comicvine_id_as_added(monkeypatch):
    """Same-title XML results retain separate membership in Add Series output."""
    comic_ids = ("160860", "168589", "166388", "168339", "169086")
    volumes = "".join(
        f"""<volume>
            <id>{comic_id}</id><name>Absolute Superman</name>
            <start_year>2025</start_year><count_of_issues>2</count_of_issues>
            <site_detail_url>https://comicvine.gamespot.com/4050-{comic_id}/</site_detail_url>
            <publisher><name>DC Comics</name></publisher>
        </volume>"""
        for comic_id in comic_ids
    )
    response = parseString(
        f"<response><number_of_total_results>5</number_of_total_results><results>{volumes}</results></response>"
    )
    config = SimpleNamespace(USE_METRON_SEARCH=False, COMICVINE_API="test-key", CV_SKIP_IMPRINT_VALIDATION=True)
    monkeypatch.setattr(comicarr, "CONFIG", config)
    monkeypatch.setattr(mb, "listLibrary", _library_with_absolute_superman_monthly)
    monkeypatch.setattr(mb, "pullsearch", Mock(return_value=response))
    monkeypatch.setattr(mb, "ignored_publisher_check", lambda publisher: False)

    result = find_comic(SimpleNamespace(config=config), "Absolute Superman", limit=20)

    membership = {row["comicid"]: (row["haveit"], row["in_library"]) for row in result["results"]}
    assert membership == {
        "160860": (_library_with_absolute_superman_monthly()["160860"], True),
        **{comic_id: ("No", False) for comic_id in comic_ids[1:]},
    }
