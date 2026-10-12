#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import sqlalchemy as sa

from alembic import op

revision = "0014_import_issue_readiness"
down_revision = "0013_series_provider_override"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("importresults")}
    if "RequiresIssueResolution" not in columns:
        op.add_column("importresults", sa.Column("RequiresIssueResolution", sa.Integer(), server_default="0"))


def downgrade():
    op.drop_column("importresults", "RequiresIssueResolution")
