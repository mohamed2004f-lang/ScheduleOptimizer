"""محرّك الفصل — موجات 2–4: مهلة، أرشيف السلة، سجل التعديل، استثناءات

Revision ID: 0005_term_ops
Revises: 0004_term_engine
Create Date: 2026-08-16
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0005_term_ops"
down_revision = "0004_term_engine"
branch_labels = None
depends_on = None

_NEW_TABLES = (
    "term_amendment_log",
    "term_registration_archives",
    "term_operation_exceptions",
)
_NEW_INDEX_MARKERS = (
    "idx_term_amend_log_term",
    "idx_term_reg_arch_term",
    "idx_term_op_exc_student",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    from backend.database.pg_convert import sqlite_ddl_to_postgres
    from backend.database.schema_ddl import INDEXES, TABLES_SCHEMA

    op.execute(text("ALTER TABLE term_windows ADD COLUMN IF NOT EXISTS grace_until TEXT"))
    op.execute(text("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS semester TEXT DEFAULT ''"))
    for name in _NEW_TABLES:
        op.execute(text(sqlite_ddl_to_postgres(TABLES_SCHEMA[name])))
    for idx in INDEXES:
        if any(marker in idx for marker in _NEW_INDEX_MARKERS):
            op.execute(text(sqlite_ddl_to_postgres(idx)))


def downgrade() -> None:
    pass
