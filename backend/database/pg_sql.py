"""
Legacy SQLite-to-PostgreSQL adapter (archived).

Runtime no longer depends on this module.
It is intentionally disabled to prevent accidental reuse.
"""

raise RuntimeError(
    "backend.database.pg_sql is archived and disabled. "
    "Use PostgreSQL-native SQL directly in runtime."
)
