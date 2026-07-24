from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

VenueCategory = Literal[
    "nightclub",
    "bar",
    "lounge",
    "rooftop",
    "live_music",
    "warehouse",
]

MUSIC_TAG_ALLOWLIST = frozenset(
    {
        "house",
        "techno",
        "hiphop",
        "latin",
        "pop",
        "rnb",
        "indie",
        "open_format",
    }
)
EXPERIENCE_TAG_ALLOWLIST = frozenset(
    {
        "dance",
        "social",
        "watching",
        "relaxing",
        "live_set",
        "rooftop_view",
    }
)


class MapVenuesQuery(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_m: int = Field(default=3000, ge=50, le=25_000)
    music_tags: list[str] = Field(default_factory=list)
    experience_tags: list[str] = Field(default_factory=list)
    price_bands: list[int] = Field(default_factory=list)
    categories: list[VenueCategory] = Field(default_factory=list)
    minimum_age: int | None = Field(default=None, ge=18, le=25)
    age_bands: list[str] | None = None
    crowd_buckets: list[str] | None = None
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("music_tags", "experience_tags", mode="before")
    @classmethod
    def split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [part for part in value.split(",") if part]
        return value

    @field_validator("price_bands", mode="before")
    @classmethod
    def split_price(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.split(",") if part]
        return value

    @field_validator("categories", mode="before")
    @classmethod
    def split_categories(cls, value: object) -> object:
        if isinstance(value, str):
            return [part for part in value.split(",") if part]
        return value

    @field_validator("music_tags")
    @classmethod
    def validate_music(cls, value: list[str]) -> list[str]:
        music = sorted({tag.lower() for tag in value})
        if any(tag not in MUSIC_TAG_ALLOWLIST for tag in music):
            raise ValueError("Unknown music_tags value.")
        return music

    @field_validator("experience_tags")
    @classmethod
    def validate_experience(cls, value: list[str]) -> list[str]:
        experience = sorted({tag.lower() for tag in value})
        if any(tag not in EXPERIENCE_TAG_ALLOWLIST for tag in experience):
            raise ValueError("Unknown experience_tags value.")
        return experience

    @field_validator("price_bands")
    @classmethod
    def validate_price(cls, value: list[int]) -> list[int]:
        bands = sorted(set(value))
        if any(band < 1 or band > 4 for band in bands):
            raise ValueError("price_bands must be 1-4.")
        return bands

    def filters_for_fingerprint(self) -> dict[str, object]:
        return {
            "music_tags": self.music_tags,
            "experience_tags": self.experience_tags,
            "price_bands": self.price_bands,
            "categories": sorted(self.categories),
            "minimum_age": self.minimum_age,
        }
