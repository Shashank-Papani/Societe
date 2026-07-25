from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class FeatureFlags:
    live_crowd_counts: bool
    calling_cards: bool
    venue_people_discovery: bool
    private_messaging: bool
    qr_verification: bool
    ble_verification: bool
    media_posting: bool
    automated_moderation: bool
    ghost_mode: bool


def load_feature_flags(settings: Settings) -> FeatureFlags:
    return FeatureFlags(
        live_crowd_counts=settings.ff_live_crowd_counts,
        calling_cards=settings.ff_calling_cards,
        venue_people_discovery=settings.ff_venue_people_discovery,
        private_messaging=settings.ff_private_messaging,
        qr_verification=settings.ff_qr_verification,
        ble_verification=settings.ff_ble_verification,
        media_posting=settings.ff_media_posting,
        automated_moderation=settings.ff_automated_moderation,
        ghost_mode=settings.ff_ghost_mode,
    )
