import json
from pathlib import Path

from openai import AsyncOpenAI

from app.models.place import Place
from app.models.search import PlaceIntent, RankedPlace

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "ranking.txt").read_text()

_RANK_PLACES_TOOL = {
    "type": "function",
    "function": {
        "name": "rank_places",
        "description": "Return all venues ranked by relevance to the user's query.",
        "parameters": {
            "type": "object",
            "properties": {
                "ranked": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "place_index": {"type": "integer", "description": "0-based index in the input list."},
                            "match_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                            "reason": {"type": "string", "description": "1-2 sentence explanation."},
                        },
                        "required": ["place_index", "match_score", "reason"],
                    },
                }
            },
            "required": ["ranked"],
        },
    },
}


def _nav_url(place: Place) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={place.lat},{place.lon}"


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
            nav_url=_nav_url(p),
        )
        for p in places
    ]
    ranked.sort(key=lambda r: (-r.match_score, r.distance_m))
    return ranked


async def rank_places(
    places: list[Place],
    query: str,
    intent: PlaceIntent,
    client: AsyncOpenAI,
    model: str,
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
        }
        for i, p in enumerate(places)
    ]
    user_message = (
        f"User query: {query}\n"
        f"Intent: {intent.model_dump_json()}\n"
        f"Venues: {json.dumps(places_payload, ensure_ascii=False)}"
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            tools=[_RANK_PLACES_TOOL],
            tool_choice={"type": "function", "function": {"name": "rank_places"}},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        tool_call = response.choices[0].message.tool_calls[0]
        args = json.loads(tool_call.function.arguments)
        ranked_items = args["ranked"]
    except Exception:
        return _fallback_ranking(places)

    result: list[RankedPlace] = []
    seen: set[int] = set()
    for item in ranked_items:
        idx = item.get("place_index", -1)
        if not isinstance(idx, int) or idx < 0 or idx >= len(places) or idx in seen:
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
                match_score=round(float(item.get("match_score", 0.5)), 2),
                reason=item.get("reason", ""),
                nav_url=_nav_url(p),
            )
        )

    # append any places the AI skipped (shouldn't happen, but be safe)
    for i, p in enumerate(places):
        if i not in seen:
            result.append(
                RankedPlace(
                    name=p.name, lat=p.lat, lon=p.lon, distance_m=p.distance_m,
                    amenity=p.amenity, cuisine=p.cuisine,
                    match_score=0.0, reason="Not ranked by AI.",
                    nav_url=_nav_url(p),
                )
            )

    # relevance first, distance as tiebreaker
    result.sort(key=lambda r: (-r.match_score, r.distance_m))
    return result
