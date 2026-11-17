#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Record the print copies an operator owns or wants.

One row per physical book. A copy points at an issue, an annual or a manga
volume number, and keeps a snapshot of the series name, item label and cover
so it outlives a removed series. Nothing in search reads it.

Revision ID: 0024_physical_copies
Revises: 0023_manga_volume_ranges
"""

import sqlalchemy as sa

from alembic import op

revision = "0024_physical_copies"
down_revision = "0023_manga_volume_ranges"
branch_labels = None
depends_on = None


def upgrade():
    if "physical_copies" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "physical_copies",
        sa.Column("CopyID", sa.String(length=36), primary_key=True),
        sa.Column("ComicID", sa.String(length=255), nullable=False),
        sa.Column("ItemKind", sa.String(length=16), nullable=False),
        sa.Column("ItemID", sa.String(length=255), nullable=True),
        sa.Column("VolumeNumber", sa.String(length=32), nullable=True),
        sa.Column("State", sa.String(length=16), nullable=False),
        sa.Column("SeriesName", sa.Text(), nullable=True),
        sa.Column("ItemLabel", sa.Text(), nullable=True),
        sa.Column("CoverURL", sa.Text(), nullable=True),
        sa.Column("VariantName", sa.Text(), nullable=True),
        sa.Column("VariantImageURL", sa.Text(), nullable=True),
        sa.Column("Printing", sa.String(length=32), nullable=True),
        sa.Column("Format", sa.String(length=16), nullable=True),
        sa.Column("GradeService", sa.String(length=8), nullable=True),
        sa.Column("Grade", sa.String(length=8), nullable=True),
        sa.Column("PaidCents", sa.Integer(), nullable=True),
        sa.Column("EstimateCents", sa.Integer(), nullable=True),
        sa.Column("Currency", sa.String(length=3), nullable=True),
        sa.Column("BoughtOn", sa.String(length=10), nullable=True),
        sa.Column("BoughtFrom", sa.Text(), nullable=True),
        sa.Column("Storage", sa.Text(), nullable=True),
        sa.Column("Barcode", sa.String(length=32), nullable=True),
        sa.Column("Notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("updated_at", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_physical_copies_comic", "physical_copies", ["ComicID"])
    op.create_index("ix_physical_copies_item", "physical_copies", ["ItemID"])


def downgrade():
    op.drop_index("ix_physical_copies_item", table_name="physical_copies")
    op.drop_index("ix_physical_copies_comic", table_name="physical_copies")
    op.drop_table("physical_copies")
