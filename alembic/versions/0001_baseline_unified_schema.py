"""baseline: مخطط موحّد (SQLite عبر ensure_tables، PostgreSQL عبر تحويل DDL)

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
    if bind.dialect.name == "sqlite":
        from backend.database.database import ensure_tables

        ensure_tables()
        return
    if bind.dialect.name == "postgresql":
        from backend.database.database import INDEXES, TABLES_SCHEMA
        from backend.database.pg_convert import sqlite_ddl_to_postgres

        for stmt in TABLES_SCHEMA.values():
            op.execute(text(sqlite_ddl_to_postgres(stmt)))
        for idx in INDEXES:
            op.execute(text(sqlite_ddl_to_postgres(idx)))
        return
    raise NotImplementedError(f"Unsupported database dialect: {bind.dialect.name}")


def downgrade() -> None:
    # مخطط معقّد؛ لا يوجد تراجع آمن تلقائياً
    pass
