from pydantic import BaseModel


class UserPreferences(BaseModel):
    diet: list[str] = []
    cuisines_liked: list[str] = []
    cuisines_disliked: list[str] = []
