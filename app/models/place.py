from pydantic import BaseModel, computed_field


class Place(BaseModel):
    name: str
    lat: float
    lon: float
    distance_m: float
    amenity: str
    cuisine: str | None = None
    opening_hours: str | None = None
    contact_phone: str | None = None

    @computed_field
    @property
    def nav_url(self) -> str:
        return f"https://www.google.com/maps/search/?api=1&query={self.lat},{self.lon}"
