"""عرض المقررات لكل قسم: UNIQUE(term_key, course_name, department_id) + حالة اعتماد لكل قسم.

Revision ID: 0009_dept_offer
Revises: 0008_term_offer
Create Date: 2026-08-17
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0009_dept_offer"
down_revision = "0008_term_offer"
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
            ALTER TABLE term_offering_state
                ADD COLUMN IF NOT EXISTS department_id INTEGER NOT NULL DEFAULT 0
            """
        )
    )
    op.execute(text("ALTER TABLE term_offering_state DROP CONSTRAINT IF EXISTS term_offering_state_pkey"))
    op.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'term_offering_state_term_dept_pk'
                ) THEN
                    ALTER TABLE term_offering_state
                        ADD CONSTRAINT term_offering_state_term_dept_pk
                        PRIMARY KEY (term_key, department_id);
                END IF;
            END $$
            """
        )
    )
    op.execute(
        text(
            """
            ALTER TABLE term_course_offerings
                ALTER COLUMN department_id SET DEFAULT 0
            """
        )
    )
    op.execute(
        text(
            """
            UPDATE term_course_offerings
            SET department_id = 0
            WHERE department_id IS NULL
            """
        )
    )
    op.execute(
        text(
            """
            ALTER TABLE term_course_offerings
                ALTER COLUMN department_id SET NOT NULL
            """
        )
    )
    op.execute(
        text(
            """
            ALTER TABLE term_course_offerings
                DROP CONSTRAINT IF EXISTS term_course_offerings_term_key_course_name_key
            """
        )
    )
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_term_offerings_term_course_dept
            ON term_course_offerings (term_key, course_name, department_id)
            """
        )
    )


def downgrade() -> None:
    pass
