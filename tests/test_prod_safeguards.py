import unittest

from langchain_core.language_models import BaseChatModel
from pydantic import ValidationError

from app.api.v1.routes.auth import LoginRequest, RegisterRequest
from app.core.config import DEFAULT_JWT_SECRET, Settings
from app.core.deps import build_ai_clients, build_llm


class StartupValidationTests(unittest.TestCase):
    def test_production_rejects_default_jwt_and_empty_key(self) -> None:
        s = Settings(environment="production", jwt_secret=DEFAULT_JWT_SECRET, groq_api_key="")
        problems = s.validate_runtime()
        self.assertEqual(len(problems), 2)

    def test_production_passes_with_secure_config(self) -> None:
        s = Settings(environment="production", jwt_secret="a-strong-random-secret", groq_api_key="gsk_x")
        self.assertEqual(s.validate_runtime(), [])

    def test_production_accepts_generic_ai_api_key(self) -> None:
        # AI_API_KEY alone (no GROQ_API_KEY) must satisfy the LLM-key check.
        s = Settings(
            environment="production", jwt_secret="a-strong-random-secret",
            groq_api_key="", ai_api_key="sk-generic",
        )
        self.assertEqual(s.validate_runtime(), [])

    def test_development_never_blocks_startup(self) -> None:
        s = Settings(environment="development", jwt_secret=DEFAULT_JWT_SECRET, groq_api_key="")
        self.assertEqual(s.validate_runtime(), [])


class AiClientFactoryTests(unittest.TestCase):
    def test_effective_api_key_falls_back_to_groq(self) -> None:
        self.assertEqual(Settings(groq_api_key="gsk_x").effective_api_key, "gsk_x")
        self.assertEqual(
            Settings(groq_api_key="gsk_x", ai_api_key="sk-generic").effective_api_key, "sk-generic"
        )

    def test_build_ai_clients_groq_returns_both_tiers(self) -> None:
        cfg = Settings(ai_provider="groq", groq_api_key="gsk_x")
        clients = build_ai_clients(cfg)
        self.assertEqual(set(clients), {"fast", "heavy"})
        self.assertIsInstance(clients["fast"], BaseChatModel)
        self.assertIsInstance(clients["heavy"], BaseChatModel)

    def test_build_ai_clients_openai_provider(self) -> None:
        cfg = Settings(ai_provider="openai", ai_api_key="sk-x", ai_model="gpt-4o-mini",
                       ai_model_fast="gpt-4o-mini")
        clients = build_ai_clients(cfg)
        self.assertIsInstance(clients["heavy"], BaseChatModel)

    def test_unknown_provider_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_llm("whatever", Settings(ai_provider="nonsense"))


class AuthValidationTests(unittest.TestCase):
    def test_invalid_email_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            RegisterRequest(email="not-an-email", password="longenough")

    def test_short_password_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            RegisterRequest(email="ok@example.com", password="short")

    def test_email_normalized(self) -> None:
        r = RegisterRequest(email="  User@Example.COM ", password="longenough")
        self.assertEqual(r.email, "user@example.com")

    def test_login_normalizes_email(self) -> None:
        r = LoginRequest(email="User@Example.com", password="x")
        self.assertEqual(r.email, "user@example.com")


if __name__ == "__main__":
    unittest.main()
