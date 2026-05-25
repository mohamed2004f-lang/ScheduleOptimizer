"""مخطط هوية الكلية: رسالة/رؤية، أهداف IG، ربط GLO، مؤشرات KPI."""

from __future__ import annotations

import logging

from backend.database.database import conn_is_postgresql, fetch_table_columns, is_postgresql

logger = logging.getLogger(__name__)

PROGRAM_PROFILE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("intro_ar", "TEXT DEFAULT ''"),
    ("mission_ar", "TEXT DEFAULT ''"),
    ("vision_ar", "TEXT DEFAULT ''"),
)

GOAL_IG_COLUMN = ("parent_ig_code", "TEXT DEFAULT ''")

COLLEGE_TABLES_SQLITE: tuple[tuple[str, str], ...] = (
    (
        "college_identity",
        """
        CREATE TABLE IF NOT EXISTS college_identity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            intro_ar TEXT DEFAULT '',
            mission_ar TEXT NOT NULL DEFAULT '',
            vision_ar TEXT NOT NULL DEFAULT '',
            values_json TEXT NOT NULL DEFAULT '[]',
            effective_from TEXT DEFAULT '',
            governance_status TEXT NOT NULL DEFAULT 'approved',
            approved_by TEXT DEFAULT '',
            approved_at TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ),
    (
        "college_strategic_goals",
        """
        CREATE TABLE IF NOT EXISTS college_strategic_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            parent_code TEXT DEFAULT '',
            title_ar TEXT NOT NULL,
            title_en TEXT DEFAULT '',
            description TEXT DEFAULT '',
            pillar TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            governance_status TEXT NOT NULL DEFAULT 'approved',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ),
    (
        "college_goal_glo_links",
        """
        CREATE TABLE IF NOT EXISTS college_goal_glo_links (
            goal_code TEXT NOT NULL,
            glo_code TEXT NOT NULL,
            alignment TEXT NOT NULL DEFAULT 'primary',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (goal_code, glo_code)
        )
        """,
    ),
    (
        "goal_kpi",
        """
        CREATE TABLE IF NOT EXISTS goal_kpi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_code TEXT NOT NULL,
            name_ar TEXT NOT NULL,
            target_value REAL,
            actual_value REAL,
            unit TEXT DEFAULT '',
            frequency TEXT DEFAULT 'annual',
            data_source TEXT NOT NULL DEFAULT 'manual',
            period_label TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            notes TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ),
)

COLLEGE_TABLES_PG: tuple[tuple[str, str], ...] = (
    (
        "college_identity",
        """
        CREATE TABLE IF NOT EXISTS college_identity (
            id BIGSERIAL PRIMARY KEY,
            intro_ar TEXT DEFAULT '',
            mission_ar TEXT NOT NULL DEFAULT '',
            vision_ar TEXT NOT NULL DEFAULT '',
            values_json TEXT NOT NULL DEFAULT '[]',
            effective_from TEXT DEFAULT '',
            governance_status TEXT NOT NULL DEFAULT 'approved',
            approved_by TEXT DEFAULT '',
            approved_at TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ),
    (
        "college_strategic_goals",
        """
        CREATE TABLE IF NOT EXISTS college_strategic_goals (
            id BIGSERIAL PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            parent_code TEXT DEFAULT '',
            title_ar TEXT NOT NULL,
            title_en TEXT DEFAULT '',
            description TEXT DEFAULT '',
            pillar TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            governance_status TEXT NOT NULL DEFAULT 'approved',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ),
    (
        "college_goal_glo_links",
        """
        CREATE TABLE IF NOT EXISTS college_goal_glo_links (
            goal_code TEXT NOT NULL,
            glo_code TEXT NOT NULL,
            alignment TEXT NOT NULL DEFAULT 'primary',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (goal_code, glo_code)
        )
        """,
    ),
    (
        "goal_kpi",
        """
        CREATE TABLE IF NOT EXISTS goal_kpi (
            id BIGSERIAL PRIMARY KEY,
            goal_code TEXT NOT NULL,
            name_ar TEXT NOT NULL,
            target_value DOUBLE PRECISION,
            actual_value DOUBLE PRECISION,
            unit TEXT DEFAULT '',
            frequency TEXT DEFAULT 'annual',
            data_source TEXT NOT NULL DEFAULT 'manual',
            period_label TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            notes TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ),
)


def _sqlite_add_column(conn, cur, table: str, col: str, ddl: str) -> None:
    cols = fetch_table_columns(conn, table)
    if col in cols:
        return
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    except Exception as e:
        logger.debug("sqlite alter %s.%s skipped: %s", table, col, e)


def ensure_college_identity_schema(conn) -> None:
    cur = conn.cursor()
    pg = conn_is_postgresql(conn)
    tables = COLLEGE_TABLES_PG if pg else COLLEGE_TABLES_SQLITE
    for _name, ddl in tables:
        try:
            cur.execute(ddl)
        except Exception as e:
            logger.warning("college identity table %s: %s", _name, e)
    if pg:
        for col, typ in PROGRAM_PROFILE_COLUMNS:
            try:
                cur.execute(f"ALTER TABLE programs ADD COLUMN IF NOT EXISTS {col} {typ}")
            except Exception as e:
                logger.debug("pg programs.%s: %s", col, e)
        try:
            cur.execute(
                f"ALTER TABLE program_goals ADD COLUMN IF NOT EXISTS {GOAL_IG_COLUMN[0]} {GOAL_IG_COLUMN[1]}"
            )
        except Exception as e:
            logger.debug("pg program_goals.parent_ig_code: %s", e)
        try:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_csg_parent ON college_strategic_goals(parent_code, is_active)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_gkpi_goal ON goal_kpi(goal_code)")
        except Exception:
            pass
    else:
        for col, typ in PROGRAM_PROFILE_COLUMNS:
            _sqlite_add_column(conn, cur, "programs", col, typ)
        _sqlite_add_column(conn, cur, "program_goals", GOAL_IG_COLUMN[0], GOAL_IG_COLUMN[1])
        for idx in (
            "CREATE INDEX IF NOT EXISTS idx_csg_parent ON college_strategic_goals(parent_code, is_active)",
            "CREATE INDEX IF NOT EXISTS idx_gkpi_goal ON goal_kpi(goal_code)",
        ):
            try:
                cur.execute(idx)
            except Exception:
                pass
    try:
        from backend.core.college_identity_seed import seed_college_identity_defaults

        seed_college_identity_defaults(conn)
    except Exception as e:
        logger.debug("college identity seed skipped: %s", e)
    try:
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
