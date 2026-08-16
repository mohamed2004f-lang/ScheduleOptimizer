"""baseline: مخطط الجداول الأساسية على PostgreSQL

Revision ID: 0001_baseline
Revises:
Create Date: 2026-04-10

"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    from backend.database.pg_convert import sqlite_ddl_to_postgres
    from backend.database.schema_ddl import INDEXES, TABLES_SCHEMA

    for stmt in TABLES_SCHEMA.values():
        op.execute(text(sqlite_ddl_to_postgres(stmt)))
    for idx in INDEXES:
        op.execute(text(sqlite_ddl_to_postgres(idx)))


def downgrade() -> None:
    pass
