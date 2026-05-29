import unittest
from fastapi.testclient import TestClient


class AuthRouteTests(unittest.TestCase):
    def test_google_redirect_returns_302(self):
        from app.main import app
        client = TestClient(app, follow_redirects=False)
        r = client.get("/auth/google")
        self.assertEqual(r.status_code, 302)
        self.assertIn("accounts.google.com", r.headers["location"])

    def test_callback_without_code_returns_400(self):
        from app.main import app
        client = TestClient(app)
        r = client.get("/auth/callback")
        self.assertEqual(r.status_code, 400)
