#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Remember the series picked for an import inbox folder.

Revision ID: 0016_import_folder_choices
Revises: 0015_issue_search_history
"""

import sqlalchemy as sa

from alembic import op

revision = "0016_import_folder_choices"
down_revision = "0015_issue_search_history"
branch_labels = None
depends_on = None


def upgrade():
    if "import_folder_choices" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "import_folder_choices",
            sa.Column("folder_key", sa.String(length=255), primary_key=True, unique=True),
            sa.Column("folder_name", sa.Text(), nullable=True),
            sa.Column("comic_id", sa.String(length=255), nullable=False),
            sa.Column("comic_name", sa.Text(), nullable=True),
            sa.Column("chosen_at", sa.String(length=40), nullable=False),
        )


def downgrade():
    op.drop_table("import_folder_choices")
