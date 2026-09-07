#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import pytest

from comicarr.app.metadata.series_type import collected_edition_type, resolve_series_edition


def test_volume_metadata_promotes_single_issue_print_to_tpb():
    assert (
        resolve_series_edition(
            series_type="Print",
            issue_count=1,
            series_year=2024,
            current_year=2026,
            volume="1",
        )
        == "TPB"
    )


def test_book_or_vol_language_promotes_single_issue_print_to_tpb():
    assert (
        resolve_series_edition(
            series_type="Print",
            issue_count=1,
            series_year=2024,
            current_year=2026,
            description="Book 1 of the Shepherdess Warriors series.",
        )
        == "TPB"
    )
    assert collected_edition_type(description="Shepherdess Warriors Vol. 1 collects the first album.") == "TPB"


def test_trade_paperback_description_promotes_to_tpb():
    assert (
        resolve_series_edition(
            series_type="Print",
            issue_count=1,
            series_year=2023,
            current_year=2026,
            description="This trade paperback reprints the original French album.",
        )
        == "TPB"
    )


def test_past_year_single_issue_without_volume_signals_stays_oneshot():
    assert (
        resolve_series_edition(
            series_type="Print",
            issue_count=1,
            series_year=2024,
            current_year=2026,
            description="It's been 10 years since the men of the village left.",
        )
        == "One-Shot"
    )


def test_explicit_cv_types_are_preserved():
    assert (
        resolve_series_edition(
            series_type="One-Shot",
            issue_count=1,
            series_year=2020,
            current_year=2026,
            volume="1",
        )
        == "One-Shot"
    )
    assert (
        resolve_series_edition(
            series_type="TPB",
            issue_count=1,
            series_year=2020,
            current_year=2026,
        )
        == "TPB"
    )


def test_multi_issue_series_volume_is_not_forced_to_tpb_or_oneshot():
    assert (
        resolve_series_edition(
            series_type="Print",
            issue_count=12,
            series_year=2016,
            current_year=2026,
            volume="3",
        )
        == "Print"
    )


def test_current_year_single_issue_is_not_forced_to_oneshot():
    assert (
        resolve_series_edition(
            series_type="Print",
            issue_count=1,
            series_year=2026,
            current_year=2026,
        )
        == "Print"
    )


@pytest.mark.parametrize(
    "reference",
    [
        "A paperback version can be found elsewhere.",
        "Hardcover editions can be found elsewhere.",
        "The trade paperback can be found here.",
        "A graphic novel edition can be found here.",
        "The TPB can be found in Book 2 of the collected series.",
    ],
)
def test_references_to_other_editions_do_not_classify_this_series(reference):
    description = "Print edition. " + "A story about warriors. " * 4 + reference
    assert (
        resolve_series_edition(
            series_type="Print",
            issue_count=1,
            series_year=2024,
            current_year=2026,
            description=description,
        )
        == "One-Shot"
    )


def test_reference_does_not_hide_affirmative_edition_metadata():
    assert (
        collected_edition_type(
            description="A paperback version can be found elsewhere. This hardcover collects issues 1-4."
        )
        == "HC"
    )
    assert (
        collected_edition_type(
            description="A hardcover edition can be found elsewhere.",
            deck="Trade paperback collecting the first four issues.",
        )
        == "TPB"
    )
