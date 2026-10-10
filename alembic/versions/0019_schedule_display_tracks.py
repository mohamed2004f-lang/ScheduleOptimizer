"""أعمدة عرض جدول الاتجاه العام + display_column على مجموعات التدريس.

Revision ID: 0019_display_tracks
Revises: 0018_sem_scope
Create Date: 2026-10-10
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0019_display_tracks"
down_revision = "0018_sem_scope"
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
            CREATE TABLE IF NOT EXISTS schedule_display_tracks (
                id BIGSERIAL PRIMARY KEY,
                semester TEXT NOT NULL,
                department_id BIGINT NOT NULL REFERENCES departments(id)
                    ON DELETE RESTRICT ON UPDATE CASCADE,
                track_index INTEGER NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (semester, department_id, track_index)
            )
            """
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_sched_display_tracks_sem_dept "
            "ON schedule_display_tracks (semester, department_id)"
        )
    )
    op.execute(
        text(
            "ALTER TABLE teaching_groups "
            "ADD COLUMN IF NOT EXISTS display_column INTEGER"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(text("ALTER TABLE teaching_groups DROP COLUMN IF EXISTS display_column"))
    op.execute(text("DROP INDEX IF EXISTS idx_sched_display_tracks_sem_dept"))
    op.execute(text("DROP TABLE IF EXISTS schedule_display_tracks"))
