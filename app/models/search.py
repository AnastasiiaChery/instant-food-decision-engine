from pydantic import BaseModel, computed_field


class SearchRequest(BaseModel):
    lat: float
    lng: float
    query: str = "something good nearby"
    mode: str = "preferences"  # autopilot | preferences | plan
    when: str | None = None  # "HH:MM" local time for planning ahead
    radius_m: int | None = None  # search radius in metres; capped at max_radius_m
    exclude_place_name: str | None = None   # autopilot: skip this place name (legacy, single)
    exclude_place_names: list[str] = []    # autopilot: skip these place names (multi)
    use_profile: bool = True
    group_size: str | None = None  # plan mode: solo | duo | small_group | large_group
    budget: str | None = None  # plan mode: budget | mid | upscale


class PlaceIntent(BaseModel):
    venue_types: list[str]
    mood: str
    price_level: list[int]
    features: list[str]
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

    @computed_field
    @property
    def nav_url(self) -> str:
        return f"https://www.google.com/maps/search/?api=1&query={self.lat},{self.lon}"


class PlaceInfo(BaseModel):
    name: str
    lat: float
    lon: float
    distance_m: int
    amenity: str
    cuisine: str | None = None

    @computed_field
    @property
    def nav_url(self) -> str:
        return f"https://www.google.com/maps/search/?api=1&query={self.lat},{self.lon}"


class PlanRecommendation(BaseModel):
    place: PlaceInfo
    reason: str
    scenario: str
