import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import DEFAULT_JWT_SECRET, Settings
from app.main import app
from app.models.search import SearchRequest


class SearchInputBoundsTests(unittest.TestCase):
    """The /api/v1/search endpoint is unauthenticated and feeds free-text into the
    LLM, so every text field must be size-bounded to cap token spend / abuse."""

    def test_normal_request_is_accepted(self) -> None:
        req = SearchRequest(lat=50.0, lng=14.0, query="cozy italian",
                            exclude_place_names=["A", "B"])
        self.assertEqual(len(req.exclude_place_names), 2)

    def test_oversized_query_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            SearchRequest(lat=0.0, lng=0.0, query="x" * 501)

    def test_too_many_exclusions_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            SearchRequest(lat=0.0, lng=0.0, exclude_place_names=["x"] * 21)

    def test_oversized_exclusion_item_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            SearchRequest(lat=0.0, lng=0.0, exclude_place_names=["y" * 201])

    def test_oversized_when_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            SearchRequest(lat=0.0, lng=0.0, when="z" * 21)


class SecurityHeadersTests(unittest.TestCase):
    def test_baseline_security_headers_present(self) -> None:
        with TestClient(app) as client:
            r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Content-Security-Policy", r.headers)
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertIn("Referrer-Policy", r.headers)

    def test_no_hsts_in_development(self) -> None:
        # HSTS must not be sent in dev (would pin localhost to https).
        with TestClient(app) as client:
            r = client.get("/health")
        self.assertNotIn("Strict-Transport-Security", r.headers)


class I18nWhitelistTests(unittest.TestCase):
    def test_supported_language_is_served(self) -> None:
        with TestClient(app) as client:
            r = client.get("/api/v1/i18n/en")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), dict)

    def test_unsupported_but_well_formed_code_is_rejected(self) -> None:
        # "zz" matches the ISO format but is not in the whitelist — must 400 so it
        # cannot trigger an LLM translation call on the unauthenticated endpoint.
        with TestClient(app) as client:
            r = client.get("/api/v1/i18n/zz")
        self.assertEqual(r.status_code, 400)

    def test_malformed_code_is_rejected(self) -> None:
        with TestClient(app) as client:
            r = client.get("/api/v1/i18n/english")
        self.assertEqual(r.status_code, 400)


class OrphanEndpointTests(unittest.TestCase):
    def test_decide_endpoint_is_removed(self) -> None:
        with TestClient(app) as client:
            r = client.post("/v1/decide", json={"latitude": 50.45, "longitude": 30.52})
        self.assertEqual(r.status_code, 404)


class OAuthStateTests(unittest.TestCase):
    def test_google_login_sets_state_cookie_and_param(self) -> None:
        with TestClient(app, follow_redirects=False) as client:
            r = client.get("/auth/google")
        self.assertEqual(r.status_code, 302)
        self.assertIn("state=", r.headers["location"])
        self.assertIn("oauth_state", r.headers.get("set-cookie", ""))

    def test_callback_rejects_mismatched_state(self) -> None:
        # A code with a state that has no matching cookie must be rejected (login-CSRF).
        with TestClient(app) as client:
            r = client.get("/auth/callback?code=abc&state=forged", follow_redirects=False)
        self.assertEqual(r.status_code, 400)


class FeedbackAuthTests(unittest.TestCase):
    def test_feedback_requires_authentication(self) -> None:
        with TestClient(app) as client:
            r = client.post(
                "/api/v1/feedback",
                json={"place_name": "X", "comment": "bad pick"},
            )
        self.assertEqual(r.status_code, 401)


class HistoryValidationTests(unittest.TestCase):
    def test_oversized_place_name_rejected(self) -> None:
        with TestClient(app) as client:
            r = client.post(
                "/api/v1/history/navigate",
                json={"place_name": "x" * 300, "place_type": "cafe", "lat": 50.0, "lng": 30.0},
            )
        self.assertEqual(r.status_code, 422)

    def test_out_of_range_lat_rejected(self) -> None:
        with TestClient(app) as client:
            r = client.post(
                "/api/v1/history/navigate",
                json={"place_name": "ok", "place_type": "cafe", "lat": 999.0, "lng": 30.0},
            )
        self.assertEqual(r.status_code, 422)


class AllowedHostsConfigTests(unittest.TestCase):
    def test_allowed_hosts_parsed_into_list(self) -> None:
        s = Settings(allowed_hosts="a.com, b.com ,")
        self.assertEqual(s.allowed_hosts_list, ["a.com", "b.com"])

    def test_wildcard_allowed_hosts_flagged_in_production(self) -> None:
        s = Settings(
            environment="production", jwt_secret="strong-secret", groq_api_key="gsk_x",
            database_url="postgresql+asyncpg://app:s3cret@db:5432/instantfood",
            redis_url="redis://redis:6379", allowed_hosts="*",
        )
        self.assertIn("ALLOWED_HOSTS", " ".join(s.validate_runtime()))

    def test_dev_never_flags_allowed_hosts(self) -> None:
        s = Settings(environment="development", jwt_secret=DEFAULT_JWT_SECRET, allowed_hosts="*")
        self.assertEqual(s.validate_runtime(), [])


if __name__ == "__main__":
    unittest.main()
