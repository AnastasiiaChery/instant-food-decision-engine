from typing import Annotated, Literal

from pydantic import BaseModel, Field, computed_field


class SearchRequest(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    # The endpoint is unauthenticated and feeds the query straight into the LLM,
    # so cap the size of every free-text field to bound token spend / abuse.
    query: str = Field(default="something good nearby", max_length=500)
    mode: Literal["autopilot", "plan", "preferences"] = "preferences"
    when: str | None = Field(default=None, max_length=20)  # "HH:MM" local time for planning ahead
    radius_m: int | None = Field(default=None, gt=0)  # search radius in metres; capped at max_radius_m
    exclude_place_name: str | None = Field(default=None, max_length=200)   # autopilot: skip this place name (legacy, single)
    exclude_place_names: list[Annotated[str, Field(max_length=200)]] = Field(default=[], max_length=20)  # autopilot: skip these place names (multi)
    use_profile: bool = True
    group_size: Literal["solo", "duo", "small_group", "large_group"] | None = None  # plan mode
    budget: Literal["budget", "mid", "upscale"] | None = None  # plan mode
    lang: str = Field(default="en", pattern=r"^[a-z]{2}(-[a-z]{2})?$")  # UI language for AI-written text


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
    match_score: float = 0.0  # planner's fit-for-occasion score (0.0–1.0)
