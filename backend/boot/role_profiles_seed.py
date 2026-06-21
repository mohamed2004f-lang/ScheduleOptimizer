"""Seed جداول role_profiles و permission_definitions."""

from __future__ import annotations

import logging

from backend.core.permissions import PERMISSION_CATALOG, ROLE_PROFILE_SEED

logger = logging.getLogger(__name__)

ROLE_PROFILES_DDL = [
    """
    CREATE TABLE IF NOT EXISTS permission_definitions (
        key TEXT PRIMARY KEY,
        group_key TEXT NOT NULL,
        group_label_ar TEXT NOT NULL,
        label_ar TEXT NOT NULL,
        description_ar TEXT,
        sort_order INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS role_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name_ar TEXT NOT NULL,
        base_role TEXT NOT NULL,
        scope_mode TEXT NOT NULL DEFAULT 'none',
        is_system INTEGER NOT NULL DEFAULT 0,
        description_ar TEXT,
        default_home_path TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS role_profile_permissions (
        profile_id INTEGER NOT NULL,
        permission_key TEXT NOT NULL,
        granted INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (profile_id, permission_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_permission_overrides (
        username TEXT NOT NULL,
        permission_key TEXT NOT NULL,
        granted INTEGER NOT NULL,
        PRIMARY KEY (username, permission_key)
    )
    """,
]

ROLE_PROFILES_DDL_PG = [
    """
    CREATE TABLE IF NOT EXISTS permission_definitions (
        key TEXT PRIMARY KEY,
        group_key TEXT NOT NULL,
        group_label_ar TEXT NOT NULL,
        label_ar TEXT NOT NULL,
        description_ar TEXT,
        sort_order INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS role_profiles (
        id BIGSERIAL PRIMARY KEY,
        code TEXT UNIQUE NOT NULL,
        name_ar TEXT NOT NULL,
        base_role TEXT NOT NULL,
        scope_mode TEXT NOT NULL DEFAULT 'none',
        is_system INTEGER NOT NULL DEFAULT 0,
        description_ar TEXT,
        default_home_path TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS role_profile_permissions (
        profile_id BIGINT NOT NULL REFERENCES role_profiles(id) ON DELETE CASCADE,
        permission_key TEXT NOT NULL REFERENCES permission_definitions(key),
        granted INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (profile_id, permission_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_permission_overrides (
        username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
        permission_key TEXT NOT NULL REFERENCES permission_definitions(key),
        granted INTEGER NOT NULL,
        PRIMARY KEY (username, permission_key)
    )
    """,
]


def ensure_role_profile_tables(conn, *, pg: bool = False) -> None:
    stmts = ROLE_PROFILES_DDL_PG if pg else ROLE_PROFILES_DDL
    cur = conn.cursor()
    for stmt in stmts:
        try:
            cur.execute(stmt)
        except Exception:
            logger.exception("role profile DDL failed")
    conn.commit()


def seed_role_profiles(conn) -> dict:
    """يُعبّئ التعاريف والقوالب إن لم تكن موجودة."""
    ensure_role_profile_tables(conn, pg=_is_pg(conn))
    cur = conn.cursor()
    stats = {"permissions": 0, "profiles": 0, "links": 0}
    for i, p in enumerate(PERMISSION_CATALOG):
        cur.execute(
            """
            INSERT INTO permission_definitions (key, group_key, group_label_ar, label_ar, sort_order)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO NOTHING
            """,
            (p["key"], p["group_key"], p["group_label_ar"], p["label_ar"], i),
        )
        stats["permissions"] += 1
    for prof in ROLE_PROFILE_SEED:
        cur.execute(
            """
            INSERT INTO role_profiles (code, name_ar, base_role, scope_mode, is_system, default_home_path)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
              name_ar = excluded.name_ar,
              base_role = excluded.base_role,
              scope_mode = excluded.scope_mode,
              is_system = excluded.is_system,
              default_home_path = excluded.default_home_path
            """,
            (
                prof["code"],
                prof["name_ar"],
                prof["base_role"],
                prof.get("scope_mode", "none"),
                int(prof.get("is_system") or 0),
                prof.get("default_home_path"),
            ),
        )
        stats["profiles"] += 1
        row = cur.execute("SELECT id FROM role_profiles WHERE code = ?", (prof["code"],)).fetchone()
        if not row:
            continue
        pid = row[0] if not hasattr(row, "keys") else row["id"]
        for pk in prof.get("permissions") or []:
            cur.execute(
                """
                INSERT INTO role_profile_permissions (profile_id, permission_key, granted)
                VALUES (?, ?, 1)
                ON CONFLICT(profile_id, permission_key) DO UPDATE SET granted = 1
                """,
                (int(pid), pk),
            )
            stats["links"] += 1
    conn.commit()
    return stats


def migrate_legacy_admin_to_system(conn, admin_username: str | None = None) -> int:
    """يحوّل حساب admin في .env إلى system_admin مخفي."""
    cur = conn.cursor()
    n = 0
    try:
        if admin_username:
            cur.execute(
                """
                UPDATE users SET role = 'system_admin', is_system_account = 1
                WHERE lower(username) = lower(?)
                """,
                (admin_username.strip(),),
            )
            n += cur.rowcount or 0
        cur.execute(
            """
            UPDATE users SET role = 'system_admin', is_system_account = 1
            WHERE lower(role) = 'admin' AND COALESCE(is_system_account, 0) = 0
            """
        )
        n += cur.rowcount or 0
    except Exception:
        logger.exception("migrate_legacy_admin_to_system failed")
    conn.commit()
    return n


def _is_pg(conn) -> bool:
    try:
        from backend.database.database import is_postgresql
        return bool(is_postgresql())
    except Exception:
        return False
