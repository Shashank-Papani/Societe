"""Baseline identity, venue catalog, and venue hours for Phase 1.

Revision ID: 0002_identity_and_venues
Revises: 0001_baseline_schemas
Create Date: 2026-07-24

venue_hours.weekday convention: Monday = 0 … Sunday = 6.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_identity_and_venues"
down_revision: str | None = "0001_baseline_schemas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            auth_subject TEXT NOT NULL UNIQUE,
            handle TEXT NOT NULL,
            display_name TEXT NOT NULL,
            bio TEXT,
            age_verified BOOLEAN NOT NULL DEFAULT FALSE,
            age_band TEXT CHECK (age_band IN ('18-20', '21-24', '25-29', '30-34', '35+')),
            account_status TEXT NOT NULL DEFAULT 'active'
                CHECK (account_status IN (
                    'active', 'restricted', 'suspended', 'deletion_requested', 'deleted'
                )),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_users_handle_lower
            ON app.users (lower(handle))
            WHERE deleted_at IS NULL
        """
    )

    op.execute(
        """
        CREATE TABLE app.user_privacy_settings (
            user_id UUID PRIMARY KEY REFERENCES app.users(id) ON DELETE CASCADE,
            ghost_mode BOOLEAN NOT NULL DEFAULT FALSE,
            discoverable_in_venue BOOLEAN NOT NULL DEFAULT FALSE,
            allow_calling_cards BOOLEAN NOT NULL DEFAULT TRUE,
            show_social_links_after_accept BOOLEAN NOT NULL DEFAULT FALSE,
            analytics_opt_out BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE app.user_devices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            platform TEXT NOT NULL CHECK (platform IN ('ios', 'android')),
            installation_id UUID NOT NULL,
            app_version TEXT,
            os_version TEXT,
            attestation_key_id TEXT,
            attestation_status TEXT NOT NULL DEFAULT 'unknown'
                CHECK (attestation_status IN ('unknown', 'valid', 'degraded', 'invalid')),
            last_seen_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (platform, installation_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_user_devices_user
            ON app.user_devices (user_id)
            WHERE revoked_at IS NULL
        """
    )

    op.execute(
        """
        CREATE TABLE app.venues (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('draft', 'active', 'temporarily_closed', 'closed')),
            street_address TEXT,
            city TEXT NOT NULL,
            region TEXT,
            country_code CHAR(2) NOT NULL,
            timezone TEXT NOT NULL,
            minimum_age SMALLINT,
            price_band SMALLINT CHECK (price_band BETWEEN 1 AND 4),
            music_tags TEXT[] NOT NULL DEFAULT '{}',
            experience_tags TEXT[] NOT NULL DEFAULT '{}',
            boundary GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
            centroid GEOGRAPHY(POINT, 4326) NOT NULL,
            entrance_point GEOGRAPHY(POINT, 4326),
            geofence_version INTEGER NOT NULL DEFAULT 1,
            max_gps_accuracy_m REAL NOT NULL DEFAULT 50,
            entry_dwell_seconds INTEGER NOT NULL DEFAULT 10,
            exit_dwell_seconds INTEGER NOT NULL DEFAULT 30,
            entry_buffer_m REAL NOT NULL DEFAULT 10,
            exit_buffer_m REAL NOT NULL DEFAULT 25,
            supports_qr_proof BOOLEAN NOT NULL DEFAULT FALSE,
            supports_ble_proof BOOLEAN NOT NULL DEFAULT FALSE,
            supports_wifi_proof BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (ST_IsValid(boundary))
        )
        """
    )
    op.execute("CREATE INDEX ix_venues_boundary_gist ON app.venues USING GIST (boundary)")
    op.execute("CREATE INDEX ix_venues_centroid_gist ON app.venues USING GIST (centroid)")
    op.execute("CREATE INDEX ix_venues_city_status ON app.venues (city, status)")
    op.execute("CREATE INDEX ix_venues_status_category ON app.venues (status, category)")
    op.execute("CREATE INDEX ix_venues_music_tags_gin ON app.venues USING GIN (music_tags)")
    op.execute(
        "CREATE INDEX ix_venues_experience_tags_gin ON app.venues USING GIN (experience_tags)"
    )

    op.execute(
        """
        CREATE TABLE app.venue_hours (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            venue_id UUID NOT NULL REFERENCES app.venues(id) ON DELETE CASCADE,
            weekday SMALLINT NOT NULL CHECK (weekday BETWEEN 0 AND 6),
            opens_local TIME NOT NULL,
            closes_local TIME NOT NULL,
            closes_next_day BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (venue_id, weekday, opens_local)
        )
        """
    )
    op.execute("CREATE INDEX ix_venue_hours_venue ON app.venue_hours (venue_id)")

    op.execute(
        """
        COMMENT ON COLUMN app.venue_hours.weekday IS
        'Weekday with Monday = 0 and Sunday = 6'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.venue_hours CASCADE")
    op.execute("DROP TABLE IF EXISTS app.venues CASCADE")
    op.execute("DROP TABLE IF EXISTS app.user_devices CASCADE")
    op.execute("DROP TABLE IF EXISTS app.user_privacy_settings CASCADE")
    op.execute("DROP TABLE IF EXISTS app.users CASCADE")
