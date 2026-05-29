import unittest
from unittest.mock import AsyncMock, MagicMock


class HistoryRouteTests(unittest.TestCase):
    def test_navigate_without_auth_returns_401(self):
        from app.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        r = client.post("/api/v1/history/navigate", json={
            "place_name": "Test Place", "place_type": "restaurant",
            "lat": 50.45, "lng": 30.52,
        })
        self.assertEqual(r.status_code, 401)

    def test_navigate_with_valid_auth_returns_200(self):
        from app.main import app
        from app.models.user import User
        from app.core.deps import get_optional_user, get_db
        from fastapi.testclient import TestClient

        fake_user = User(id=1, email="test@example.com")

        async def override_user():
            return fake_user

        async def override_db():
            db = AsyncMock()
            db.add = MagicMock()
            db.commit = AsyncMock()
            yield db

        app.dependency_overrides[get_optional_user] = override_user
        app.dependency_overrides[get_db] = override_db
        try:
            client = TestClient(app)
            r = client.post("/api/v1/history/navigate", json={
                "place_name": "Test Place", "place_type": "restaurant",
                "lat": 50.45, "lng": 30.52,
            })
        finally:
            app.dependency_overrides.clear()

        self.assertEqual(r.status_code, 200)
