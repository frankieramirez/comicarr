#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Record who made a change in Activity, so MCP writes show "via MCP".

Revision ID: 0017_activity_actor
Revises: 0016_import_folder_choices
"""

import sqlalchemy as sa

from alembic import op

revision = "0017_activity_actor"
down_revision = "0016_import_folder_choices"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("activity_events")}
    if "actor" not in columns:
        op.add_column("activity_events", sa.Column("actor", sa.String(length=32), nullable=True))


def downgrade():
    with op.batch_alter_table("activity_events") as batch:
        batch.drop_column("actor")
