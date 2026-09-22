"""امتحانات اختيارية مربوطة بمجموعة تدريس (split).

Revision ID: 0015_exams_tg
Revises: 0014_tg_instructors
Create Date: 2026-09-21
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0015_exams_tg"
down_revision = "0014_tg_instructors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(text("ALTER TABLE exams ADD COLUMN IF NOT EXISTS teaching_group_id BIGINT"))
    op.execute(
        text("CREATE INDEX IF NOT EXISTS idx_exams_teaching_group ON exams(teaching_group_id)")
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(text("DROP INDEX IF EXISTS idx_exams_teaching_group"))
    op.execute(text("ALTER TABLE exams DROP COLUMN IF EXISTS teaching_group_id"))
