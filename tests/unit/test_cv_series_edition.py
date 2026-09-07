#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from xml.dom.minidom import parseString

import pytest


@pytest.mark.parametrize("issue_count, expected_type", [(1, "TPB"), (12, "Print")])
def test_cv_helper_uses_known_count_for_book_deck(issue_count, expected_type):
    from comicarr.cv import get_imprint_volume_and_booktype

    result = get_imprint_volume_and_booktype(
        False,
        "2024",
        "Example Publisher",
        "4000-1",
        "A collected edition.",
        "Book 1 of the Shepherdess Warriors series.",
        issue_count=issue_count,
        series_name="Shepherdess Warriors",
    )

    assert result["Type"] == expected_type


def test_get_comic_info_passes_count_and_deck_to_cv_resolver():
    from comicarr.cv import GetComicInfo

    dom = parseString(
        """
        <results>
          <name>Shepherdess Warriors</name>
          <id>4050-123</id>
          <start_year>2024</start_year>
          <count_of_issues>1</count_of_issues>
          <description>A collected edition.</description>
          <deck>Book 1 of the Shepherdess Warriors series.</deck>
          <site_detail_url>https://example.invalid/series</site_detail_url>
          <site_detail_url>https://example.invalid/issue</site_detail_url>
          <aliases>None</aliases>
          <issue><id>4000-1</id><name>Book 1</name></issue>
        </results>
        """
    )

    result = GetComicInfo("4050-123", dom)

    assert result["ComicIssues"] == "1"
    assert result["Type"] == "TPB"
