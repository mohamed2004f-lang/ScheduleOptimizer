"""عمود بداية نافذة التقويم event_date_start.

Revision ID: 0007_cal_start
Revises: 0006_spring_new
Create Date: 2026-08-16
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0007_cal_start"
down_revision = "0006_spring_new"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(text("ALTER TABLE academic_calendar ADD COLUMN IF NOT EXISTS event_date_start TEXT"))


def downgrade() -> None:
    pass
