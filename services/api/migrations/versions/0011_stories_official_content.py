"""Stories, story views/reports, and official venue posts.

Revision ID: 0011_stories_official_content
Revises: 0010_venue_organizations
Create Date: 2026-07-29

Phase 8A: user Stories, official venue Stories, story viewing/reporting,
and persistent official venue posts. Extends media_assets.purpose with
user_story while preserving existing live_vibe and venue_owned rows.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_stories_official_content"
down_revision: str | None = "0010_venue_organizations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- media purpose: add user_story ---------------------------------
    op.execute(
        """
        ALTER TABLE app.media_assets
            DROP CONSTRAINT IF EXISTS media_assets_purpose_check
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
            ADD CONSTRAINT media_assets_purpose_check
            CHECK (purpose IN ('live_vibe', 'user_story', 'venue_owned'))
        """
    )
    op.execute(
        """
        ALTER TABLE app.media_assets
            ADD CONSTRAINT media_assets_purpose_shape_check
            CHECK (
                (
                    purpose IN ('live_vibe', 'user_story')
                    AND author_check_in_id IS NOT NULL
                    AND device_id IS NOT NULL
                    AND organization_id IS NULL
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

    # ---- stories -------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.stories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            venue_id UUID NOT NULL REFERENCES app.venues(id) ON DELETE CASCADE,
            media_asset_id UUID NOT NULL UNIQUE
                REFERENCES app.media_assets(id) ON DELETE CASCADE,
            author_type TEXT NOT NULL
                CHECK (author_type IN ('user', 'venue')),
            author_user_id UUID REFERENCES app.users(id) ON DELETE SET NULL,
            organization_id UUID REFERENCES app.organizations(id) ON DELETE SET NULL,
            created_by_user_id UUID REFERENCES app.users(id) ON DELETE SET NULL,
            attribution_mode TEXT NOT NULL
                CHECK (attribution_mode IN ('attributed', 'anonymous', 'official')),
            caption TEXT,
            vibe_tags TEXT[] NOT NULL DEFAULT '{}',
            reply_policy TEXT NOT NULL DEFAULT 'disabled'
                CHECK (reply_policy IN ('disabled', 'connections', 'everyone')),
            publication_status TEXT NOT NULL DEFAULT 'draft'
                CHECK (publication_status IN (
                    'draft', 'uploaded', 'processing', 'moderation_pending',
                    'published', 'expired', 'hidden', 'rejected', 'failed', 'deleted'
                )),
            moderation_status TEXT NOT NULL DEFAULT 'pending',
            published_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT stories_author_shape_check CHECK (
                (
                    author_type = 'user'
                    AND author_user_id IS NOT NULL
                    AND organization_id IS NULL
                    AND attribution_mode IN ('attributed', 'anonymous')
                )
                OR (
                    author_type = 'venue'
                    AND organization_id IS NOT NULL
                    AND created_by_user_id IS NOT NULL
                    AND author_user_id IS NULL
                    AND attribution_mode = 'official'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_stories_venue_active
            ON app.stories (venue_id, published_at DESC)
            WHERE publication_status = 'published' AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_stories_author_user_active
            ON app.stories (author_user_id, published_at DESC)
            WHERE author_type = 'user'
              AND publication_status = 'published'
              AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_stories_expires_at
            ON app.stories (expires_at)
            WHERE publication_status = 'published' AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_stories_org
            ON app.stories (organization_id, published_at DESC)
            WHERE author_type = 'venue'
        """
    )

    # ---- story views ---------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.story_views (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            story_id UUID NOT NULL REFERENCES app.stories(id) ON DELETE CASCADE,
            viewer_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            viewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (story_id, viewer_user_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_story_views_viewer
            ON app.story_views (viewer_user_id, viewed_at DESC)
        """
    )

    # ---- story reports -------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.story_reports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            story_id UUID NOT NULL REFERENCES app.stories(id) ON DELETE CASCADE,
            reporter_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            reason TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'reviewing', 'resolved', 'dismissed')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_story_reports_active
            ON app.story_reports (reporter_user_id, story_id)
            WHERE status IN ('open', 'reviewing')
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_story_reports_story
            ON app.story_reports (story_id, created_at DESC)
        """
    )

    # ---- official venue posts ------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.official_venue_posts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            venue_id UUID NOT NULL REFERENCES app.venues(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL
                REFERENCES app.organizations(id) ON DELETE CASCADE,
            created_by_user_id UUID NOT NULL
                REFERENCES app.users(id) ON DELETE RESTRICT,
            media_asset_id UUID UNIQUE
                REFERENCES app.media_assets(id) ON DELETE SET NULL,
            post_type TEXT NOT NULL
                CHECK (post_type IN (
                    'announcement', 'event', 'dj', 'special',
                    'policy', 'promotion', 'general'
                )),
            title TEXT,
            body TEXT NOT NULL,
            call_to_action_type TEXT,
            call_to_action_url TEXT,
            publication_status TEXT NOT NULL DEFAULT 'draft'
                CHECK (publication_status IN (
                    'draft', 'processing', 'moderation_pending',
                    'published', 'archived', 'rejected', 'failed', 'deleted'
                )),
            moderation_status TEXT NOT NULL DEFAULT 'pending',
            published_at TIMESTAMPTZ,
            archived_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_official_venue_posts_venue_published
            ON app.official_venue_posts (venue_id, published_at DESC)
            WHERE publication_status = 'published' AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_official_venue_posts_org
            ON app.official_venue_posts (organization_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.ix_official_venue_posts_org")
    op.execute("DROP INDEX IF EXISTS app.ix_official_venue_posts_venue_published")
    op.execute("DROP TABLE IF EXISTS app.official_venue_posts")

    op.execute("DROP INDEX IF EXISTS app.ix_story_reports_story")
    op.execute("DROP INDEX IF EXISTS app.uq_story_reports_active")
    op.execute("DROP TABLE IF EXISTS app.story_reports")

    op.execute("DROP INDEX IF EXISTS app.ix_story_views_viewer")
    op.execute("DROP TABLE IF EXISTS app.story_views")

    op.execute("DROP INDEX IF EXISTS app.ix_stories_org")
    op.execute("DROP INDEX IF EXISTS app.ix_stories_expires_at")
    op.execute("DROP INDEX IF EXISTS app.ix_stories_author_user_active")
    op.execute("DROP INDEX IF EXISTS app.ix_stories_venue_active")
    op.execute("DROP TABLE IF EXISTS app.stories")

    # Restore prior purpose constraint (user_story rows must be gone first).
    op.execute("DELETE FROM app.media_assets WHERE purpose = 'user_story'")
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
