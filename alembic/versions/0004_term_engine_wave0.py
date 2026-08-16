"""محرّك الفصل — موجة 0: term_master + نوافذ + نسخ التقويم

Revision ID: 0004_term_engine
Revises: 0003_invite_hash
Create Date: 2026-08-16
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0004_term_engine"
down_revision = "0003_invite_hash"
branch_labels = None
depends_on = None

_NEW_TABLES = ("term_master", "term_windows", "academic_calendar_versions")
_NEW_INDEX_MARKERS = (
    "idx_term_master_current",
    "idx_term_master_year_season",
    "idx_term_windows_term",
    "idx_cal_versions_term",
)


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
