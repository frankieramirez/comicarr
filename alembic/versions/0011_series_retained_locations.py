#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Folders that still hold a Series' files after its location changed (#1006).

Revision ID: 0011_series_retained_locations
Revises: 0010_search_backlog_budget
"""

import sqlalchemy as sa

from alembic import op

revision = "0011_series_retained_locations"
down_revision = "0010_search_backlog_budget"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("comics")}
    if "RetainedLocations" not in columns:
        op.add_column("comics", sa.Column("RetainedLocations", sa.Text()))


def downgrade():
    op.drop_column("comics", "RetainedLocations")
