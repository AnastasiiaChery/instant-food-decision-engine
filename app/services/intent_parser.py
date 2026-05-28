import json
from pathlib import Path

from openai import AsyncOpenAI

from app.models.search import PlaceIntent

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "intent.txt").read_text()

_PARSE_INTENT_TOOL = {
    "type": "function",
    "function": {
        "name": "parse_search_intent",
        "description": "Extract structured search intent from a user's free-text food venue request.",
        "parameters": {
            "type": "object",
            "properties": {
                "venue_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["restaurant", "fast_food", "cafe"]},
                    "description": "Types of venues the user is looking for.",
                },
                "mood": {
                    "type": "string",
                    "description": "Atmosphere or mood the user wants (e.g. 'cozy', 'lively', 'quiet').",
                },
                "price_level": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1, "maximum": 4},
                    "description": "Acceptable price levels (1=cheap, 4=upscale).",
                },
                "features": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific features requested (e.g. 'terrace', 'wifi', 'parking').",
                },
                "time_sensitivity": {
                    "type": "string",
                    "description": "Whether the user needs somewhere open right now or is planning ahead.",
                },
            },
            "required": ["venue_types", "mood", "price_level", "features", "time_sensitivity"],
        },
    },
}

_DEFAULT_INTENT = PlaceIntent(
    venue_types=["restaurant", "cafe"],
    mood="casual",
    price_level=[1, 2, 3],
    features=[],
    time_sensitivity="right now",
)


async def parse_intent(query: str, client: AsyncOpenAI, model: str) -> PlaceIntent:
    try:
        response = await client.chat.completions.create(
            model=model,
            tools=[_PARSE_INTENT_TOOL],
            tool_choice={"type": "function", "function": {"name": "parse_search_intent"}},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
        )
        tool_call = response.choices[0].message.tool_calls[0]
        args = json.loads(tool_call.function.arguments)
        return PlaceIntent(**args)
    except Exception:
        return _DEFAULT_INTENT
