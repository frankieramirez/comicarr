#  Copyright (C) 2025–2026 Comicarr contributors
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

"""Generic title words in fuzzy matching (#1068, #1102)."""

import pytest

from comicarr.app.imports.scanutil import name_similarity


@pytest.mark.parametrize(
    ("name1", "name2"),
    [
        ("Wizard Magazine", "MAD Magazine"),
        ("Detective Comics", "Action Comics"),
        ("The Flash", "The Mask"),
    ],
)
def test_shared_generic_word_cannot_carry_a_match(name1, name2):
    assert name_similarity(name1, name2) < 0.8


def test_generic_words_never_raise_a_score():
    # Dropping "The" and "Comics" would make these identical; the score stays the full comparison.
    assert name_similarity("Wizard Magazine", "Wizard: The Comics Magazine") < 0.8
    assert name_similarity("The Amazing Spider-Man", "Amazing Spider-Man") < 1.0


def test_name_of_only_generic_words_is_compared_as_written():
    # "Magazine" has no distinguishing word, so the rule does not apply.
    assert name_similarity("Magazine", "MAD Magazine") == pytest.approx(0.8)
    assert name_similarity("The Comics", "the comics") == 1.0


def test_exact_titles_still_score_one():
    assert name_similarity("MAD Magazine", "Mad Magazine!") == 1.0
