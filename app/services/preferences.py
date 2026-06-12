"""Render a user's taste profile into a compact prompt block.

Shared by the ranker and the planner so both describe the user the same way.
Lives outside the prompt .txt files because the text depends on which fields
the user actually filled in — empty fields produce no lines, so the model is
never told about preferences the user did not set.
"""

from app.models.profile import UserPreferences

_DIET_LABELS = {
    "vegetarian": "vegetarian",
    "vegan": "vegan",
    "pescatarian": "pescatarian",
    "halal": "halal",
    "kosher": "kosher",
    "gluten_free": "gluten-free",
    "lactose_free": "lactose-free",
}

_SPICE = {
    "none": "avoid spicy dishes and cuisines built around heat",
    "mild": "mild spice is fine, nothing extreme",
    "love": "loves bold, spicy food — lean into cuisines known for heat",
}

_STYLE = {
    "adventurous": (
        "adventurous eater — favor authentic, local, street-food and "
        "hole-in-the-wall spots over tourist-safe or chain options"
    ),
    "balanced": "open to both local discoveries and familiar comfort food",
    "familiar": (
        "prefers familiar, comfortable, well-reviewed places over very "
        "local or experimental ones"
    ),
}

_AVOID_LABELS = {
    "no_fast_food": "global fast-food chains",
    "no_seafood": "seafood",
    "no_raw": "raw fish / sushi",
    "no_pork": "pork",
    "no_very_spicy": "very spicy food",
    "no_offal": "offal / organ meat",
}

_DRINKS = {
    "wine": "appreciates a good wine list / wine bars",
    "craft_beer": "into craft beer",
    "cocktails": "enjoys cocktail bars",
    "specialty_coffee": "values specialty coffee",
    "no_alcohol": "no alcohol focus needed — alcohol-free friendly",
}

_CUISINE_LABELS = {
    "italian": "Italian", "japanese": "Japanese", "thai": "Thai",
    "chinese": "Chinese", "indian": "Indian", "mexican": "Mexican",
    "vietnamese": "Vietnamese", "korean": "Korean", "georgian": "Georgian",
    "mediterranean": "Mediterranean", "middle_eastern": "Middle Eastern",
    "french": "French", "american": "American", "spanish": "Spanish",
    "greek": "Greek", "turkish": "Turkish", "seafood": "Seafood",
    "bbq": "BBQ & grill",
}


def _labels(values: list[str], table: dict[str, str]) -> list[str]:
    return [table.get(v, v.replace("_", " ")) for v in values if v]


def build_preferences_block(preferences: UserPreferences | None) -> str:
    """Compact 'Diner profile' block for the LLM, or '' if nothing is set."""
    if not preferences:
        return ""

    lines: list[str] = []

    diet = _labels(preferences.diet, _DIET_LABELS)
    if diet:
        lines.append(
            f"- Dietary restrictions (MUST respect strictly): {', '.join(diet)}"
        )

    if preferences.spice in _SPICE:
        lines.append(f"- Spice: {_SPICE[preferences.spice]}")

    if preferences.adventure in _STYLE:
        lines.append(f"- Style: {_STYLE[preferences.adventure]}")

    liked = _labels(preferences.cuisines_liked, _CUISINE_LABELS)
    if liked:
        lines.append(
            "- Favorite cuisines (boost when they genuinely fit the occasion): "
            f"{', '.join(liked)}"
        )

    avoid = _labels(preferences.avoid, _AVOID_LABELS)
    if avoid:
        lines.append(
            f"- Deal-breakers (exclude or strongly downrank): {', '.join(avoid)}"
        )

    if preferences.cuisines_disliked:
        lines.append(
            f"- Also dislikes (downrank): {', '.join(preferences.cuisines_disliked)}"
        )

    drinks = _labels(preferences.drinks, _DRINKS)
    if drinks:
        lines.append(f"- Drinks: {'; '.join(drinks)}")

    if not lines:
        return ""

    return "\n## Diner profile (personalize picks to this person)\n" + "\n".join(lines)
