import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services.places_client import OVERPASS_URLS, _fetch_raw


def _fake_response(payload: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def _error_response() -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "error",
        request=httpx.Request("POST", "https://example.com"),
        response=httpx.Response(500),
    )
    return resp


class OverpassResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_fallback_endpoint_when_primary_raises(self) -> None:
        async def mock_post(url: str, **kwargs):
            if "primary" in url:
                raise httpx.ConnectError("primary down")
            return _fake_response({
                "elements": [{
                    "lat": 50.45, "lon": 30.52,
                    "tags": {"name": "Fallback Place", "amenity": "restaurant"},
                }]
            })

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = mock_post

        with patch("app.services.places_client.OVERPASS_URLS", ["https://primary", "https://backup"]):
            candidates = await _fetch_raw(50.4501, 30.5234, ["restaurant"], 2000, client)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["name"], "Fallback Place")

    async def test_sends_query_in_data_field(self) -> None:
        captured: dict = {}

        async def mock_post(url: str, **kwargs):
            captured.update(kwargs)
            return _fake_response({"elements": []})

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = mock_post

        await _fetch_raw(50.4501, 30.5234, ["restaurant"], 2000, client)

        self.assertIn("data", captured)
        self.assertIn("data", captured["data"])

    async def test_skips_non_json_response_and_uses_next_endpoint(self) -> None:
        async def mock_post(url: str, **kwargs):
            if "primary" in url:
                resp = MagicMock()
                resp.raise_for_status = MagicMock()
                resp.json.side_effect = ValueError("not json")
                return resp
            return _fake_response({
                "elements": [{
                    "lat": 50.45, "lon": 30.52,
                    "tags": {"name": "Valid After Invalid", "amenity": "restaurant"},
                }]
            })

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = mock_post

        with patch("app.services.places_client.OVERPASS_URLS", ["https://primary", "https://backup"]):
            candidates = await _fetch_raw(50.4501, 30.5234, ["restaurant"], 2000, client)

        self.assertEqual(candidates[0]["name"], "Valid After Invalid")


if __name__ == "__main__":
    unittest.main()
