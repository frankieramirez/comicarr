#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Remove the empty story arc rows that searches used to insert.

A search that set DateAdded on a wanted arc issue upserted by IssueID, but the
storyarcs upsert keys on IssueArcID, so each search inserted a row holding only
IssueID and DateAdded (#1514). Those rows belong to no arc and nothing reads them.

Revision ID: 0025_storyarcs_empty_rows
Revises: 0024_physical_copies
"""

import sqlalchemy as sa

from alembic import op

revision = "0025_storyarcs_empty_rows"
down_revision = "0024_physical_copies"
branch_labels = None
depends_on = None


def upgrade():
    if "storyarcs" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    storyarcs = sa.table(
        "storyarcs",
        sa.column("StoryArcID"),
        sa.column("IssueArcID"),
        sa.column("ComicName"),
    )
    # Core quotes the mixed-case column names, which PostgreSQL needs.
    op.execute(
        sa.delete(storyarcs).where(
            storyarcs.c.StoryArcID.is_(None),
            storyarcs.c.IssueArcID.is_(None),
            storyarcs.c.ComicName.is_(None),
        )
    )


def downgrade():
    # The deleted rows carried no arc data, so there is nothing to restore.
    pass
