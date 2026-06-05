import re
from datetime import UTC, datetime
from math import asin, cos, radians, sin, sqrt
from typing import Any, Protocol

import httpx
from fastapi import HTTPException

from app.models.place import Place

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
VALID_AMENITIES = {"restaurant", "fast_food", "cafe", "bar", "pub", "biergarten", "food_court"}


class PlacesClient(Protocol):
    async def fetch(
        self,
        lat: float,
        lng: float,
        venue_types: list[str],
        radius_m: int,
        http_client: httpx.AsyncClient,
    ) -> list[Place]: ...


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(a))


def _is_open_now(opening_hours: str | None, now_utc: datetime | None = None) -> bool:
    if not opening_hours:
        return True
    normalized = opening_hours.strip().lower()
    if normalized in {"24/7", "24h"}:
        return True
    if "off" in normalized or "closed" in normalized:
        return False

    current = now_utc or datetime.now(UTC)
    day_token = ["mo", "tu", "we", "th", "fr", "sa", "su"][current.weekday()]
    current_minutes = current.hour * 60 + current.minute

    for segment in normalized.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        if day_token not in segment and "-" not in segment:
            continue
        matches = re.findall(r"(\d{2}):(\d{2})-(\d{2}):(\d{2})", segment)
        for h1, m1, h2, m2 in matches:
            start = int(h1) * 60 + int(m1)
            end = int(h2) * 60 + int(m2)
            if start <= current_minutes <= end:
                return True

    return True


def _candidate_key(candidate: dict[str, Any]) -> str:
    return (
        f"{candidate.get('name', '').strip().lower()}|"
        f"{float(candidate.get('lat', 0.0)):.5f}|"
        f"{float(candidate.get('lon', 0.0)):.5f}"
    )


def _deduplicate(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in candidates:
        key = _candidate_key(c)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def _build_overpass_query(lat: float, lon: float, venue_types: list[str], radius_m: int) -> str:
    amenity_regex = "|".join(venue_types)
    return f"""
[out:json][timeout:12];
(
  node["amenity"~"{amenity_regex}"](around:{radius_m},{lat},{lon});
  way["amenity"~"{amenity_regex}"](around:{radius_m},{lat},{lon});
);
out center tags;
"""


def _parse_elements(elements: list[dict], lat: float, lon: float) -> list[dict[str, Any]]:
    candidates = []
    for element in elements:
        tags = element.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        c_lat = element.get("lat") or element.get("center", {}).get("lat")
        c_lon = element.get("lon") or element.get("center", {}).get("lon")
        if c_lat is None or c_lon is None:
            continue
        candidates.append({
            "name": name,
            "lat": float(c_lat),
            "lon": float(c_lon),
            "distance_m": _distance_m(lat, lon, float(c_lat), float(c_lon)),
            "amenity": tags.get("amenity"),
            "cuisine": tags.get("cuisine"),
            "opening_hours": tags.get("opening_hours"),
            "contact_phone": tags.get("phone"),
        })
    return candidates


_HEADERS = {"User-Agent": "instant-food-decision-engine/1.0"}


async def _fetch_raw(
    lat: float,
    lon: float,
    venue_types: list[str],
    radius_m: int,
    http_client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    query = _build_overpass_query(lat, lon, venue_types, radius_m)
    last_error: Exception | None = None
    for url in OVERPASS_URLS:
        try:
            response = await http_client.post(url, data={"data": query}, headers=_HEADERS, timeout=15.0)
            response.raise_for_status()
            parsed = response.json()
            if not isinstance(parsed, dict):
                raise ValueError("Overpass response is not a JSON object")
            return _parse_elements(parsed.get("elements", []), lat, lon)
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            continue
    raise HTTPException(status_code=502, detail=f"All Overpass endpoints failed: {last_error}")


def _is_explicitly_closed(opening_hours: str | None) -> bool:
    if not opening_hours:
        return False
    normalized = opening_hours.strip().lower()
    return normalized in {"off", "closed", "no"}


def _metadata_score(c: dict[str, Any]) -> float:
    """Proxy for quality: more OSM metadata = more reliable place."""
    return sum([
        bool(c.get("cuisine")),
        bool(c.get("opening_hours")),
        bool(c.get("contact_phone")),
    ]) / 3.0


class OverpassPlacesClient:
    async def fetch(
        self,
        lat: float,
        lng: float,
        venue_types: list[str],
        radius_m: int,
        http_client: httpx.AsyncClient,
        max_radius_m: int | None = None,
        now_utc: datetime | None = None,
    ) -> list[Place]:
        candidates = await _fetch_raw(lat, lng, venue_types, radius_m, http_client)
        filtered = self._filter(candidates, radius_m, now_utc, strict_hours=True)
        filtered = _deduplicate(filtered)

        # expand radius if too few results
        if len(filtered) < 5 and max_radius_m and max_radius_m > radius_m:
            candidates = await _fetch_raw(lat, lng, venue_types, max_radius_m, http_client)
            filtered = self._filter(candidates, max_radius_m, now_utc, strict_hours=True)
            filtered = _deduplicate(filtered)

        # fallback: relax "open now" — keep everything except explicitly closed
        if not filtered:
            candidates = await _fetch_raw(lat, lng, venue_types, max_radius_m or radius_m, http_client)
            filtered = self._filter(candidates, max_radius_m or radius_m, now_utc, strict_hours=False)
            filtered = _deduplicate(filtered)

        return [
            Place(
                name=c["name"],
                lat=c["lat"],
                lon=c["lon"],
                distance_m=c["distance_m"],
                amenity=c["amenity"] or "restaurant",
                cuisine=c.get("cuisine"),
                opening_hours=c.get("opening_hours"),
                contact_phone=c.get("contact_phone"),
            )
            for c in filtered
        ]

    def _filter(
        self,
        candidates: list[dict],
        max_distance_m: int,
        now_utc: datetime | None,
        strict_hours: bool = True,
    ) -> list[dict]:
        result = []
        for c in candidates:
            if c["distance_m"] > max_distance_m:
                continue
            if c.get("amenity") not in VALID_AMENITIES:
                continue
            if _is_explicitly_closed(c.get("opening_hours")):
                continue
            if strict_hours and not _is_open_now(c.get("opening_hours"), now_utc=now_utc):
                continue
            result.append(c)
        return result


def passes_min_quality_filters(
    candidate: dict[str, Any], max_distance_m: int = 2500, now_utc: datetime | None = None
) -> bool:
    return (
        candidate["distance_m"] <= max_distance_m
        and candidate.get("amenity") in VALID_AMENITIES
        and _is_open_now(candidate.get("opening_hours"), now_utc=now_utc)
    )


# helpers re-exported for the legacy /v1/decide route
def score_candidate(candidate: dict[str, Any], distance_weight: float, reliability_weight: float) -> float:
    distance_score = max(0.0, 1.0 - (candidate["distance_m"] / 2500.0))
    has_cuisine = 1.0 if candidate.get("cuisine") else 0.0
    has_opening_hours = 1.0 if candidate.get("opening_hours") else 0.0
    has_contact = 1.0 if candidate.get("contact_phone") else 0.0
    reliability_score = (has_cuisine + has_opening_hours + has_contact) / 3.0
    return distance_weight * distance_score + reliability_weight * reliability_score
