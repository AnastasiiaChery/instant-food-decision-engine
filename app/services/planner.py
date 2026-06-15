import json
import logging
from collections.abc import Awaitable, Callable

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.models.place import Place
from app.models.profile import UserPreferences
from app.models.search import PlaceInfo, PlaceIntent, PlanRecommendation
from app.services.places_client import VALID_AMENITIES, _deduplicate, _fetch_raw
from app.services.preferences import build_preferences_block
from app.services.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("plan.txt")

_prompt = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", "{user_message}"),
])

_MAX_SEARCH_CALLS = 2
_MAX_AGENT_STEPS = 6


# --- Pydantic models ---

class _PlanItem(BaseModel):
    place_index: int = Field(description="0-based index in the input venues list")
    match_score: float = Field(ge=0.0, le=1.0)
    reason: str
    scenario: str


class _PlanOutput(BaseModel):
    recommendations: list[_PlanItem] = Field(max_length=8, description="Top 5-8 curated picks, best first")


class _SearchMoreArgs(BaseModel):
    venue_types: list[str] = Field(
        description=(
            "OSM amenity types to search for. Valid values: "
            "restaurant, cafe, bar, pub, biergarten, wine_bar, cocktail_bar, "
            "juice_bar, fast_food, food_court, ice_cream, food_hall, taproom."
        )
    )
    radius_km: float = Field(
        ge=0.3, le=5.0,
        description="Search radius in km. Start with 1.5 for modest expansion, use 3.0+ only when needed.",
    )


class _FinalizePlanItem(BaseModel):
    place_index: int = Field(
        description="0-based index in the venues list (includes any venues added by search_more_places)"
    )
    match_score: float = Field(ge=0.0, le=1.0, description="How well this venue fits occasion and group (0.0–1.0)")
    reason: str = Field(description="Format: '[X-min walk] · [cuisine/type] · [why it fits THIS occasion/group]'")
    scenario: str = Field(description="Short factual label (4–6 words), e.g. 'Thai street kitchen · 3 min'")


class _FinalizePlanArgs(BaseModel):
    recommendations: list[_FinalizePlanItem] = Field(
        min_length=1, max_length=8,
        description="Top 5–8 curated picks, best first",
    )


# --- Tool stubs (schemas only — execution is handled manually in the agent loop) ---

def _noop(*args, **kwargs) -> str:
    return "ok"


_SEARCH_TOOL = StructuredTool.from_function(
    func=_noop,
    name="search_more_places",
    description=(
        "Search for additional venues when the current list lacks suitable options for the occasion. "
        "Use when there are no quiet restaurants for a romantic dinner, no venues with capacity for a large group, "
        "or no matching cuisine type. New venues are appended to the list with new indices."
    ),
    args_schema=_SearchMoreArgs,
)

_FINALIZE_TOOL = StructuredTool.from_function(
    func=_noop,
    name="finalize_plan",
    description=(
        "Submit your final curated plan. Call this when you have chosen the best venues. "
        "You MUST call this tool to complete the task — do not output JSON directly."
    ),
    args_schema=_FinalizePlanArgs,
)


# --- Tool execution ---

async def _do_search(
    venue_types: list[str],
    radius_km: float,
    lat: float,
    lng: float,
    http_client: httpx.AsyncClient,
    all_places: list[Place],
    known_keys: set[str],
) -> str:
    valid_types = [t for t in venue_types if t in VALID_AMENITIES][:8]
    if not valid_types:
        return (
            "No valid venue types provided. "
            "Valid: restaurant, cafe, bar, pub, biergarten, wine_bar, cocktail_bar, fast_food, food_court."
        )

    radius_m = min(int(radius_km * 1000), 5000)

    try:
        raw = await _fetch_raw(lat, lng, valid_types, radius_m, http_client)
    except Exception as exc:
        return f"Search failed: {exc}"

    raw = _deduplicate(raw)
    new_items = [
        c for c in raw
        if f"{c['name'].lower()}|{c['lat']:.5f}|{c['lon']:.5f}" not in known_keys
    ][:15]

    if not new_items:
        return (
            f"No new venues found for types={valid_types} within {radius_km}km. "
            "Try different venue types or a larger radius."
        )

    start_idx = len(all_places)
    for c in new_items:
        known_keys.add(f"{c['name'].lower()}|{c['lat']:.5f}|{c['lon']:.5f}")
        all_places.append(Place(
            name=c["name"],
            lat=c["lat"],
            lon=c["lon"],
            distance_m=c["distance_m"],
            amenity=c["amenity"] or "restaurant",
            cuisine=c.get("cuisine"),
            opening_hours=c.get("opening_hours"),
        ))

    entries = [
        {
            "index": start_idx + i,
            "name": c["name"],
            "amenity": c["amenity"],
            "cuisine": c.get("cuisine"),
            "distance_m": round(c["distance_m"]),
        }
        for i, c in enumerate(new_items)
    ]
    return (
        f"Found {len(new_items)} new venues. Total list now has {len(all_places)} venues.\n"
        f"New entries:\n{json.dumps(entries, ensure_ascii=False)}"
    )


# --- Agent loop ---

async def _run_tool_agent(
    user_message: str,
    all_places: list[Place],
    known_keys: set[str],
    llm: BaseChatModel,
    http_client: httpx.AsyncClient,
    lat: float,
    lng: float,
    on_search: Callable[[list[str], float], Awaitable[None]] | None = None,
    max_radius_km: float | None = None,
) -> list[_FinalizePlanItem] | None:
    llm_with_tools = llm.bind_tools([_SEARCH_TOOL, _FINALIZE_TOOL])
    messages: list = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_message)]
    search_calls = 0

    for step in range(_MAX_AGENT_STEPS):
        response: AIMessage | None = None
        for attempt in range(3):
            try:
                response = await llm_with_tools.ainvoke(messages)
                break
            except Exception as exc:
                # Groq raises BadRequestError(code="tool_use_failed") when the model
                # emits a malformed tool call — that's retriable. Detect it duck-typed
                # (via the error code) so the planner stays provider-agnostic; any other
                # error, or other providers' errors, propagate as before.
                if getattr(exc, "code", None) == "tool_use_failed" and attempt < 2:
                    logger.warning(
                        "planner: tool_use_failed on step %d attempt %d, retrying", step, attempt
                    )
                    continue
                raise
        assert response is not None
        messages.append(response)

        if not response.tool_calls:
            logger.warning("planner agent: no tool call at step %d", step)
            return None

        for tc in response.tool_calls:
            name, tc_id, args = tc["name"], tc["id"], tc["args"]

            if name == "finalize_plan":
                try:
                    return [_FinalizePlanItem(**item) for item in args.get("recommendations", [])]
                except Exception:
                    logger.exception("finalize_plan validation failed: %s", args)
                    return None

            if name == "search_more_places":
                if search_calls >= _MAX_SEARCH_CALLS:
                    content = (
                        f"Search limit reached ({_MAX_SEARCH_CALLS} calls). "
                        "Please call finalize_plan now with the venues you have."
                    )
                else:
                    search_calls += 1
                    # Honour the user's radius as a hard ceiling — the agent must never
                    # widen the search beyond what the user explicitly set.
                    req_radius = float(args.get("radius_km", 1.5))
                    radius_km = min(req_radius, max_radius_km) if max_radius_km else req_radius
                    if on_search is not None:
                        try:
                            await on_search(args.get("venue_types", []), radius_km)
                        except Exception:
                            logger.exception("on_search progress callback failed")
                    content = await _do_search(
                        venue_types=args.get("venue_types", []),
                        radius_km=radius_km,
                        lat=lat,
                        lng=lng,
                        http_client=http_client,
                        all_places=all_places,
                        known_keys=known_keys,
                    )
                messages.append(ToolMessage(content=content, tool_call_id=tc_id))

            else:
                messages.append(ToolMessage(content=f"Unknown tool: {name}", tool_call_id=tc_id))

    logger.warning("planner agent reached max steps without calling finalize_plan")
    return None


# --- Helpers ---

def _build_user_message(
    query: str,
    group_size: str | None,
    budget: str | None,
    intent: PlaceIntent,
    time_context: str | None,
    places: list[Place],
    pre_scores: list[float] | None,
    preferences: UserPreferences | None,
    with_tools: bool = False,
    lang: str = "en",
    max_radius_km: float | None = None,
) -> str:
    places_payload = [
        {
            "index": i,
            "name": p.name,
            "amenity": p.amenity,
            "cuisine": p.cuisine,
            "distance_m": round(p.distance_m),
            "opening_hours": p.opening_hours,
            **({"relevance_score": round(pre_scores[i], 2)} if pre_scores and i < len(pre_scores) else {}),
        }
        for i, p in enumerate(places)
    ]
    msg = (
        f"User query: {query or 'something good nearby'}\n"
        f"Group size: {group_size or 'solo'}\n"
        f"Budget: {budget or 'any'}\n"
        f"Intent: {intent.model_dump_json()}\n"
    )
    if time_context:
        msg += f"Current local time: {time_context}\n"
    msg += f"Venues ({len(places)} total): {json.dumps(places_payload, ensure_ascii=False)}"
    msg += build_preferences_block(preferences)
    if lang and lang != "en":
        msg += (
            f"\n\nWrite every \"reason\" and \"scenario\" text in the language with "
            f"ISO code '{lang}'. Keep place names in their original form."
        )
    if with_tools:
        msg += (
            "\n\nIf the current venue list lacks suitable options for this occasion and group, "
            "call search_more_places to expand the search before finalizing. "
            "When ready, call finalize_plan with your recommendations."
        )
        if max_radius_km is not None:
            msg += (
                f"\nThe user set a search radius of {max_radius_km:g}km — never call "
                f"search_more_places with a radius_km above {max_radius_km:g}. If nothing "
                "suitable exists within that radius, finalize with the best of what you have."
            )
    return msg


def _fallback_recommendations(places: list[Place]) -> list[PlanRecommendation]:
    top = sorted(places, key=lambda p: p.distance_m)[:8]
    return [
        PlanRecommendation(
            place=PlaceInfo(
                name=p.name, lat=p.lat, lon=p.lon,
                distance_m=round(p.distance_m), amenity=p.amenity, cuisine=p.cuisine,
            ),
            reason=f"Nearby {p.amenity} at ~{round(p.distance_m)}m.",
            scenario="Quick option",
            match_score=round(max(0.0, 1.0 - p.distance_m / 2500.0), 2),
        )
        for p in top
    ]


# --- Public API ---

async def plan_places(
    places: list[Place],
    query: str,
    intent: PlaceIntent,
    group_size: str | None,
    llm: BaseChatModel,
    budget: str | None = None,
    preferences: UserPreferences | None = None,
    time_context: str | None = None,
    pre_scores: list[float] | None = None,
    http_client: httpx.AsyncClient | None = None,
    lat: float | None = None,
    lng: float | None = None,
    on_search: Callable[[list[str], float], Awaitable[None]] | None = None,
    lang: str = "en",
    max_radius_km: float | None = None,
) -> list[PlanRecommendation]:
    if not places:
        return []

    all_places: list[Place] = list(places)
    known_keys: set[str] = {f"{p.name.lower()}|{p.lat:.5f}|{p.lon:.5f}" for p in all_places}
    can_search = http_client is not None and lat is not None and lng is not None

    user_message = _build_user_message(
        query, group_size, budget, intent, time_context,
        all_places, pre_scores, preferences, with_tools=can_search, lang=lang,
        max_radius_km=max_radius_km,
    )

    items: list[_FinalizePlanItem] | None = None

    if can_search:
        try:
            items = await _run_tool_agent(
                user_message, all_places, known_keys, llm, http_client, lat, lng,
                on_search=on_search, max_radius_km=max_radius_km,
            )
        except Exception:
            logger.exception("tool agent failed for query %r, falling back to simple chain", query)

    if items is None:
        # The fallback chain has no tools bound — rebuild the message without the
        # "call search_more_places / finalize_plan" instructions so we don't ask
        # the model to call tools it can't see.
        chain_message = (
            _build_user_message(
                query, group_size, budget, intent, time_context,
                all_places, pre_scores, preferences, with_tools=False, lang=lang,
            )
            if can_search
            else user_message
        )
        chain = (_prompt | llm.with_structured_output(_PlanOutput)).with_retry(stop_after_attempt=2)
        try:
            output: _PlanOutput = await chain.ainvoke({"user_message": chain_message})
            items = [
                _FinalizePlanItem(
                    place_index=item.place_index,
                    match_score=item.match_score,
                    reason=item.reason,
                    scenario=item.scenario,
                )
                for item in output.recommendations
            ]
        except Exception:
            logger.exception("planning chain failed for query %r (%d places), using fallback", query, len(places))
            return _fallback_recommendations(places)

    result: list[PlanRecommendation] = []
    seen: set[int] = set()
    for item in items:
        idx = item.place_index
        if idx < 0 or idx >= len(all_places) or idx in seen:
            continue
        seen.add(idx)
        p = all_places[idx]
        result.append(PlanRecommendation(
            place=PlaceInfo(
                name=p.name, lat=p.lat, lon=p.lon,
                distance_m=round(p.distance_m), amenity=p.amenity, cuisine=p.cuisine,
            ),
            reason=item.reason,
            scenario=item.scenario,
            match_score=round(float(item.match_score), 2),
        ))

    return result if result else _fallback_recommendations(places)
