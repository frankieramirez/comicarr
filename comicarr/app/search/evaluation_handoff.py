#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Translate evaluated candidates only where legacy acquisition needs them."""

from comicarr.app.search.evaluation import ReleaseCandidateEvaluation


def handoff_matches(candidates, *, manual_grab=False):
    matches = []
    for candidate in candidates:
        if isinstance(candidate, ReleaseCandidateEvaluation):
            if candidate._handoff is None:
                continue
            match = dict(candidate._handoff)
        else:
            # Existing non-evaluation acquisition callers already supply matches.
            match = dict(candidate)
        if manual_grab:
            match["downloadit"] = True
        matches.append(match)
    return matches
