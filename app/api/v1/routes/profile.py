from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

_STATIC = Path(__file__).resolve().parent.parent.parent.parent.parent / "static"

from app.core.deps import get_optional_user
from app.infrastructure.database import get_db
from app.models.profile import UserPreferences
from app.models.user import User

router = APIRouter()


@router.get("/profile/setup")
async def profile_setup_page():
    return FileResponse(_STATIC / "profile_setup.html")


@router.get("/api/v1/profile/preferences", response_model=UserPreferences)
async def get_preferences(
    user: User | None = Depends(get_optional_user),
) -> UserPreferences:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return UserPreferences(**(user.preferences or {}))


@router.put("/api/v1/profile/preferences", response_model=UserPreferences)
async def update_preferences(
    body: UserPreferences,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> UserPreferences:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    user.preferences = body.model_dump()
    await db.commit()
    await db.refresh(user)
    return UserPreferences(**user.preferences)


class UpdateMeRequest(BaseModel):
    display_name: str


@router.get("/api/v1/profile/me")
async def get_me(user: User | None = Depends(get_optional_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"id": user.id, "email": user.email, "display_name": user.display_name}


@router.put("/api/v1/profile/me")
async def update_me(
    body: UpdateMeRequest,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    user.display_name = body.display_name.strip() or None
    await db.commit()
    await db.refresh(user)
    return {"id": user.id, "email": user.email, "display_name": user.display_name}
