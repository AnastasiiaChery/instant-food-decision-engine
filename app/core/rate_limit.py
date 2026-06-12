"""Shared rate limiter.

A single Limiter instance is reused across routers (search, auth, feedback) so
all per-IP limits share one backend and one registration on app.state.limiter.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
