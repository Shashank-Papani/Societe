"""Presence retention: outside confirmation fields and venue radius overrides.

Revision ID: 0009_presence_retention
Revises: 0008_calling_card_integrity
Create Date: 2026-07-25

Adds lease-retention evidence metadata on check_ins and optional per-venue
entry/retention radius overrides. Does not drop existing lease columns.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009_presence_retention"
down_revision: str | None = "0008_calling_card_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.check_ins
            ADD COLUMN IF NOT EXISTS last_valid_evidence_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS last_distance_meters DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS last_location_accuracy_meters DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS last_evidence_observed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS outside_confirmation_count SMALLINT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS first_outside_observed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS last_outside_observed_at TIMESTAMPTZ
        """
    )
    op.execute(
        """
        ALTER TABLE app.venues
            ADD COLUMN IF NOT EXISTS entry_radius_m DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS retention_radius_m DOUBLE PRECISION
        """
    )
    op.execute(
        """
        ALTER TABLE app.check_ins
            DROP CONSTRAINT IF EXISTS check_ins_state_check
        """
    )
    # Recreate state check including rechecking (active outside-confirmation window).
    op.execute(
        """
        ALTER TABLE app.check_ins
            ADD CONSTRAINT check_ins_state_check
            CHECK (state IN (
                'provisional', 'verified', 'rechecking', 'degraded', 'exited', 'revoked'
            ))
        """
    )
    # One active presence per user includes rechecking.
    op.execute("DROP INDEX IF EXISTS app.uq_check_ins_one_active_per_user")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_check_ins_one_active_per_user
            ON app.check_ins(user_id)
            WHERE state IN ('provisional', 'verified', 'rechecking', 'degraded')
        """
    )
    op.execute("DROP INDEX IF EXISTS app.ix_check_ins_venue_active")
    op.execute(
        """
        CREATE INDEX ix_check_ins_venue_active
            ON app.check_ins(venue_id, lease_expires_at)
            WHERE state IN ('verified', 'rechecking', 'degraded')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.ix_check_ins_venue_active")
    op.execute(
        """
        CREATE INDEX ix_check_ins_venue_active
            ON app.check_ins(venue_id, lease_expires_at)
            WHERE state IN ('verified', 'degraded')
        """
    )
    op.execute("DROP INDEX IF EXISTS app.uq_check_ins_one_active_per_user")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_check_ins_one_active_per_user
            ON app.check_ins(user_id)
            WHERE state IN ('provisional', 'verified', 'degraded')
        """
    )
    # Move any rechecking rows back to verified before tightening the check.
    op.execute(
        """
        UPDATE app.check_ins
        SET state = 'verified'
        WHERE state = 'rechecking'
        """
    )
    op.execute(
        """
        ALTER TABLE app.check_ins
            DROP CONSTRAINT IF EXISTS check_ins_state_check
        """
    )
    op.execute(
        """
        ALTER TABLE app.check_ins
            ADD CONSTRAINT check_ins_state_check
            CHECK (state IN ('provisional', 'verified', 'degraded', 'exited', 'revoked'))
        """
    )
    op.execute(
        """
        ALTER TABLE app.venues
            DROP COLUMN IF EXISTS entry_radius_m,
            DROP COLUMN IF EXISTS retention_radius_m
        """
    )
    op.execute(
        """
        ALTER TABLE app.check_ins
            DROP COLUMN IF EXISTS last_valid_evidence_at,
            DROP COLUMN IF EXISTS last_distance_meters,
            DROP COLUMN IF EXISTS last_location_accuracy_meters,
            DROP COLUMN IF EXISTS last_evidence_observed_at,
            DROP COLUMN IF EXISTS outside_confirmation_count,
            DROP COLUMN IF EXISTS first_outside_observed_at,
            DROP COLUMN IF EXISTS last_outside_observed_at
        """
    )
