import unittest


class HistoryModelTests(unittest.TestCase):
    def test_history_model_has_required_columns(self):
        from app.models.history import SearchHistory
        cols = {c.name for c in SearchHistory.__table__.columns}
        for col in ("id", "user_id", "place_osm_id", "place_name", "place_type", "lat", "lng", "chosen_at"):
            self.assertIn(col, cols)

    def test_history_has_foreign_key_to_users(self):
        from app.models.user import User  # noqa: F401 — registers users table in metadata
        from app.models.history import SearchHistory
        fks = {fk.column.table.name for fk in SearchHistory.__table__.foreign_keys}
        self.assertIn("users", fks)
