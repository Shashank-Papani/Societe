"""Calling Card integrity: custom_message, active-grant uniqueness, duplicate cleanup.

Revision ID: 0008_calling_card_integrity
Revises: 0007_auth_onboarding_profiles
Create Date: 2026-07-25

Cleanup keeps the newest active grant per canonical user pair and revokes
duplicates with revoked_reason = 'duplicate_cleanup'. Message history is kept.
Blocked pairs stay revoked (user_blocked) and are not reconnected.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_calling_card_integrity"
down_revision: str | None = "0007_auth_onboarding_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.calling_cards
            ADD COLUMN IF NOT EXISTS custom_message TEXT
        """
    )
    # Backfill from legacy reason_text (trim / cap later in app validation).
    op.execute(
        """
        UPDATE app.calling_cards
           SET custom_message = NULLIF(BTRIM(reason_text), '')
         WHERE custom_message IS NULL
           AND reason_text IS NOT NULL
           AND BTRIM(reason_text) <> ''
        """
    )

    # Deterministic cleanup: keep newest non-revoked grant per unordered pair.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY LEAST(user_a_id, user_b_id), GREATEST(user_a_id, user_b_id)
                    ORDER BY created_at DESC, id DESC
                ) AS rn
            FROM app.connection_grants
            WHERE revoked_at IS NULL
        )
        UPDATE app.connection_grants g
           SET revoked_at = NOW(),
               revoked_reason = 'duplicate_cleanup'
          FROM ranked r
         WHERE g.id = r.id
           AND r.rn > 1
           AND g.revoked_at IS NULL
        """
    )

    # Expire older duplicate pending cards for the same pair+venue (keep newest).
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY pair_low, pair_high, venue_id
                    ORDER BY created_at DESC, id DESC
                ) AS rn
            FROM app.calling_cards
            WHERE status = 'pending'
        )
        UPDATE app.calling_cards c
           SET status = 'expired',
               responded_at = NOW(),
               cancelled_reason = 'duplicate_cleanup'
          FROM ranked r
         WHERE c.id = r.id
           AND r.rn > 1
           AND c.status = 'pending'
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_connection_grants_one_active_pair
            ON app.connection_grants (
                LEAST(user_a_id, user_b_id),
                GREATEST(user_a_id, user_b_id)
            )
            WHERE revoked_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.uq_connection_grants_one_active_pair")
    op.execute(
        """
        ALTER TABLE app.calling_cards
            DROP COLUMN IF EXISTS custom_message
        """
    )
