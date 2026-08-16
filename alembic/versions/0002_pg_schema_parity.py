"""parity: ترقيات PostgreSQL التي كانت تُطبَّق عند الإقلاع عبر ensure_tables

Revision ID: 0002_pg_parity
Revises: 0001_baseline
Create Date: 2026-08-15

Idempotent: ALTER/CREATE IF NOT EXISTS. آمن على قواعد أُنشئت سابقاً عبر الإقلاع.
"""
from __future__ import annotations

from alembic import op

revision = "0002_pg_parity"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    from backend.database.database import _ensure_tables_postgresql

    _ensure_tables_postgresql()


def downgrade() -> None:
    pass
