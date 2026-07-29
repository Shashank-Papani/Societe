"""Venue organizations, ownership, claims, invitations, audit, cover.

Revision ID: 0010_venue_organizations
Revises: 0009_presence_retention
Create Date: 2026-07-28

Phase 7A foundation: organizations, staff memberships, venue ownership
linkage, claim workflow, invitations, append-only audit events, and an
explicit venue primary cover media association. Venue-owned media is
distinguished from user Live Vibes via media_assets.purpose.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_venue_organizations"
down_revision: str | None = "0009_presence_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.organizations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'suspended', 'deleted')),
            created_by_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_organizations_normalized_name_active
            ON app.organizations (normalized_name)
            WHERE status <> 'deleted' AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_organizations_created_by
            ON app.organizations (created_by_user_id)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.organization_members (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL
                REFERENCES app.organizations(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            role TEXT NOT NULL
                CHECK (role IN ('owner', 'manager', 'content_editor', 'analyst')),
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'removed')),
            invited_by_user_id UUID REFERENCES app.users(id) ON DELETE SET NULL,
            joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            removed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_organization_members_active
            ON app.organization_members (organization_id, user_id)
            WHERE status = 'active'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_organization_members_user
            ON app.organization_members (user_id)
            WHERE status = 'active'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_organization_members_org_role
            ON app.organization_members (organization_id, role)
            WHERE status = 'active'
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.venue_claims (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            venue_id UUID NOT NULL REFERENCES app.venues(id) ON DELETE CASCADE,
            claimant_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            claimant_organization_id UUID
                REFERENCES app.organizations(id) ON DELETE SET NULL,
            requested_organization_name TEXT,
            business_email TEXT,
            evidence_reference TEXT,
            justification TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN (
                    'pending', 'under_review', 'approved', 'rejected', 'cancelled'
                )),
            reviewed_by_user_id UUID REFERENCES app.users(id) ON DELETE SET NULL,
            reviewed_at TIMESTAMPTZ,
            rejection_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_venue_claims_active_claimant
            ON app.venue_claims (venue_id, claimant_user_id)
            WHERE status IN ('pending', 'under_review')
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_venue_claims_claimant
            ON app.venue_claims (claimant_user_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_venue_claims_status
            ON app.venue_claims (status, created_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.venue_organizations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            venue_id UUID NOT NULL REFERENCES app.venues(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL
                REFERENCES app.organizations(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'unlinked')),
            approved_claim_id UUID REFERENCES app.venue_claims(id) ON DELETE SET NULL,
            linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            unlinked_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_venue_organizations_active_venue
            ON app.venue_organizations (venue_id)
            WHERE status = 'active'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_venue_organizations_org
            ON app.venue_organizations (organization_id)
            WHERE status = 'active'
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.organization_invitations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL
                REFERENCES app.organizations(id) ON DELETE CASCADE,
            email_normalized TEXT NOT NULL,
            role TEXT NOT NULL
                CHECK (role IN ('owner', 'manager', 'content_editor', 'analyst')),
            token_hash TEXT NOT NULL,
            invited_by_user_id UUID NOT NULL
                REFERENCES app.users(id) ON DELETE RESTRICT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'accepted', 'expired', 'revoked')),
            expires_at TIMESTAMPTZ NOT NULL,
            accepted_by_user_id UUID REFERENCES app.users(id) ON DELETE SET NULL,
            accepted_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_organization_invitations_token_hash
            ON app.organization_invitations (token_hash)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_organization_invitations_pending_email
            ON app.organization_invitations (organization_id, email_normalized)
            WHERE status = 'pending'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_organization_invitations_org
            ON app.organization_invitations (organization_id, created_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.venue_audit_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID REFERENCES app.organizations(id) ON DELETE SET NULL,
            venue_id UUID REFERENCES app.venues(id) ON DELETE SET NULL,
            actor_user_id UUID REFERENCES app.users(id) ON DELETE SET NULL,
            event_type TEXT NOT NULL,
            target_type TEXT,
            target_id UUID,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_venue_audit_events_org
            ON app.venue_audit_events (organization_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_venue_audit_events_venue
            ON app.venue_audit_events (venue_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_venue_audit_events_type
            ON app.venue_audit_events (event_type, created_at DESC)
        """
    )

    # Venue-owned media vs user Live Vibes.
    op.execute(
        """
        ALTER TABLE app.media_assets
            ADD COLUMN IF NOT EXISTS purpose TEXT NOT NULL DEFAULT 'live_vibe',
            ADD COLUMN IF NOT EXISTS organization_id UUID
                REFERENCES app.organizations(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE app.media_assets
            ALTER COLUMN author_check_in_id DROP NOT NULL,
            ALTER COLUMN device_id DROP NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE app.media_assets
            DROP CONSTRAINT IF EXISTS media_assets_purpose_check
        """
    )
    op.execute(
        """
        ALTER TABLE app.media_assets
            ADD CONSTRAINT media_assets_purpose_check
            CHECK (purpose IN ('live_vibe', 'venue_owned'))
        """
    )
    op.execute(
        """
        ALTER TABLE app.media_assets
            DROP CONSTRAINT IF EXISTS media_assets_purpose_shape_check
        """
    )
    op.execute(
        """
        ALTER TABLE app.media_assets
            ADD CONSTRAINT media_assets_purpose_shape_check
            CHECK (
                (
                    purpose = 'live_vibe'
                    AND author_check_in_id IS NOT NULL
                    AND device_id IS NOT NULL
                )
                OR (
                    purpose = 'venue_owned'
                    AND organization_id IS NOT NULL
                    AND author_check_in_id IS NULL
                    AND device_id IS NULL
                )
            )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_media_assets_venue_owned
            ON app.media_assets (venue_id, organization_id)
            WHERE purpose = 'venue_owned' AND deleted_at IS NULL
        """
    )

    op.execute(
        """
        ALTER TABLE app.venues
            ADD COLUMN IF NOT EXISTS primary_cover_media_id UUID
                REFERENCES app.media_assets(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_venues_primary_cover
            ON app.venues (primary_cover_media_id)
            WHERE primary_cover_media_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.ix_venues_primary_cover")
    op.execute(
        """
        ALTER TABLE app.venues
            DROP COLUMN IF EXISTS primary_cover_media_id
        """
    )

    op.execute("DROP INDEX IF EXISTS app.ix_media_assets_venue_owned")
    op.execute(
        """
        ALTER TABLE app.media_assets
            DROP CONSTRAINT IF EXISTS media_assets_purpose_shape_check
        """
    )
    op.execute(
        """
        ALTER TABLE app.media_assets
            DROP CONSTRAINT IF EXISTS media_assets_purpose_check
        """
    )
    # Restore NOT NULL only for live_vibe rows; venue_owned must be removed first.
    op.execute("DELETE FROM app.media_assets WHERE purpose = 'venue_owned'")
    op.execute(
        """
        ALTER TABLE app.media_assets
            DROP COLUMN IF EXISTS organization_id,
            DROP COLUMN IF EXISTS purpose
        """
    )
    op.execute(
        """
        UPDATE app.media_assets
        SET author_check_in_id = author_check_in_id
        WHERE author_check_in_id IS NOT NULL
        """
    )
    # Re-apply NOT NULL after venue_owned rows are gone.
    op.execute(
        """
        ALTER TABLE app.media_assets
            ALTER COLUMN author_check_in_id SET NOT NULL,
            ALTER COLUMN device_id SET NOT NULL
        """
    )

    op.execute("DROP INDEX IF EXISTS app.ix_venue_audit_events_type")
    op.execute("DROP INDEX IF EXISTS app.ix_venue_audit_events_venue")
    op.execute("DROP INDEX IF EXISTS app.ix_venue_audit_events_org")
    op.execute("DROP TABLE IF EXISTS app.venue_audit_events")

    op.execute("DROP INDEX IF EXISTS app.ix_organization_invitations_org")
    op.execute("DROP INDEX IF EXISTS app.uq_organization_invitations_pending_email")
    op.execute("DROP INDEX IF EXISTS app.uq_organization_invitations_token_hash")
    op.execute("DROP TABLE IF EXISTS app.organization_invitations")

    op.execute("DROP INDEX IF EXISTS app.ix_venue_organizations_org")
    op.execute("DROP INDEX IF EXISTS app.uq_venue_organizations_active_venue")
    op.execute("DROP TABLE IF EXISTS app.venue_organizations")

    op.execute("DROP INDEX IF EXISTS app.ix_venue_claims_status")
    op.execute("DROP INDEX IF EXISTS app.ix_venue_claims_claimant")
    op.execute("DROP INDEX IF EXISTS app.uq_venue_claims_active_claimant")
    op.execute("DROP TABLE IF EXISTS app.venue_claims")

    op.execute("DROP INDEX IF EXISTS app.ix_organization_members_org_role")
    op.execute("DROP INDEX IF EXISTS app.ix_organization_members_user")
    op.execute("DROP INDEX IF EXISTS app.uq_organization_members_active")
    op.execute("DROP TABLE IF EXISTS app.organization_members")

    op.execute("DROP INDEX IF EXISTS app.ix_organizations_created_by")
    op.execute("DROP INDEX IF EXISTS app.uq_organizations_normalized_name_active")
    op.execute("DROP TABLE IF EXISTS app.organizations")
