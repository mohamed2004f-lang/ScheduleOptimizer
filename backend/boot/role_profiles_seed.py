"""Seed جداول role_profiles و permission_definitions."""

from __future__ import annotations

import logging

from backend.core.permissions import PERMISSION_CATALOG, ROLE_PROFILE_SEED
from backend.core.role_profile_policy import LOCKED_PROFILE_CODES

logger = logging.getLogger(__name__)

_SEED_CODES = frozenset(p["code"] for p in ROLE_PROFILE_SEED)

# مفاتيح تشغيل قسم يجب ألا تبقى ممنوحة افتراضياً لقالب العميد/الوكيل
_LEADERSHIP_STALE_DEPT_OPS = (
    "can_manage_schedule_edit",
    "can_manage_exam_schedule_edit",
    "can_manage_courses_edit",
    "can_manage_students",
    "can_manage_registrations_edit",
    "can_manage_enrollment_plans_edit",
    "can_manage_transcript_admin",
    "can_manage_instructors_edit",
    "can_migrate_registrations_to_transcript",
    "can_edit_accreditation_catalog",
)

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
        default_home_path TEXT,
        is_active INTEGER NOT NULL DEFAULT 1
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
        default_home_path TEXT,
        is_active INTEGER NOT NULL DEFAULT 1
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
    # ترقية: عمود is_active للقواعد القديمة
    try:
        if pg:
            cur.execute(
                "ALTER TABLE role_profiles ADD COLUMN IF NOT EXISTS is_active INTEGER NOT NULL DEFAULT 1"
            )
        else:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(role_profiles)").fetchall()]
            if "is_active" not in cols:
                cur.execute(
                    "ALTER TABLE role_profiles ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
                )
    except Exception:
        logger.debug("role_profiles.is_active column ensure skipped", exc_info=True)
    conn.commit()


def seed_role_profiles(conn) -> dict:
    """يُعبّئ التعاريف والقوالب إن لم تكن موجودة — دون مسح تخصيصات القوالب المخصصة."""
    ensure_role_profile_tables(conn, pg=_is_pg(conn))
    cur = conn.cursor()
    stats = {"permissions": 0, "profiles": 0, "links": 0, "links_inserted": 0, "custom_skipped": 0}
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
        code = prof["code"]
        existing = cur.execute(
            "SELECT id, COALESCE(is_system, 0) FROM role_profiles WHERE code = ? LIMIT 1",
            (code,),
        ).fetchone()
        existed = existing is not None
        cur.execute(
            """
            INSERT INTO role_profiles (code, name_ar, base_role, scope_mode, is_system, default_home_path, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(code) DO UPDATE SET
              name_ar = excluded.name_ar,
              base_role = excluded.base_role,
              scope_mode = excluded.scope_mode,
              is_system = excluded.is_system,
              default_home_path = excluded.default_home_path
            """,
            (
                code,
                prof["name_ar"],
                prof["base_role"],
                prof.get("scope_mode", "none"),
                int(prof.get("is_system") or 0),
                prof.get("default_home_path"),
            ),
        )
        stats["profiles"] += 1
        row = cur.execute("SELECT id FROM role_profiles WHERE code = ?", (code,)).fetchone()
        if not row:
            continue
        pid = int(row[0] if not hasattr(row, "keys") else row["id"])
        locked = code in LOCKED_PROFILE_CODES
        if locked:
            # مزامنة كاملة للقوالب المقفلة
            for pk in prof.get("permissions") or []:
                cur.execute(
                    """
                    INSERT INTO role_profile_permissions (profile_id, permission_key, granted)
                    VALUES (?, ?, 1)
                    ON CONFLICT(profile_id, permission_key) DO UPDATE SET granted = 1
                    """,
                    (pid, pk),
                )
                stats["links"] += 1
        else:
            # قوالب seed غير مقفلة: أضف المفاتيح الناقصة فقط (لا تُلغِ تخصيصات سابقة)
            for pk in prof.get("permissions") or []:
                cur.execute(
                    """
                    INSERT INTO role_profile_permissions (profile_id, permission_key, granted)
                    VALUES (?, ?, 1)
                    ON CONFLICT(profile_id, permission_key) DO NOTHING
                    """,
                    (pid, pk),
                )
                try:
                    if cur.rowcount:
                        stats["links_inserted"] += 1
                except Exception:
                    pass
                stats["links"] += 1
        if existed and not locked and int(prof.get("is_system") or 0) == 0:
            stats["custom_skipped"] += 0  # placeholder for metrics clarity
    # لا تلمس قوالب DB غير الموجودة في seed (مخصصة)
    try:
        custom_rows = cur.execute(
            "SELECT code FROM role_profiles WHERE code NOT IN ({})".format(
                ",".join("?" for _ in _SEED_CODES)
            ),
            tuple(_SEED_CODES),
        ).fetchall()
        stats["custom_profiles"] = len(custom_rows or [])
    except Exception:
        stats["custom_profiles"] = 0
    sanitize = sanitize_leadership_profile_permissions(conn)
    stats["leadership_sanitized"] = sanitize
    conn.commit()
    return stats


def sanitize_leadership_profile_permissions(conn) -> dict:
    """
    إزالة منح تشغيل القسم القديمة من قوالب العميد/الوكيل،
    وإضافة مفاتيح العرض وتشغيل الكلية الافتراضية إن نقصت.
    """
    from backend.core.capability_gates import COLLEGE_OPS_EDIT_KEYS, LEADERSHIP_PANEL_VIEW_KEYS

    cur = conn.cursor()
    out = {"profiles": 0, "removed": 0, "added": 0}
    ensure_keys = set(COLLEGE_OPS_EDIT_KEYS) | set(LEADERSHIP_PANEL_VIEW_KEYS)
    for code in ("college_dean", "academic_vice_dean"):
        row = cur.execute("SELECT id FROM role_profiles WHERE code = ? LIMIT 1", (code,)).fetchone()
        if not row:
            continue
        pid = int(row[0] if not hasattr(row, "keys") else row["id"])
        out["profiles"] += 1
        for key in _LEADERSHIP_STALE_DEPT_OPS:
            cur.execute(
                "DELETE FROM role_profile_permissions WHERE profile_id = ? AND permission_key = ?",
                (pid, key),
            )
            try:
                out["removed"] += int(cur.rowcount or 0)
            except Exception:
                pass
        # مفاتيح seed الأساسية غير التشغيلية + العرض/تشغيل الكلية
        seed = next((p for p in ROLE_PROFILE_SEED if p.get("code") == code), None) or {}
        wanted = set(seed.get("permissions") or []) | ensure_keys
        wanted -= set(_LEADERSHIP_STALE_DEPT_OPS)
        cat = {p["key"]: p for p in PERMISSION_CATALOG}
        for pk in sorted(wanted):
            meta = cat.get(pk)
            if meta:
                try:
                    cur.execute(
                        """
                        INSERT INTO permission_definitions (key, group_key, group_label_ar, label_ar, sort_order)
                        VALUES (?, ?, ?, ?, 0)
                        ON CONFLICT(key) DO NOTHING
                        """,
                        (pk, meta["group_key"], meta["group_label_ar"], meta["label_ar"]),
                    )
                except Exception:
                    pass
            cur.execute(
                """
                INSERT INTO role_profile_permissions (profile_id, permission_key, granted)
                VALUES (?, ?, 1)
                ON CONFLICT(profile_id, permission_key) DO UPDATE SET granted = 1
                """,
                (pid, pk),
            )
            out["added"] += 1
    logger.info(
        "sanitize_leadership_profile_permissions profiles=%s removed=%s added=%s",
        out["profiles"],
        out["removed"],
        out["added"],
    )
    return out


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
