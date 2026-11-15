#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Own manga volumes as first-class rows, not issues (ADR-0004, #1278).

Revision ID: 0022_manga_volumes
Revises: 0021_comics_kind_varchar
"""

import sqlalchemy as sa

from alembic import op

revision = "0022_manga_volumes"
down_revision = "0021_comics_kind_varchar"
branch_labels = None
depends_on = None


def upgrade():
    if "manga_volumes" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "manga_volumes",
            sa.Column("VolumeID", sa.String(length=255), primary_key=True),
            sa.Column("ComicID", sa.String(length=255), nullable=False),
            sa.Column("VolumeNumber", sa.String(length=32), nullable=False),
            sa.Column("Status", sa.String(length=16), nullable=False),
            sa.Column("Location", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.String(length=40), nullable=False),
        )
        op.create_index("ix_manga_volumes_comic", "manga_volumes", ["ComicID"])


def downgrade():
    op.drop_index("ix_manga_volumes_comic", table_name="manga_volumes")
    op.drop_table("manga_volumes")
