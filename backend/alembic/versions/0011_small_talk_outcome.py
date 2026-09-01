"""Add the small_talk chat outcome

Revision ID: 0011_small_talk_outcome
Revises: 0010_request_engine
Create Date: 2026-09-01 05:12:44.108221
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0011_small_talk_outcome'
down_revision: Union[str, None] = '0010_request_engine'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autogenerate does not notice values added to an existing enum, and SQLite
    # does not enforce enum membership — so this has to be written by hand or it
    # only fails against real Postgres, at request time.
    op.execute("ALTER TYPE chat_outcome ADD VALUE IF NOT EXISTS 'small_talk'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum, and rebuilding the type would
    # mean rewriting every chat_messages row. One unused label is the cheaper
    # thing to leave behind.
    pass
