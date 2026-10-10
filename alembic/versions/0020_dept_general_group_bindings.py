"""ربط القسم التخصصي بمجموعة اتجاه عام + ترحيل.

Revision ID: 0020_gen_bindings
Revises: 0019_display_tracks
Create Date: 2026-10-10
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0020_gen_bindings"
down_revision = "0019_display_tracks"
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
            CREATE TABLE IF NOT EXISTS department_general_group_bindings (
                id BIGSERIAL PRIMARY KEY,
                semester TEXT NOT NULL,
                consumer_department_id BIGINT NOT NULL REFERENCES departments(id)
                    ON DELETE RESTRICT ON UPDATE CASCADE,
                course_name TEXT NOT NULL,
                teaching_group_id BIGINT NOT NULL REFERENCES teaching_groups(id)
                    ON DELETE RESTRICT ON UPDATE CASCADE,
                updated_by TEXT DEFAULT '',
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (semester, consumer_department_id, course_name)
            )
            """
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_dept_gen_bind_sem_dept "
            "ON department_general_group_bindings (semester, consumer_department_id)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(text("DROP INDEX IF EXISTS idx_dept_gen_bind_sem_dept"))
    op.execute(text("DROP TABLE IF EXISTS department_general_group_bindings"))
