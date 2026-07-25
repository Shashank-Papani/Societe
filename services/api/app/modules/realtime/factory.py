from __future__ import annotations

from app.core.config import Settings
from app.db.session import get_redis
from app.modules.realtime.appsync import AppSyncRealtimePublisher
from app.modules.realtime.local import LocalPushPublisher, LocalRealtimeHub, NoopPushPublisher
from app.modules.realtime.protocols import PushPublisher, RealtimePublisher

# Process-wide hubs so the dispatcher and tests share one sink in local mode.
_LOCAL_HUB = LocalRealtimeHub()
_LOCAL_PUSH = LocalPushPublisher()


def build_realtime_publisher(settings: Settings) -> RealtimePublisher:
    if settings.realtime_provider == "appsync":
        return AppSyncRealtimePublisher(settings)
    _LOCAL_HUB.bind_redis(get_redis(settings))
    return _LOCAL_HUB


def build_push_publisher(settings: Settings) -> PushPublisher:
    if settings.push_provider == "noop":
        return NoopPushPublisher()
    return _LOCAL_PUSH


def reset_local_publishers() -> None:
    """Test helper: clear recorded local publishes."""
    _LOCAL_HUB.clear()
    _LOCAL_PUSH.clear()
