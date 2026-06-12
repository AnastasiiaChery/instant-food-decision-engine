from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.services import translator

router = APIRouter()


@router.get("/api/v1/i18n/{lang}")
async def get_i18n(lang: str, request: Request) -> JSONResponse:
    if not translator.is_valid_lang(lang.lower()):
        raise HTTPException(status_code=400, detail="Invalid language code")
    ai_client = request.app.state.ai_client
    data = await translator.get_translations(lang, ai_client)
    # Revalidate on every load: the base dictionary gains keys between deploys,
    # and a long max-age left browsers showing a stale dict (missing new keys)
    # for up to a day. The payload is small; server-side it's cached in memory.
    return JSONResponse(content=data, headers={"Cache-Control": "no-cache"})
