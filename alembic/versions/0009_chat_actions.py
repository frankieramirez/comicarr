#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Persist confirmed-action proposals on library chat messages.

Revision ID: 0009_chat_actions
Revises: 0008_manga_series_modes
"""

import sqlalchemy as sa

from alembic import op

revision = "0009_chat_actions"
down_revision = "0008_manga_series_modes"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("ai_chat_messages")}
    if "action" not in columns:
        op.add_column("ai_chat_messages", sa.Column("action", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("ai_chat_messages", "action")
