#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""A volume label belongs to the volume, not to the series title.

The token walker truncates a parsed title at the volume position it found, but
it does not always find the long form. `Series Vol.33` then kept the label in
the title and matched no series at all, while `Series v33` -- the same release,
named the short way -- parsed correctly.
"""

import pytest


def _strip(series_name, volume_number):
    from comicarr.filechecker import strip_trailing_volume_label

    return strip_trailing_volume_label(series_name, volume_number)


class TestStripTrailingVolumeLabel:
    @pytest.mark.parametrize(
        "series_name",
        [
            "One-Punch Man Vol 33",
            "One-Punch Man Vol.33",
            "One-Punch Man Vol33",
            "One-Punch Man vol. 33",
            "One-Punch Man Volume 33",
            "One-Punch Man v33",
            "One-Punch Man-v33",
            "One-Punch Man v033",
        ],
    )
    def test_every_spelling_of_the_label_is_removed(self, series_name):
        assert _strip(series_name, "33") == "One-Punch Man"

    def test_a_zero_padded_detected_volume_still_matches(self):
        assert _strip("One-Punch Man v06", "06") == "One-Punch Man"

    def test_a_label_for_a_different_volume_is_left_alone(self):
        """The number must be the volume that was actually detected."""
        assert _strip("Some Series Vol 2", "33") == "Some Series Vol 2"

    def test_a_trailing_number_that_is_not_a_label_is_left_alone(self):
        assert _strip("Fantastic Four 4", "4") == "Fantastic Four 4"
        assert _strip("District 9", "9") == "District 9"

    def test_a_label_that_is_not_at_the_end_is_left_alone(self):
        assert _strip("Heavy Metal Volume 5 Special", "5") == "Heavy Metal Volume 5 Special"

    def test_no_detected_volume_means_nothing_is_removed(self):
        assert _strip("One-Punch Man Vol 33", None) == "One-Punch Man Vol 33"

    def test_a_title_that_is_only_a_label_is_kept(self):
        """Stripping it away would leave a name that matches every series."""
        assert _strip("Vol 33", "33") == "Vol 33"

    def test_a_non_numeric_detected_volume_is_ignored(self):
        assert _strip("One-Punch Man Vol 33", "unknown") == "One-Punch Man Vol 33"

    def test_an_empty_series_name_is_returned_unchanged(self):
        assert _strip("", "33") == ""
        assert _strip(None, "33") is None


def _parse(filename):
    """Parse one filename the way the scan does, and return the result."""
    from unittest.mock import MagicMock

    import comicarr
    from comicarr.filechecker import FileChecker

    if comicarr.LOG_LEVEL is None:
        comicarr.LOG_LEVEL = 0
    config = MagicMock()
    config.IGNORE_SEARCH_WORDS = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(comicarr, "CONFIG", config)
        return FileChecker(dir="/tmp", file=filename, justparse=True).listFiles()


class TestVolumeLabelParsing:
    """What the parse actually produces, rather than what parseit's source says.

    Asserting on the source text of parseit passed while the behaviour was
    still broken: the call was present, but the regex behind it did not match
    the long form, so `One-Punch Man Vol.33` parsed as the series
    `'One-Punch Man Vol .33'` and matched nothing.
    """

    @pytest.mark.parametrize(
        "filename",
        [
            "One-Punch Man Vol.33 (2014) (Digital).cbz",
            "One-Punch Man Vol 33 (2014) (Digital).cbz",
            "One-Punch Man Volume 33 (2014) (Digital).cbz",
            "One-Punch Man v33 (2014) (Digital).cbz",
            "One-Punch Man v033 (2014) (Digital).cbz",
        ],
    )
    def test_the_label_never_reaches_the_series_title(self, filename):
        from comicarr.app.manga.ledger import volume_numbers_match

        parsed = _parse(filename)

        assert parsed["series_name"] == "One-Punch Man", (
            "the volume label survived into the series title, which matches no series"
        )
        # Compared through the ledger rule rather than by string: the parse
        # keeps whatever padding the filename used (`v033`), and normalising
        # that is the ledger's job, not the parser's.
        assert volume_numbers_match(parsed["series_volume"], "33"), "the volume was not read off as the volume"

    def test_a_short_and_a_long_form_of_one_release_parse_alike(self):
        """The whole point: the same release named two ways is one release."""
        short = _parse("One-Punch Man v06 (2014).cbz")
        long_form = _parse("One-Punch Man Vol.06 (2014).cbz")

        assert short["series_name"] == long_form["series_name"] == "One-Punch Man"
        assert short["series_volume"] == long_form["series_volume"] == "v06"

    def test_a_chapter_file_keeps_its_number_and_claims_no_volume(self):
        """Control: the strip must not invent a volume for a numbered chapter."""
        parsed = _parse("Chainsaw Man 165.cbz")

        assert parsed["series_name"] == "Chainsaw Man"
        assert parsed["issue_number"] == "165"
        assert parsed["series_volume"] is None
