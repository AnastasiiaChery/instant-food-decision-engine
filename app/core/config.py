from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_JWT_SECRET = "change-me-in-prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Deployment environment. In "production" the app refuses to start with insecure
    # defaults (see validate_runtime); anything else is treated as local/dev.
    environment: str = "development"
    log_level: str = "INFO"

    # LLM provider: "groq" (default) | "openai" (any OpenAI-compatible endpoint) | "gemini".
    # The provider, the per-tier models and the key are all swappable via env so the
    # production model can be changed without a code release (see docs/llm-provider-routing-plan.md).
    ai_provider: str = "groq"

    # Groq: LLM provider (llama via OpenAI-compatible API)
    groq_api_key: str = ""
    # Generic key for the selected provider. Falls back to groq_api_key when empty,
    # so existing Groq-only deployments keep working unchanged.
    ai_api_key: str = ""
    ai_base_url: str = "https://api.groq.com/openai/v1"

    # Two model "tiers": heavy for reasoning-heavy steps (ranking, planning), fast for
    # light steps (intent parsing, UI translation) — the fast tier is ~10x cheaper/faster.
    ai_model: str = "llama-3.3-70b-versatile"        # heavy
    ai_model_fast: str = "llama-3.1-8b-instant"      # fast

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

    @property
    def effective_api_key(self) -> str:
        """API key for the active provider, with backward-compat fallback to GROQ_API_KEY."""
        return self.ai_api_key or self.groq_api_key

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
        if not self.effective_api_key:
            problems.append(
                f"No LLM API key set for provider '{self.ai_provider}' — set AI_API_KEY "
                "(or GROQ_API_KEY) — the LLM features will fail at runtime"
            )
        return problems


settings = Settings()
