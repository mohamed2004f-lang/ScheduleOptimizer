"""تقويم الربيع: بند تسجيل المستجدين كرقم 2 مع إزاحة البنود التالية.

Revision ID: 0006_spring_new
Revises: 0005_term_ops
Create Date: 2026-08-16
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0006_spring_new"
down_revision = "0005_term_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )

    def _titles(item_no: int) -> list[str]:
        rows = bind.execute(
            text(
                """
                SELECT title FROM academic_calendar
                WHERE term IN ('spring', 'ربيع', 'فصل الربيع')
                  AND item_no = :n
                  AND COALESCE(is_deleted, 0) = 0
                """
            ),
            {"n": item_no},
        ).fetchall()
        return [str(r[0] or "") for r in rows or []]

    t2 = _titles(2)
    t3 = _titles(3)
    if any("المستجدين" in t for t in t2):
        return
    if any("بداية الدراسة" in t for t in t3) and not any("بداية الدراسة" in t for t in t2):
        return

    bind.execute(
        text(
            """
            UPDATE academic_calendar SET item_no = item_no + 1000
            WHERE term IN ('spring', 'ربيع', 'فصل الربيع') AND item_no >= 2
            """
        )
    )
    bind.execute(
        text(
            """
            UPDATE academic_calendar SET item_no = item_no - 999
            WHERE term IN ('spring', 'ربيع', 'فصل الربيع') AND item_no >= 1002
            """
        )
    )
    bind.execute(
        text(
            """
            UPDATE term_windows
            SET calendar_item_no = calendar_item_no + 1
            WHERE term_key LIKE 'spring:%'
              AND calendar_item_no IS NOT NULL
              AND calendar_item_no >= 2
            """
        )
    )


def downgrade() -> None:
    pass
