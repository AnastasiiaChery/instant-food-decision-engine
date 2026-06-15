"""Analytics ingest + admin dashboard.

POST /api/v1/events      — the browser posts a small batch of behaviour events.
                           Open to anonymous visitors (that's the point: we want the
                           pre-login funnel), but rate-limited and tightly bounded.
GET  /api/v1/admin/stats — aggregate dashboard, locked to ANALYTICS_ADMIN_EMAILS.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_db, get_optional_user
from app.core.rate_limit import limiter
from app.models.analytics import Event
from app.models.user import User
from app.services.analytics import collect_stats

router = APIRouter()
logger = logging.getLogger(__name__)

# Only these event names are accepted — an allowlist keeps the table clean and stops
# a hostile client from inventing arbitrary high-cardinality names.
ALLOWED_EVENTS = {
    "page_view",
    "search_started",
    "places_shown",
    "recommendation_shown",
    "navigate_clicked",
    "favorite_clicked",
    "signup",
    "login",
}


class EventIn(BaseModel):
    name: str = Field(max_length=64)
    session_id: str | None = Field(default=None, max_length=36)
    path: str | None = Field(default=None, max_length=255)
    # Free-form, but bounded: at most a handful of small scalar properties.
    props: dict = Field(default_factory=dict)


class EventBatch(BaseModel):
    anon_id: str = Field(max_length=36)
    # One sendBeacon may carry several events; cap the batch so a single call can't
    # write an unbounded number of rows.
    events: list[EventIn] = Field(max_length=20)


def _sanitize_props(props: dict) -> dict:
    """Keep props small and scalar — drop nested structures and over-long strings."""
    clean: dict = {}
    for key, value in list(props.items())[:10]:
        if not isinstance(key, str):
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)):
            clean[key[:40]] = value
        elif isinstance(value, str):
            clean[key[:40]] = value[:120]
        # nested dicts/lists are intentionally dropped
    return clean


@router.post("/api/v1/events")
@limiter.limit("120/minute")
async def ingest_events(
    payload: EventBatch,
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    if not settings.analytics_enabled:
        return {"ok": True, "accepted": 0}

    accepted = 0
    for ev in payload.events:
        if ev.name not in ALLOWED_EVENTS:
            continue
        db.add(
            Event(
                anon_id=payload.anon_id,
                user_id=user.id if user else None,
                session_id=ev.session_id,
                name=ev.name,
                props=_sanitize_props(ev.props),
                path=ev.path,
            )
        )
        accepted += 1

    if accepted:
        await db.commit()
    return {"ok": True, "accepted": accepted}


@router.get("/api/v1/admin/stats")
async def admin_stats(
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    allowlist = settings.analytics_admin_emails_list
    if not user or user.email.lower() not in allowlist:
        # 404 (not 403) so the endpoint's existence isn't advertised to non-admins.
        raise HTTPException(status_code=404, detail="Not found")
    return await collect_stats(db)
