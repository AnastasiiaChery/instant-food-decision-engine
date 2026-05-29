from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_optional_user
from app.models.history import SearchHistory
from app.models.user import User

router = APIRouter()


class NavigatePayload(BaseModel):
    place_osm_id: str | None = None
    place_name: str
    place_type: str
    lat: float
    lng: float
    query: str | None = None
    match_score: float | None = None


@router.post("/api/v1/history/navigate")
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
    )
    db.add(entry)
    await db.commit()
    return {"ok": True}
