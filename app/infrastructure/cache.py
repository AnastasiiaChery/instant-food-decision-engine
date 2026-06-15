import asyncio
import json
import math
from typing import Any

from app.core.config import settings

_redis_client: Any = None
# Guards client creation: without it, concurrent first-use requests each build a
# separate connection pool and all but one leak.
_client_lock = asyncio.Lock()

CACHE_TTL_SECONDS = 3600  # 1 hour; OSM data is stable and we fetch all types per cell


async def _get_client() -> Any:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not settings.redis_url:
        return None
    async with _client_lock:
        if _redis_client is None:  # re-check: another coroutine may have built it
            try:
                import redis.asyncio as aioredis
                _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
            except Exception:
                _redis_client = None
    return _redis_client


async def close_client() -> None:
    """Close the shared Redis connection pool. Called at app shutdown so redeploys
    don't leak server-side connections."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:
            pass
        _redis_client = None


def _cache_key(lat: float, lng: float, radius_m: int) -> str:
    lat_r = round(lat, 3)
    lng_r = round(lng, 3)
    # Snap radius UP to the nearest 500m boundary so requests at 400m, 499m, 500m all
    # share the same key; the caller filters by the exact radius after the cache read.
    tier = math.ceil(radius_m / 500) * 500
    return f"places_v2:{lat_r}:{lng_r}:{tier}"


async def get_cached(lat: float, lng: float, radius_m: int) -> list[dict] | None:
    client = await _get_client()
    if client is None:
        return None
    try:
        raw = await client.get(_cache_key(lat, lng, radius_m))
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def set_cached(lat: float, lng: float, radius_m: int, data: list[dict]) -> None:
    client = await _get_client()
    if client is None:
        return
    try:
        await client.setex(_cache_key(lat, lng, radius_m), CACHE_TTL_SECONDS, json.dumps(data))
    except Exception:
        pass


async def get_json(key: str) -> Any | None:
    """Generic JSON read. Returns None if Redis is absent or the key is missing."""
    client = await _get_client()
    if client is None:
        return None
    try:
        raw = await client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def set_json(key: str, data: Any, ttl_seconds: int | None = None) -> None:
    """Generic JSON write. No-op when Redis is not configured."""
    client = await _get_client()
    if client is None:
        return
    try:
        payload = json.dumps(data, ensure_ascii=False)
        if ttl_seconds:
            await client.setex(key, ttl_seconds, payload)
        else:
            await client.set(key, payload)
    except Exception:
        pass
