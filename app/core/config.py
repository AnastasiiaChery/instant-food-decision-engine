from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Groq: LLM provider (llama via OpenAI-compatible API)
    groq_api_key: str = ""
    ai_base_url: str = "https://api.groq.com/openai/v1"
    ai_model: str = "llama-3.3-70b-versatile"

    # LangSmith: optional observability platform for LLM tracing (smith.langchain.com).
    # When langsmith_api_key is set, all LLM calls (intent parsing, ranking, planning)
    # are traced automatically — prompts, responses, latency, token usage.
    # Leave empty to disable tracing entirely; the app works fine without it.
    langsmith_api_key: str = ""
    langsmith_tracing: str = "true"
    langsmith_project: str = "instant-food-decision-engine"

    redis_url: str = ""
    port: int = 8000

    distance_weight: float = 0.75
    reliability_weight: float = 0.25
    search_radius_m: int = 1500
    max_radius_m: int = 3000

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/instantfood"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/callback"
    jwt_secret: str = "change-me-in-prod"
    jwt_expire_minutes: int = 10080


settings = Settings()
