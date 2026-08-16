"""
واجهة توافق لطبقة قاعدة البيانات.

التنفيذ موزّع على وحدات شقيقة تحت ``backend.database``.
كل الاستيرادات القديمة من هذا الملف تبقى صالحة دون تغيير المستدعين.
"""
from __future__ import annotations

import logging

from backend.database.backfills import (
    HOME_ASSIGNMENT_SECTION_ID,
    backfill_academic_pathway_defaults,
    backfill_instructor_cross_department_data,
)
from backend.database.connection import (
    close_pool,
    db_transaction,
    get_connection,
    _get_or_create_pool,
    _pg_pool,
)
from backend.database.db_config import (
    DATABASE_URL,
    DB_FILE,
    PG_POOL_MAX_SIZE,
    PG_POOL_MIN_SIZE,
    PROJECT_ROOT,
    _in_pytest,
    _pg_conninfo,
    _sqlite_db_file_path,
    allow_ensure_tables,
    is_postgresql,
    make_url,
    require_postgres_url,
)
from backend.database.helpers import (
    ALLOWED_TABLES,
    migrate_to_foreign_keys,
    table_to_dicts,
    validate_table_name,
)
from backend.database.introspection import (
    conn_is_postgresql,
    fetch_table_columns,
    schedule_pk_column,
    sql_notifications_user_col,
    table_exists,
)
from backend.database.migrations_postgresql import _ensure_tables_postgresql
from backend.database.pg_compat import (
    _adapt_pg_execute_sql,
    _PgConnectionWrapper,
    _PgCursorWrapper,
    _PgRowAdapter,
    _wrap_pg_row,
)
from backend.database.schema_ddl import INDEXES, TABLES_SCHEMA
from backend.database.schema_guard import (
    alembic_revision_present,
    assert_schema_ready,
    ensure_tables,
)

logger = logging.getLogger(__name__)

# اسم قديم استخدمه بعض مسارات الاعتماد
SCHEMA = TABLES_SCHEMA

__all__ = [
    "ALLOWED_TABLES",
    "DATABASE_URL",
    "DB_FILE",
    "HOME_ASSIGNMENT_SECTION_ID",
    "INDEXES",
    "PG_POOL_MAX_SIZE",
    "PG_POOL_MIN_SIZE",
    "PROJECT_ROOT",
    "SCHEMA",
    "TABLES_SCHEMA",
    "_PgConnectionWrapper",
    "_PgCursorWrapper",
    "_PgRowAdapter",
    "_adapt_pg_execute_sql",
    "_ensure_tables_postgresql",
    "_get_or_create_pool",
    "_in_pytest",
    "_pg_conninfo",
    "_pg_pool",
    "_sqlite_db_file_path",
    "_wrap_pg_row",
    "alembic_revision_present",
    "allow_ensure_tables",
    "assert_schema_ready",
    "backfill_academic_pathway_defaults",
    "backfill_instructor_cross_department_data",
    "close_pool",
    "conn_is_postgresql",
    "db_transaction",
    "ensure_tables",
    "fetch_table_columns",
    "get_connection",
    "is_postgresql",
    "make_url",
    "migrate_to_foreign_keys",
    "require_postgres_url",
    "schedule_pk_column",
    "sql_notifications_user_col",
    "table_exists",
    "table_to_dicts",
    "validate_table_name",
]
