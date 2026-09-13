"""إخفاء حركات خاطئة في سجل الإضافة والإسقاط.

Revision ID: 0013_reg_chg_hidden
Revises: 0012_offer_prop_inst
Create Date: 2026-09-11
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0013_reg_chg_hidden"
down_revision = "0012_offer_prop_inst"
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
            ALTER TABLE registration_changes_log
                ADD COLUMN IF NOT EXISTS is_hidden INTEGER NOT NULL DEFAULT 0
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(text("ALTER TABLE registration_changes_log DROP COLUMN IF EXISTS is_hidden"))
