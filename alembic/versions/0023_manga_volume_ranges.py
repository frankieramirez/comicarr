#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Let an operator say which chapter a manga volume ends at.

MangaDex lists the chapters of only some volumes; Comicarr estimates the
rest from neighbouring volumes, and this is the correction for a wrong one.

Revision ID: 0023_manga_volume_ranges
Revises: 0022_manga_volumes
"""

import sqlalchemy as sa

from alembic import op

revision = "0023_manga_volume_ranges"
down_revision = "0022_manga_volumes"
branch_labels = None
depends_on = None


def upgrade():
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("manga_volumes")}
    if "LastChapter" not in existing:
        op.add_column("manga_volumes", sa.Column("LastChapter", sa.String(length=32), nullable=True))


def downgrade():
    with op.batch_alter_table("manga_volumes") as batch:
        batch.drop_column("LastChapter")
