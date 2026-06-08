import json
from typing import Any

from app.core.config import settings

_redis_client: Any = None

CACHE_TTL_SECONDS = 1200  # 20 minutes


async def _get_client() -> Any:
    global _redis_client
    if _redis_client is None and settings.redis_url:
        try:
            import redis.asyncio as aioredis
            _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        except Exception:
            _redis_client = None
    return _redis_client


def _cache_key(lat: float, lng: float, venue_types: list[str], radius_m: int) -> str:
    lat_r = round(lat, 3)
    lng_r = round(lng, 3)
    types_str = ",".join(sorted(venue_types))
    return f"places:{lat_r}:{lng_r}:{radius_m}:{types_str}"


async def get_cached(lat: float, lng: float, venue_types: list[str], radius_m: int) -> list[dict] | None:
    client = await _get_client()
    if client is None:
        return None
    try:
        raw = await client.get(_cache_key(lat, lng, venue_types, radius_m))
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def set_cached(lat: float, lng: float, venue_types: list[str], radius_m: int, data: list[dict]) -> None:
    client = await _get_client()
    if client is None:
        return
    try:
        await client.setex(_cache_key(lat, lng, venue_types, radius_m), CACHE_TTL_SECONDS, json.dumps(data))
    except Exception:
        pass
