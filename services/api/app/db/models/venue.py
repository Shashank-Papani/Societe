from __future__ import annotations

import uuid
from datetime import datetime, time

from geoalchemy2 import Geography, Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Venue(Base):
    __tablename__ = "venues"
    __table_args__ = (
        CheckConstraint("ST_IsValid(boundary)", name="ck_venues_boundary_valid"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    street_address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
    minimum_age: Mapped[int | None] = mapped_column(SmallInteger)
    price_band: Mapped[int | None] = mapped_column(SmallInteger)
    music_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    experience_tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    boundary = mapped_column(Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=False)
    centroid = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    entrance_point = mapped_column(Geography(geometry_type="POINT", srid=4326))
    geofence_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    max_gps_accuracy_m: Mapped[float] = mapped_column(nullable=False, server_default=text("50"))
    entry_dwell_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")
    exit_dwell_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    entry_buffer_m: Mapped[float] = mapped_column(nullable=False, server_default=text("10"))
    exit_buffer_m: Mapped[float] = mapped_column(nullable=False, server_default=text("25"))
    supports_qr_proof: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    supports_ble_proof: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    supports_wifi_proof: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    hours: Mapped[list[VenueHours]] = relationship(back_populates="venue", lazy="selectin")


class VenueHours(Base):
    """Opening intervals. weekday: Monday=0 … Sunday=6."""

    __tablename__ = "venue_hours"
    __table_args__ = (
        UniqueConstraint("venue_id", "weekday", "opens_local"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.venues.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    opens_local: Mapped[time] = mapped_column(Time, nullable=False)
    closes_local: Mapped[time] = mapped_column(Time, nullable=False)
    closes_next_day: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    venue: Mapped[Venue] = relationship(back_populates="hours")
