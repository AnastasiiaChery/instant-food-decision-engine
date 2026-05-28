import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models.place import Place


def _make_places():
    return [
        Place(name="Place A", lat=50.45, lon=30.52, distance_m=120.0, amenity="restaurant", cuisine="thai", opening_hours="24/7"),
        Place(name="Place B", lat=50.451, lon=30.521, distance_m=200.0, amenity="restaurant", cuisine="asian", opening_hours="24/7"),
    ]


class TimingDebugTests(unittest.TestCase):
    def test_decide_returns_debug_timings_when_requested(self) -> None:
        with patch(
            "app.api.v1.routes.decide._places_client.fetch",
            new_callable=AsyncMock,
            return_value=_make_places(),
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/v1/decide",
                    json={"latitude": 50.4501, "longitude": 30.5234, "debug": True},
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("debug_timings_ms", data)
        timings = data["debug_timings_ms"]
        self.assertIn("fetch_candidates", timings)
        self.assertIn("filter_candidates", timings)
        self.assertIn("rank_candidates", timings)
        self.assertIn("total", timings)


if __name__ == "__main__":
    unittest.main()
