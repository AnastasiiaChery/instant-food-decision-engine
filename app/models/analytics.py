"""First-party analytics tables.

Two lean, append-only tables that keep all tracking inside our own Postgres —
no third-party analytics SaaS:

* ``events``       — product behaviour sent from the browser (page views, searches,
                     navigate/favorite clicks). Drives DAU/MAU, funnels, retention.
* ``request_log``  — one row per HTTP request written by middleware. Drives RPS,
                     latency percentiles and error rates.

Both carry a ``ts`` index because every query is time-windowed, and both are pruned
by the retention job (see app.services.analytics) so the tables don't grow forever.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    # Pseudonymous id from the browser's localStorage — lets us count anonymous
    # visitors and the pre-login funnel without any personal data.
    anon_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # Linked once the visitor authenticates; SET NULL on user deletion so analytics
    # survive account removal as anonymous rows (GDPR erasure detaches, not deletes).
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    props: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)


class RequestLog(Base):
    __tablename__ = "request_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    # Short error label for 5xx (the failing path); full traces stay in app logs.
    error: Mapped[str | None] = mapped_column(String(255), nullable=True)
