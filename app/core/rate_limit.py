"""Shared rate limiter.

A single Limiter instance is reused across routers (search, auth, feedback) so
all per-IP limits share one backend and one registration on app.state.limiter.

When REDIS_URL is set, limits are stored in Redis so they hold across multiple
workers/instances and survive restarts. With no Redis configured (local/dev) it
falls back to in-process memory storage — correct only for a single process.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url or "memory://",
)
