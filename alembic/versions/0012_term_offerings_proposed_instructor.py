"""عمود الأستاذ المقترح في عرض مقررات الفصل (استرشادي فقط).

Revision ID: 0012_offer_prop_inst
Revises: 0011_admin_close
Create Date: 2026-08-22
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0012_offer_prop_inst"
down_revision = "0011_admin_close"
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
            ALTER TABLE term_course_offerings
                ADD COLUMN IF NOT EXISTS proposed_instructor_id INTEGER
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(
        text("ALTER TABLE term_course_offerings DROP COLUMN IF EXISTS proposed_instructor_id")
    )
