from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.deps import get_optional_user
from app.core.rate_limit import limiter
from app.models.profile import UserPreferences
from app.models.search import SearchRequest
from app.models.user import User
from app.services.search_service import stream_search

router = APIRouter()


async def _event_stream(
    request: SearchRequest,
    http_client: httpx.AsyncClient,
    preferences: UserPreferences | None,
    ai_client,
) -> AsyncIterator[str]:
    async for chunk in stream_search(request, http_client, ai_client, preferences):
        yield chunk


@router.post("/api/v1/search")
@limiter.limit("10/minute")
async def search(
    payload: SearchRequest,
    request: Request,
    user: User | None = Depends(get_optional_user),
) -> StreamingResponse:
    http_client: httpx.AsyncClient = request.app.state.http_client
    ai_client = request.app.state.ai_client
    preferences: UserPreferences | None = None
    if payload.use_profile and user and user.preferences:
        preferences = UserPreferences(**user.preferences)
    return StreamingResponse(
        _event_stream(payload, http_client, preferences, ai_client),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
