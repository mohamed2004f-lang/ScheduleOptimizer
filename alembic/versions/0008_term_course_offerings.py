"""عرض مقررات الفصل: term_course_offerings + term_offering_state

Revision ID: 0008_term_offer
Revises: 0007_cal_start
Create Date: 2026-08-17
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0008_term_offer"
down_revision = "0007_cal_start"
branch_labels = None
depends_on = None

_NEW_TABLES = ("term_course_offerings", "term_offering_state")
_NEW_INDEX_MARKERS = ("idx_term_offerings_term", "idx_term_offerings_dept")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    from backend.database.pg_convert import sqlite_ddl_to_postgres
    from backend.database.schema_ddl import INDEXES, TABLES_SCHEMA

    for name in _NEW_TABLES:
        op.execute(text(sqlite_ddl_to_postgres(TABLES_SCHEMA[name])))
    for idx in INDEXES:
        if any(marker in idx for marker in _NEW_INDEX_MARKERS):
            op.execute(text(sqlite_ddl_to_postgres(idx)))


def downgrade() -> None:
    pass
