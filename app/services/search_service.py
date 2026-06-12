import asyncio
import json
import logging
import math
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
from app.services.places_client import (
    VALID_AMENITIES,
    _deduplicate,
    _distance_m,
    _fetch_raw,
    _filter_candidates,
    _is_open_now,
)


_NAMED_WHEN: dict[str, str] = {
    "breakfast": "09:00",
    "lunch": "12:30",
    "dinner": "19:30",
}


def _parse_when_utc(when: str | None, lng: float | None = None) -> datetime:
    """Resolve the reference time for the open-now filter, in UTC.

    "now"/empty/unparseable → current local time, so even one-tap autopilot
    (which never sends `when`) avoids recommending a venue that is closed right
    now. A named meal or explicit HH:MM → that time today, in the location's
    approximate timezone.
    """
    offset_hours = max(-12, min(14, round((lng or 0) / 15)))
    local_tz = timezone(timedelta(hours=offset_hours))
    now_local = datetime.now(local_tz)

    normalized = (when or "").strip().lower()
    if normalized in ("now", ""):
        return now_local.astimezone(UTC)
    time_str = _NAMED_WHEN.get(normalized, when)
    try:
        t = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        return now_local.astimezone(UTC)
    return now_local.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0).astimezone(UTC)


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


def _plan_recommendations_event(
    recs: list[PlanRecommendation], notice: str | None = None
) -> str:
    payload: dict[str, Any] = {"recommendations": [r.model_dump() for r in recs]}
    if notice:
        payload["notice"] = notice
    return f"event: recommendations\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _relaxed_notice(intent: PlaceIntent) -> str:
    """Message shown when no venue clears the match threshold, but we still surface
    the best-rated alternatives so the user can refine rather than hit a dead end."""
    wanted: list[str] = []
    if intent.cuisine:
        wanted.append(f"{', '.join(intent.cuisine)} cuisine")
    if intent.features:
        wanted.append(", ".join(intent.features))
    criteria = " · ".join(wanted)
    if criteria:
        return (
            f"No spots matching {criteria} nearby. "
            "Showing the best-rated alternatives — widen the radius or change your query to refine."
        )
    return (
        "Nothing closely matched your exact criteria nearby. "
        "Showing the best-rated alternatives — widen the radius or adjust your query to refine."
    )


def _no_match_event(query: str) -> str:
    data = {"query": query}
    return f"event: no_match\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _planning_event(message: str) -> str:
    """Intermediate progress for the (potentially slow) plan-mode agent run."""
    return f"event: planning\ndata: {json.dumps({'message': message}, ensure_ascii=False)}\n\n"


def _error_event(message: str) -> str:
    return f"event: error\ndata: {json.dumps({'detail': message})}\n\n"


_PLAN_NO_MATCH_THRESHOLD = 0.4  # fixed for plan mode (planner agent handles expansion)
_PLAN_TIMEOUT_S = 25.0  # hard budget for the agentic planner run before falling back

_OUTDOOR_KW = frozenset({"terrace", "rooftop", "outdoor", "garden", "patio", "balcony"})
_QUIET_KW = frozenset({"quiet", "cozy", "intimate", "calm"})
_QUICK_MOOD_MAX_M = 600


def _no_match_threshold(n_candidates: int) -> float:
    """Scale the no-match threshold by how many candidates were ranked.

    Fewer options → lower bar (something is better than nothing).
    Many options → slightly higher bar (can afford to be strict).
    """
    if n_candidates <= 3:
        return 0.30
    if n_candidates >= 20:
        return 0.43
    return 0.40


def _quality_score(p: Place, intent: PlaceIntent) -> float:
    """Pre-sort score before sending to AI. Accounts for mood, venue type, cuisine, and features."""
    dist_score = max(0.0, 1.0 - p.distance_m / (settings.max_radius_m or 3000))
    meta_score = sum([bool(p.cuisine), bool(p.opening_hours), bool(p.contact_phone)]) / 3.0

    # Distance weight shifts based on mood — now covers all six intent moods
    if intent.mood == "quick":
        dist_w, meta_w = 0.90, 0.10
    elif intent.mood in ("romantic", "business", "cozy"):
        dist_w, meta_w = 0.55, 0.45
    elif intent.mood == "lively":
        dist_w, meta_w = 0.65, 0.35
    else:  # casual (default)
        dist_w, meta_w = 0.70, 0.30

    score = dist_w * dist_score + meta_w * meta_score

    # Venue type match boost — intended type ranks above same-distance alternatives
    if p.amenity in set(intent.venue_types):
        score = min(1.0, score + 0.15)

    # Cuisine match boost — pushes exact-cuisine venues above closer no-info venues
    if intent.cuisine and p.cuisine:
        cuisine_lower = {c.lower() for c in intent.cuisine}
        if any(c in p.cuisine.lower() for c in cuisine_lower):
            score = min(1.0, score + 0.25)

    # Name-based cuisine hint: slightly weaker than a tag match
    if intent.cuisine and not p.cuisine:
        name_lower = p.name.lower()
        cuisine_lower = {c.lower() for c in intent.cuisine}
        if any(c in name_lower for c in cuisine_lower):
            score = min(1.0, score + 0.20)

    # Feature hints from place name (limited OSM data, but worth catching)
    if intent.features:
        feat = {f.lower() for f in intent.features}
        name_lower = p.name.lower()
        if feat & {"outdoor", "terrace", "rooftop", "garden"} and any(kw in name_lower for kw in _OUTDOOR_KW):
            score = min(1.0, score + 0.10)
        # Quiet/cozy intent → gentle penalty for loud venue types
        if feat & _QUIET_KW and p.amenity in ("bar", "pub", "biergarten"):
            score = max(0.0, score - 0.15)

    return score


async def _prepare_places(
    request: SearchRequest,
    radius_m: int,
    venue_types: list[str],
    intent: PlaceIntent,
    now_utc: datetime,
    http_client: httpx.AsyncClient,
) -> list[Place]:
    """Fetch (cached) + filter + sort venues for one radius.

    Caches ALL venue types for the geo-cell so different intent queries share the
    same entry. The cache key snaps radius to 500m tiers; distance_m is recomputed
    from stored lat/lon on every cache hit so each caller gets correct distances.

    Raises if Overpass fails; returns [] when the area simply has nothing.
    Safe to call more than once per request (e.g. autopilot retry at wider radius).
    """
    # Snap to 500m ceiling tier — requests at 400/499/500m share one key; we filter
    # to the actual radius after the read.
    cache_radius = math.ceil(radius_m / 500) * 500

    cached = await cache.get_cached(request.lat, request.lng, cache_radius)
    if cached is not None:
        # Recompute distance from the caller's exact position; the cached value was
        # relative to whichever request populated the cell.
        all_places: list[Place] = [
            Place(**{**d, "distance_m": _distance_m(request.lat, request.lng, d["lat"], d["lon"])})
            for d in cached
        ]
    else:
        try:
            raw = await _fetch_raw(
                request.lat, request.lng,
                sorted(VALID_AMENITIES),
                cache_radius,
                http_client,
            )
        except Exception:
            logger.exception("places fetch failed at (%.4f, %.4f)", request.lat, request.lng)
            raise

        # Time-agnostic filter at fetch radius; open-now applied per request below.
        filtered = _filter_candidates(raw, cache_radius, now_utc=None, strict_hours=False)
        filtered = _deduplicate(filtered)

        # Store raw dicts — no nav_url; distance_m is recomputed on every cache read.
        await cache.set_cached(request.lat, request.lng, cache_radius, filtered)

        all_places = [
            Place(
                name=c["name"], lat=c["lat"], lon=c["lon"],
                distance_m=c["distance_m"], amenity=c.get("amenity") or "restaurant",
                cuisine=c.get("cuisine"), opening_hours=c.get("opening_hours"),
                contact_phone=c.get("contact_phone"),
            )
            for c in filtered
        ]

    if not all_places:
        return []

    # Trim to the exact requested radius (cache tier may be larger).
    places: list[Place] = (
        [p for p in all_places if p.distance_m <= radius_m]
        if cache_radius > radius_m else all_places
    )
    if not places:
        return []

    # Open-now filter for the reference time (`when`, or current time for autopilot /
    # "now"). Applied here — not at fetch — so the fetch cache stays time-agnostic and
    # reusable across breakfast/lunch/dinner. `_is_open_now` is lenient on unknown OSM
    # hours (keeps them), so only explicitly-closed venues are dropped. If nothing is
    # open at that hour, keep the full set rather than show nothing.
    open_places = [p for p in places if _is_open_now(p.opening_hours, now_utc=now_utc)]
    if open_places:
        places = open_places

    # Mood-based distance cap: "quick" searches should only see walkable options
    if intent.mood == "quick":
        capped = [p for p in places if p.distance_m <= _QUICK_MOOD_MAX_M]
        if capped:
            places = capped

    # Venue type filter: if intent specifies types and enough exist, drop irrelevant ones
    # so AI focuses on what the user actually wants (bars when asking for cocktails, etc.)
    if intent.venue_types:
        intended = set(intent.venue_types)
        typed = [p for p in places if p.amenity in intended]
        if len(typed) >= 5:
            places = typed

    return sorted(places, key=lambda p: _quality_score(p, intent), reverse=True)[:30]


async def stream_search(
    request: SearchRequest,
    http_client: httpx.AsyncClient,
    ai_client: ChatGroq,
    preferences: UserPreferences | None = None,
) -> AsyncIterator[str]:
    radius_m = min(request.radius_m or settings.search_radius_m, settings.max_radius_m)
    now_utc = _parse_when_utc(request.when, request.lng)
    time_context = _local_time_str(request.lat, request.lng)

    # Parse intent first — determines which venue types to actually fetch (never raises)
    intent: PlaceIntent = await intent_parser.parse_intent(request.query, ai_client)
    yield _intent_event(intent, request.query)

    venue_types = [vt for vt in intent.venue_types if vt in VALID_AMENITIES] or [
        "restaurant", "cafe", "bar", "pub"
    ]

    try:
        places = await _prepare_places(request, radius_m, venue_types, intent, now_utc, http_client)
    except Exception:
        logger.exception("places fetch failed at (%.4f, %.4f)", request.lat, request.lng)
        yield _error_event("Could not load nearby places right now. Please try again shortly.")
        return

    if not places:
        yield _error_event("No suitable places found nearby.")
        return

    yield _place_event(places)

    if request.mode == "plan":
        # Pick the planner's candidate set with the cheap pre-sort score we already
        # use for the ordering above. The planner does its own semantic ranking (and
        # can expand the search via tools), so a second full LLM pre-rank here was
        # redundant — dropping it removes one Groq round-trip from every plan request.
        scored = sorted(
            ((p, _quality_score(p, intent)) for p in places),
            key=lambda x: -x[1],
        )[:15]
        plan_places = [p for p, _ in scored]
        pre_scores = [s for _, s in scored]

        # Bridge the agent's (slow) tool calls to SSE: the planner runs as a task and
        # pushes progress messages onto a queue we drain into the stream. A None
        # sentinel marks completion.
        progress_q: asyncio.Queue[str | None] = asyncio.Queue()

        async def _on_search(venue_types: list[str], radius_km: float) -> None:
            label = ", ".join(venue_types) or "more venues"
            await progress_q.put(
                _planning_event(f"Few good matches — expanding search ({label}, {radius_km:g}km)…")
            )

        async def _run_planner() -> list[PlanRecommendation]:
            try:
                return await planner.plan_places(
                    plan_places, request.query, intent,
                    request.group_size, ai_client,
                    budget=request.budget,
                    preferences=preferences, time_context=time_context, pre_scores=pre_scores,
                    http_client=http_client, lat=request.lat, lng=request.lng,
                    on_search=_on_search, lang=request.lang,
                )
            finally:
                await progress_q.put(None)

        planner_task = asyncio.create_task(_run_planner())
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _PLAN_TIMEOUT_S
        timed_out = False
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    msg = await asyncio.wait_for(progress_q.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    timed_out = True
                    break
                if msg is None:
                    break
                yield msg
            if timed_out:
                logger.warning(
                    "planner exceeded %.0fs budget for query %r — using fallback",
                    _PLAN_TIMEOUT_S, request.query,
                )
                recs = planner._fallback_recommendations(plan_places)
            else:
                recs = await planner_task
        except Exception:
            logger.exception("planner failed for query %r, using fallback", request.query)
            recs = planner._fallback_recommendations(plan_places)
        finally:
            # On timeout or client disconnect (GeneratorExit) the task would otherwise
            # keep running and burn Groq tokens — cancel it.
            if not planner_task.done():
                planner_task.cancel()

        if not recs:
            yield _no_match_event(request.query)
            return

        # The notice now reflects the planner's *final* fit scores (after any
        # search_more_places expansion) rather than a pre-rank guess — so we don't
        # warn "no exact match" when the agent actually found good options.
        relaxed = max((r.match_score for r in recs), default=0.0) < _PLAN_NO_MATCH_THRESHOLD
        yield _plan_recommendations_event(recs, notice=_relaxed_notice(intent) if relaxed else None)
        return

    try:
        ranked = await ranker.rank_places(
            places, request.query, intent, ai_client,
            preferences=preferences, time_context=time_context, lang=request.lang,
        )
    except Exception:
        logger.exception("ranker failed for query %r, using fallback", request.query)
        ranked = ranker._fallback_ranking(places)

    if not ranked or ranked[0].match_score < _no_match_threshold(len(ranked)):
        # Autopilot is one-tap — the user has no radius/query control, so "widen your
        # radius" advice is useless. Retry once at the max radius before giving up.
        if request.mode == "autopilot" and radius_m < settings.max_radius_m:
            radius_m = settings.max_radius_m
            try:
                wider = await _prepare_places(request, radius_m, venue_types, intent, now_utc, http_client)
            except Exception:
                logger.exception("widen fetch failed for query %r", request.query)
                wider = []
            if wider:
                places = wider
                yield _place_event(places)
                try:
                    ranked = await ranker.rank_places(
                        places, request.query, intent, ai_client,
                        preferences=preferences, time_context=time_context, lang=request.lang,
                    )
                except Exception:
                    logger.exception("ranker failed on widen for query %r, using fallback", request.query)
                    ranked = ranker._fallback_ranking(places)

        if not ranked or ranked[0].match_score < _no_match_threshold(len(ranked)):
            yield _no_match_event(request.query)
            return

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
