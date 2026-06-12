from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_JWT_SECRET = "change-me-in-prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Deployment environment. In "production" the app refuses to start with insecure
    # defaults (see validate_runtime); anything else is treated as local/dev.
    environment: str = "development"
    log_level: str = "INFO"

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
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_expire_minutes: int = 10080

    # SQLAlchemy connection-pool sizing (per worker process).
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_s: int = 1800

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in ("production", "prod")

    def validate_runtime(self) -> list[str]:
        """Return a list of fatal misconfigurations for production.

        Empty list means safe to start. Used for fail-fast at app startup so a
        deploy with insecure defaults never serves traffic (forgeable JWTs, a
        non-functional LLM that silently degrades every request, etc.).
        """
        problems: list[str] = []
        if not self.is_production:
            return problems
        if not self.jwt_secret or self.jwt_secret == DEFAULT_JWT_SECRET:
            problems.append("JWT_SECRET is unset or the insecure default — set a strong random secret")
        if not self.groq_api_key:
            problems.append("GROQ_API_KEY is empty — the LLM features will fail at runtime")
        return problems


settings = Settings()
