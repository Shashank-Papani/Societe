"""Auth, onboarding, profiles, sessions, and policy history.

Revision ID: 0007_auth_onboarding_profiles
Revises: 0006_private_messaging
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_auth_onboarding_profiles"
down_revision: str | None = "0006_private_messaging"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.users
            ADD COLUMN IF NOT EXISTS date_of_birth DATE,
            ADD COLUMN IF NOT EXISTS onboarding_state TEXT NOT NULL DEFAULT 'completed',
            ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS profile_photo_media_id UUID,
            ADD COLUMN IF NOT EXISTS handle_locked_at TIMESTAMPTZ
        """
    )
    op.execute(
        """
        ALTER TABLE app.users DROP CONSTRAINT IF EXISTS users_account_status_check
        """
    )
    op.execute(
        """
        ALTER TABLE app.users
            ADD CONSTRAINT users_account_status_check
            CHECK (account_status IN (
                'active', 'restricted', 'suspended', 'deactivated',
                'deletion_requested', 'deleted'
            ))
        """
    )
    op.execute(
        """
        ALTER TABLE app.users DROP CONSTRAINT IF EXISTS users_onboarding_state_check
        """
    )
    op.execute(
        """
        ALTER TABLE app.users
            ADD CONSTRAINT users_onboarding_state_check
            CHECK (onboarding_state IN (
                'authentication_verified',
                'profile_required',
                'age_required',
                'age_ineligible',
                'policy_acceptance_required',
                'privacy_required',
                'completed'
            ))
        """
    )

    # Existing rows (including Dev Alpha/Beta) keep working social behavior.
    op.execute(
        """
        UPDATE app.users
        SET onboarding_state = 'completed',
            onboarding_completed_at = COALESCE(onboarding_completed_at, NOW()),
            handle_locked_at = COALESCE(handle_locked_at, NOW()),
            age_verified = TRUE
        WHERE deleted_at IS NULL
        """
    )

    op.execute(
        """
        ALTER TABLE app.user_privacy_settings
            ADD COLUMN IF NOT EXISTS allow_messages_from_connections BOOLEAN
                NOT NULL DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS notify_calling_cards BOOLEAN
                NOT NULL DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS notify_messages BOOLEAN
                NOT NULL DEFAULT TRUE
        """
    )
    # Existing users retain messaging-capable privacy; new OTP users override
    # in application code with conservative defaults at insert time.
    op.execute(
        """
        UPDATE app.user_privacy_settings
        SET allow_messages_from_connections = TRUE
        """
    )
    # Tighten column defaults for future inserts (new OTP users).
    op.execute(
        """
        ALTER TABLE app.user_privacy_settings
            ALTER COLUMN allow_calling_cards SET DEFAULT FALSE,
            ALTER COLUMN allow_messages_from_connections SET DEFAULT FALSE,
            ALTER COLUMN discoverable_in_venue SET DEFAULT FALSE,
            ALTER COLUMN show_social_links_after_accept SET DEFAULT FALSE
        """
    )

    op.execute(
        """
        CREATE TABLE app.auth_identities (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            normalized_email TEXT NOT NULL,
            verified_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT auth_identities_provider_check
                CHECK (provider IN ('email')),
            CONSTRAINT auth_identities_provider_email_unique
                UNIQUE (provider, normalized_email)
        )
        """
    )
    op.execute("CREATE INDEX auth_identities_user_id_idx ON app.auth_identities (user_id)")

    op.execute(
        """
        CREATE TABLE app.otp_challenges (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            normalized_email TEXT NOT NULL,
            code_hash TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT 'login',
            expires_at TIMESTAMPTZ NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 5,
            consumed_at TIMESTAMPTZ,
            created_ip_hash TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT otp_challenges_purpose_check
                CHECK (purpose IN ('login', 'reactivation'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX otp_challenges_email_active_idx
            ON app.otp_challenges (normalized_email, created_at DESC)
            WHERE consumed_at IS NULL
        """
    )

    op.execute(
        """
        CREATE TABLE app.auth_refresh_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            device_id UUID NOT NULL REFERENCES app.user_devices(id) ON DELETE CASCADE,
            family_id UUID NOT NULL,
            token_hash TEXT NOT NULL,
            previous_token_hash TEXT,
            expires_at TIMESTAMPTZ NOT NULL,
            rotated_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            revoke_reason TEXT,
            last_used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT auth_refresh_sessions_token_hash_unique UNIQUE (token_hash)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX auth_refresh_sessions_user_id_idx
            ON app.auth_refresh_sessions (user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX auth_refresh_sessions_family_id_idx
            ON app.auth_refresh_sessions (family_id)
        """
    )
    op.execute(
        """
        CREATE INDEX auth_refresh_sessions_previous_hash_idx
            ON app.auth_refresh_sessions (previous_token_hash)
            WHERE previous_token_hash IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE app.user_policy_acceptances (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            policy_type TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            accepted_ip_hash TEXT,
            accepted_user_agent_hash TEXT,
            CONSTRAINT user_policy_acceptances_type_check
                CHECK (policy_type IN ('terms_of_service', 'privacy_policy')),
            CONSTRAINT user_policy_acceptances_unique
                UNIQUE (user_id, policy_type, policy_version)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE app.user_interests (
            user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            tag TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, tag)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE app.profile_media_assets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            device_id UUID NOT NULL REFERENCES app.user_devices(id) ON DELETE RESTRICT,
            lifecycle_status TEXT NOT NULL DEFAULT 'intent_pending',
            moderation_status TEXT NOT NULL DEFAULT 'pending',
            quarantine_object_key TEXT NOT NULL,
            processed_object_key TEXT,
            declared_mime_type TEXT NOT NULL,
            declared_byte_size BIGINT NOT NULL,
            detected_mime_type TEXT,
            byte_size BIGINT,
            width INTEGER,
            height INTEGER,
            checksum_sha256 TEXT,
            intent_expires_at TIMESTAMPTZ NOT NULL,
            intent_consumed_at TIMESTAMPTZ,
            moderation_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            uploaded_at TIMESTAMPTZ,
            processed_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            deleted_reason TEXT
        )
        """
    )
    op.execute(
        """
        ALTER TABLE app.users
            ADD CONSTRAINT users_profile_photo_media_id_fkey
            FOREIGN KEY (profile_photo_media_id)
            REFERENCES app.profile_media_assets(id)
            ON DELETE SET NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app.users DROP CONSTRAINT IF EXISTS users_profile_photo_media_id_fkey")
    op.execute("DROP TABLE IF EXISTS app.profile_media_assets")
    op.execute("DROP TABLE IF EXISTS app.user_interests")
    op.execute("DROP TABLE IF EXISTS app.user_policy_acceptances")
    op.execute("DROP TABLE IF EXISTS app.auth_refresh_sessions")
    op.execute("DROP TABLE IF EXISTS app.otp_challenges")
    op.execute("DROP TABLE IF EXISTS app.auth_identities")
    op.execute(
        """
        ALTER TABLE app.user_privacy_settings
            DROP COLUMN IF EXISTS allow_messages_from_connections,
            DROP COLUMN IF EXISTS notify_calling_cards,
            DROP COLUMN IF EXISTS notify_messages
        """
    )
    op.execute(
        """
        ALTER TABLE app.user_privacy_settings
            ALTER COLUMN allow_calling_cards SET DEFAULT TRUE
        """
    )
    op.execute(
        """
        ALTER TABLE app.users
            DROP COLUMN IF EXISTS date_of_birth,
            DROP COLUMN IF EXISTS onboarding_state,
            DROP COLUMN IF EXISTS onboarding_completed_at,
            DROP COLUMN IF EXISTS deactivated_at,
            DROP COLUMN IF EXISTS profile_photo_media_id,
            DROP COLUMN IF EXISTS handle_locked_at
        """
    )
