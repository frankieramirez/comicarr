#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Add bounded Interactive release search session storage.

Revision ID: 0006_interactive_search_sessions
Revises: 0005_activity_events
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_interactive_search_sessions"
down_revision = "0005_activity_events"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "interactive_search_sessions" not in existing_tables:
        op.create_table(
            "interactive_search_sessions",
            sa.Column("session_id", sa.String(length=64), primary_key=True),
            sa.Column("slot_digest", sa.String(length=64), nullable=False),
            sa.Column("actor_digest", sa.String(length=64), nullable=False),
            sa.Column("browser_digest", sa.String(length=64), nullable=False),
            sa.Column("entity_type", sa.String(length=32), nullable=False),
            sa.Column("entity_id", sa.String(length=255), nullable=False),
            sa.Column("series_id", sa.String(length=255)),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.Column("updated_at", sa.String(length=40), nullable=False),
            sa.Column("expires_at", sa.String(length=40), nullable=False),
            sa.UniqueConstraint("slot_digest", name="uq_interactive_search_session_slot"),
        )
    if "interactive_search_candidates" not in existing_tables:
        op.create_table(
            "interactive_search_candidates",
            sa.Column("candidate_id", sa.String(length=64), primary_key=True),
            sa.Column("session_id", sa.String(length=64), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("public_json", sa.Text(), nullable=False),
            sa.Column("reconstruction_json", sa.Text(), nullable=False),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.Column("updated_at", sa.String(length=40), nullable=False),
            sa.Column("expires_at", sa.String(length=40), nullable=False),
            sa.UniqueConstraint(
                "session_id",
                "ordinal",
                name="uq_interactive_search_candidate_ordinal",
            ),
        )

    inspector = sa.inspect(bind)
    session_indexes = {index["name"] for index in inspector.get_indexes("interactive_search_sessions")}
    if "interactive_search_sessions_expiry" not in session_indexes:
        op.create_index(
            "interactive_search_sessions_expiry",
            "interactive_search_sessions",
            ["expires_at"],
        )
    if "interactive_search_sessions_scope" not in session_indexes:
        op.create_index(
            "interactive_search_sessions_scope",
            "interactive_search_sessions",
            ["entity_type", "entity_id"],
        )
    candidate_indexes = {index["name"] for index in inspector.get_indexes("interactive_search_candidates")}
    if "interactive_search_candidates_session" not in candidate_indexes:
        op.create_index(
            "interactive_search_candidates_session",
            "interactive_search_candidates",
            ["session_id", "ordinal"],
        )
    if "interactive_search_candidates_expiry" not in candidate_indexes:
        op.create_index(
            "interactive_search_candidates_expiry",
            "interactive_search_candidates",
            ["expires_at"],
        )


def downgrade():
    op.drop_index(
        "interactive_search_candidates_expiry",
        table_name="interactive_search_candidates",
    )
    op.drop_index(
        "interactive_search_candidates_session",
        table_name="interactive_search_candidates",
    )
    op.drop_table("interactive_search_candidates")
    op.drop_index(
        "interactive_search_sessions_scope",
        table_name="interactive_search_sessions",
    )
    op.drop_index(
        "interactive_search_sessions_expiry",
        table_name="interactive_search_sessions",
    )
    op.drop_table("interactive_search_sessions")
