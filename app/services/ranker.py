import json
import logging
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from app.models.place import Place
from app.models.profile import UserPreferences
from app.models.search import PlaceIntent, RankedPlace
from app.services.preferences import build_preferences_block

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "ranking.txt").read_text()

_prompt = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", "{user_message}"),
])


class _RankedItem(BaseModel):
    place_index: int = Field(description="0-based index of this venue in the input list")
    match_score: float = Field(ge=0.0, le=1.0, description="Relevance score 0.0–1.0")
    reason: str = Field(description="1-2 sentences explaining why this venue fits the request")


class _RankingOutput(BaseModel):
    ranked: list[_RankedItem]


def _fallback_ranking(places: list[Place]) -> list[RankedPlace]:
    ranked = [
        RankedPlace(
            name=p.name,
            lat=p.lat,
            lon=p.lon,
            distance_m=p.distance_m,
            amenity=p.amenity,
            cuisine=p.cuisine,
            match_score=round(max(0.0, 1.0 - p.distance_m / 2500.0), 2),
            reason=f"Nearby {p.amenity} at ~{round(p.distance_m)}m.",
        )
        for p in places
    ]
    ranked.sort(key=lambda r: (-r.match_score, r.distance_m))
    return ranked


async def rank_places(
    places: list[Place],
    query: str,
    intent: PlaceIntent,
    llm: BaseChatModel,
    preferences: UserPreferences | None = None,
    time_context: str | None = None,
    lang: str = "en",
) -> list[RankedPlace]:
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
        }
        for i, p in enumerate(places)
    ]
    user_message = (
        f"User query: {query}\n"
        f"Intent: {intent.model_dump_json()}\n"
    )
    if time_context:
        user_message += f"Current local time: {time_context}\n"
    user_message += f"Venues: {json.dumps(places_payload, ensure_ascii=False)}"
    user_message += build_preferences_block(preferences)
    if lang and lang != "en":
        user_message += f"\n\nWrite every \"reason\" text in the language with ISO code '{lang}'."

    chain = (_prompt | llm.with_structured_output(_RankingOutput)).with_retry(stop_after_attempt=2)
    try:
        output: _RankingOutput = await chain.ainvoke({"user_message": user_message})
        ranked_items = output.ranked
    except Exception:
        logger.exception("ranking failed for query %r (%d places), using fallback", query, len(places))
        return _fallback_ranking(places)

    result: list[RankedPlace] = []
    seen: set[int] = set()
    for item in ranked_items:
        idx = item.place_index
        if idx < 0 or idx >= len(places) or idx in seen:
            continue
        seen.add(idx)
        p = places[idx]
        result.append(
            RankedPlace(
                name=p.name,
                lat=p.lat,
                lon=p.lon,
                distance_m=p.distance_m,
                amenity=p.amenity,
                cuisine=p.cuisine,
                match_score=round(float(item.match_score), 2),
                reason=item.reason,
            )
        )

    result.sort(key=lambda r: (-r.match_score, r.distance_m))
    return result
