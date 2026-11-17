#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Let an operator state which chapters a manga volume holds.

MangaDex lists the chapters of only some volumes. A volume row may now carry
the first and last chapter it holds, set by the operator; Comicarr estimates
the rest from neighbouring volumes.

Revision ID: 0023_manga_volume_ranges
Revises: 0022_manga_volumes
"""

import sqlalchemy as sa

from alembic import op

revision = "0023_manga_volume_ranges"
down_revision = "0022_manga_volumes"
branch_labels = None
depends_on = None

_COLUMNS = ("FirstChapter", "LastChapter")


def upgrade():
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("manga_volumes")}
    for name in _COLUMNS:
        if name not in existing:
            op.add_column("manga_volumes", sa.Column(name, sa.String(length=32), nullable=True))


def downgrade():
    with op.batch_alter_table("manga_volumes") as batch:
        for name in reversed(_COLUMNS):
            batch.drop_column(name)
