import unittest


class UserModelTests(unittest.TestCase):
    def test_user_model_has_required_columns(self):
        from app.models.user import User
        cols = {c.name for c in User.__table__.columns}
        self.assertIn("id", cols)
        self.assertIn("email", cols)
        self.assertIn("google_id", cols)
        self.assertIn("created_at", cols)

    def test_user_email_is_unique(self):
        from app.models.user import User
        email_col = User.__table__.c.email
        self.assertTrue(email_col.unique)
