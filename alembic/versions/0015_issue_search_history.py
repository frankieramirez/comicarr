#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Keep the candidates of each issue's most recent automatic search.

Revision ID: 0015_issue_search_history
Revises: 0014_import_issue_readiness
"""

import sqlalchemy as sa

from alembic import op

revision = "0015_issue_search_history"
down_revision = "0014_import_issue_readiness"
branch_labels = None
depends_on = None


def upgrade():
    if "issue_search_history" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "issue_search_history",
            sa.Column("issue_id", sa.String(length=255), primary_key=True),
            sa.Column("searched_at", sa.String(length=40), nullable=False),
            sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("summary_json", sa.Text(), nullable=False),
        )


def downgrade():
    op.drop_table("issue_search_history")
