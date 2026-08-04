"""مشاركات أرشيف موحّدة — كلية وقسم (قراءة للمستلمين)."""

from __future__ import annotations

import datetime
from typing import Any

from backend.database.database import is_postgresql, table_exists
from backend.services.quality_metrics import _row_val

SOURCE_COLLEGE = "college_item"
SOURCE_DEPT = "dept_item"
TARGET_ROLE = "role"
TARGET_USER = "user"
TARGET_DEPT_ALL = "dept_all_instructors"

SHAREABLE_ROLES: tuple[str, ...] = (
    "college_dean",
    "academic_vice_dean",
    "college_quality_lead",
    "head_of_department",
)


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


def _row_dict(row) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return {}


def ensure_archive_share_tables(conn) -> None:
    if table_exists(conn, "archive_share_grants"):
        return
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS archive_share_grants (
                id BIGSERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                item_id BIGINT NOT NULL,
                target_kind TEXT NOT NULL,
                target_role TEXT DEFAULT '',
                target_user_id BIGINT,
                target_username TEXT DEFAULT '',
                target_department_id BIGINT,
                shared_by TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
    else:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS archive_share_grants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                target_kind TEXT NOT NULL,
                target_role TEXT DEFAULT '',
                target_user_id INTEGER,
                target_username TEXT DEFAULT '',
                target_department_id INTEGER,
                shared_by TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
    try:
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_archive_share_item "
            "ON archive_share_grants(source, item_id, is_active)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_archive_share_target "
            "ON archive_share_grants(target_kind, target_role, target_username, is_active)"
        )
    except Exception:
        pass
    conn.commit()


def _normalize_role_target(role: str) -> str:
    r = (role or "").strip().lower()
    aliases = {
        "college_quality_head": "college_quality_lead",
        "is_college_quality_lead": "college_quality_lead",
        "dean": "college_dean",
        "vice_dean": "academic_vice_dean",
        "hod": "head_of_department",
    }
    r = aliases.get(r, r)
    if r not in SHAREABLE_ROLES:
        raise ValueError(f"دور مشاركة غير مدعوم: {role}")
    return r


def replace_item_shares(
    conn,
    *,
    source: str,
    item_id: int,
    grants: list[dict[str, Any]],
    shared_by: str,
) -> list[dict[str, Any]]:
    """يستبدل منح المشاركة النشطة للبند بمنح جديدة."""
    ensure_archive_share_tables(conn)
    if source not in (SOURCE_COLLEGE, SOURCE_DEPT):
        raise ValueError("مصدر مشاركة غير معروف")
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE archive_share_grants
        SET is_active = 0
        WHERE source = ? AND item_id = ? AND COALESCE(is_active, 1) = 1
        """,
        (source, int(item_id)),
    )
    now = _now()
    out: list[dict[str, Any]] = []
    for g in grants or []:
        kind = (g.get("target_kind") or "").strip().lower()
        if kind == TARGET_ROLE:
            role = _normalize_role_target(str(g.get("target_role") or ""))
            dept_raw = g.get("target_department_id")
            dept_id = int(dept_raw) if dept_raw not in (None, "", "null") else None
            # رؤساء أقسام يمكن تقييدهم بقسم محدد
            cur.execute(
                """
                INSERT INTO archive_share_grants (
                    source, item_id, target_kind, target_role, target_user_id,
                    target_username, target_department_id, shared_by, created_at, is_active
                ) VALUES (?, ?, ?, ?, NULL, '', ?, ?, ?, 1)
                """,
                (source, int(item_id), TARGET_ROLE, role, dept_id, (shared_by or "")[:120], now),
            )
            out.append({"target_kind": TARGET_ROLE, "target_role": role, "target_department_id": dept_id})
        elif kind == TARGET_USER:
            uname = (g.get("target_username") or "").strip()
            uid_raw = g.get("target_user_id")
            uid = int(uid_raw) if uid_raw not in (None, "", "null") else None
            if not uname and uid is None:
                raise ValueError("مستخدم المشاركة مطلوب")
            if not uname and uid is not None and table_exists(conn, "users"):
                row = cur.execute("SELECT username FROM users WHERE id = ?", (uid,)).fetchone()
                uname = str(_row_val(row, 0, "username") or "") if row else ""
            if not uname:
                raise ValueError("تعذر تحديد اسم المستخدم للمشاركة")
            cur.execute(
                """
                INSERT INTO archive_share_grants (
                    source, item_id, target_kind, target_role, target_user_id,
                    target_username, target_department_id, shared_by, created_at, is_active
                ) VALUES (?, ?, ?, '', ?, ?, NULL, ?, ?, 1)
                """,
                (
                    source,
                    int(item_id),
                    TARGET_USER,
                    uid,
                    uname[:120],
                    (shared_by or "")[:120],
                    now,
                ),
            )
            out.append({"target_kind": TARGET_USER, "target_username": uname, "target_user_id": uid})
        elif kind == TARGET_DEPT_ALL:
            dept_raw = g.get("target_department_id")
            if dept_raw in (None, "", "null"):
                raise ValueError("قسم مطلوب لمشاركة كل أعضاء التدريس")
            dept_id = int(dept_raw)
            cur.execute(
                """
                INSERT INTO archive_share_grants (
                    source, item_id, target_kind, target_role, target_user_id,
                    target_username, target_department_id, shared_by, created_at, is_active
                ) VALUES (?, ?, ?, '', NULL, '', ?, ?, ?, 1)
                """,
                (source, int(item_id), TARGET_DEPT_ALL, dept_id, (shared_by or "")[:120], now),
            )
            out.append({"target_kind": TARGET_DEPT_ALL, "target_department_id": dept_id})
        else:
            raise ValueError(f"نوع مستلم غير معروف: {kind}")
    conn.commit()
    return out


def list_item_shares(conn, *, source: str, item_id: int) -> list[dict[str, Any]]:
    ensure_archive_share_tables(conn)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, source, item_id, target_kind, target_role, target_user_id,
               target_username, target_department_id, shared_by, created_at, is_active
        FROM archive_share_grants
        WHERE source = ? AND item_id = ? AND COALESCE(is_active, 1) = 1
        ORDER BY id
        """,
        (source, int(item_id)),
    ).fetchall() or []
    out = []
    for r in rows:
        d = _row_dict(r)
        if not d and r is not None:
            keys = [
                "id", "source", "item_id", "target_kind", "target_role", "target_user_id",
                "target_username", "target_department_id", "shared_by", "created_at", "is_active",
            ]
            d = {keys[i]: r[i] for i in range(min(len(keys), len(r)))}
        out.append(d)
    return out


def _user_department_id(conn, username: str) -> int | None:
    if not username or not table_exists(conn, "users"):
        return None
    cur = conn.cursor()
    row = cur.execute(
        "SELECT department_id FROM users WHERE username = ? LIMIT 1",
        (username,),
    ).fetchone()
    if not row:
        return None
    val = _row_val(row, 0, "department_id")
    try:
        return int(val) if val not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _is_instructor_in_dept(conn, username: str, department_id: int) -> bool:
    """عضو تدريس مرتبط بالقسم عبر users.department_id أو instructors."""
    uname = (username or "").strip()
    if not uname:
        return False
    ud = _user_department_id(conn, uname)
    if ud is not None and int(ud) == int(department_id):
        return True
    if not table_exists(conn, "instructors"):
        return False
    cur = conn.cursor()
    # ربط شائع: instructors.code أو name يطابق username، أو عبر جدول منفصل
    try:
        row = cur.execute(
            """
            SELECT id FROM instructors
            WHERE department_id = ?
              AND (
                LOWER(COALESCE(instructor_id, '')) = LOWER(?)
                OR LOWER(COALESCE(code, '')) = LOWER(?)
                OR LOWER(COALESCE(name_ar, '')) = LOWER(?)
              )
            LIMIT 1
            """,
            (int(department_id), uname, uname, uname),
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def user_can_read_shared_item(
    conn,
    *,
    source: str,
    item_id: int,
    username: str,
    user_role: str,
    is_college_quality_lead: bool = False,
    home_department_id: int | None = None,
) -> bool:
    """هل يملك المستخدم منحة قراءة نشطة على البند؟"""
    ensure_archive_share_tables(conn)
    uname = (username or "").strip()
    role = (user_role or "").strip().lower()
    effective_roles = {role}
    if is_college_quality_lead:
        effective_roles.add("college_quality_lead")
    shares = list_item_shares(conn, source=source, item_id=item_id)
    if not shares:
        return False
    user_dept = home_department_id
    if user_dept is None:
        user_dept = _user_department_id(conn, uname)

    for s in shares:
        kind = (s.get("target_kind") or "").strip()
        if kind == TARGET_USER:
            tu = (s.get("target_username") or "").strip()
            if tu and tu.lower() == uname.lower():
                return True
        elif kind == TARGET_ROLE:
            tr = (s.get("target_role") or "").strip().lower()
            if tr not in effective_roles:
                continue
            tdept = s.get("target_department_id")
            if tr == "head_of_department" and tdept not in (None, ""):
                if user_dept is None or int(user_dept) != int(tdept):
                    continue
            return True
        elif kind == TARGET_DEPT_ALL:
            tdept = s.get("target_department_id")
            if tdept in (None, ""):
                continue
            if role in ("instructor", "head_of_department") or is_college_quality_lead:
                if _is_instructor_in_dept(conn, uname, int(tdept)):
                    return True
                if user_dept is not None and int(user_dept) == int(tdept):
                    return True
    return False


def list_shared_item_ids_for_user(
    conn,
    *,
    source: str,
    username: str,
    user_role: str,
    is_college_quality_lead: bool = False,
    home_department_id: int | None = None,
) -> list[int]:
    ensure_archive_share_tables(conn)
    uname = (username or "").strip()
    role = (user_role or "").strip().lower()
    effective_roles = {role}
    if is_college_quality_lead:
        effective_roles.add("college_quality_lead")
    user_dept = home_department_id if home_department_id is not None else _user_department_id(conn, uname)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT item_id, target_kind, target_role, target_username, target_department_id
        FROM archive_share_grants
        WHERE source = ? AND COALESCE(is_active, 1) = 1
        """,
        (source,),
    ).fetchall() or []
    ids: set[int] = set()
    for r in rows:
        d = _row_dict(r)
        if not d and r is not None:
            keys = ["item_id", "target_kind", "target_role", "target_username", "target_department_id"]
            d = {keys[i]: r[i] for i in range(min(len(keys), len(r)))}
        kind = (d.get("target_kind") or "").strip()
        item_id = int(d.get("item_id") or 0)
        if not item_id:
            continue
        if kind == TARGET_USER:
            tu = (d.get("target_username") or "").strip()
            if tu and tu.lower() == uname.lower():
                ids.add(item_id)
        elif kind == TARGET_ROLE:
            tr = (d.get("target_role") or "").strip().lower()
            if tr not in effective_roles:
                continue
            tdept = d.get("target_department_id")
            if tr == "head_of_department" and tdept not in (None, ""):
                if user_dept is None or int(user_dept) != int(tdept):
                    continue
            ids.add(item_id)
        elif kind == TARGET_DEPT_ALL:
            tdept = d.get("target_department_id")
            if tdept in (None, ""):
                continue
            ok = False
            if user_dept is not None and int(user_dept) == int(tdept):
                ok = True
            elif _is_instructor_in_dept(conn, uname, int(tdept)):
                ok = True
            if ok:
                ids.add(item_id)
    return sorted(ids)
