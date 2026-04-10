"""
تحويل بسيط من DDL الخاص بـ SQLite إلى صيغة مقبولة في PostgreSQL.
يُستخدم في ترحيلات Alembic الأولية فقط؛ راجع docs/ALEMBIC.md.
"""
from __future__ import annotations

import re


def sqlite_ddl_to_postgres(sql: str) -> str:
    s = sql.strip()
    # SQLite: INTEGER PRIMARY KEY AUTOINCREMENT -> PostgreSQL: SERIAL PRIMARY KEY
    # (SERIAL = INTEGER + sequence؛ يتوافق مع أعمدة INTEGER الأجنبية)
    s = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "SERIAL PRIMARY KEY",
        s,
        flags=re.IGNORECASE,
    )
    # PostgreSQL يحجز user (وغيرها) كأسماء؛ نضع علامات اقتباس للأعمدة المتعارضة
    s = re.sub(r"^(\s*)user(\s+TEXT\b)", r'\1"user"\2', s, flags=re.MULTILINE | re.IGNORECASE)
    s = re.sub(
        r"ON\s+notifications\s*\(\s*user\s*,",
        'ON notifications ("user",',
        s,
        flags=re.IGNORECASE,
    )
    return s
