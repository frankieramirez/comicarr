#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Give comics.ContentType and ReadingDirection their declared VARCHAR(16) type (#1252).

Pre-Alembic releases (v0.19.x) added both columns as TEXT. Installs that
started on Alembic got VARCHAR(16) from the baseline, so adopted installs
reported drift. On SQLite the two are the same storage and the comparison
hook treats them as equal; PostgreSQL and MySQL store them differently, so
this revision converts a TEXT column there. A column holding a value longer
than 16 characters is left as TEXT rather than truncated.

Revision ID: 0021_comics_kind_varchar
Revises: 0020_drop_redundant_pk_uniques
"""

import sqlalchemy as sa

from alembic import op
from comicarr import logger

revision = "0021_comics_kind_varchar"
down_revision = "0020_drop_redundant_pk_uniques"
branch_labels = None
depends_on = None

_COLUMNS = ("ContentType", "ReadingDirection")


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    reflected = {column["name"]: column for column in sa.inspect(bind).get_columns("comics")}
    comics = sa.table("comics", *(sa.column(name) for name in _COLUMNS))
    for name in _COLUMNS:
        column = reflected.get(name)
        # TEXT reflects as an unbounded String; VARCHAR(16) already matches.
        if column is None or not isinstance(column["type"], sa.String) or column["type"].length is not None:
            continue
        longest = bind.execute(sa.select(sa.func.max(sa.func.char_length(comics.c[name])))).scalar()
        if longest is not None and longest > 16:
            logger.warning(
                "[MIGRATION] comics.%s keeps its TEXT type: a stored value is %s characters, longer than 16"
                % (name, longest)
            )
            continue
        op.alter_column(
            "comics",
            name,
            existing_type=column["type"],
            type_=sa.String(length=16),
            existing_nullable=column.get("nullable", True),
            existing_server_default=column.get("default"),
        )


def downgrade():
    # VARCHAR(16) is what every Alembic-born install already has; there is
    # no TEXT state worth restoring.
    pass
