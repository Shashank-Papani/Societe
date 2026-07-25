"""Calling Cards, connection grants, and user blocks for Phase 4.

Revision ID: 0005_calling_cards_and_blocks
Revises: 0004_media_and_live_vibes
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_calling_cards_and_blocks"
down_revision: str | None = "0004_media_and_live_vibes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.user_blocks (
            blocker_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            blocked_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            reason_code TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (blocker_user_id, blocked_user_id),
            CHECK (blocker_user_id <> blocked_user_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_user_blocks_reverse
            ON app.user_blocks (blocked_user_id, blocker_user_id)
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.is_blocked(a UUID, b UUID)
        RETURNS BOOLEAN
        LANGUAGE sql
        STABLE
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM app.user_blocks ub
                WHERE (ub.blocker_user_id = a AND ub.blocked_user_id = b)
                   OR (ub.blocker_user_id = b AND ub.blocked_user_id = a)
            );
        $$
        """
    )

    op.execute(
        """
        CREATE TABLE app.calling_cards (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sender_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            recipient_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            venue_id UUID NOT NULL REFERENCES app.venues(id) ON DELETE CASCADE,
            sender_check_in_id UUID NOT NULL REFERENCES app.check_ins(id) ON DELETE RESTRICT,
            recipient_check_in_id UUID NOT NULL REFERENCES app.check_ins(id) ON DELETE RESTRICT,
            pair_low UUID GENERATED ALWAYS AS (LEAST(sender_user_id, recipient_user_id)) STORED,
            pair_high UUID GENERATED ALWAYS AS (GREATEST(sender_user_id, recipient_user_id)) STORED,
            reason_code TEXT,
            reason_text TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN (
                    'pending', 'accepted', 'declined', 'expired', 'cancelled', 'blocked'
                )),
            idempotency_key TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            responded_at TIMESTAMPTZ,
            response_action TEXT
                CHECK (
                    response_action IS NULL
                    OR response_action IN ('share_info', 'make_move', 'accept_only')
                ),
            cancelled_reason TEXT,
            CHECK (sender_user_id <> recipient_user_id),
            UNIQUE(sender_user_id, idempotency_key)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_calling_cards_one_pending_pair
            ON app.calling_cards(pair_low, pair_high, venue_id)
            WHERE status = 'pending'
        """
    )
    op.execute(
        """
        CREATE INDEX ix_calling_cards_recipient_pending
            ON app.calling_cards(recipient_user_id, created_at DESC)
            WHERE status = 'pending'
        """
    )
    op.execute(
        """
        CREATE INDEX ix_calling_cards_sender_recent
            ON app.calling_cards(sender_user_id, created_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE app.connection_grants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            calling_card_id UUID NOT NULL UNIQUE REFERENCES app.calling_cards(id) ON DELETE CASCADE,
            user_a_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            user_b_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            revoked_reason TEXT
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_connection_grants_pair
            ON app.connection_grants(user_a_id, user_b_id)
            WHERE revoked_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.connection_grants CASCADE")
    op.execute("DROP TABLE IF EXISTS app.calling_cards CASCADE")
    op.execute("DROP FUNCTION IF EXISTS app.is_blocked(UUID, UUID)")
    op.execute("DROP TABLE IF EXISTS app.user_blocks CASCADE")
