from pydantic import BaseModel


class UserPreferences(BaseModel):
    """A user's durable taste profile.

    Stored as JSON on the user row, so adding fields is backward-compatible:
    older records simply fall back to the defaults below. `cuisines_disliked`
    is the legacy free-text field — kept so existing users' data is still
    honored, but no longer written by the UI (replaced by structured `avoid`).
    """

    diet: list[str] = []            # hard constraints: vegetarian, vegan, halal…
    spice: str | None = None        # "none" | "mild" | "love"
    adventure: str | None = None    # "adventurous" | "balanced" | "familiar"
    cuisines_liked: list[str] = []  # canonical cuisine slugs (italian, thai…)
    avoid: list[str] = []           # deal-breaker slugs (no_fast_food, no_seafood…)
    drinks: list[str] = []          # wine, craft_beer, cocktails, specialty_coffee, no_alcohol
    cuisines_disliked: list[str] = []  # legacy free-text, still honored if present
