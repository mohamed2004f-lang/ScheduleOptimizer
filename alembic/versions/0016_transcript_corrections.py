"""امتحانات/كشف: طلبات تصحيح كشف الدرجات من المشرف لاعتماد رئيس القسم.

Revision ID: 0016_tx_corr
Revises: 0015_exams_tg
Create Date: 2026-09-27
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0016_tx_corr"
down_revision = "0015_exams_tg"
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
            CREATE TABLE IF NOT EXISTS transcript_correction_requests (
                id BIGSERIAL PRIMARY KEY,
                student_id TEXT NOT NULL,
                semester TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                reason TEXT NOT NULL DEFAULT '',
                hod_note TEXT NOT NULL DEFAULT '',
                submitted_by TEXT NOT NULL DEFAULT '',
                instructor_id BIGINT,
                department_id BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                submitted_at TIMESTAMPTZ,
                reviewed_at TIMESTAMPTZ,
                reviewed_by TEXT NOT NULL DEFAULT ''
            )
            """
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_tx_corr_status_dept "
            "ON transcript_correction_requests (status, department_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_tx_corr_student "
            "ON transcript_correction_requests (student_id, semester)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_tx_corr_instructor "
            "ON transcript_correction_requests (instructor_id, status)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise NotImplementedError(
            f"ScheduleOptimizer migrations support PostgreSQL only, got {bind.dialect.name}"
        )
    op.execute(text("DROP INDEX IF EXISTS idx_tx_corr_instructor"))
    op.execute(text("DROP INDEX IF EXISTS idx_tx_corr_student"))
    op.execute(text("DROP INDEX IF EXISTS idx_tx_corr_status_dept"))
    op.execute(text("DROP TABLE IF EXISTS transcript_correction_requests"))
