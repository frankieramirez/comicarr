#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Per-series manga bare-number and monitor modes.

Revision ID: 0008_manga_series_modes
Revises: 0007_interactive_search_progress
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_manga_series_modes"
down_revision = "0007_interactive_search_progress"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("comics")}
    additions = (
        ("BareNumberMode", sa.String(length=16), "auto"),
        ("MonitorMode", sa.String(length=16), "blended"),
    )
    for name, type_, default in additions:
        if name in columns:
            continue
        op.add_column("comics", sa.Column(name, type_, server_default=default))


def downgrade():
    for name in ("MonitorMode", "BareNumberMode"):
        op.drop_column("comics", name)
