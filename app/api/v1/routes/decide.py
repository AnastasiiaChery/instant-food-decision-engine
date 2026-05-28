import time
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.places_client import (
    OverpassPlacesClient,
    _candidate_key,
    score_candidate,
)

router = APIRouter()
_places_client = OverpassPlacesClient()


class DecideRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    mode: str = Field(default="autopilot")
    exclude_keys: list[str] = Field(default_factory=list)
    debug: bool = Field(default=False)


def _place_to_response(place: Any) -> dict[str, Any]:
    return {
        "name": place.name,
        "lat": place.lat,
        "lon": place.lon,
        "distance_m": round(place.distance_m),
        "amenity": place.amenity,
        "cuisine": place.cuisine,
    }


def _place_key(place: Any) -> str:
    return _candidate_key({"name": place.name, "lat": place.lat, "lon": place.lon})


@router.post("/v1/decide")
async def decide(payload: DecideRequest, request: Request) -> dict:
    total_started = time.perf_counter()
    http_client: httpx.AsyncClient = request.app.state.http_client

    fetch_started = time.perf_counter()
    places = await _places_client.fetch(
        lat=payload.latitude,
        lng=payload.longitude,
        venue_types=["restaurant", "fast_food", "cafe"],
        radius_m=settings.search_radius_m,
        http_client=http_client,
        max_radius_m=settings.max_radius_m,
        now_utc=datetime.now(UTC),
    )
    fetch_ms = round((time.perf_counter() - fetch_started) * 1000, 2)

    filter_started = time.perf_counter()
    if not places:
        raise HTTPException(status_code=404, detail="No suitable places found nearby.")
    excluded = {item.strip().lower() for item in payload.exclude_keys}
    if excluded:
        places = [p for p in places if _place_key(p) not in excluded]
        if not places:
            raise HTTPException(status_code=404, detail="No additional options found nearby.")
    filter_ms = round((time.perf_counter() - filter_started) * 1000, 2)

    rank_started = time.perf_counter()
    dw, rw = settings.distance_weight, settings.reliability_weight
    total = dw + rw
    if total > 0:
        dw, rw = dw / total, rw / total
    ranked = sorted(
        places,
        key=lambda p: score_candidate(
            {"distance_m": p.distance_m, "cuisine": p.cuisine,
             "opening_hours": p.opening_hours, "contact_phone": p.contact_phone},
            dw, rw,
        ),
        reverse=True,
    )
    rank_ms = round((time.perf_counter() - rank_started) * 1000, 2)

    top = ranked[0]
    alt = ranked[1] if len(ranked) > 1 else None

    reliability = []
    if top.opening_hours:
        reliability.append("opening hours available")
    if top.cuisine:
        reliability.append("cuisine specified")

    why_parts = [f"Best nearby option at ~{round(top.distance_m)}m", "passed minimum quality filters"]
    if reliability:
        why_parts.append(", ".join(reliability))

    response: dict[str, Any] = {
        "recommended_place": _place_to_response(top),
        "why": ". ".join(why_parts) + ".",
        "navigate_url": f"https://www.google.com/maps/search/?api=1&query={top.lat},{top.lon}",
        "another_option": _place_to_response(alt) if alt else None,
    }
    if payload.debug:
        response["debug_timings_ms"] = {
            "fetch_candidates": fetch_ms,
            "filter_candidates": filter_ms,
            "rank_candidates": rank_ms,
            "total": round((time.perf_counter() - total_started) * 1000, 2),
        }
    return response
