"""سلة التسجيلات متعددة الفصول: UNIQUE(student_id, course_name, semester).

Revision ID: 0010_reg_sem_uq
Revises: 0009_dept_offer
Create Date: 2026-08-17
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0010_reg_sem_uq"
down_revision = "0009_dept_offer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    # توحيد القيم الفارغة قبل القيد الجديد
    op.execute(
        text(
            """
            UPDATE registrations
            SET semester = COALESCE(NULLIF(TRIM(semester), ''), '')
            WHERE semester IS NULL
            """
        )
    )
    op.execute(
        text(
            """
            ALTER TABLE registrations
                ALTER COLUMN semester SET DEFAULT ''
            """
        )
    )
    # إسقاط القيد القديم إن وُجد
    op.execute(
        text(
            """
            ALTER TABLE registrations
                DROP CONSTRAINT IF EXISTS registrations_student_id_course_name_key
            """
        )
    )
    op.execute(text("DROP INDEX IF EXISTS ux_registrations_student_course"))
    op.execute(text("DROP INDEX IF EXISTS registrations_student_id_course_name_key"))
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_registrations_student_course_sem
            ON registrations (student_id, course_name, semester)
            """
        )
    )


def downgrade() -> None:
    pass
