import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.deps import build_ai_clients, configure_langsmith
from app.core.rate_limit import limiter
from app.infrastructure import cache
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.feedback import router as feedback_router
from app.api.v1.routes.history import router as history_router
from app.api.v1.routes.i18n import router as i18n_router
from app.api.v1.routes.profile import router as profile_router
from app.api.v1.routes.search import router as search_router

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"
INDEX_FILE = STATIC_DIR / "index.html"
PRIVACY_FILE = STATIC_DIR / "privacy.html"
TERMS_FILE = STATIC_DIR / "terms.html"

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
    clients = build_ai_clients()
    app.state.ai_clients = clients
    # Backward-compat alias: anything still reaching for a single client gets the heavy one.
    app.state.ai_client = clients["heavy"]
    async with httpx.AsyncClient(timeout=15.0) as client:
        app.state.http_client = client
        try:
            yield
        finally:
            await cache.close_client()


# Interactive API docs leak the full endpoint/schema surface, so they are disabled in
# production. Anything non-prod (local/dev) keeps /docs, /redoc and /openapi.json.
_docs_enabled = not settings.is_production
app = FastAPI(
    title="NomPilot — AI Dining Autopilot",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Reject requests whose Host header is not in the allowlist (DNS-rebinding / Host
# spoofing). Skipped when ALLOWED_HOSTS is "*" (dev default); required in prod.
if settings.allowed_hosts_list != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts_list)

# Content-Security-Policy: the SPA is same-origin; the only third parties are the
# Leaflet bundle (unpkg), Google Fonts, and the OSM/Carto map tiles + Nominatim
# geocoder. 'unsafe-inline' stays on style-src only (inline style="" attributes and
# Leaflet's runtime styles); script-src is locked to self + unpkg, so an injected
# inline <script> cannot run even if the localStorage token were the target.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https://unpkg.com https://*.basemaps.cartocdn.com; "
    "connect-src 'self' https://nominatim.openstreetmap.org; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Attach baseline security headers to every response."""
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", _CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(self), camera=(), microphone=()"
    )
    # HSTS only in production (over HTTPS); sending it on plain-http dev would pin
    # localhost to https and break local testing.
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """One structured line per request: method, path, status, latency."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "request method=%s path=%s status=%d duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(history_router)
app.include_router(i18n_router)
app.include_router(search_router)
app.include_router(feedback_router)


@app.get("/")
def root() -> FileResponse:
    return FileResponse(INDEX_FILE)


@app.get("/privacy")
def privacy() -> FileResponse:
    return FileResponse(PRIVACY_FILE)


@app.get("/terms")
def terms() -> FileResponse:
    return FileResponse(TERMS_FILE)


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    return {"status": "ready", "static_available": INDEX_FILE.exists()}
