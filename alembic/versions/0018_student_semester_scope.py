"""تصنيف فصل كشف الدرجات: اتجاه عام أو قسم تخصص (+ شعبة إن وُجدت).

Revision ID: 0018_sem_scope
Revises: 0017_transfer_eq
Create Date: 2026-10-02
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0018_sem_scope"
down_revision = "0017_transfer_eq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS student_semester_scope (
                student_id TEXT NOT NULL,
                semester TEXT NOT NULL,
                scope_kind TEXT NOT NULL DEFAULT 'department',
                department_id BIGINT,
                teaching_group_id BIGINT,
                group_code TEXT NOT NULL DEFAULT '',
                department_label TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                updated_by TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (student_id, semester)
            )
            """
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_student_sem_scope_dept "
            "ON student_semester_scope (department_id)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(text("DROP INDEX IF EXISTS idx_student_sem_scope_dept"))
    op.execute(text("DROP TABLE IF EXISTS student_semester_scope"))
