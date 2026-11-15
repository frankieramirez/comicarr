#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Alembic environment backed by Comicarr's application-owned engine."""

from alembic import context
from comicarr import logger
from comicarr.app.core.schema import autogenerate_include_object, compare_column_type
from comicarr.db import get_engine
from comicarr.tables import metadata

config = context.config
target_metadata = metadata


def run_migrations_offline():
    """Generate SQL using only an explicit URL supplied by an operator."""

    url = config.get_main_option("sqlalchemy.url")
    if not url:
        logger.error("[ALEMBIC-ENV] Offline migrations require an explicit sqlalchemy.url")
        raise RuntimeError("offline migrations require an explicit sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations through the application engine or caller connection."""

    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=compare_column_type,
            include_object=autogenerate_include_object(connection),
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    try:
        engine = config.attributes.get("engine") or get_engine()
    except TypeError as error:
        raise RuntimeError("online migrations require DATABASE_URL or an initialized Comicarr configuration") from error
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=compare_column_type,
            include_object=autogenerate_include_object(connection),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
