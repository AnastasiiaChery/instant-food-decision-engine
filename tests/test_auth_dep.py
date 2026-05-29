import unittest
from unittest.mock import AsyncMock, MagicMock


class AuthDepTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_none_when_no_authorization_header(self):
        from app.core.deps import get_optional_user
        request = MagicMock()
        request.headers = {}
        result = await get_optional_user(request, db=AsyncMock())
        self.assertIsNone(result)

    async def test_returns_none_when_token_invalid(self):
        from app.core.deps import get_optional_user
        request = MagicMock()
        request.headers = {"authorization": "Bearer badtoken"}
        result = await get_optional_user(request, db=AsyncMock())
        self.assertIsNone(result)
