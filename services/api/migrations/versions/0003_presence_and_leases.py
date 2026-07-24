"""Presence check-ins, limited location evidence, and outbox for Phase 2.

Revision ID: 0003_presence_and_leases
Revises: 0002_identity_and_venues
Create Date: 2026-07-24

verified_until / grace_until drive the verified → degraded → exited lifecycle.
lease_expires_at mirrors grace_until for architecture compatibility.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_presence_and_leases"
down_revision: str | None = "0002_identity_and_venues"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.check_ins (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            venue_id UUID NOT NULL REFERENCES app.venues(id) ON DELETE CASCADE,
            state TEXT NOT NULL
                CHECK (state IN ('provisional', 'verified', 'degraded', 'exited', 'revoked')),
            verification_level TEXT NOT NULL
                CHECK (verification_level IN ('weak', 'standard')),
            confidence_score SMALLINT NOT NULL CHECK (confidence_score BETWEEN 0 AND 100),
            entry_method TEXT NOT NULL
                CHECK (entry_method IN (
                    'fused_location', 'wifi', 'ble', 'qr', 'hybrid', 'manual'
                )),
            ghost_mode_snapshot BOOLEAN NOT NULL,
            discoverable_snapshot BOOLEAN NOT NULL,
            entered_at TIMESTAMPTZ NOT NULL,
            verified_at TIMESTAMPTZ,
            last_verified_at TIMESTAMPTZ,
            verified_until TIMESTAMPTZ,
            grace_until TIMESTAMPTZ,
            lease_expires_at TIMESTAMPTZ NOT NULL,
            exited_at TIMESTAMPTZ,
            exit_reason TEXT,
            risk_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
            geofence_version INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_check_ins_one_active_per_user
            ON app.check_ins(user_id)
            WHERE state IN ('provisional', 'verified', 'degraded')
        """
    )
    op.execute(
        """
        CREATE INDEX ix_check_ins_venue_active
            ON app.check_ins(venue_id, lease_expires_at)
            WHERE state IN ('verified', 'degraded')
        """
    )
    op.execute(
        """
        CREATE INDEX ix_check_ins_user_recent
            ON app.check_ins(user_id, entered_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_check_ins_verified_until
            ON app.check_ins(verified_until)
            WHERE state = 'verified' AND verified_until IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_check_ins_grace_until
            ON app.check_ins(grace_until)
            WHERE state IN ('verified', 'degraded') AND grace_until IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE ephemeral.location_evidence (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            check_in_id UUID REFERENCES app.check_ins(id) ON DELETE SET NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            point GEOGRAPHY(POINT, 4326) NOT NULL,
            horizontal_accuracy_m REAL NOT NULL CHECK (horizontal_accuracy_m >= 0),
            speed_mps REAL,
            altitude_m REAL,
            source TEXT NOT NULL,
            is_mock BOOLEAN,
            is_simulated BOOLEAN,
            device_attestation_status TEXT,
            risk_score SMALLINT NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
            risk_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
            purge_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (id, purge_at)
        ) PARTITION BY RANGE (purge_at)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ephemeral.location_evidence_default
            PARTITION OF ephemeral.location_evidence DEFAULT
        """
    )
    op.execute(
        """
        CREATE INDEX ix_location_evidence_user_time
            ON ephemeral.location_evidence_default(user_id, observed_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_location_evidence_point_gist
            ON ephemeral.location_evidence_default USING GIST(point)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_location_evidence_purge
            ON ephemeral.location_evidence_default(purge_at)
        """
    )

    op.execute(
        """
        CREATE TABLE app.outbox_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            aggregate_type TEXT NOT NULL,
            aggregate_id UUID NOT NULL,
            event_type TEXT NOT NULL,
            event_version INTEGER NOT NULL DEFAULT 1,
            payload JSONB NOT NULL,
            trace_id TEXT,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_at TIMESTAMPTZ,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_outbox_unpublished
            ON app.outbox_events(available_at, occurred_at)
            WHERE published_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.outbox_events CASCADE")
    op.execute("DROP TABLE IF EXISTS ephemeral.location_evidence CASCADE")
    op.execute("DROP TABLE IF EXISTS app.check_ins CASCADE")
