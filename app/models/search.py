from pydantic import BaseModel


class SearchRequest(BaseModel):
    lat: float
    lng: float
    query: str


class PlaceIntent(BaseModel):
    venue_types: list[str]
    mood: str
    price_level: list[int]
    features: list[str]
    time_sensitivity: str


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
