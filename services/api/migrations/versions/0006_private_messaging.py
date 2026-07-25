"""Private messaging tables and durable connection grants.

Revision ID: 0006_private_messaging
Revises: 0005_calling_cards_and_blocks
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_private_messaging"
down_revision: str | None = "0005_calling_cards_and_blocks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Accepted grants are durable for messaging (ADR 0014). NULL expires_at =
    # not bound to venue-night 06:00. revoked_at remains the off-switch.
    op.execute(
        """
        ALTER TABLE app.connection_grants
            ALTER COLUMN expires_at DROP NOT NULL
        """
    )
    op.execute(
        """
        UPDATE app.connection_grants
        SET expires_at = NULL
        WHERE revoked_at IS NULL
        """
    )

    op.execute(
        """
        CREATE TABLE app.conversations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_low_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            user_high_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            originating_connection_grant_id UUID NOT NULL
                REFERENCES app.connection_grants(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_message_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            revoked_reason TEXT,
            CHECK (user_low_id < user_high_id),
            UNIQUE (user_low_id, user_high_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_conversations_last_message_at
            ON app.conversations (last_message_at DESC NULLS LAST)
        """
    )

    op.execute(
        """
        CREATE TABLE app.messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL
                REFERENCES app.conversations(id) ON DELETE CASCADE,
            sender_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            client_message_id TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'sent'
                CHECK (status IN ('sent', 'deleted')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            edited_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            moderation_status TEXT,
            moderation_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (sender_user_id, client_message_id),
            CHECK (char_length(btrim(body)) > 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_messages_conversation_created
            ON app.messages (conversation_id, created_at DESC, id DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE app.conversation_members (
            conversation_id UUID NOT NULL
                REFERENCES app.conversations(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            last_read_message_id UUID REFERENCES app.messages(id) ON DELETE SET NULL,
            last_read_at TIMESTAMPTZ,
            unread_count INTEGER NOT NULL DEFAULT 0
                CHECK (unread_count >= 0),
            muted_at TIMESTAMPTZ,
            archived_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (conversation_id, user_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_conversation_members_user_archived
            ON app.conversation_members (user_id, archived_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.conversation_members CASCADE")
    op.execute("DROP TABLE IF EXISTS app.messages CASCADE")
    op.execute("DROP TABLE IF EXISTS app.conversations CASCADE")
    op.execute(
        """
        UPDATE app.connection_grants
        SET expires_at = COALESCE(expires_at, now() + interval '1 day')
        WHERE expires_at IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE app.connection_grants
            ALTER COLUMN expires_at SET NOT NULL
        """
    )
