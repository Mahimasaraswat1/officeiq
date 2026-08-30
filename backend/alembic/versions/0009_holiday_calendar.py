"""Module 1: company holiday calendar

Revision ID: 0009_holiday_calendar
Revises: 0008_chat_error_message
Create Date: 2026-08-30 11:29:36.794270
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.core.types  # TZDateTime, referenced by the column definitions below


revision: str = '0009_holiday_calendar'
down_revision: Union[str, None] = '0008_chat_error_message'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'holidays',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('holiday_date', sa.Date(), nullable=False),
        sa.Column(
            'type',
            sa.Enum('public', 'restricted', 'company', name='holiday_type'),
            nullable=False,
        ),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column(
            'created_at',
            app.core.types.TZDateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            app.core.types.TZDateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('holiday_date', 'name', name='uq_holiday_date_name'),
    )
    op.create_index(
        op.f('ix_holidays_holiday_date'), 'holidays', ['holiday_date'], unique=False
    )
    op.create_index(op.f('ix_holidays_type'), 'holidays', ['type'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_holidays_type'), table_name='holidays')
    op.drop_index(op.f('ix_holidays_holiday_date'), table_name='holidays')
    op.drop_table('holidays')

    # Autogenerate does not clean up the enum types it created, and leaving it
    # behind makes a re-upgrade fail with "type already exists".
    sa.Enum(name='holiday_type').drop(op.get_bind(), checkfirst=True)
