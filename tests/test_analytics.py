import unittest


class AnalyticsModelTests(unittest.TestCase):
    def test_event_model_has_required_columns(self):
        from app.models.analytics import Event
        cols = {c.name for c in Event.__table__.columns}
        for col in ("id", "ts", "anon_id", "user_id", "session_id", "name", "props", "path"):
            self.assertIn(col, cols)

    def test_event_user_fk_sets_null_on_delete(self):
        from app.models.user import User  # noqa: F401 — registers users table
        from app.models.analytics import Event
        fk = next(iter(Event.__table__.foreign_keys))
        self.assertEqual(fk.column.table.name, "users")
        self.assertEqual(fk.ondelete, "SET NULL")

    def test_request_log_model_has_required_columns(self):
        from app.models.analytics import RequestLog
        cols = {c.name for c in RequestLog.__table__.columns}
        for col in ("id", "ts", "method", "path", "status", "duration_ms", "error"):
            self.assertIn(col, cols)


class AnalyticsServiceTests(unittest.TestCase):
    def test_noise_paths_are_skipped(self):
        from app.services.analytics import should_log_path
        self.assertFalse(should_log_path("/health"))
        self.assertFalse(should_log_path("/ready"))
        self.assertFalse(should_log_path("/favicon.ico"))
        self.assertFalse(should_log_path("/static/js/main.js"))
        self.assertFalse(should_log_path("/api/v1/events"))

    def test_real_paths_are_logged(self):
        from app.services.analytics import should_log_path
        self.assertTrue(should_log_path("/api/v1/search"))
        self.assertTrue(should_log_path("/auth/login"))
        self.assertTrue(should_log_path("/"))

    def test_props_sanitizer_drops_nested_and_truncates(self):
        from app.api.v1.routes.events import _sanitize_props
        out = _sanitize_props({
            "mode": "plan",
            "count": 5,
            "ok": True,
            "nested": {"a": 1},
            "long": "x" * 500,
        })
        self.assertEqual(out["mode"], "plan")
        self.assertEqual(out["count"], 5)
        self.assertEqual(out["ok"], True)
        self.assertNotIn("nested", out)
        self.assertEqual(len(out["long"]), 120)


class AnalyticsConfigTests(unittest.TestCase):
    def test_admin_emails_parsed_and_lowercased(self):
        from app.core.config import Settings
        s = Settings(analytics_admin_emails="A@B.com, c@d.com ")
        self.assertEqual(s.analytics_admin_emails_list, ["a@b.com", "c@d.com"])

    def test_admin_emails_empty_means_locked(self):
        from app.core.config import Settings
        s = Settings(analytics_admin_emails="")
        self.assertEqual(s.analytics_admin_emails_list, [])


if __name__ == "__main__":
    unittest.main()
