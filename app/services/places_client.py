import asyncio
import logging
import re
from datetime import UTC, datetime
from math import asin, cos, radians, sin, sqrt
from typing import Any, Protocol

import httpx
from fastapi import HTTPException

from app.models.place import Place

logger = logging.getLogger(__name__)

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]
VALID_AMENITIES = {
    "restaurant", "fast_food", "cafe", "bar", "pub", "biergarten", "food_court",
    "cocktail_bar", "wine_bar", "juice_bar", "ice_cream", "food_hall", "taproom",
}


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


_DAYS = ["mo", "tu", "we", "th", "fr", "sa", "su"]


def _day_applies(day_part: str, day_idx: int) -> bool:
    """Does a segment's day spec (e.g. 'mo-fr', 'we-th', 'mo, su', '') cover today?

    Empty spec → applies every day. A spec with day tokens that don't include
    today → not applicable. A spec with no recognisable day tokens (e.g. 'ph') →
    treated as applicable (lenient, avoids over-filtering on exotic rules).
    """
    if not day_part:
        return True
    found_day_token = False
    for part in day_part.split(","):
        days = re.findall(r"mo|tu|we|th|fr|sa|su", part)
        if not days:
            continue
        found_day_token = True
        if "-" in part and len(days) >= 2:
            start, end = _DAYS.index(days[0]), _DAYS.index(days[-1])
            if start <= end:
                if start <= day_idx <= end:
                    return True
            elif day_idx >= start or day_idx <= end:  # wrap-around, e.g. fr-mo
                return True
        elif any(_DAYS.index(d) == day_idx for d in days):
            return True
    return not found_day_token


def _is_open_now(opening_hours: str | None, now_utc: datetime | None = None) -> bool:
    if not opening_hours:
        return True
    normalized = opening_hours.strip().lower()
    if normalized in {"24/7", "24h", "24x7"}:
        return True

    current = now_utc or datetime.now(UTC)
    day_idx = current.weekday()
    now_min = current.hour * 60 + current.minute

    applicable_found = False
    for raw in normalized.split(";"):
        segment = raw.strip()
        if not segment:
            continue
        is_off = "off" in segment or "closed" in segment
        time_start = re.search(r"\d{1,2}:\d{2}", segment)
        if time_start:
            day_part = segment[: time_start.start()]
        else:  # no times: "off", "mo-fr off", "su closed"
            day_part = segment.replace("off", "").replace("closed", "")
        day_part = day_part.strip().strip(",").strip()

        if not _day_applies(day_part, day_idx):
            continue
        applicable_found = True
        if is_off:
            return False
        for h1, m1, h2, m2 in re.findall(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", segment):
            start = int(h1) * 60 + int(m1)
            end = int(h2) * 60 + int(m2)
            if end <= start:  # overnight span, e.g. 14:00-02:00
                if now_min >= start or now_min <= end:
                    return True
            elif start <= now_min <= end:
                return True

    # A segment covered today but no time window matched → closed.
    # No segment mentioned today → hours unknown for today → stay lenient.
    return not applicable_found


def _candidate_key(candidate: dict[str, Any]) -> str:
    return (
        f"{candidate.get('name', '').strip().lower()}|"
        f"{float(candidate.get('lat', 0.0)):.5f}|"
        f"{float(candidate.get('lon', 0.0)):.5f}"
    )


_SAME_PLACE_RADIUS_M = 80


def _deduplicate(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen_exact: set[str] = set()
    for c in candidates:
        key = _candidate_key(c)
        if key in seen_exact:
            continue
        name = c.get("name", "").strip().lower()
        lat, lon = float(c.get("lat", 0)), float(c.get("lon", 0))
        is_dup = any(
            u.get("name", "").strip().lower() == name
            and _distance_m(lat, lon, float(u["lat"]), float(u["lon"])) <= _SAME_PLACE_RADIUS_M
            for u in unique
        )
        if not is_dup:
            seen_exact.add(key)
            unique.append(c)
    return unique


def _build_overpass_query(lat: float, lon: float, venue_types: list[str], radius_m: int) -> str:
    amenity_regex = "|".join(venue_types)
    return f"""
[out:json][timeout:25][maxsize:33554432];
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
    for i, url in enumerate(OVERPASS_URLS):
        try:
            response = await http_client.post(url, data={"data": query}, headers=_HEADERS, timeout=20.0)
            response.raise_for_status()
            parsed = response.json()
            if not isinstance(parsed, dict):
                raise ValueError("Overpass response is not a JSON object")
            return _parse_elements(parsed.get("elements", []), lat, lon)
        except (httpx.HTTPError, ValueError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning(
                "Overpass endpoint failed [%s] %s: %s(%s)",
                status or "network",
                url,
                type(exc).__name__,
                exc,
            )
            last_error = exc
            # On rate-limit or transient error give the next mirror a moment;
            # on 504 the server is already saturated — hit the next mirror immediately.
            if i < len(OVERPASS_URLS) - 1 and status != 504:
                await asyncio.sleep(0.5)
    logger.error(
        "All Overpass endpoints failed: %s: %s",
        type(last_error).__name__,
        last_error,
    )
    raise HTTPException(status_code=502, detail="Map data provider is temporarily unavailable. Please try again shortly.")


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


def _filter_candidates(
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
        filter_open: bool = True,
    ) -> list[Place]:
        # filter_open=False returns a time-agnostic set (callers that cache across
        # different `when` values apply the open-now filter themselves per request).
        candidates = await _fetch_raw(lat, lng, venue_types, radius_m, http_client)
        filtered = _filter_candidates(candidates, radius_m, now_utc, strict_hours=filter_open)
        filtered = _deduplicate(filtered)

        # expand radius if too few results
        if len(filtered) < 5 and max_radius_m and max_radius_m > radius_m:
            candidates = await _fetch_raw(lat, lng, venue_types, max_radius_m, http_client)
            filtered = _filter_candidates(candidates, max_radius_m, now_utc, strict_hours=filter_open)
            filtered = _deduplicate(filtered)

        # fallback: relax "open now" — keep everything except explicitly closed
        if not filtered:
            candidates = await _fetch_raw(lat, lng, venue_types, max_radius_m or radius_m, http_client)
            filtered = _filter_candidates(candidates, max_radius_m or radius_m, now_utc, strict_hours=False)
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
