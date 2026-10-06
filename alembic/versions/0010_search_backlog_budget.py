#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Persist Wanted/RSS backlog pass cursor and per-issue RSS skip state.

Revision ID: 0010_search_backlog_budget
Revises: 0009_chat_actions
"""

import sqlalchemy as sa

from alembic import op

revision = "0010_search_backlog_budget"
down_revision = "0009_chat_actions"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "search_backlog_state" not in existing_tables:
        op.create_table(
            "search_backlog_state",
            sa.Column("pass_kind", sa.String(length=32), primary_key=True),
            sa.Column("cursor_key", sa.String(length=255)),
            sa.Column("rssdb_generation", sa.String(length=40), nullable=False, server_default=""),
            sa.Column("updated_at", sa.String(length=40), nullable=False),
        )
    if "rss_search_seen" not in existing_tables:
        op.create_table(
            "rss_search_seen",
            sa.Column("pass_kind", sa.String(length=32), primary_key=True),
            sa.Column("issue_id", sa.String(length=255), primary_key=True),
            sa.Column("checked_at", sa.String(length=40), nullable=False),
        )


def downgrade():
    op.drop_table("rss_search_seen")
    op.drop_table("search_backlog_state")
