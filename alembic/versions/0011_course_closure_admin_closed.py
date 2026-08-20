"""توسيع قيد حالة تقارير الإقفال ليشمل الإقفال الإداري.

Revision ID: 0011_admin_close
Revises: 0010_reg_sem_uq
Create Date: 2026-08-19
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0011_admin_close"
down_revision = "0010_reg_sem_uq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(text("ALTER TABLE course_closure_reports DROP CONSTRAINT IF EXISTS course_closure_status_chk"))
    op.execute(
        text(
            """
            ALTER TABLE course_closure_reports
            ADD CONSTRAINT course_closure_status_chk
            CHECK (status IN ('draft', 'submitted', 'approved', 'rejected', 'admin_closed'))
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(text("ALTER TABLE course_closure_reports DROP CONSTRAINT IF EXISTS course_closure_status_chk"))
    op.execute(
        text(
            """
            ALTER TABLE course_closure_reports
            ADD CONSTRAINT course_closure_status_chk
            CHECK (status IN ('draft', 'submitted', 'approved', 'rejected'))
            """
        )
    )
