import unittest

from app.models.search import PlaceIntent
from app.services.search_service import _matches_cuisine


def _intent(cuisine: list[str] | None) -> PlaceIntent:
    return PlaceIntent(
        venue_types=["restaurant"],
        mood="casual",
        price_level=[],
        features=[],
        cuisine=cuisine,
    )


class CuisineGateTests(unittest.TestCase):
    def test_no_requested_cuisine_always_matches(self) -> None:
        # No cuisine constraint → every venue trivially "matches" (gate stays off).
        self.assertTrue(_matches_cuisine("Le Choupinet", "french", _intent(None)))

    def test_tag_match(self) -> None:
        intent = _intent(["ukrainian"])
        self.assertTrue(_matches_cuisine("Borsch House", "ukrainian", intent))
        self.assertTrue(_matches_cuisine("Mixed", "eastern_european;ukrainian", intent))

    def test_wrong_cuisine_tag_does_not_match(self) -> None:
        # The trace bug: mediterranean/tapas/italian venues for a ukrainian request.
        intent = _intent(["ukrainian"])
        self.assertFalse(_matches_cuisine("Kehribar", "mediterranean", intent))
        self.assertFalse(_matches_cuisine("Ma Cachette", "tapas", intent))
        self.assertFalse(_matches_cuisine("Jardin des Pâtes", "pasta;italian", intent))

    def test_name_hint_when_tag_absent(self) -> None:
        intent = _intent(["ukrainian"])
        self.assertTrue(_matches_cuisine("Ukrainian Kitchen", None, intent))
        self.assertFalse(_matches_cuisine("Le Petit Cluny", None, intent))

    def test_name_hint_ignored_when_tag_present(self) -> None:
        # A wrong tag is authoritative even if the name happens to contain the word.
        intent = _intent(["ukrainian"])
        self.assertFalse(_matches_cuisine("Ukrainian-style Bistro", "french", intent))


if __name__ == "__main__":
    unittest.main()
