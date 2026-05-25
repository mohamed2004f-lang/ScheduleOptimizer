"""مخطط تقييم المخرجات المرتبط بالدرجات (بنود تقييم CLO + إتقان الطالب)."""

from __future__ import annotations

import logging

from backend.database.database import conn_is_postgresql

logger = logging.getLogger(__name__)

TABLES_SQLITE: tuple[tuple[str, str], ...] = (
    (
        "section_assessment_items",
        """
        CREATE TABLE IF NOT EXISTS section_assessment_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL,
            semester TEXT NOT NULL,
            clo_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            assessment_type TEXT NOT NULL DEFAULT 'other',
            max_score REAL NOT NULL DEFAULT 100,
            weight_percent REAL NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (clo_id) REFERENCES course_learning_outcomes(id) ON DELETE CASCADE
        )
        """,
    ),
    (
        "student_assessment_scores",
        """
        CREATE TABLE IF NOT EXISTS student_assessment_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assessment_item_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            score REAL,
            is_absent INTEGER NOT NULL DEFAULT 0 CHECK (is_absent IN (0, 1)),
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (assessment_item_id, student_id),
            FOREIGN KEY (assessment_item_id) REFERENCES section_assessment_items(id) ON DELETE CASCADE
        )
        """,
    ),
    (
        "student_clo_mastery",
        """
        CREATE TABLE IF NOT EXISTS student_clo_mastery (
            student_id TEXT NOT NULL,
            section_id INTEGER NOT NULL,
            semester TEXT NOT NULL,
            clo_id INTEGER NOT NULL,
            mastery_percent REAL,
            source TEXT NOT NULL DEFAULT 'computed',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (student_id, section_id, semester, clo_id),
            FOREIGN KEY (clo_id) REFERENCES course_learning_outcomes(id) ON DELETE CASCADE
        )
        """,
    ),
    (
        "section_clo_assessments",
        """
        CREATE TABLE IF NOT EXISTS section_clo_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL,
            instructor_id INTEGER NOT NULL,
            semester TEXT NOT NULL,
            clo_id INTEGER NOT NULL,
            achievement_percent INTEGER CHECK (achievement_percent BETWEEN 0 AND 100),
            notes TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (section_id, instructor_id, semester, clo_id),
            FOREIGN KEY (clo_id) REFERENCES course_learning_outcomes(id) ON DELETE CASCADE
        )
        """,
    ),
)

TABLES_PG: tuple[tuple[str, str], ...] = (
    (
        "section_assessment_items",
        """
        CREATE TABLE IF NOT EXISTS section_assessment_items (
            id BIGSERIAL PRIMARY KEY,
            section_id BIGINT NOT NULL,
            semester TEXT NOT NULL,
            clo_id BIGINT NOT NULL,
            label TEXT NOT NULL,
            assessment_type TEXT NOT NULL DEFAULT 'other',
            max_score DOUBLE PRECISION NOT NULL DEFAULT 100,
            weight_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT sai_clo_fk FOREIGN KEY (clo_id)
                REFERENCES course_learning_outcomes(id) ON DELETE CASCADE
        )
        """,
    ),
    (
        "student_assessment_scores",
        """
        CREATE TABLE IF NOT EXISTS student_assessment_scores (
            id BIGSERIAL PRIMARY KEY,
            assessment_item_id BIGINT NOT NULL,
            student_id TEXT NOT NULL,
            score DOUBLE PRECISION,
            is_absent INTEGER NOT NULL DEFAULT 0 CHECK (is_absent IN (0, 1)),
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (assessment_item_id, student_id),
            CONSTRAINT sas_item_fk FOREIGN KEY (assessment_item_id)
                REFERENCES section_assessment_items(id) ON DELETE CASCADE
        )
        """,
    ),
    (
        "student_clo_mastery",
        """
        CREATE TABLE IF NOT EXISTS student_clo_mastery (
            student_id TEXT NOT NULL,
            section_id BIGINT NOT NULL,
            semester TEXT NOT NULL,
            clo_id BIGINT NOT NULL,
            mastery_percent DOUBLE PRECISION,
            source TEXT NOT NULL DEFAULT 'computed',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (student_id, section_id, semester, clo_id),
            CONSTRAINT scm_clo_fk FOREIGN KEY (clo_id)
                REFERENCES course_learning_outcomes(id) ON DELETE CASCADE
        )
        """,
    ),
    (
        "section_clo_assessments",
        """
        CREATE TABLE IF NOT EXISTS section_clo_assessments (
            id BIGSERIAL PRIMARY KEY,
            section_id BIGINT NOT NULL,
            instructor_id BIGINT NOT NULL,
            semester TEXT NOT NULL,
            clo_id BIGINT NOT NULL,
            achievement_percent INTEGER CHECK (achievement_percent BETWEEN 0 AND 100),
            notes TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (section_id, instructor_id, semester, clo_id),
            CONSTRAINT sca_clo_fk FOREIGN KEY (clo_id)
                REFERENCES course_learning_outcomes(id) ON DELETE CASCADE
        )
        """,
    ),
)

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_sai_section_sem ON section_assessment_items(section_id, semester, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_sas_item ON student_assessment_scores(assessment_item_id)",
    "CREATE INDEX IF NOT EXISTS idx_scm_student ON student_clo_mastery(student_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_scm_section ON student_clo_mastery(section_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_sca_section ON section_clo_assessments(section_id, semester)",
)


def ensure_outcome_assessment_schema(conn) -> None:
    cur = conn.cursor()
    pg = conn_is_postgresql(conn)
    tables = TABLES_PG if pg else TABLES_SQLITE
    for name, ddl in tables:
        try:
            cur.execute(ddl)
        except Exception as e:
            logger.warning("outcome assessment table %s: %s", name, e)
    for idx in INDEXES:
        try:
            cur.execute(idx)
        except Exception:
            pass
    try:
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
