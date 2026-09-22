"""فريق التدريس لمجموعة المقرر (رئيسي + مساعدون).

Revision ID: 0014_tg_instructors
Revises: 0013_reg_chg_hidden
Create Date: 2026-09-21
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0014_tg_instructors"
down_revision = "0013_reg_chg_hidden"
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
            CREATE TABLE IF NOT EXISTS teaching_group_instructors (
                id SERIAL PRIMARY KEY,
                teaching_group_id INTEGER NOT NULL
                    REFERENCES teaching_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
                instructor_id INTEGER NOT NULL
                    REFERENCES instructors(id) ON DELETE RESTRICT ON UPDATE CASCADE,
                role TEXT NOT NULL DEFAULT 'primary'
                    CHECK (role IN ('primary', 'assistant', 'co_teacher')),
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (teaching_group_id, instructor_id)
            )
            """
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_tgi_group ON teaching_group_instructors(teaching_group_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_tgi_instructor ON teaching_group_instructors(instructor_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_tgi_role ON teaching_group_instructors(teaching_group_id, role)"
        )
    )
    # ترحيل: كل مجموعة حالية → صف primary من instructor_id
    op.execute(
        text(
            """
            INSERT INTO teaching_group_instructors (teaching_group_id, instructor_id, role, sort_order)
            SELECT tg.id, tg.instructor_id, 'primary', 0
            FROM teaching_groups tg
            WHERE tg.instructor_id IS NOT NULL AND tg.instructor_id > 0
              AND NOT EXISTS (
                SELECT 1 FROM teaching_group_instructors tgi
                WHERE tgi.teaching_group_id = tg.id AND tgi.instructor_id = tg.instructor_id
              )
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(text("DROP TABLE IF EXISTS teaching_group_instructors"))
