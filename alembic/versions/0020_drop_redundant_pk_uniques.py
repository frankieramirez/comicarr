#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Drop unique constraints that only repeat a single-column primary key (#1251, #1257).

``search_backlog_state.pass_kind``, ``import_folder_choices.folder_key`` and
``mcp_tool_calls.tool_name`` were declared ``primary_key=True, unique=True``.
Whether an install also got the redundant unique constraint depended on how
the table was first created (baseline ``create_all``, an older migration, or
the dialect), so upgraded and fresh installs disagreed and ``alembic check``
reported drift. The metadata now declares only the primary key, and this
revision removes the duplicate wherever one exists.

SQLite's inline ``UNIQUE`` is an unnamed autoindex that Alembic does not
compare and cannot drop without a table rebuild, so SQLite is left as is.

Revision ID: 0020_drop_redundant_pk_uniques
Revises: 0019_snatched_size_bigint
"""

import sqlalchemy as sa

from alembic import op

revision = "0020_drop_redundant_pk_uniques"
down_revision = "0019_snatched_size_bigint"
branch_labels = None
depends_on = None

_PRIMARY_KEYS = (
    ("search_backlog_state", "pass_kind"),
    ("import_folder_choices", "folder_key"),
    ("mcp_tool_calls", "tool_name"),
)


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, column in _PRIMARY_KEYS:
        if table not in tables:
            continue
        dropped = set()
        for constraint in inspector.get_unique_constraints(table):
            name = constraint.get("name")
            if name and list(constraint.get("column_names") or ()) == [column]:
                op.drop_constraint(name, table, type_="unique")
                dropped.add(name)
        for index in inspector.get_indexes(table):
            name = index.get("name")
            if (
                name
                and name not in dropped
                and index.get("unique")
                and not index.get("duplicates_constraint")
                and list(index.get("column_names") or ()) == [column]
            ):
                op.drop_index(name, table_name=table)


def downgrade():
    # The dropped constraints only repeated the primary key, so there is
    # nothing to restore: uniqueness is enforced either way.
    pass
