#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Record the last call to each MCP tool name, for the deprecation registry.

Revision ID: 0018_mcp_tool_calls
Revises: 0017_activity_actor
"""

import sqlalchemy as sa

from alembic import op

revision = "0018_mcp_tool_calls"
down_revision = "0017_activity_actor"
branch_labels = None
depends_on = None


def upgrade():
    if "mcp_tool_calls" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "mcp_tool_calls",
            sa.Column("tool_name", sa.String(length=64), primary_key=True, unique=True),
            sa.Column("last_called_at", sa.String(length=40), nullable=False),
        )


def downgrade():
    op.drop_table("mcp_tool_calls")
