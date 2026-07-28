#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Architecture boundary tests for the placement stage.

`place()` is journal-blind: it holds no journal import and writes no markers.
The *caller* owns the `post_processing` / `moved` bracket, as a release-phase
contract. That is a convention no type can enforce, so it is enforced here
instead -- by scanning source, in the `test_fastapi_db_boundary.py` idiom, so a
reintroduction fails even if nothing calls it.
"""

import re
from pathlib import Path

COMICARR_ROOT = Path(__file__).parents[2] / "comicarr"
PLACEMENT = COMICARR_ROOT / "app" / "common" / "placement.py"

# Every module permitted to call place(). Adding a module here is a deliberate
# act: it means someone has decided who writes that call's journal bracket.
PLACE_CALLERS = {
    "comicarr/postprocessor.py",
    "comicarr/app/storyarcs/service.py",
    "comicarr/app/imports/finalization.py",
}

# Callers that legitimately place files outside the post-processing journal.
# Story arcs run from a location-update pass, not a release; manual import
# finalization has its own transactional rollback and never enters the journal.
BRACKETLESS_CALLERS = {
    "comicarr/app/storyarcs/service.py",
    "comicarr/app/imports/finalization.py",
}


def _sources():
    for path in COMICARR_ROOT.rglob("*.py"):
        if "_vendor" in path.parts:
            continue
        yield path


def _relative(path):
    return str(path.relative_to(COMICARR_ROOT.parent))


CALL = re.compile(r"(?<![\w.])place\s*\(|placement\.place\s*\(")


def test_only_registered_modules_call_the_placement_stage():
    callers = {_relative(path) for path in _sources() if path != PLACEMENT and CALL.search(path.read_text())}

    assert callers <= PLACE_CALLERS, (
        "unregistered module calls place(); decide who owns its journal bracket "
        "and add it to PLACE_CALLERS: %s" % sorted(callers - PLACE_CALLERS)
    )


def test_post_processor_callers_also_write_the_pre_move_marker():
    """A destructive placement in postprocessor.py must sit inside a bracket.

    The marker is written per release phase rather than per call, so this checks
    co-presence in the module rather than adjacency to any one call.
    """
    postprocessor = COMICARR_ROOT / "postprocessor.py"
    source = postprocessor.read_text()

    if "placement.place(" not in source and "= place(" not in source:
        return

    assert '_journal_pp("post_processing"' in source, (
        "postprocessor.py places files but never writes the pre-move marker"
    )
    assert '_journal_pp("moved"' in source, "postprocessor.py places files but never writes the post-move marker"


def test_the_placement_stage_is_journal_blind():
    source = PLACEMENT.read_text()

    assert "_journal_pp" not in source, "placement.py must not write journal markers"
    assert "pipeline_journal" not in source
    for marker in ('"post_processing"', '"moved"', '"post_processed"'):
        assert marker not in source, "placement.py must not know the marker %s exists" % marker


def test_the_placement_stage_does_not_depend_on_the_downloads_package():
    """Imports and story arcs need placement; neither may pull in downloads to get it."""
    source = PLACEMENT.read_text()

    assert "app.downloads" not in source
    assert "app/downloads" not in source


def test_the_placement_stage_reads_config_lazily():
    """A module-level `import comicarr` would let the config object be captured early."""
    source = PLACEMENT.read_text()
    module_level_imports = [
        line for line in source.splitlines() if line.startswith("import ") or line.startswith("from ")
    ]

    assert not any("comicarr" in line for line in module_level_imports), (
        "placement.py must import comicarr inside place(), so CONFIG is resolved at call time"
    )
