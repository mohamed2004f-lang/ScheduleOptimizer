"""تجزئة رموز دعوات الاستبيان الخارجية

Revision ID: 0003_invite_hash
Revises: 0002_pg_parity
Create Date: 2026-08-16
"""
from __future__ import annotations

from alembic import op

revision = "0003_invite_hash"
down_revision = "0002_pg_parity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'survey_invites'
            ) THEN
                ALTER TABLE survey_invites ADD COLUMN IF NOT EXISTS token_hash TEXT;
                CREATE UNIQUE INDEX IF NOT EXISTS uq_survey_invites_token_hash
                    ON survey_invites (token_hash);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    pass
