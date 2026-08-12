#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Add durable Interactive release-search polling progress.

Revision ID: 0007_interactive_search_progress
Revises: 0006_interactive_search_sessions
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_interactive_search_progress"
down_revision = "0006_interactive_search_sessions"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("interactive_search_sessions")}
    additions = (
        ("provider_total", sa.Integer(), "0"),
        ("provider_completed", sa.Integer(), "0"),
        ("current_provider", sa.String(length=255), None),
        ("provider_failures_json", sa.String(length=8192), "[]"),
    )
    for name, type_, default in additions:
        if name in columns:
            continue
        kwargs = {"nullable": name == "current_provider"}
        if default is not None:
            kwargs["server_default"] = default
        op.add_column("interactive_search_sessions", sa.Column(name, type_, **kwargs))


def downgrade():
    for name in (
        "provider_failures_json",
        "current_provider",
        "provider_completed",
        "provider_total",
    ):
        op.drop_column("interactive_search_sessions", name)
