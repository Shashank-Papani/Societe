from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from redis.asyncio import Redis


class VenueStaticCache:
    def __init__(self, redis: Redis[str], *, ttl_seconds: int = 600) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    def _key(self, venue_id: UUID | str) -> str:
        return f"venue:static:v1:{venue_id}"

    async def get_many(self, venue_ids: list[UUID]) -> dict[str, dict[str, Any]]:
        if not venue_ids:
            return {}
        keys = [self._key(vid) for vid in venue_ids]
        values = await self._redis.mget(keys)
        out: dict[str, dict[str, Any]] = {}
        for venue_id, raw in zip(venue_ids, values, strict=True):
            if raw:
                out[str(venue_id)] = json.loads(raw)
        return out

    async def set_many(self, cards: dict[str, dict[str, Any]]) -> None:
        if not cards:
            return
        pipe = self._redis.pipeline()
        for venue_id, card in cards.items():
            pipe.set(self._key(venue_id), json.dumps(card), ex=self._ttl)
        await pipe.execute()

    async def invalidate_all_static(self) -> None:
        async for key in self._redis.scan_iter(match="venue:static:v1:*"):
            await self._redis.delete(key)
