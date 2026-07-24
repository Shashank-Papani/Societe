from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "app"}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    auth_subject: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    handle: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    bio: Mapped[str | None] = mapped_column(Text)
    age_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    age_band: Mapped[str | None] = mapped_column(Text)
    account_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    privacy: Mapped[UserPrivacySettings | None] = relationship(
        back_populates="user", uselist=False, lazy="selectin"
    )
    devices: Mapped[list[UserDevice]] = relationship(back_populates="user")


class UserPrivacySettings(Base):
    __tablename__ = "user_privacy_settings"
    __table_args__ = {"schema": "app"}  # noqa: RUF012

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.users.id", ondelete="CASCADE"), primary_key=True
    )
    ghost_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    discoverable_in_venue: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    allow_calling_cards: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    show_social_links_after_accept: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    analytics_opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="privacy")


class UserDevice(Base):
    __tablename__ = "user_devices"
    __table_args__ = (
        UniqueConstraint("platform", "installation_id"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.users.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    app_version: Mapped[str | None] = mapped_column(Text)
    os_version: Mapped[str | None] = mapped_column(Text)
    attestation_key_id: Mapped[str | None] = mapped_column(Text)
    attestation_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="devices")
