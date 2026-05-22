"""ترقية مخطط مخرجات التعلم (PLO/CLO/GLO) — متوافق SQLite وPostgreSQL."""

from __future__ import annotations

import logging

from backend.database.database import fetch_table_columns, is_postgresql

logger = logging.getLogger(__name__)

PLO_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("title_en", "TEXT DEFAULT ''"),
    ("domain", "TEXT DEFAULT 'skills'"),
    ("bloom_level", "TEXT DEFAULT ''"),
    ("performance_indicator", "TEXT DEFAULT ''"),
    ("accreditation_tag", "TEXT DEFAULT ''"),
    ("version", "INTEGER NOT NULL DEFAULT 1"),
    ("effective_from", "TEXT DEFAULT ''"),
    ("governance_status", "TEXT NOT NULL DEFAULT 'draft'"),
    ("approved_by", "TEXT DEFAULT ''"),
    ("approved_at", "TEXT DEFAULT ''"),
    ("parent_glo_code", "TEXT DEFAULT ''"),
)

LINK_COVERAGE_COLUMN = ("coverage_level", "TEXT NOT NULL DEFAULT ''")

NEW_TABLES_SQLITE: tuple[tuple[str, str], ...] = (
    (
        "course_learning_outcomes",
        """
        CREATE TABLE IF NOT EXISTS course_learning_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_course_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            title_ar TEXT NOT NULL,
            title_en TEXT DEFAULT '',
            description TEXT DEFAULT '',
            bloom_level TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (program_course_id, code),
            FOREIGN KEY (program_course_id) REFERENCES program_courses(id) ON DELETE CASCADE
        )
        """,
    ),
    (
        "clo_plo_links",
        """
        CREATE TABLE IF NOT EXISTS clo_plo_links (
            clo_id INTEGER NOT NULL,
            outcome_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (clo_id, outcome_id),
            FOREIGN KEY (clo_id) REFERENCES course_learning_outcomes(id) ON DELETE CASCADE,
            FOREIGN KEY (outcome_id) REFERENCES program_learning_outcomes(id) ON DELETE CASCADE
        )
        """,
    ),
    (
        "plo_revision_log",
        """
        CREATE TABLE IF NOT EXISTS plo_revision_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            outcome_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            snapshot_json TEXT DEFAULT '',
            actor TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (outcome_id) REFERENCES program_learning_outcomes(id) ON DELETE CASCADE
        )
        """,
    ),
)

NEW_TABLES_PG: tuple[tuple[str, str], ...] = (
    (
        "course_learning_outcomes",
        """
        CREATE TABLE IF NOT EXISTS course_learning_outcomes (
            id BIGSERIAL PRIMARY KEY,
            program_course_id BIGINT NOT NULL,
            code TEXT NOT NULL,
            title_ar TEXT NOT NULL,
            title_en TEXT DEFAULT '',
            description TEXT DEFAULT '',
            bloom_level TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (program_course_id, code),
            CONSTRAINT clo_pc_fk FOREIGN KEY (program_course_id)
                REFERENCES program_courses(id) ON DELETE CASCADE
        )
        """,
    ),
    (
        "clo_plo_links",
        """
        CREATE TABLE IF NOT EXISTS clo_plo_links (
            clo_id BIGINT NOT NULL,
            outcome_id BIGINT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (clo_id, outcome_id),
            CONSTRAINT cloplo_clo_fk FOREIGN KEY (clo_id)
                REFERENCES course_learning_outcomes(id) ON DELETE CASCADE,
            CONSTRAINT cloplo_plo_fk FOREIGN KEY (outcome_id)
                REFERENCES program_learning_outcomes(id) ON DELETE CASCADE
        )
        """,
    ),
    (
        "plo_revision_log",
        """
        CREATE TABLE IF NOT EXISTS plo_revision_log (
            id BIGSERIAL PRIMARY KEY,
            outcome_id BIGINT NOT NULL,
            action TEXT NOT NULL,
            snapshot_json TEXT DEFAULT '',
            actor TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT plor_outcome_fk FOREIGN KEY (outcome_id)
                REFERENCES program_learning_outcomes(id) ON DELETE CASCADE
        )
        """,
    ),
)

PG_ALTER_PLO = [
    f"ALTER TABLE program_learning_outcomes ADD COLUMN IF NOT EXISTS {col} {typ}"
    for col, typ in PLO_EXTRA_COLUMNS
]
PG_ALTER_LINKS = [
    "ALTER TABLE program_course_learning_outcomes ADD COLUMN IF NOT EXISTS coverage_level TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE plo_course_master_links ADD COLUMN IF NOT EXISTS coverage_level TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE section_ilo_assessments ADD COLUMN IF NOT EXISTS clo_id BIGINT",
]


def _sqlite_add_column(conn, cur, table: str, col: str, ddl: str) -> None:
    cols = fetch_table_columns(conn, table)
    if col in cols:
        return
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    except Exception as e:
        logger.debug("sqlite alter %s.%s skipped: %s", table, col, e)


def ensure_plo_enhancement_schema(conn) -> None:
    """يُستدعى بعد إنشاء الجداول الأساسية."""
    cur = conn.cursor()
    pg = is_postgresql()
    if pg:
        for stmt in PG_ALTER_PLO + PG_ALTER_LINKS:
            try:
                cur.execute(stmt)
            except Exception as e:
                logger.debug("pg plo alter skipped: %s", e)
        for _name, ddl in NEW_TABLES_PG:
            try:
                cur.execute(ddl)
            except Exception as e:
                logger.warning("pg plo table %s: %s", _name, e)
        try:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_clo_program_course ON course_learning_outcomes(program_course_id, is_active)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_plor_outcome ON plo_revision_log(outcome_id)")
        except Exception:
            pass
    else:
        for col, typ in PLO_EXTRA_COLUMNS:
            _sqlite_add_column(conn, cur, "program_learning_outcomes", col, typ)
        for table in ("program_course_learning_outcomes", "plo_course_master_links"):
            _sqlite_add_column(conn, cur, table, LINK_COVERAGE_COLUMN[0], LINK_COVERAGE_COLUMN[1])
        _sqlite_add_column(conn, cur, "section_ilo_assessments", "clo_id", "INTEGER")
        for _name, ddl in NEW_TABLES_SQLITE:
            try:
                cur.execute(ddl)
            except Exception as e:
                logger.warning("sqlite plo table %s: %s", _name, e)
        for idx in (
            "CREATE INDEX IF NOT EXISTS idx_clo_program_course ON course_learning_outcomes(program_course_id, is_active)",
            "CREATE INDEX IF NOT EXISTS idx_plor_outcome ON plo_revision_log(outcome_id)",
        ):
            try:
                cur.execute(idx)
            except Exception:
                pass
    try:
        conn.commit()
    except Exception:
        pass
