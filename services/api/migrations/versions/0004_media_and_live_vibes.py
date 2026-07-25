"""Media assets, Live Vibes, derivatives, jobs, reports, moderation for Phase 3.

Revision ID: 0004_media_and_live_vibes
Revises: 0003_presence_and_leases
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_media_and_live_vibes"
down_revision: str | None = "0003_presence_and_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.media_assets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            venue_id UUID NOT NULL REFERENCES app.venues(id) ON DELETE CASCADE,
            author_check_in_id UUID NOT NULL REFERENCES app.check_ins(id) ON DELETE RESTRICT,
            device_id UUID NOT NULL REFERENCES app.user_devices(id) ON DELETE RESTRICT,
            media_type TEXT NOT NULL CHECK (media_type IN ('image', 'video')),
            lifecycle_status TEXT NOT NULL DEFAULT 'intent_pending'
                CHECK (lifecycle_status IN (
                    'intent_pending', 'uploaded', 'validating', 'processing',
                    'moderation_pending', 'ready', 'upload_expired', 'invalid',
                    'processing_failed', 'rejected', 'manual_review', 'deleted', 'revoked'
                )),
            moderation_status TEXT NOT NULL DEFAULT 'pending'
                CHECK (moderation_status IN (
                    'pending', 'approved', 'rejected', 'manual_review', 'quarantined'
                )),
            attribution_mode TEXT NOT NULL CHECK (attribution_mode IN ('attributed', 'anonymous')),
            quarantine_object_key TEXT NOT NULL,
            declared_mime_type TEXT NOT NULL,
            declared_byte_size BIGINT NOT NULL CHECK (declared_byte_size > 0),
            detected_mime_type TEXT,
            byte_size BIGINT,
            width INTEGER,
            height INTEGER,
            duration_ms INTEGER,
            checksum_sha256 TEXT,
            original_filename TEXT,
            caption TEXT,
            vibe_tags TEXT[] NOT NULL DEFAULT '{}',
            intent_expires_at TIMESTAMPTZ NOT NULL,
            intent_consumed_at TIMESTAMPTZ,
            generation INTEGER NOT NULL DEFAULT 1,
            moderation_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            uploaded_at TIMESTAMPTZ,
            processed_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            deleted_reason TEXT
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_media_assets_owner_created
            ON app.media_assets(owner_user_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_media_assets_lifecycle
            ON app.media_assets(lifecycle_status, intent_expires_at)
        """
    )

    op.execute(
        """
        CREATE TABLE app.live_vibes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            venue_id UUID NOT NULL REFERENCES app.venues(id) ON DELETE CASCADE,
            author_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            media_asset_id UUID NOT NULL UNIQUE REFERENCES app.media_assets(id) ON DELETE CASCADE,
            author_check_in_id UUID NOT NULL REFERENCES app.check_ins(id) ON DELETE RESTRICT,
            caption TEXT,
            vibe_tags TEXT[] NOT NULL DEFAULT '{}',
            attribution_mode TEXT NOT NULL CHECK (attribution_mode IN ('attributed', 'anonymous')),
            publication_status TEXT NOT NULL DEFAULT 'draft'
                CHECK (publication_status IN (
                    'draft', 'processing', 'published', 'expired',
                    'hidden', 'removed', 'rejected', 'deleted', 'revoked'
                )),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            hidden_at TIMESTAMPTZ,
            hidden_reason TEXT
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_live_vibes_venue_feed
            ON app.live_vibes(venue_id, published_at DESC, id DESC)
            WHERE publication_status = 'published'
        """
    )
    op.execute(
        """
        CREATE INDEX ix_live_vibes_expiration
            ON app.live_vibes(expires_at)
            WHERE publication_status IN ('processing', 'published')
        """
    )
    op.execute(
        """
        CREATE INDEX ix_live_vibes_author
            ON app.live_vibes(author_user_id, created_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE app.media_derivatives (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            media_asset_id UUID NOT NULL REFERENCES app.media_assets(id) ON DELETE CASCADE,
            variant_type TEXT NOT NULL,
            storage_provider TEXT NOT NULL DEFAULT 'minio',
            object_key TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            byte_size BIGINT NOT NULL,
            width INTEGER,
            height INTEGER,
            duration_ms INTEGER,
            codec TEXT,
            checksum_sha256 TEXT NOT NULL,
            generation INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'ready'
                CHECK (status IN ('ready', 'failed', 'deleted')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (media_asset_id, variant_type, generation)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_media_derivatives_asset
            ON app.media_derivatives(media_asset_id)
        """
    )

    op.execute(
        """
        CREATE TABLE app.media_processing_jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            media_asset_id UUID NOT NULL REFERENCES app.media_assets(id) ON DELETE CASCADE,
            job_type TEXT NOT NULL
                CHECK (job_type IN ('validate_process', 'moderate', 'expire_cleanup')),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN (
                    'pending', 'leased', 'succeeded', 'failed', 'dead_letter'
                )),
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            leased_at TIMESTAMPTZ,
            lease_owner TEXT,
            last_error_category TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_media_jobs_claim
            ON app.media_processing_jobs(status, next_attempt_at, job_type)
            WHERE status IN ('pending', 'leased')
        """
    )

    op.execute(
        """
        CREATE TABLE app.moderation_cases (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            media_asset_id UUID REFERENCES app.media_assets(id) ON DELETE CASCADE,
            subject_user_id UUID REFERENCES app.users(id) ON DELETE CASCADE,
            status TEXT NOT NULL
                CHECK (status IN (
                    'open', 'auto_approved', 'auto_rejected',
                    'needs_review', 'resolved', 'appealed'
                )),
            policy_version TEXT NOT NULL,
            final_action TEXT,
            reviewer_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.moderation_signals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            moderation_case_id UUID NOT NULL
                REFERENCES app.moderation_cases(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            model_version TEXT,
            category TEXT NOT NULL,
            confidence NUMERIC(5,2),
            raw_reference TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE app.content_reports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            reporter_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            live_vibe_id UUID NOT NULL REFERENCES app.live_vibes(id) ON DELETE CASCADE,
            reason TEXT NOT NULL CHECK (reason IN (
                'spam', 'harassment', 'sexual_content', 'violence',
                'hate', 'illegal', 'other'
            )),
            description TEXT,
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'triaged', 'resolved', 'dismissed')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at TIMESTAMPTZ,
            UNIQUE (reporter_user_id, live_vibe_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_content_reports_vibe
            ON app.content_reports(live_vibe_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.content_reports CASCADE")
    op.execute("DROP TABLE IF EXISTS app.moderation_signals CASCADE")
    op.execute("DROP TABLE IF EXISTS app.moderation_cases CASCADE")
    op.execute("DROP TABLE IF EXISTS app.media_processing_jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS app.media_derivatives CASCADE")
    op.execute("DROP TABLE IF EXISTS app.live_vibes CASCADE")
    op.execute("DROP TABLE IF EXISTS app.media_assets CASCADE")
