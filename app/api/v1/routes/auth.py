import re
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, field_validator
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_db
from app.core.rate_limit import limiter
from app.core.security import create_access_token
from app.models.user import User

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Pragmatic email check — avoids pulling in the optional email-validator
# dependency that pydantic's EmailStr requires, while still rejecting garbage.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("Invalid email address")
    return email


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        return _normalize_email(v)

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        return _normalize_email(v)


@router.post("/auth/register")
@limiter.limit("5/minute")
async def register(body: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email,
        display_name=body.display_name,
        password_hash=pwd_context.hash(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user_id=user.id, email=user.email, display_name=user.display_name)
    return {"token": token}


@router.post("/auth/login")
@limiter.limit("5/minute")
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not pwd_context.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user_id=user.id, email=user.email, display_name=user.display_name)
    return {"token": token}

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# Short-lived cookie holding the OAuth `state` nonce. Scoped to the callback path
# and HttpOnly so only the callback can read it back to defeat login-CSRF.
_OAUTH_STATE_COOKIE = "oauth_state"
_OAUTH_STATE_PATH = "/auth/callback"


@router.get("/auth/google")
async def google_login():
    # CSRF nonce: echoed by Google in the callback and compared against the cookie.
    state = secrets.token_urlsafe(32)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "state": state,
    }
    resp = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302)
    resp.set_cookie(
        _OAUTH_STATE_COOKIE, state,
        max_age=600, httponly=True, samesite="lax",
        secure=settings.is_production, path=_OAUTH_STATE_PATH,
    )
    return resp


@router.get("/auth/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # Verify the CSRF state against the cookie set in /auth/google.
    cookie_state = request.cookies.get(_OAUTH_STATE_COOKIE)
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            })
            token_resp.raise_for_status()
            access_token = token_resp.json()["access_token"]

            info_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            info_resp.raise_for_status()
            info = info_resp.json()
        google_id = info["sub"]
        email = info["email"]
    except (httpx.HTTPError, KeyError, ValueError):
        # Upstream failure / unexpected response shape — surface a clean 502 rather
        # than leaking a traceback to the user.
        raise HTTPException(status_code=502, detail="Google sign-in failed, please try again")

    display_name = info.get("name")

    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if not user:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

    if user:
        user.google_id = google_id
        user.display_name = display_name
    else:
        user = User(email=email, google_id=google_id, display_name=display_name)
        db.add(user)

    await db.commit()
    await db.refresh(user)

    jwt_token = create_access_token(user_id=user.id, email=user.email, display_name=user.display_name)
    # Return the token in the URL *fragment*, not the query string: fragments are
    # never sent to the server (kept out of access logs) nor in the Referer header.
    resp = RedirectResponse(f"/#token={jwt_token}")
    resp.delete_cookie(_OAUTH_STATE_COOKIE, path=_OAUTH_STATE_PATH)
    return resp
