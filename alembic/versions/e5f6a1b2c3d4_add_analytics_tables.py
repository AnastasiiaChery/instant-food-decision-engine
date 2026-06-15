"""add_analytics_tables

Creates the two first-party analytics tables: events (product behaviour from the
browser) and request_log (one row per HTTP request from middleware).

Revision ID: e5f6a1b2c3d4
Revises: d4e5f6a1b2c3
Create Date: 2026-06-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e5f6a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'events',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('anon_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('session_id', sa.String(length=36), nullable=True),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('props', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('path', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_events_ts', 'events', ['ts'])
    op.create_index('ix_events_anon_id', 'events', ['anon_id'])
    op.create_index('ix_events_user_id', 'events', ['user_id'])
    op.create_index('ix_events_name', 'events', ['name'])

    op.create_table(
        'request_log',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('method', sa.String(length=8), nullable=False),
        sa.Column('path', sa.String(length=255), nullable=False),
        sa.Column('status', sa.Integer(), nullable=False),
        sa.Column('duration_ms', sa.Float(), nullable=False),
        sa.Column('error', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_request_log_ts', 'request_log', ['ts'])


def downgrade() -> None:
    op.drop_index('ix_request_log_ts', table_name='request_log')
    op.drop_table('request_log')
    op.drop_index('ix_events_name', table_name='events')
    op.drop_index('ix_events_user_id', table_name='events')
    op.drop_index('ix_events_anon_id', table_name='events')
    op.drop_index('ix_events_ts', table_name='events')
    op.drop_table('events')
