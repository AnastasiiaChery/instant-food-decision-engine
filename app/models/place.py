from pydantic import BaseModel


class Place(BaseModel):
    name: str
    lat: float
    lon: float
    distance_m: float
    amenity: str
    cuisine: str | None = None
    opening_hours: str | None = None
    contact_phone: str | None = None
