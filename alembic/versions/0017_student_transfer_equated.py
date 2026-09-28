"""وسم انتقال الطالب ومقررات المعادلة في الكشف.

Revision ID: 0017_transfer_eq
Revises: 0016_tx_corr
Create Date: 2026-09-28
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0017_transfer_eq"
down_revision = "0016_tx_corr"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(text("ALTER TABLE students ADD COLUMN IF NOT EXISTS transfer_kind TEXT DEFAULT ''"))
    op.execute(
        text("ALTER TABLE students ADD COLUMN IF NOT EXISTS transfer_from_department_id BIGINT")
    )
    op.execute(
        text("ALTER TABLE students ADD COLUMN IF NOT EXISTS transfer_from_label TEXT DEFAULT ''")
    )
    op.execute(
        text(
            "ALTER TABLE grades ADD COLUMN IF NOT EXISTS is_equated INTEGER NOT NULL DEFAULT 0"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_grades_equated "
            "ON grades (student_id, is_equated)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(text("DROP INDEX IF EXISTS idx_grades_equated"))
    op.execute(text("ALTER TABLE grades DROP COLUMN IF EXISTS is_equated"))
    op.execute(text("ALTER TABLE students DROP COLUMN IF EXISTS transfer_from_label"))
    op.execute(text("ALTER TABLE students DROP COLUMN IF EXISTS transfer_from_department_id"))
    op.execute(text("ALTER TABLE students DROP COLUMN IF EXISTS transfer_kind"))
