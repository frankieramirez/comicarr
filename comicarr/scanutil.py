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

"""
Shared utilities for library scanners (comicsync, mangasync, importinbox).

Provides fuzzy title matching, name normalization, and common constants
used across all scan modules.
"""

import re
from difflib import SequenceMatcher

COMIC_EXTENSIONS = (".cbr", ".cbz", ".cb7", ".pdf")


def normalize_title(name):
    """Normalize a title for comparison: lowercase, strip punctuation and common particles."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


# Words a title can share with an unrelated title. They never decide a match:
# "Wizard Magazine" and "MAD Magazine" have only "Magazine" in common (#1068, #1102).
GENERIC_TITLE_WORDS = frozenset({"the", "a", "an", "magazine", "comic", "comics"})


def _similarity(n1, n2):
    seq_score = SequenceMatcher(None, n1, n2).ratio()

    s1 = set(n1.split())
    s2 = set(n2.split())
    jaccard = len(s1 & s2) / len(s1 | s2) if (s1 | s2) else 0.0

    containment = 0.0
    if n1 in n2 or n2 in n1:
        containment = min(len(n1), len(n2)) / max(len(n1), len(n2))

    return max(seq_score, jaccard, containment)


def _without_generic_words(normalized):
    return " ".join(word for word in normalized.split() if word not in GENERIC_TITLE_WORDS)


def name_similarity(name1, name2):
    """Similarity score between two names (0.0 to 1.0).

    Uses SequenceMatcher on normalized strings for character-level similarity,
    combined with Jaccard word overlap to handle word reordering.

    Generic words (``GENERIC_TITLE_WORDS``) cannot lift a score: when both
    names still have other words without them, the score is the lower of the
    full comparison and the comparison of those other words. A name made only
    of generic words is compared as written.
    """
    n1 = normalize_title(name1)
    n2 = normalize_title(name2)

    if not n1 or not n2:
        return 0.0

    if n1 == n2:
        return 1.0

    score = _similarity(n1, n2)
    d1 = _without_generic_words(n1)
    d2 = _without_generic_words(n2)
    if d1 and d2 and (d1 != n1 or d2 != n2):
        score = min(score, _similarity(d1, d2))
    return score


def find_best_match(search_name, results, name_key="name", alt_titles_key="alt_titles"):
    """Find the best matching result from a search results list.

    Checks primary title and alt titles for each result using fuzzy matching.

    Returns (best_match_dict, best_score) or (None, 0.0).
    """
    best_match = None
    best_score = 0.0
    normalized_search = normalize_title(search_name)

    for result in results:
        candidate_names = [result.get(name_key, "")]
        candidate_names.extend(result.get(alt_titles_key, []))

        for candidate in candidate_names:
            if not candidate:
                continue
            normalized_candidate = normalize_title(candidate)

            if normalized_search == normalized_candidate:
                return result, 1.0

            score = name_similarity(search_name, candidate)
            if score > best_score:
                best_score = score
                best_match = result

    return best_match, best_score
