import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, Request
from langchain_core.language_models import BaseChatModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
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


def build_llm(model: str, cfg: Settings | None = None) -> BaseChatModel:
    """Construct a chat model for the configured provider.

    Provider-specific client classes are imported lazily so an unused provider's
    package never has to be installed (e.g. langchain-google-genai is only needed
    when AI_PROVIDER=gemini).
    """
    cfg = cfg or settings
    provider = cfg.ai_provider.strip().lower()
    api_key = cfg.effective_api_key or "no-key"

    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(api_key=api_key, model=model)
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(api_key=api_key, model=model, base_url=cfg.ai_base_url or None)
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(google_api_key=api_key, model=model)
    raise ValueError(
        f"Unknown AI_PROVIDER {cfg.ai_provider!r} (expected 'groq', 'openai' or 'gemini')"
    )


def build_ai_clients(cfg: Settings | None = None) -> dict[str, BaseChatModel]:
    """Build the per-tier clients used across the app.

    "fast" → light steps (intent parsing, UI translation); "heavy" → reasoning-heavy
    steps (ranking, planning). Built once at startup and reused for every request.
    """
    cfg = cfg or settings
    return {
        "fast": build_llm(cfg.ai_model_fast, cfg),
        "heavy": build_llm(cfg.ai_model, cfg),
    }


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
