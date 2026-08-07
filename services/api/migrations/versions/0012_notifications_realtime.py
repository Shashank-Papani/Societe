"""Notifications, preferences, push tokens, and delivery foundation.

Revision ID: 0012_notifications_realtime
Revises: 0011_stories_official_content
Create Date: 2026-07-30

Phase 9A: in-app notifications, preferences, device push-token columns,
push deliveries, and idempotent event-consumption tracking.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_notifications_realtime"
down_revision: str | None = "0011_stories_official_content"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.user_devices
            ADD COLUMN IF NOT EXISTS push_provider TEXT,
            ADD COLUMN IF NOT EXISTS push_token_hash TEXT,
            ADD COLUMN IF NOT EXISTS push_token_suffix TEXT,
            ADD COLUMN IF NOT EXISTS push_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS push_last_registered_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS push_last_success_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS push_invalidated_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS push_failure_count INTEGER NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE app.user_devices
            DROP CONSTRAINT IF EXISTS user_devices_push_provider_check
        """
    )
    op.execute(
        """
        ALTER TABLE app.user_devices
            ADD CONSTRAINT user_devices_push_provider_check
            CHECK (push_provider IS NULL OR push_provider IN ('expo'))
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS user_devices_active_push_token_hash_uq
            ON app.user_devices (push_token_hash)
            WHERE push_token_hash IS NOT NULL
              AND push_enabled = TRUE
              AND push_invalidated_at IS NULL
              AND revoked_at IS NULL
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.notifications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            recipient_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            notification_type TEXT NOT NULL,
            actor_user_id UUID REFERENCES app.users(id) ON DELETE SET NULL,
            venue_id UUID REFERENCES app.venues(id) ON DELETE SET NULL,
            conversation_id UUID REFERENCES app.conversations(id) ON DELETE SET NULL,
            calling_card_id UUID REFERENCES app.calling_cards(id) ON DELETE SET NULL,
            story_id UUID REFERENCES app.stories(id) ON DELETE SET NULL,
            organization_id UUID REFERENCES app.organizations(id) ON DELETE SET NULL,
            venue_claim_id UUID REFERENCES app.venue_claims(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            deep_link TEXT,
            grouping_key TEXT,
            dedupe_key TEXT NOT NULL,
            occurrence_count INTEGER NOT NULL DEFAULT 1
                CHECK (occurrence_count >= 1),
            priority TEXT NOT NULL DEFAULT 'normal'
                CHECK (priority IN ('normal', 'high')),
            read_at TIMESTAMPTZ,
            dismissed_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            latest_event_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT notifications_dedupe_key_uq UNIQUE (dedupe_key)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS notifications_recipient_latest_idx
            ON app.notifications (recipient_user_id, latest_event_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS notifications_recipient_unread_idx
            ON app.notifications (recipient_user_id, latest_event_at DESC)
            WHERE read_at IS NULL AND dismissed_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS notifications_grouping_active_idx
            ON app.notifications (recipient_user_id, grouping_key)
            WHERE dismissed_at IS NULL AND grouping_key IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.notification_preferences (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            category TEXT NOT NULL
                CHECK (category IN (
                    'messages', 'calling_cards', 'stories',
                    'venue_management', 'account'
                )),
            in_app_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            push_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT notification_preferences_user_category_uq
                UNIQUE (user_id, category)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.notification_deliveries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            notification_id UUID NOT NULL
                REFERENCES app.notifications(id) ON DELETE CASCADE,
            device_id UUID NOT NULL
                REFERENCES app.user_devices(id) ON DELETE CASCADE,
            channel TEXT NOT NULL DEFAULT 'push'
                CHECK (channel IN ('push')),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN (
                    'pending', 'sending', 'delivered',
                    'retryable', 'permanently_failed', 'cancelled'
                )),
            attempt_count INTEGER NOT NULL DEFAULT 0
                CHECK (attempt_count >= 0),
            next_attempt_at TIMESTAMPTZ,
            provider_message_id TEXT,
            delivered_at TIMESTAMPTZ,
            failed_at TIMESTAMPTZ,
            last_error_code TEXT,
            lease_owner TEXT,
            lease_expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT notification_deliveries_unique
                UNIQUE (notification_id, device_id, channel)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS notification_deliveries_claim_idx
            ON app.notification_deliveries (status, next_attempt_at, created_at)
            WHERE status IN ('pending', 'retryable')
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.notification_event_consumptions (
            event_id UUID PRIMARY KEY
                REFERENCES app.outbox_events(id) ON DELETE CASCADE,
            notification_id UUID
                REFERENCES app.notifications(id) ON DELETE SET NULL,
            consumed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.notification_event_consumptions")
    op.execute("DROP TABLE IF EXISTS app.notification_deliveries")
    op.execute("DROP TABLE IF EXISTS app.notification_preferences")
    op.execute("DROP TABLE IF EXISTS app.notifications")
    op.execute("DROP INDEX IF EXISTS app.user_devices_active_push_token_hash_uq")
    op.execute(
        """
        ALTER TABLE app.user_devices
            DROP CONSTRAINT IF EXISTS user_devices_push_provider_check
        """
    )
    op.execute(
        """
        ALTER TABLE app.user_devices
            DROP COLUMN IF EXISTS push_provider,
            DROP COLUMN IF EXISTS push_token_hash,
            DROP COLUMN IF EXISTS push_token_suffix,
            DROP COLUMN IF EXISTS push_enabled,
            DROP COLUMN IF EXISTS push_last_registered_at,
            DROP COLUMN IF EXISTS push_last_success_at,
            DROP COLUMN IF EXISTS push_invalidated_at,
            DROP COLUMN IF EXISTS push_failure_count
        """
    )
