from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.deps import get_ai_client
from app.models.search import SearchRequest
from app.services.search_service import stream_search

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


async def _event_stream(
    request: SearchRequest, http_client: httpx.AsyncClient
) -> AsyncIterator[str]:
    ai_client = get_ai_client()
    async for chunk in stream_search(request, http_client, ai_client):
        yield chunk


@router.post("/api/v1/search")
@limiter.limit("10/minute")
async def search(payload: SearchRequest, request: Request) -> StreamingResponse:
    http_client: httpx.AsyncClient = request.app.state.http_client
    return StreamingResponse(
        _event_stream(payload, http_client),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
