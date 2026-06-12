from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.deps import get_optional_user
from app.core.rate_limit import limiter
from app.models.user import User
from app.services.telegram import send_feedback

router = APIRouter()


class FeedbackPayload(BaseModel):
    place_name: str = Field(max_length=255)
    query: str | None = Field(default=None, max_length=500)
    mode: str = Field(default="autopilot", max_length=20)
    comment: str = Field(min_length=1, max_length=1000)


@router.post("/api/v1/feedback")
@limiter.limit("20/minute")
async def submit_feedback(
    payload: FeedbackPayload,
    request: Request,
    user: User | None = Depends(get_optional_user),
):
    await send_feedback(
        http_client=request.app.state.http_client,
        place_name=payload.place_name,
        query=payload.query,
        mode=payload.mode,
        comment=payload.comment,
        user_email=user.email if user else None,
    )
    return {"ok": True}
