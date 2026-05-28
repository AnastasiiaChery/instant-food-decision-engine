import unittest

from fastapi.testclient import TestClient

from app.main import app


class FaviconTests(unittest.TestCase):
    def test_favicon_endpoint_is_not_404(self) -> None:
        with TestClient(app) as client:
            response = client.get("/favicon.ico")
        self.assertNotEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
