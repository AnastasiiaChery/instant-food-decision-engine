import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.core.config import settings
from app.models.search import PlaceIntent, RankedPlace, SearchRequest
from app.services import intent_parser, ranker
from app.services.places_client import OverpassPlacesClient

_places_client = OverpassPlacesClient()


def _place_event(places: list[Any]) -> str:
    data = [
        {
            "name": p.name,
            "distance_m": round(p.distance_m),
            "amenity": p.amenity,
            "cuisine": p.cuisine,
            "lat": p.lat,
            "lon": p.lon,
            "nav_url": f"https://www.google.com/maps/search/?api=1&query={p.lat},{p.lon}",
        }
        for p in places
    ]
    return f"event: places\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _ranked_event(ranked: list[RankedPlace]) -> str:
    data = [r.model_dump() for r in ranked]
    return f"event: ranked\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _error_event(message: str) -> str:
    return f"event: error\ndata: {json.dumps({'detail': message})}\n\n"


async def stream_search(
    request: SearchRequest,
    http_client: httpx.AsyncClient,
    ai_client: AsyncOpenAI,
) -> AsyncIterator[str]:
    try:
        intent: PlaceIntent = await intent_parser.parse_intent(
            request.query, ai_client, settings.ai_model
        )
    except Exception:
        intent = PlaceIntent(
            venue_types=["restaurant", "cafe"],
            mood="casual",
            price_level=[1, 2, 3],
            features=[],
            time_sensitivity="right now",
        )

    venue_types = intent.venue_types or ["restaurant", "fast_food", "cafe"]

    try:
        if len(venue_types) > 1:
            # fetch different venue types in parallel
            results = await asyncio.gather(
                *[
                    _places_client.fetch(
                        lat=request.lat,
                        lng=request.lng,
                        venue_types=[vt],
                        radius_m=settings.search_radius_m,
                        http_client=http_client,
                        max_radius_m=settings.max_radius_m,
                    )
                    for vt in venue_types
                ],
                return_exceptions=True,
            )
            places = []
            seen_names: set[str] = set()
            for batch in results:
                if isinstance(batch, Exception):
                    continue
                for p in batch:
                    key = f"{p.name.lower()}|{p.lat:.5f}|{p.lon:.5f}"
                    if key not in seen_names:
                        seen_names.add(key)
                        places.append(p)
        else:
            places = await _places_client.fetch(
                lat=request.lat,
                lng=request.lng,
                venue_types=venue_types,
                radius_m=settings.search_radius_m,
                http_client=http_client,
                max_radius_m=settings.max_radius_m,
            )
    except Exception as exc:
        yield _error_event(str(exc))
        return

    if not places:
        yield _error_event("No suitable places found nearby.")
        return

    # pick top 20 by quality: distance (70%) + metadata completeness (30%)
    def _quality_score(p: Any) -> float:
        dist_score = max(0.0, 1.0 - p.distance_m / (settings.max_radius_m or 3000))
        meta_score = sum([bool(p.cuisine), bool(p.opening_hours), bool(p.contact_phone)]) / 3.0
        return 0.7 * dist_score + 0.3 * meta_score

    places = sorted(places, key=_quality_score, reverse=True)[:20]

    # send raw places immediately — fast, no AI wait
    yield _place_event(places)

    # AI ranking — takes 1-2s
    try:
        ranked = await ranker.rank_places(places, request.query, intent, ai_client, settings.ai_model)
    except Exception:
        ranked = ranker._fallback_ranking(places)

    yield _ranked_event(ranked)
