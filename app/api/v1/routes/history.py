from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_optional_user
from app.core.rate_limit import limiter
from app.models.history import SearchHistory
from app.models.user import User

router = APIRouter()


class NavigatePayload(BaseModel):
    # Bounded so an authenticated client can't write arbitrarily large rows.
    place_osm_id: str | None = Field(default=None, max_length=64)
    place_name: str = Field(max_length=255)
    place_type: str = Field(max_length=64)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    query: str | None = Field(default=None, max_length=500)
    match_score: float | None = None
    action_type: str = Field(default="navigate", max_length=32)


@router.post("/api/v1/history/navigate")
@limiter.limit("60/minute")
async def record_navigate(
    payload: NavigatePayload,
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    entry = SearchHistory(
        user_id=user.id,
        place_osm_id=payload.place_osm_id,
        place_name=payload.place_name,
        place_type=payload.place_type,
        lat=payload.lat,
        lng=payload.lng,
        query=payload.query,
        match_score=payload.match_score,
        action_type=payload.action_type,
    )
    db.add(entry)
    await db.commit()
    return {"ok": True}


@router.get("/api/v1/history")
async def get_history(
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    result = await db.execute(
        select(SearchHistory)
        .where(SearchHistory.user_id == user.id)
        .order_by(desc(SearchHistory.chosen_at))
        .limit(50)
    )
    entries = result.scalars().all()

    return [
        {
            "id": e.id,
            "place_name": e.place_name,
            "place_type": e.place_type,
            "lat": e.lat,
            "lng": e.lng,
            "nav_url": f"https://www.google.com/maps/dir/?api=1&destination={e.lat},{e.lng}",
            "action_type": e.action_type,
            "chosen_at": e.chosen_at.isoformat(),
        }
        for e in entries
    ]
