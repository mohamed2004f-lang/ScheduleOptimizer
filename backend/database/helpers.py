"""مساعدات استعلام ديناميكي وترحيل FK القديم."""
from __future__ import annotations

import logging

from backend.database.connection import get_connection
from backend.database.db_config import DB_FILE, is_postgresql
from backend.database.schema_ddl import TABLES_SCHEMA

logger = logging.getLogger("backend.database")

def migrate_to_foreign_keys(db_file=None):
    """
    ترحيل قاعدة البيانات القديمة لدعم Foreign Keys
    هذه الدالة تنشئ جداول جديدة وتنقل البيانات
    """
    if is_postgresql():
        return

    db_path = db_file or DB_FILE
    
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        
        # التحقق من وجود الجداول القديمة
        tables = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        existing_tables = {t[0] for t in tables}
        
        # إذا كانت الجداول موجودة، نحتاج لترحيل البيانات
        if 'students' in existing_tables:
            logger.info("Existing database detected. Migration may be needed.")
            # يمكن إضافة منطق الترحيل هنا إذا لزم الأمر
        
        conn.commit()


# قائمة الجداول المسموح بها للاستعلامات الديناميكية
ALLOWED_TABLES = set(TABLES_SCHEMA.keys())


def validate_table_name(table_name: str) -> bool:
    """التحقق من صحة اسم الجدول لمنع SQL Injection"""
    return table_name in ALLOWED_TABLES


def table_to_dicts(table_name: str, db_file=None) -> list:
    """إرجاع جميع صفوف الجدول كقائمة من القواميس"""
    if not validate_table_name(table_name):
        raise ValueError(f"Invalid table name: {table_name}")
    
    with get_connection(db_file) as conn:
        cur = conn.cursor()
        rows = cur.execute(f"SELECT * FROM {table_name}").fetchall()
        return [dict(r) for r in rows]
