#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Marker for operator content-kind writes (#976).

Revision ID: 0012_content_kind_set_by
Revises: 0011_series_retained_locations
"""

import sqlalchemy as sa

from alembic import op

revision = "0012_content_kind_set_by"
down_revision = "0011_series_retained_locations"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("comics")}
    if "ContentKindSetBy" not in columns:
        op.add_column("comics", sa.Column("ContentKindSetBy", sa.String(length=16)))


def downgrade():
    op.drop_column("comics", "ContentKindSetBy")
