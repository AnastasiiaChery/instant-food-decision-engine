import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.deps import configure_langsmith, get_ai_client
from app.core.rate_limit import limiter
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.decide import router as decide_router
from app.api.v1.routes.feedback import router as feedback_router
from app.api.v1.routes.history import router as history_router
from app.api.v1.routes.i18n import router as i18n_router
from app.api.v1.routes.profile import router as profile_router
from app.api.v1.routes.search import router as search_router

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_FILE = PROJECT_ROOT / "static" / "index.html"

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    problems = settings.validate_runtime()
    if problems:
        raise RuntimeError(
            "Refusing to start in production with insecure configuration:\n  - "
            + "\n  - ".join(problems)
        )
    if not settings.google_client_id or not settings.google_client_secret:
        logger.warning("Google OAuth is not configured — /auth/google login will not work.")

    configure_langsmith()
    app.state.ai_client = get_ai_client()
    async with httpx.AsyncClient(timeout=15.0) as client:
        app.state.http_client = client
        yield


app = FastAPI(title="Instant Food Decision Engine", version="0.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(history_router)
app.include_router(i18n_router)
app.include_router(search_router)
app.include_router(feedback_router)
app.include_router(decide_router)


@app.get("/")
def root() -> FileResponse:
    return FileResponse(INDEX_FILE)


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    return {"status": "ready", "static_available": INDEX_FILE.exists()}
