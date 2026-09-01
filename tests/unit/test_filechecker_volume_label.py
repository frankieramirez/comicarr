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


class TestVolumeLabelWiring:
    """The helper is only useful if parseit consults it."""

    @staticmethod
    def _source():
        import inspect

        from comicarr.filechecker import FileChecker

        return inspect.getsource(FileChecker.parseit)

    def test_parseit_strips_the_label_from_the_series_title(self):
        assert "strip_trailing_volume_label(series_name, detected_volume)" in self._source(), (
            "parseit no longer removes an already-detected volume label from the "
            "series title; a 'Series Vol.NN' release will match no series"
        )

    def test_the_manga_volume_regex_result_is_used_when_the_walker_missed_it(self):
        src = self._source()
        assert "detected_volume = manga_volume" in src, (
            "the long-form label is only found by the manga volume regex, so that "
            "is the value the strip has to be driven by"
        )
