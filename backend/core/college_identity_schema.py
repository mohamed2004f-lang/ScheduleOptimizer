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

COLLEGE_IDENTITY_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("strategic_plan_summary_ar", "TEXT DEFAULT ''"),
)

PROGRAM_IG_ALIGNMENT_SQLITE = (
    "program_ig_alignment",
    """
    CREATE TABLE IF NOT EXISTS program_ig_alignment (
        program_id INTEGER NOT NULL,
        ig_code TEXT NOT NULL,
        alignment_type TEXT NOT NULL DEFAULT 'supports',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (program_id, ig_code)
    )
    """,
)

PROGRAM_IG_ALIGNMENT_PG = (
    "program_ig_alignment",
    """
    CREATE TABLE IF NOT EXISTS program_ig_alignment (
        program_id INTEGER NOT NULL,
        ig_code TEXT NOT NULL,
        alignment_type TEXT NOT NULL DEFAULT 'supports',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (program_id, ig_code)
    )
    """,
)

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


def _commit_schema_step(conn, label: str = "") -> None:
    """يُثبّت DDL قبل البذرة؛ يمنع تراجع PostgreSQL عن ALTER عند فشل لاحق."""
    try:
        conn.commit()
    except Exception as e:
        logger.warning("college identity schema commit%s: %s", f" ({label})" if label else "", e)
        try:
            conn.rollback()
        except Exception:
            pass


def _pg_recover_transaction(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


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
    alignment_tbl = PROGRAM_IG_ALIGNMENT_PG if pg else PROGRAM_IG_ALIGNMENT_SQLITE
    try:
        cur.execute(alignment_tbl[1])
    except Exception as e:
        logger.debug("program_ig_alignment: %s", e)
    if pg:
        for col, typ in PROGRAM_PROFILE_COLUMNS:
            try:
                cur.execute(f"ALTER TABLE programs ADD COLUMN IF NOT EXISTS {col} {typ}")
            except Exception as e:
                logger.debug("pg programs.%s: %s", col, e)
                _pg_recover_transaction(conn)
        try:
            cur.execute(
                f"ALTER TABLE program_goals ADD COLUMN IF NOT EXISTS {GOAL_IG_COLUMN[0]} {GOAL_IG_COLUMN[1]}"
            )
        except Exception as e:
            logger.debug("pg program_goals.parent_ig_code: %s", e)
            _pg_recover_transaction(conn)
        identity_cols = {c.lower() for c in fetch_table_columns(conn, "college_identity")}
        for col, typ in COLLEGE_IDENTITY_EXTRA_COLUMNS:
            if col.lower() in identity_cols:
                continue
            try:
                cur.execute(f"ALTER TABLE college_identity ADD COLUMN {col} {typ}")
                identity_cols.add(col.lower())
                logger.info("college_identity: added column %s", col)
            except Exception as e:
                logger.warning("pg college_identity.%s: %s", col, e)
                _pg_recover_transaction(conn)
        _commit_schema_step(conn, "ddl columns")
        try:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_csg_parent ON college_strategic_goals(parent_code, is_active)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_gkpi_goal ON goal_kpi(goal_code)")
        except Exception as e:
            logger.debug("college identity indexes: %s", e)
            _pg_recover_transaction(conn)
    else:
        for col, typ in PROGRAM_PROFILE_COLUMNS:
            _sqlite_add_column(conn, cur, "programs", col, typ)
        _sqlite_add_column(conn, cur, "program_goals", GOAL_IG_COLUMN[0], GOAL_IG_COLUMN[1])
        for col, typ in COLLEGE_IDENTITY_EXTRA_COLUMNS:
            _sqlite_add_column(conn, cur, "college_identity", col, typ)
        _commit_schema_step(conn, "ddl columns")
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
    _commit_schema_step(conn, "seed")
