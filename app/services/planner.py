import json
import logging
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from app.models.place import Place
from app.models.profile import UserPreferences
from app.models.search import PlaceInfo, PlaceIntent, PlanRecommendation

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "plan.txt").read_text()

_prompt = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", "{user_message}"),
])


class _PlanItem(BaseModel):
    place_index: int = Field(description="0-based index in the input venues list")
    match_score: float = Field(ge=0.0, le=1.0, description="Relevance score for this occasion and group")
    reason: str = Field(description="1-2 sentences explaining why this place fits the occasion and group")
    scenario: str = Field(description="Short label: 'Best match', 'Romantic spot', 'Great for groups', 'Hidden gem', 'Celebration pick', 'Business dinner', 'Quick option', 'Local favourite'")


class _PlanOutput(BaseModel):
    recommendations: list[_PlanItem] = Field(max_length=5, description="Top 3-5 curated picks, best first")


def _fallback_recommendations(places: list[Place]) -> list[PlanRecommendation]:
    top = sorted(places, key=lambda p: p.distance_m)[:5]
    return [
        PlanRecommendation(
            place=PlaceInfo(
                name=p.name, lat=p.lat, lon=p.lon,
                distance_m=round(p.distance_m), amenity=p.amenity, cuisine=p.cuisine,
            ),
            reason=f"Nearby {p.amenity} at ~{round(p.distance_m)}m.",
            scenario="Quick option",
        )
        for p in top
    ]


async def plan_places(
    places: list[Place],
    query: str,
    intent: PlaceIntent,
    group_size: str | None,
    occasion: str | None,
    llm: ChatGroq,
    preferences: UserPreferences | None = None,
    time_context: str | None = None,
    pre_scores: list[float] | None = None,
) -> list[PlanRecommendation]:
    if not places:
        return []

    places_payload = [
        {
            "index": i,
            "name": p.name,
            "amenity": p.amenity,
            "cuisine": p.cuisine,
            "distance_m": round(p.distance_m),
            "opening_hours": p.opening_hours,
            **({"relevance_score": round(pre_scores[i], 2)} if pre_scores else {}),
        }
        for i, p in enumerate(places)
    ]
    user_message = (
        f"User query: {query or 'something good nearby'}\n"
        f"Occasion: {occasion or 'casual'}\n"
        f"Group size: {group_size or 'solo'}\n"
        f"Intent: {intent.model_dump_json()}\n"
    )
    if time_context:
        user_message += f"Current local time: {time_context}\n"
    user_message += f"Venues ({len(places)} total): {json.dumps(places_payload, ensure_ascii=False)}"
    if preferences:
        if preferences.diet:
            user_message += f"\nUser dietary restrictions (apply strictly): {', '.join(preferences.diet)}"
        if preferences.cuisines_liked:
            user_message += f"\nCuisines this user loves: {', '.join(preferences.cuisines_liked)}"
        if preferences.cuisines_disliked:
            user_message += f"\nCuisines this user dislikes (avoid if possible): {', '.join(preferences.cuisines_disliked)}"

    chain = (_prompt | llm.with_structured_output(_PlanOutput)).with_retry(stop_after_attempt=2)
    try:
        output: _PlanOutput = await chain.ainvoke({"user_message": user_message})
    except Exception:
        logger.exception("planning failed for query %r (%d places), using fallback", query, len(places))
        return _fallback_recommendations(places)

    result: list[PlanRecommendation] = []
    seen: set[int] = set()
    for item in output.recommendations:
        idx = item.place_index
        if idx < 0 or idx >= len(places) or idx in seen:
            continue
        seen.add(idx)
        p = places[idx]
        result.append(PlanRecommendation(
            place=PlaceInfo(
                name=p.name, lat=p.lat, lon=p.lon,
                distance_m=round(p.distance_m), amenity=p.amenity, cuisine=p.cuisine,
            ),
            reason=item.reason,
            scenario=item.scenario,
        ))

    return result if result else _fallback_recommendations(places)
