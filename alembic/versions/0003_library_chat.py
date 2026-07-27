#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Add private, durable Library Chat conversations.

Revision ID: 0003_library_chat
Revises: 0002_legacy_adoption
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_library_chat"
down_revision = "0002_legacy_adoption"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "ai_chat_threads" not in existing_tables:
        op.create_table(
            "ai_chat_threads",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("username", sa.String(length=255), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.Column("updated_at", sa.String(length=40), nullable=False),
        )
    if "ai_chat_messages" not in existing_tables:
        op.create_table(
            "ai_chat_messages",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("thread_id", sa.String(length=64), nullable=False),
            sa.Column("parent_message_id", sa.String(length=64)),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("results", sa.Text()),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        )
    if "ai_chat_attachments" not in existing_tables:
        op.create_table(
            "ai_chat_attachments",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("thread_id", sa.String(length=64), nullable=False),
            sa.Column("message_id", sa.String(length=64), nullable=False),
            sa.Column("filename", sa.Text(), nullable=False),
            sa.Column("media_type", sa.String(length=64), nullable=False),
            sa.Column("byte_size", sa.Integer(), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.Column("relative_path", sa.Text(), nullable=False),
            sa.Column("created_at", sa.String(length=40), nullable=False),
        )

    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("ai_chat_threads")}
    if "ai_chat_threads_owner_updated" not in indexes:
        op.create_index(
            "ai_chat_threads_owner_updated",
            "ai_chat_threads",
            ["username", "updated_at"],
        )
    indexes = {index["name"] for index in inspector.get_indexes("ai_chat_messages")}
    if "ai_chat_messages_thread_created" not in indexes:
        op.create_index(
            "ai_chat_messages_thread_created",
            "ai_chat_messages",
            ["thread_id", "created_at"],
        )
    indexes = {index["name"] for index in inspector.get_indexes("ai_chat_attachments")}
    if "ai_chat_attachments_message" not in indexes:
        op.create_index(
            "ai_chat_attachments_message",
            "ai_chat_attachments",
            ["message_id"],
        )
    if "ai_chat_attachments_thread_created" not in indexes:
        op.create_index(
            "ai_chat_attachments_thread_created",
            "ai_chat_attachments",
            ["thread_id", "created_at"],
        )


def downgrade():
    op.drop_index("ai_chat_attachments_thread_created", table_name="ai_chat_attachments")
    op.drop_index("ai_chat_attachments_message", table_name="ai_chat_attachments")
    op.drop_index("ai_chat_messages_thread_created", table_name="ai_chat_messages")
    op.drop_index("ai_chat_threads_owner_updated", table_name="ai_chat_threads")
    op.drop_table("ai_chat_attachments")
    op.drop_table("ai_chat_messages")
    op.drop_table("ai_chat_threads")
