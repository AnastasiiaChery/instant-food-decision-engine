"""First-party analytics: ingest, retention and dashboard aggregates.

Everything here runs against our own Postgres. There is no third-party tracker —
the browser posts behaviour events to /api/v1/events, middleware records one
request_log row per HTTP call, and this module turns both into numbers.

Writes are best-effort: analytics must never break a user request, so the record
helpers open their own short-lived session and swallow their own errors.
"""
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.infrastructure.database import async_session_factory
from app.models.analytics import Event, RequestLog

logger = logging.getLogger(__name__)

# Paths that are pure noise for load metrics: static assets, health probes from the
# load balancer, and the analytics ingest itself (logging it would be recursive).
_SKIP_PREFIXES = ("/static", "/api/v1/events")
_SKIP_EXACT = {"/health", "/ready", "/favicon.ico"}


def should_log_path(path: str) -> bool:
    if path in _SKIP_EXACT:
        return False
    return not any(path.startswith(p) for p in _SKIP_PREFIXES)


async def record_request(method: str, path: str, status: int, duration_ms: float) -> None:
    """Persist one request_log row. Best-effort: never raises into the caller."""
    if not settings.analytics_enabled or not should_log_path(path):
        return
    # Path is bounded to the column width; query strings are dropped upstream.
    error = path if status >= 500 else None
    try:
        async with async_session_factory() as session:
            session.add(
                RequestLog(
                    method=method[:8],
                    path=path[:255],
                    status=status,
                    duration_ms=duration_ms,
                    error=error[:255] if error else None,
                )
            )
            await session.commit()
    except Exception:  # pragma: no cover - telemetry must not crash requests
        logger.warning("failed to record request_log row", exc_info=True)


def fire_and_forget_request(method: str, path: str, status: int, duration_ms: float) -> None:
    """Schedule a request_log write without awaiting it (keeps the response fast)."""
    if not settings.analytics_enabled or not should_log_path(path):
        return
    task = asyncio.create_task(record_request(method, path, status, duration_ms))
    # Hold a reference so the task isn't garbage-collected before it runs, and
    # surface any unexpected error in logs instead of as an "unawaited" warning.
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


_background_tasks: set[asyncio.Task] = set()


async def prune_old_rows() -> tuple[int, int]:
    """Delete analytics rows past their retention window. Returns (events, requests)."""
    now = datetime.now(UTC)
    events_cutoff = now - timedelta(days=settings.analytics_events_retention_days)
    requests_cutoff = now - timedelta(days=settings.analytics_requests_retention_days)
    async with async_session_factory() as session:
        ev = await session.execute(delete(Event).where(Event.ts < events_cutoff))
        rq = await session.execute(delete(RequestLog).where(RequestLog.ts < requests_cutoff))
        await session.commit()
        return ev.rowcount or 0, rq.rowcount or 0


async def retention_loop(interval_s: int = 24 * 3600, initial_delay_s: int = 60) -> None:
    """Background task: prune shortly after startup, then once per `interval_s`.

    The short initial delay keeps the very first request fast and means a
    short-lived process (e.g. a test client that boots and shuts down at once)
    is cancelled during the wait, before it ever touches the database.
    Idempotent, so running it in every worker is harmless. Started from the app
    lifespan; cancelled on shutdown.
    """
    await asyncio.sleep(initial_delay_s)
    while True:
        try:
            events, requests = await prune_old_rows()
            if events or requests:
                logger.info("analytics retention pruned events=%d requests=%d", events, requests)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("analytics retention prune failed", exc_info=True)
        await asyncio.sleep(interval_s)


# --- Dashboard aggregates --------------------------------------------------------

async def collect_stats(session: AsyncSession) -> dict:
    """Compute the admin dashboard payload from events + request_log.

    All windows are relative to now(); the heavy lifting is done in SQL so the
    payload is small. Designed for low-traffic launch volumes — fine to call on
    each dashboard load without caching.
    """
    now = datetime.now(UTC)
    d1 = now - timedelta(days=1)
    d7 = now - timedelta(days=7)
    d30 = now - timedelta(days=30)

    # --- Audience: unique visitors keyed on anon_id ---
    dau = await session.scalar(
        select(func.count(func.distinct(Event.anon_id))).where(Event.ts >= d1)
    )
    mau = await session.scalar(
        select(func.count(func.distinct(Event.anon_id))).where(Event.ts >= d30)
    )
    signups_7d = await session.scalar(
        select(func.count()).select_from(Event).where(Event.name == "signup", Event.ts >= d7)
    )

    # --- Behaviour funnel (last 7d), counting distinct visitors at each step ---
    async def step(name: str) -> int:
        return await session.scalar(
            select(func.count(func.distinct(Event.anon_id))).where(
                Event.name == name, Event.ts >= d7
            )
        ) or 0

    visitors = await step("page_view")
    searched = await step("search_started")
    got_result = await step("recommendation_shown")
    navigated = await step("navigate_clicked")

    # --- Searches by mode (last 7d) ---
    mode_rows = (
        await session.execute(
            select(Event.props["mode"].astext, func.count())
            .where(Event.name == "search_started", Event.ts >= d7)
            .group_by(Event.props["mode"].astext)
        )
    ).all()
    searches_by_mode = {(m or "unknown"): c for m, c in mode_rows}

    # --- Ops: request volume, latency, errors (last 24h) ---
    req_total = await session.scalar(
        select(func.count()).select_from(RequestLog).where(RequestLog.ts >= d1)
    )
    errors_5xx = await session.scalar(
        select(func.count())
        .select_from(RequestLog)
        .where(RequestLog.ts >= d1, RequestLog.status >= 500)
    )
    # p50/p95 latency for the main search endpoint over the last 24h.
    latency = (
        await session.execute(
            select(
                func.percentile_cont(0.5).within_group(RequestLog.duration_ms),
                func.percentile_cont(0.95).within_group(RequestLog.duration_ms),
            ).where(RequestLog.ts >= d1, RequestLog.path == "/api/v1/search")
        )
    ).first()
    p50, p95 = (latency or (None, None))

    # --- Slowest / busiest endpoints (last 24h) ---
    endpoint_rows = (
        await session.execute(
            select(
                RequestLog.path,
                func.count(),
                func.percentile_cont(0.95).within_group(RequestLog.duration_ms),
            )
            .where(RequestLog.ts >= d1)
            .group_by(RequestLog.path)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()
    endpoints = [
        {"path": p, "count": c, "p95_ms": round(q, 1) if q is not None else None}
        for p, c, q in endpoint_rows
    ]

    return {
        "generated_at": now.isoformat(),
        "audience": {
            "dau": dau or 0,
            "mau": mau or 0,
            "signups_7d": signups_7d or 0,
        },
        "funnel_7d": {
            "visitors": visitors,
            "searched": searched,
            "got_result": got_result,
            "navigated": navigated,
            "search_to_navigate_pct": round(100 * navigated / searched, 1) if searched else 0.0,
        },
        "searches_by_mode_7d": searches_by_mode,
        "ops_24h": {
            "requests": req_total or 0,
            "errors_5xx": errors_5xx or 0,
            "error_rate_pct": round(100 * (errors_5xx or 0) / req_total, 2) if req_total else 0.0,
            "search_p50_ms": round(p50, 1) if p50 is not None else None,
            "search_p95_ms": round(p95, 1) if p95 is not None else None,
            "endpoints": endpoints,
        },
    }
