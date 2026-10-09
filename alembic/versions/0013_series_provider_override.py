#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Per-Series search provider override (#1063).

Revision ID: 0013_series_provider_override
Revises: 0012_content_kind_set_by
"""

import sqlalchemy as sa

from alembic import op

revision = "0013_series_provider_override"
down_revision = "0012_content_kind_set_by"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("comics")}
    if "ProviderOverride" not in columns:
        op.add_column("comics", sa.Column("ProviderOverride", sa.Text()))


def downgrade():
    op.drop_column("comics", "ProviderOverride")
