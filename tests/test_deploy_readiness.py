import unittest

from fastapi.testclient import TestClient

from app.main import app


class DeployReadinessTests(unittest.TestCase):
    def test_ready_endpoint_reports_ready(self) -> None:
        with TestClient(app) as client:
            response = client.get("/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("status"), "ready")


if __name__ == "__main__":
    unittest.main()
