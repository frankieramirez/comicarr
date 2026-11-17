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
    op.execute(sa.text("DELETE FROM storyarcs WHERE StoryArcID IS NULL AND IssueArcID IS NULL AND ComicName IS NULL"))


def downgrade():
    # The deleted rows carried no arc data, so there is nothing to restore.
    pass
