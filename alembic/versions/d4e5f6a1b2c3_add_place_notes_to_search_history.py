"""add_place_notes_to_search_history

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-06-05

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('search_history', sa.Column('place_notes', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('search_history', 'place_notes')
