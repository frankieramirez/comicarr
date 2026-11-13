#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The secondary story-arc copy of a post-processed library issue.

Ported from the arc branch at the end of ``PostProcessor.Process_next``. The
caller owns the journal: it runs this under its own arc-scoped release key and
records ``moved`` once the copy returns.
"""

import os
from dataclasses import dataclass

from comicarr.app.common import placement


@dataclass(frozen=True)
class ArcMembership:
    """One watched arc the placed issue belongs to (a ``storyarcs`` row)."""

    story_arc: str
    story_arc_id: str
    issue_arc_id: str
    reading_order: int | str | None
    publisher: str | None

    @classmethod
    def from_row(cls, row) -> "ArcMembership":
        publisher = row["Publisher"] if row["Publisher"] is not None else row["IssuePublisher"]
        return cls(
            story_arc=row["StoryArc"],
            story_arc_id=row["StoryArcID"],
            issue_arc_id=row["IssueArcID"],
            reading_order=row["ReadingOrder"],
            publisher=publisher,
        )


@dataclass(frozen=True)
class ArcCopyResult:
    """Where the arc's copy of the issue is, and how it got there.

    With ``COPY2ARCDIR`` off there is no copy: ``destination`` is the library
    file, which is what the arc row records, and ``operation`` is None.
    """

    destination: str
    operation: str | None
    outcome: placement.Outcome | None


class ArcCopyError(OSError):
    """The arc copy did not happen; the library file is untouched."""


class ArcFolderError(ArcCopyError):
    """The arc folder could not be validated or created."""


def reading_order_prefix(reading_order) -> str:
    """``7`` -> ``007``, ``42`` -> ``042``, ``123`` -> ``123``."""
    return str(reading_order).zfill(3) if int(reading_order) <= 99 else str(reading_order)


def copy_issue_to_arc(
    library_file: str,
    membership: ArcMembership,
    *,
    span_years: str | None = None,
    config=None,
    free_space=None,
    create_directory=None,
    place=None,
) -> ArcCopyResult:
    """Make the arc folder's copy of ``library_file`` for one arc membership.

    The folder comes from ``ARC_FOLDERFORMAT``, ``STORYARCDIR`` and
    ``STORYARC_LOCATION`` (the grab-bag folder when only ``COPY2ARCDIR`` is
    set), the operation from ``ARC_FILEOPS`` and
    ``ARC_FILEOPS_SOFTLINK_RELATIVE``, and the filename gains the reading-order
    prefix when ``READ2FILENAME`` is on. Raises ``ArcFolderError`` when the
    folder cannot be made, and ``ArcCopyError`` when the disk is full or
    placement fails.
    """
    from comicarr import helpers
    from comicarr.app.storyarcs import service

    if config is None:
        import comicarr

        config = comicarr.CONFIG
    if free_space is None:
        free_space = helpers.get_free_space
    if create_directory is None:
        create_directory = service.ensure_arc_directory
    if place is None:
        place = placement.place

    if config.COPY2ARCDIR is not True:
        return ArcCopyResult(library_file, None, None)

    if span_years is None:
        span_years = service.spantheyears(membership.story_arc_id)
    arc_folder = service.arcformat(membership.story_arc, span_years, membership.publisher, config=config)
    if not arc_folder or not create_directory(arc_folder):
        raise ArcFolderError(f"Unable to validate or create the story-arc folder {arc_folder}")

    filename = os.path.basename(library_file)
    if config.READ2FILENAME:
        filename = f"{reading_order_prefix(membership.reading_order)}-{filename}"
    destination = os.path.join(arc_folder, filename)

    if free_space(arc_folder) is False:
        raise ArcCopyError(f"Not enough free space in {arc_folder}")
    try:
        result = place(
            library_file, destination, placement.Purpose.ARC, on_existing=placement.OnExisting.UNGUARDED, config=config
        )
    except Exception as e:
        raise ArcCopyError(str(e)) from e
    return ArcCopyResult(result.destination, result.effective_mode, result.outcome)
