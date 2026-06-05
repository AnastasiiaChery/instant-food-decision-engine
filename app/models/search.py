from pydantic import BaseModel


class SearchRequest(BaseModel):
    lat: float
    lng: float
    query: str
    when: str | None = None  # "HH:MM" local time for planning ahead
    radius_m: int | None = None  # search radius in metres; capped at max_radius_m


class PlaceIntent(BaseModel):
    venue_types: list[str]
    mood: str
    price_level: list[int]
    features: list[str]
    time_sensitivity: str
    cuisine: list[str] | None = None


class RankedPlace(BaseModel):
    name: str
    lat: float
    lon: float
    distance_m: float
    amenity: str
    cuisine: str | None = None
    match_score: float
    reason: str
    nav_url: str
