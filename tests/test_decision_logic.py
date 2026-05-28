import unittest
from datetime import UTC, datetime

from app.services.places_client import (
    _is_open_now,
    passes_min_quality_filters,
    score_candidate,
)


class DecisionLogicTests(unittest.TestCase):
    def test_open_now_filter_accepts_open_hours(self) -> None:
        candidate = {
            "distance_m": 300,
            "amenity": "restaurant",
            "opening_hours": "24/7",
        }
        current_time = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
        self.assertTrue(passes_min_quality_filters(candidate, now_utc=current_time))

    def test_open_now_filter_rejects_off_hours(self) -> None:
        candidate = {
            "distance_m": 300,
            "amenity": "restaurant",
            "opening_hours": "off",
        }
        current_time = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
        self.assertFalse(passes_min_quality_filters(candidate, now_utc=current_time))

    def test_is_open_now_returns_true_for_24_7(self) -> None:
        self.assertTrue(_is_open_now("24/7"))
        self.assertTrue(_is_open_now("24h"))

    def test_score_candidate_uses_weights(self) -> None:
        candidate = {
            "distance_m": 500,
            "cuisine": "thai",
            "opening_hours": "24/7",
            "contact_phone": "+1",
        }
        score = score_candidate(candidate, distance_weight=0.9, reliability_weight=0.1)
        self.assertGreater(score, 0.75)


if __name__ == "__main__":
    unittest.main()
