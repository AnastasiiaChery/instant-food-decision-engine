import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx
from langchain_groq import ChatGroq

from app.core.config import settings

logger = logging.getLogger(__name__)
from app.infrastructure import cache
from app.models.place import Place
from app.models.profile import UserPreferences
from app.models.search import PlaceIntent, PlanRecommendation, RankedPlace, SearchRequest
from app.services import intent_parser, planner, ranker
from app.services.places_client import OverpassPlacesClient

_places_client = OverpassPlacesClient()

_ALL_VENUE_TYPES = ["restaurant", "fast_food", "cafe", "bar", "pub", "biergarten", "food_court"]
_VALID_VENUE_TYPES = set(_ALL_VENUE_TYPES)


def _parse_when_utc(when: str | None) -> datetime | None:
    if not when:
        return None
    try:
        t = datetime.strptime(when, "%H:%M").time()
        return datetime.now(UTC).replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    except ValueError:
        return None


def _local_time_str(lat: float, lng: float) -> str:
    """Estimate local time from longitude (rough UTC offset, good enough for meal-time context)."""
    offset_hours = max(-12, min(14, round(lng / 15)))
    local_tz = timezone(timedelta(hours=offset_hours))
    local_dt = datetime.now(local_tz)
    day = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][local_dt.weekday()]
    sign = "+" if offset_hours >= 0 else ""
    return f"{day} {local_dt.strftime('%H:%M')} (UTC{sign}{offset_hours})"


def _walk_label(distance_m: float) -> str:
    minutes = round(distance_m / 80)
    return f"{round(distance_m)}m away" if minutes <= 1 else f"~{minutes} min walk"


def _signals(place: RankedPlace) -> list[str]:
    """Compact chips shown under the recommendation card — no distance (already in reason)."""
    out = []
    if place.cuisine:
        out.append(place.cuisine.replace("_", " ").title())
    elif place.amenity not in ("restaurant", "food"):
        out.append(place.amenity.replace("_", " ").title())
    out.append(f"{round(place.match_score * 100)}% match")
    return out


def _intent_event(intent: PlaceIntent, query: str) -> str:
    data = {
        "query": query,
        "venue_types": intent.venue_types,
        "mood": intent.mood,
        "cuisine": intent.cuisine or [],
        "features": intent.features,
    }
    return f"event: intent\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _recommendation_event(top: RankedPlace, fallback: RankedPlace | None) -> str:
    data: dict[str, Any] = {
        "place": top.model_dump(),
        "reason": top.reason,
        "signals": _signals(top),
        "fallback_place": fallback.model_dump() if fallback else None,
        "fallback_signals": _signals(fallback) if fallback else [],
    }
    return f"event: recommendation\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _place_event(places: list[Place]) -> str:
    data = [
        {
            "name": p.name,
            "distance_m": round(p.distance_m),
            "amenity": p.amenity,
            "cuisine": p.cuisine,
            "lat": p.lat,
            "lon": p.lon,
            "nav_url": p.nav_url,
        }
        for p in places
    ]
    return f"event: places\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _ranked_event(ranked: list[RankedPlace]) -> str:
    data = [r.model_dump() for r in ranked]
    return f"event: ranked\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _plan_recommendations_event(recs: list[PlanRecommendation]) -> str:
    data = [r.model_dump() for r in recs]
    return f"event: recommendations\ndata: {json.dumps({'recommendations': data}, ensure_ascii=False)}\n\n"


def _error_event(message: str) -> str:
    return f"event: error\ndata: {json.dumps({'detail': message})}\n\n"


def _quality_score(p: Place, intent: PlaceIntent) -> float:
    """Pre-sort score before sending to AI. Accounts for mood and cuisine match."""
    dist_score = max(0.0, 1.0 - p.distance_m / (settings.max_radius_m or 3000))
    meta_score = sum([bool(p.cuisine), bool(p.opening_hours), bool(p.contact_phone)]) / 3.0

    # Distance weight shifts based on mood
    if intent.mood == "quick":
        dist_w, meta_w = 0.9, 0.1
    elif intent.mood in ("romantic", "business"):
        dist_w, meta_w = 0.55, 0.45
    else:
        dist_w, meta_w = 0.7, 0.3

    score = dist_w * dist_score + meta_w * meta_score

    # Cuisine match boost — pushes exact-cuisine venues above closer no-info venues
    if intent.cuisine and p.cuisine:
        cuisine_lower = {c.lower() for c in intent.cuisine}
        if any(c in p.cuisine.lower() for c in cuisine_lower):
            score = min(1.0, score + 0.25)

    return score


async def stream_search(
    request: SearchRequest,
    http_client: httpx.AsyncClient,
    ai_client: ChatGroq,
    preferences: UserPreferences | None = None,
) -> AsyncIterator[str]:
    radius_m = min(request.radius_m or settings.search_radius_m, settings.max_radius_m)
    now_utc = _parse_when_utc(request.when)
    time_context = _local_time_str(request.lat, request.lng)

    # Intent parsing runs concurrently with places fetching.
    # We use a fixed superset of all venue types as the cache key so a single
    # cache entry serves every query at the same location/radius regardless of intent.
    intent_task: asyncio.Task[PlaceIntent] = asyncio.create_task(
        intent_parser.parse_intent(request.query, ai_client)
    )

    try:
        cached = await cache.get_cached(request.lat, request.lng, _ALL_VENUE_TYPES, radius_m)
        if cached is not None:
            all_places: list[Place] = [Place(**d) for d in cached]
        else:
            fetch_results = await asyncio.gather(
                *[
                    _places_client.fetch(
                        lat=request.lat,
                        lng=request.lng,
                        venue_types=[vt],
                        radius_m=radius_m,
                        http_client=http_client,
                        max_radius_m=settings.max_radius_m,
                        now_utc=now_utc,
                    )
                    for vt in _ALL_VENUE_TYPES
                ],
                return_exceptions=True,
            )
            errors = [r for r in fetch_results if isinstance(r, Exception)]
            if len(errors) == len(fetch_results):
                logger.exception("places fetch failed at (%.4f, %.4f)", request.lat, request.lng)
                intent_task.cancel()
                yield _error_event(str(errors[0]))
                return
            all_places = []
            seen_keys: set[str] = set()
            for batch in fetch_results:
                if isinstance(batch, Exception):
                    continue
                for p in batch:
                    key = f"{p.name.lower()}|{p.lat:.5f}|{p.lon:.5f}"
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_places.append(p)
            await cache.set_cached(
                request.lat, request.lng, _ALL_VENUE_TYPES, radius_m,
                [p.model_dump() for p in all_places],
            )
    except Exception as exc:
        logger.exception("places fetch failed at (%.4f, %.4f)", request.lat, request.lng)
        intent_task.cancel()
        yield _error_event(str(exc))
        return

    # Wait for intent — usually already done while places were being fetched
    try:
        intent: PlaceIntent = await intent_task
    except Exception:
        logger.exception("intent task failed for query %r, using default", request.query)
        intent = PlaceIntent(
            venue_types=["restaurant", "cafe", "bar", "pub"],
            mood="casual",
            price_level=[1, 2, 3],
            features=[],
        )

    # Validate and sanitize venue_types from intent
    intent_types = [t for t in (intent.venue_types or []) if t in _VALID_VENUE_TYPES]
    if not intent_types:
        intent_types = list(_ALL_VENUE_TYPES)

    # Filter places to intent's venue types
    places: list[Place] = [p for p in all_places if p.amenity in set(intent_types)] or all_places

    if not places:
        yield _error_event("No suitable places found nearby.")
        return

    # Soft boost for cuisine: quality_score gives +0.25 to matching venues.
    # No hard filter — AI sees all candidates and makes the nuanced call.
    places = sorted(places, key=lambda p: _quality_score(p, intent), reverse=True)[:20]

    # Emit parsed intent for transparency, then the place list
    yield _intent_event(intent, request.query)
    yield _place_event(places)

    if request.mode == "plan":
        # Stage 1: rank to get pre-computed relevance scores
        try:
            ranked = await ranker.rank_places(
                places, request.query, intent, ai_client,
                preferences=preferences, time_context=time_context,
            )
        except Exception:
            logger.exception("ranker failed in plan pre-stage for query %r", request.query)
            ranked = ranker._fallback_ranking(places)

        # Stage 2: pass original places + pre-scores to planner
        MIN_SCORE = 0.2
        score_map = {r.name: r.match_score for r in ranked}
        scored = sorted(
            [(p, score_map.get(p.name, 0.0)) for p in places],
            key=lambda x: -x[1],
        )
        relevant = [(p, s) for p, s in scored if s >= MIN_SCORE] or scored[:10]
        plan_places = [p for p, _ in relevant]
        pre_scores = [s for _, s in relevant]

        try:
            recs = await planner.plan_places(
                plan_places, request.query, intent,
                request.group_size, request.occasion, ai_client,
                preferences=preferences, time_context=time_context, pre_scores=pre_scores,
            )
        except Exception:
            logger.exception("planner failed for query %r, using fallback", request.query)
            recs = planner._fallback_recommendations(plan_places)
        yield _plan_recommendations_event(recs)
        return

    try:
        ranked = await ranker.rank_places(
            places, request.query, intent, ai_client,
            preferences=preferences, time_context=time_context,
        )
    except Exception:
        logger.exception("ranker failed for query %r, using fallback", request.query)
        ranked = ranker._fallback_ranking(places)

    MIN_SCORE = 0.2
    relevant = [r for r in ranked if r.match_score >= MIN_SCORE]
    candidates = relevant if relevant else ranked[:5]

    if request.mode == "autopilot":
        # Combine legacy single-name and new multi-name exclusion
        excluded: set[str] = set(request.exclude_place_names)
        if request.exclude_place_name:
            excluded.add(request.exclude_place_name)
        if excluded:
            filtered = [r for r in candidates if r.name not in excluded]
            candidates = filtered if filtered else candidates
        top = candidates[0]
        fallback = candidates[1] if len(candidates) > 1 else None
        yield _recommendation_event(top, fallback)
    else:
        yield _ranked_event(candidates)
