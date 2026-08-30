"""Module 2: generic request & approval engine

Revision ID: 0010_request_engine
Revises: 0009_holiday_calendar
Create Date: 2026-08-30 12:04:11.220418
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.core.types  # TZDateTime, referenced by the column definitions below


revision: str = '0010_request_engine'
down_revision: Union[str, None] = '0009_holiday_calendar'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_NOTIFICATION_TYPES = (
    'request_submitted',
    'request_approved',
    'request_rejected',
)


def upgrade() -> None:
    # Autogenerate does not notice values added to an existing enum, and
    # SQLite (which the test suite uses) does not enforce enum membership at
    # all — so a missing value here only ever surfaces as a 500 against real
    # Postgres. Adding them explicitly is the only way this stays correct.
    for value in NEW_NOTIFICATION_TYPES:
        op.execute(
            f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{value}'"
        )


    op.create_table('requests',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('request_code', sa.String(length=32), nullable=False),
    sa.Column('type', sa.Enum('leave', name='request_type'), nullable=False),
    sa.Column('employee_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'approved', 'rejected', 'cancelled', name='request_status'), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('summary', sa.String(length=255), nullable=False),
    sa.Column('assigned_to_id', sa.Uuid(), nullable=True),
    sa.Column('submitted_at', app.core.types.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('decided_at', app.core.types.TZDateTime(timezone=True), nullable=True),
    sa.Column('decided_by_id', sa.Uuid(), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('created_at', app.core.types.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', app.core.types.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['assigned_to_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_requests_assigned_to_id'), 'requests', ['assigned_to_id'], unique=False)
    op.create_index(op.f('ix_requests_employee_id'), 'requests', ['employee_id'], unique=False)
    op.create_index(op.f('ix_requests_request_code'), 'requests', ['request_code'], unique=True)
    op.create_index(op.f('ix_requests_status'), 'requests', ['status'], unique=False)
    op.create_index('ix_requests_status_type', 'requests', ['status', 'type'], unique=False)
    op.create_index(op.f('ix_requests_type'), 'requests', ['type'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_requests_type'), table_name='requests')
    op.drop_index('ix_requests_status_type', table_name='requests')
    op.drop_index(op.f('ix_requests_status'), table_name='requests')
    op.drop_index(op.f('ix_requests_request_code'), table_name='requests')
    op.drop_index(op.f('ix_requests_employee_id'), table_name='requests')
    op.drop_index(op.f('ix_requests_assigned_to_id'), table_name='requests')
    op.drop_table('requests')

    # Autogenerate does not clean up the enum types it created, and leaving them
    # behind makes a re-upgrade fail with "type already exists".
    bind = op.get_bind()
    for enum_name in ('request_status', 'request_type'):
        sa.Enum(name=enum_name).drop(bind, checkfirst=True)

    # The notification_type values added above are deliberately left in place.
    # Postgres cannot drop a value from an enum, and rebuilding the type would
    # mean rewriting every notification row — far more destructive than leaving
    # three unused labels behind.
