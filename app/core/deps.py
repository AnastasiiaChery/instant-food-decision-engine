from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from openai import AsyncOpenAI

from app.core.config import settings


@asynccontextmanager
async def lifespan_http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        yield client


def get_ai_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.groq_api_key or "no-key",
        base_url=settings.ai_base_url,
    )
