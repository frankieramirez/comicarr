#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Widen snatched.Size to 64 bits so grabs over 2 GiB fit (#1300).

SQLite's INTEGER is already 64-bit, so only PostgreSQL and MySQL change.

Revision ID: 0019_snatched_size_bigint
Revises: 0018_mcp_tool_calls
"""

import sqlalchemy as sa

from alembic import op

revision = "0019_snatched_size_bigint"
down_revision = "0018_mcp_tool_calls"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column(
        "snatched",
        "Size",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column(
        "snatched",
        "Size",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
