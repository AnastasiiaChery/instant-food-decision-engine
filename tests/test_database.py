import unittest
from app.infrastructure.database import async_session_factory, engine


class DatabaseSetupTests(unittest.TestCase):
    def test_engine_uses_asyncpg_dialect(self):
        from sqlalchemy.dialects.postgresql.asyncpg import dialect
        self.assertEqual(type(engine.dialect), dialect)

    def test_session_factory_is_callable(self):
        session = async_session_factory()
        import asyncio
        asyncio.run(session.close())
