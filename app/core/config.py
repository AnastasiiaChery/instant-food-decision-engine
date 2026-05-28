from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    groq_api_key: str = ""
    ai_base_url: str = "https://api.groq.com/openai/v1"
    ai_model: str = "llama-3.3-70b-versatile"

    redis_url: str = ""
    port: int = 8000

    distance_weight: float = 0.75
    reliability_weight: float = 0.25
    search_radius_m: int = 1500
    max_radius_m: int = 3000


settings = Settings()
