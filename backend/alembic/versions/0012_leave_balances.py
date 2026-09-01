"""Module 3: leave balances

Revision ID: 0012_leave_balances
Revises: 0011_small_talk_outcome
Create Date: 2026-09-01 06:02:18.774310
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.core.types  # TZDateTime, referenced by the column definitions below


revision: str = '0012_leave_balances'
down_revision: Union[str, None] = '0011_small_talk_outcome'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table('leave_balances',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('employee_id', sa.Uuid(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('leave_kind', sa.Enum('annual', 'sick', 'unpaid', name='leave_kind'), nullable=False),
    sa.Column('entitled_days', sa.Numeric(precision=5, scale=1), nullable=False),
    sa.Column('carried_forward_days', sa.Numeric(precision=5, scale=1), nullable=False),
    sa.Column('used_days', sa.Numeric(precision=5, scale=1), nullable=False),
    sa.Column('created_at', app.core.types.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', app.core.types.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_id', 'year', 'leave_kind', name='uq_leave_balance_period')
    )
    op.create_index(op.f('ix_leave_balances_employee_id'), 'leave_balances', ['employee_id'], unique=False)
    op.create_index(op.f('ix_leave_balances_year'), 'leave_balances', ['year'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_leave_balances_year'), table_name='leave_balances')
    op.drop_index(op.f('ix_leave_balances_employee_id'), table_name='leave_balances')
    op.drop_table('leave_balances')

    # Autogenerate does not clean up the enum types it created, and leaving it
    # behind makes a re-upgrade fail with "type already exists".
    sa.Enum(name='leave_kind').drop(op.get_bind(), checkfirst=True)
