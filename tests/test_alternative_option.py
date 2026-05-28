import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models.place import Place


def _place(name, lat, lon, distance_m, cuisine="thai"):
    return Place(
        name=name, lat=lat, lon=lon, distance_m=distance_m,
        amenity="restaurant", cuisine=cuisine, opening_hours="24/7", contact_phone="+1",
    )


class AlternativeOptionTests(unittest.TestCase):
    def test_another_option_skips_duplicate_top_place(self) -> None:
        places = [
            _place("Same Place", 50.4501, 30.5234, 200.0),
            _place("Same Place", 50.4501, 30.5234, 200.0),
            _place("Different Place", 50.4510, 30.5240, 300.0, cuisine="asian"),
        ]
        # deduplicate happens inside OverpassPlacesClient.fetch already,
        # but the route uses _deduplicate via the client — simulate post-dedup result
        deduped = [places[0], places[2]]

        with patch(
            "app.api.v1.routes.decide._places_client.fetch",
            new_callable=AsyncMock,
            return_value=deduped,
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/v1/decide",
                    json={"latitude": 50.4501, "longitude": 30.5234},
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["recommended_place"]["name"], "Same Place")
        self.assertEqual(data["another_option"]["name"], "Different Place")

    def test_decide_respects_excluded_keys_for_next_option_request(self) -> None:
        places = [
            _place("Same Place", 50.4501, 30.5234, 200.0),
            _place("Different Place", 50.4510, 30.5240, 300.0, cuisine="asian"),
        ]

        with patch(
            "app.api.v1.routes.decide._places_client.fetch",
            new_callable=AsyncMock,
            return_value=places,
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/v1/decide",
                    json={
                        "latitude": 50.4501,
                        "longitude": 30.5234,
                        "exclude_keys": ["same place|50.45010|30.52340"],
                    },
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["recommended_place"]["name"], "Different Place")


if __name__ == "__main__":
    unittest.main()
