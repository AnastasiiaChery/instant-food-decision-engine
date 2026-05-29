import unittest


class JWTTests(unittest.TestCase):
    def test_token_roundtrip_returns_user_id(self):
        from app.core.security import create_access_token, decode_access_token
        token = create_access_token(user_id=42)
        payload = decode_access_token(token)
        self.assertEqual(payload["sub"], "42")

    def test_expired_token_returns_none(self):
        from app.core.security import create_access_token, decode_access_token
        token = create_access_token(user_id=1, expire_minutes=-1)
        result = decode_access_token(token)
        self.assertIsNone(result)

    def test_invalid_token_returns_none(self):
        from app.core.security import decode_access_token
        result = decode_access_token("not.a.valid.token")
        self.assertIsNone(result)
