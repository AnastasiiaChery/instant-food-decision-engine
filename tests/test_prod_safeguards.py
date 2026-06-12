import unittest

from pydantic import ValidationError

from app.api.v1.routes.auth import LoginRequest, RegisterRequest
from app.core.config import DEFAULT_JWT_SECRET, Settings


class StartupValidationTests(unittest.TestCase):
    def test_production_rejects_default_jwt_and_empty_groq(self) -> None:
        s = Settings(environment="production", jwt_secret=DEFAULT_JWT_SECRET, groq_api_key="")
        problems = s.validate_runtime()
        self.assertEqual(len(problems), 2)

    def test_production_passes_with_secure_config(self) -> None:
        s = Settings(environment="production", jwt_secret="a-strong-random-secret", groq_api_key="gsk_x")
        self.assertEqual(s.validate_runtime(), [])

    def test_development_never_blocks_startup(self) -> None:
        s = Settings(environment="development", jwt_secret=DEFAULT_JWT_SECRET, groq_api_key="")
        self.assertEqual(s.validate_runtime(), [])


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
