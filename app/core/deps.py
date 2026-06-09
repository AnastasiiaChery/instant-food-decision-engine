import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, Request
from langchain_groq import ChatGroq
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_access_token
from app.infrastructure.database import get_db
from app.models.user import User


def configure_langsmith() -> None:
    """Enable LangSmith tracing if an API key is configured.

    Sets both the modern LANGSMITH_* names (langsmith>=0.2) and the legacy
    LANGCHAIN_* names so tracing works regardless of the installed version.
    """
    if settings.langsmith_api_key:
        for key, val in (
            ("LANGSMITH_API_KEY",    settings.langsmith_api_key),
            ("LANGSMITH_TRACING",    settings.langsmith_tracing),
            ("LANGSMITH_PROJECT",    settings.langsmith_project),
            ("LANGCHAIN_API_KEY",    settings.langsmith_api_key),
            ("LANGCHAIN_TRACING_V2", settings.langsmith_tracing),
            ("LANGCHAIN_PROJECT",    settings.langsmith_project),
        ):
            os.environ.setdefault(key, val)


@asynccontextmanager
async def lifespan_http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        yield client


def get_ai_client() -> ChatGroq:
    return ChatGroq(
        api_key=settings.groq_api_key or "no-key",
        model=settings.ai_model,
    )


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if not payload:
        return None
    user_id = int(payload.get("sub", 0))
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
