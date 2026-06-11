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

    def test_is_open_now_respects_opening_hours(self) -> None:
        thu_0900 = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)   # Thursday
        thu_1700 = datetime(2026, 6, 11, 17, 0, tzinfo=UTC)
        sun_1100 = datetime(2026, 6, 14, 11, 0, tzinfo=UTC)  # Sunday
        sun_1300 = datetime(2026, 6, 14, 13, 0, tzinfo=UTC)
        late_0100 = datetime(2026, 6, 11, 1, 0, tzinfo=UTC)

        # A dinner-only venue must be CLOSED at breakfast — this was the regression
        # where _is_open_now always returned True for out-of-hours times.
        self.assertFalse(_is_open_now("Tu-Su 16:00-23:00", now_utc=thu_0900))
        self.assertTrue(_is_open_now("Tu-Su 16:00-23:00", now_utc=thu_1700))
        self.assertFalse(_is_open_now("Mo-Su 10:00-18:00", now_utc=thu_0900))
        self.assertTrue(_is_open_now("Mo-Su 08:00-21:00", now_utc=thu_0900))

        # Per-day segments
        self.assertFalse(
            _is_open_now("Mo-Th 10:00-22:00; Fr-Su 11:00-23:00", now_utc=thu_0900)
        )
        self.assertTrue(
            _is_open_now("Mo-Sa 10:00-23:00; Su 12:00-23:00", now_utc=sun_1300)
        )
        self.assertFalse(
            _is_open_now("Mo-Sa 10:00-23:00; Su 12:00-23:00", now_utc=sun_1100)
        )

        # Overnight span crossing midnight
        self.assertTrue(_is_open_now("Mo-Su 14:00-02:00", now_utc=late_0100))

        # Explicit closed markers
        self.assertFalse(_is_open_now("off", now_utc=thu_0900))
        self.assertFalse(_is_open_now("closed", now_utc=thu_0900))

        # Unknown / not-listed today → stay lenient (don't over-filter)
        self.assertTrue(_is_open_now(None, now_utc=thu_0900))
        self.assertTrue(_is_open_now("Mo-Fr 09:00-17:00", now_utc=sun_1300))

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
