#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Bare-number interpretation for manga filenames."""

from comicarr.app.manga.bare_numbers import interpret_bare_numbers
from comicarr.manga_parser import parse_manga_filename


def test_prefixed_volume_is_always_a_volume():
    result = parse_manga_filename("One Piece v10.cbz", bare_number_mode="chapters")
    assert result["volume_number"] == 10
    assert result["chapter_number"] is None


def test_explicit_volumes_mode_reads_naruto_bare_number_as_volume():
    result = parse_manga_filename("Naruto 12.cbr", bare_number_mode="volumes")
    assert result["volume_number"] == 12
    assert result["chapter_number"] is None


def test_explicit_chapters_mode_keeps_bare_number_as_chapter():
    result = parse_manga_filename("One Piece 1161.cbz", bare_number_mode="chapters")
    assert result["chapter_number"] == 1161.0
    assert result["volume_number"] is None


def test_auto_uses_volume_count_when_folder_matches_completed_set():
    numbers = list(range(1, 20))
    assert interpret_bare_numbers("auto", bare_numbers=numbers, volume_count=72, chapter_count=700) == "volumes"
    result = parse_manga_filename(
        "Naruto 12.cbr",
        bare_number_mode="auto",
        bare_numbers=numbers,
        volume_count=72,
        chapter_count=700,
    )
    assert result["volume_number"] == 12
    assert result["chapter_number"] is None


def test_auto_treats_number_beyond_last_volume_as_chapter():
    assert interpret_bare_numbers("auto", bare_numbers=[1161], volume_count=115, chapter_count=1190) == "chapters"
    result = parse_manga_filename(
        "One Piece 1161.cbz",
        bare_number_mode="auto",
        bare_numbers=[1161],
        volume_count=115,
        chapter_count=1190,
    )
    assert result["chapter_number"] == 1161.0
    assert result["volume_number"] is None


def test_default_auto_without_folder_counts_stays_chapter():
    result = parse_manga_filename("Chainsaw Man 165.cbz")
    assert result["chapter_number"] == 165.0
    assert result["volume_number"] is None
