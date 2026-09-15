"""سياسة تواصل الأستاذ وروابط مجموعات المقرر (ظهور اختياري للطالب)."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from backend.database.database import fetch_table_columns, table_exists

_PHONE_DIGITS_RE = re.compile(r"\D+")
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._]{2,34}$")
_ALLOWED_PLATFORMS = frozenset({"whatsapp", "telegram", "other"})


def normalize_whatsapp_phone(raw: Any) -> str | None:
    """أرقام دولية بدون + أو مسافات؛ يُرجع None إن فارغ/غير صالح."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    digits = _PHONE_DIGITS_RE.sub("", s)
    if digits.startswith("00"):
        digits = digits[2:]
    # ليبيا محلي: 09xxxxxxxx → 2189xxxxxxx
    if digits.startswith("0") and len(digits) == 10 and digits[1] == "9":
        digits = "218" + digits[1:]
    if len(digits) < 8 or len(digits) > 15:
        return None
    if not digits.isdigit():
        return None
    return digits


def ensure_instructor_contact_schema(conn) -> bool:
    """
    يضمن أعمدة تواصل الأساتذة وجدول روابط المجموعات على القاعدة الحية.
    يُستدعى عند أول استخدام حتى لا تعتمد الواجهة على إعادة تشغيل الترحيل فقط.
    """
    from backend.database.database import is_postgresql

    cur = conn.cursor()
    cols = {c.lower() for c in (fetch_table_columns(conn, "instructors") or [])}
    alters = [
        ("contact_email_visible", "INTEGER NOT NULL DEFAULT 0"),
        ("whatsapp_phone", "TEXT"),
        ("whatsapp_phone_visible", "INTEGER NOT NULL DEFAULT 0"),
        ("whatsapp_username", "TEXT"),
        ("whatsapp_username_key", "TEXT"),
        ("whatsapp_username_visible", "INTEGER NOT NULL DEFAULT 0"),
    ]
    pg = is_postgresql()
    for name, typ in alters:
        if name in cols:
            continue
        try:
            if pg:
                cur.execute(f"ALTER TABLE instructors ADD COLUMN IF NOT EXISTS {name} {typ}")
            else:
                cur.execute(f"ALTER TABLE instructors ADD COLUMN {name} {typ}")
        except Exception:
            pass
    if not table_exists(conn, "course_group_links"):
        try:
            if pg:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS course_group_links (
                        id BIGSERIAL PRIMARY KEY,
                        teaching_group_id BIGINT NOT NULL,
                        semester TEXT NOT NULL DEFAULT '',
                        platform TEXT NOT NULL DEFAULT 'other'
                            CHECK (platform IN ('whatsapp', 'telegram', 'other')),
                        label_ar TEXT NOT NULL DEFAULT '',
                        url TEXT NOT NULL,
                        is_visible INTEGER NOT NULL DEFAULT 0 CHECK (is_visible IN (0, 1)),
                        sort_order INTEGER NOT NULL DEFAULT 0,
                        created_by_instructor_id BIGINT,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            else:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS course_group_links (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        teaching_group_id INTEGER NOT NULL,
                        semester TEXT NOT NULL DEFAULT '',
                        platform TEXT NOT NULL DEFAULT 'other'
                            CHECK (platform IN ('whatsapp', 'telegram', 'other')),
                        label_ar TEXT NOT NULL DEFAULT '',
                        url TEXT NOT NULL,
                        is_visible INTEGER NOT NULL DEFAULT 0 CHECK (is_visible IN (0, 1)),
                        sort_order INTEGER NOT NULL DEFAULT 0,
                        created_by_instructor_id INTEGER,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_cgl_tg_vis ON course_group_links(teaching_group_id, is_visible)"
            )
        except Exception:
            pass
    try:
        conn.commit()
    except Exception:
        pass
    # إعادة قراءة الأعمدة بعد ALTER
    return instructor_contact_columns_ready(conn)


def normalize_whatsapp_username(raw: Any) -> str | None:
    """يطبّع اسم مستخدم واتساب بدون @؛ None إن فارغ/غير صالح."""
    if raw is None:
        return None
    s = str(raw).strip().lstrip("@").strip()
    if not s:
        return None
    if not _USERNAME_RE.match(s):
        return None
    return s


def normalize_whatsapp_username_key(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if not s:
        return None
    if len(s) > 32:
        return None
    if not re.match(r"^[A-Z0-9\-]+$", s):
        return None
    return s


def whatsapp_phone_link(phone_digits: str | None) -> str | None:
    if not phone_digits:
        return None
    return f"https://wa.me/{phone_digits}"


def validate_group_link_url(url: Any, platform: str) -> tuple[bool, str | None]:
    """التحقق من رابط مجموعة المقرر حسب المنصة."""
    plat = (platform or "other").strip().lower()
    if plat not in _ALLOWED_PLATFORMS:
        return False, "منصة غير مدعومة."
    raw = str(url or "").strip()
    if not raw:
        return False, "الرابط مطلوب."
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return False, "يُسمح بروابط http/https فقط."
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "رابط غير صالح."
    if plat == "whatsapp":
        if host not in ("chat.whatsapp.com", "wa.me", "www.whatsapp.com", "api.whatsapp.com"):
            return False, "رابط واتساب غير معروف (استخدم chat.whatsapp.com أو wa.me)."
    elif plat == "telegram":
        if host not in ("t.me", "telegram.me", "www.t.me"):
            return False, "رابط تيليغرام غير معروف (استخدم t.me)."
    return True, None


def coerce_bool01(raw: Any, default: int = 0) -> int:
    if raw is None:
        return int(default)
    if isinstance(raw, str):
        return 0 if raw.strip().lower() in ("0", "false", "no", "") else 1
    return 1 if bool(raw) else 0


def instructor_contact_columns_ready(conn) -> bool:
    cols = {c.lower() for c in (fetch_table_columns(conn, "instructors") or [])}
    needed = {
        "contact_email_visible",
        "whatsapp_phone",
        "whatsapp_phone_visible",
        "whatsapp_username",
        "whatsapp_username_key",
        "whatsapp_username_visible",
    }
    return needed.issubset(cols)


def course_group_links_ready(conn) -> bool:
    return table_exists(conn, "course_group_links")


def parse_contact_settings_payload(
    data: dict,
    *,
    visibility_scope: str = "full",
) -> tuple[dict | None, str | None]:
    """
    يحوّل جسم الطلب إلى حقول جاهزة للحفظ.

    visibility_scope:
      - full: الأستاذ يتحكم بكل أعلام الظهور
      - email_only: الإدارة/رئيس القسم يضبط ظهور الإيميل فقط؛ ظهور واتساب يبقى للأستاذ
    """
    phone_raw = data.get("whatsapp_phone")
    phone = None
    if phone_raw not in (None, ""):
        phone = normalize_whatsapp_phone(phone_raw)
        if phone is None:
            return None, "رقم واتساب غير صالح."

    uname_raw = data.get("whatsapp_username")
    uname = None
    if uname_raw not in (None, ""):
        uname = normalize_whatsapp_username(uname_raw)
        if uname is None:
            return None, "اسم مستخدم واتساب غير صالح."

    key_raw = data.get("whatsapp_username_key")
    key = None
    if key_raw not in (None, ""):
        key = normalize_whatsapp_username_key(key_raw)
        if key is None:
            return None, "مفتاح اسم المستخدم غير صالح."

    email_vis = coerce_bool01(data.get("contact_email_visible"), 0)
    scope = (visibility_scope or "full").strip().lower()
    if scope not in ("full", "email_only"):
        scope = "full"

    if scope == "full":
        phone_vis = coerce_bool01(data.get("whatsapp_phone_visible"), 0)
        uname_vis = coerce_bool01(data.get("whatsapp_username_visible"), 0)
        if phone_vis and not phone:
            return None, "لا يمكن إظهار رقم واتساب دون إدخال رقم صالح."
        if uname_vis and not uname:
            return None, "لا يمكن إظهار اسم المستخدم دون إدخال اسم صالح."
        return {
            "contact_email_visible": email_vis,
            "whatsapp_phone": phone,
            "whatsapp_phone_visible": phone_vis,
            "whatsapp_username": uname,
            "whatsapp_username_key": key if uname else None,
            "whatsapp_username_visible": uname_vis,
            "visibility_scope": "full",
        }, None

    # email_only: لا يُقبل فرض ظهور واتساب من الإدارة
    return {
        "contact_email_visible": email_vis,
        "whatsapp_phone": phone,
        "whatsapp_username": uname,
        "whatsapp_username_key": key if uname else None,
        "visibility_scope": "email_only",
    }, None


def load_instructor_contact_row(conn, instructor_id: int) -> dict:
    """إعدادات التواصل كاملة لصاحب الصلاحية (إدارة/الأستاذ نفسه)."""
    cur = conn.cursor()
    if not instructor_contact_columns_ready(conn):
        row = cur.execute(
            "SELECT id, name, email FROM instructors WHERE id = ? LIMIT 1",
            (int(instructor_id),),
        ).fetchone()
        if not row:
            return {}
        return {
            "instructor_id": int(row[0]),
            "name": row[1] or "",
            "email": row[2] or "",
            "contact_email_visible": 0,
            "whatsapp_phone": None,
            "whatsapp_phone_visible": 0,
            "whatsapp_username": None,
            "whatsapp_username_key": None,
            "whatsapp_username_visible": 0,
        }
    row = cur.execute(
        """
        SELECT id, name, email,
               COALESCE(contact_email_visible, 0),
               whatsapp_phone,
               COALESCE(whatsapp_phone_visible, 0),
               whatsapp_username,
               whatsapp_username_key,
               COALESCE(whatsapp_username_visible, 0)
        FROM instructors WHERE id = ? LIMIT 1
        """,
        (int(instructor_id),),
    ).fetchone()
    if not row:
        return {}
    return {
        "instructor_id": int(row[0]),
        "name": row[1] or "",
        "email": row[2] or "",
        "contact_email_visible": int(row[3] or 0),
        "whatsapp_phone": row[4],
        "whatsapp_phone_visible": int(row[5] or 0),
        "whatsapp_username": row[6],
        "whatsapp_username_key": row[7],
        "whatsapp_username_visible": int(row[8] or 0),
    }


def save_instructor_contact_settings(conn, instructor_id: int, fields: dict) -> None:
    if not instructor_contact_columns_ready(conn):
        raise RuntimeError("أعمدة التواصل غير جاهزة.")
    scope = str(fields.get("visibility_scope") or "full").strip().lower()
    existing = load_instructor_contact_row(conn, int(instructor_id))
    if scope == "email_only":
        phone_vis = int(existing.get("whatsapp_phone_visible") or 0)
        uname_vis = int(existing.get("whatsapp_username_visible") or 0)
    else:
        phone_vis = int(fields.get("whatsapp_phone_visible") or 0)
        uname_vis = int(fields.get("whatsapp_username_visible") or 0)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE instructors SET
            contact_email_visible = ?,
            whatsapp_phone = ?,
            whatsapp_phone_visible = ?,
            whatsapp_username = ?,
            whatsapp_username_key = ?,
            whatsapp_username_visible = ?
        WHERE id = ?
        """,
        (
            int(fields.get("contact_email_visible") or 0),
            fields.get("whatsapp_phone"),
            phone_vis,
            fields.get("whatsapp_username"),
            fields.get("whatsapp_username_key"),
            uname_vis,
            int(instructor_id),
        ),
    )


def list_group_links(conn, teaching_group_id: int, *, visible_only: bool = False) -> list[dict]:
    if not course_group_links_ready(conn):
        return []
    cur = conn.cursor()
    vis_sql = " AND COALESCE(is_visible, 0) = 1" if visible_only else ""
    rows = cur.execute(
        f"""
        SELECT id, teaching_group_id, semester, platform, label_ar, url,
               COALESCE(is_visible, 0), COALESCE(sort_order, 0),
               created_by_instructor_id, updated_at
        FROM course_group_links
        WHERE teaching_group_id = ?{vis_sql}
        ORDER BY COALESCE(sort_order, 0), id
        """,
        (int(teaching_group_id),),
    ).fetchall()
    out = []
    for r in rows or []:
        out.append(
            {
                "id": int(r[0]),
                "teaching_group_id": int(r[1]),
                "semester": r[2] or "",
                "platform": r[3] or "other",
                "label_ar": r[4] or "",
                "url": r[5] or "",
                "is_visible": int(r[6] or 0),
                "sort_order": int(r[7] or 0),
                "created_by_instructor_id": r[8],
                "updated_at": r[9],
            }
        )
    return out


def replace_group_links(
    conn,
    *,
    teaching_group_id: int,
    semester: str,
    links: list[dict],
    created_by_instructor_id: int | None,
) -> list[dict]:
    """يستبدل روابط المجموعة بالقائمة المرسلة."""
    if not course_group_links_ready(conn):
        raise RuntimeError("جدول روابط المجموعات غير جاهز.")
    sem = (semester or "").strip()
    cleaned: list[dict] = []
    for i, raw in enumerate(links or []):
        if not isinstance(raw, dict):
            continue
        plat = str(raw.get("platform") or "other").strip().lower()
        if plat not in _ALLOWED_PLATFORMS:
            raise ValueError(f"منصة غير مدعومة في العنصر {i + 1}.")
        label = str(raw.get("label_ar") or "").strip()
        if not label:
            raise ValueError(f"التسمية مطلوبة في العنصر {i + 1}.")
        url = str(raw.get("url") or "").strip()
        ok, msg = validate_group_link_url(url, plat)
        if not ok:
            raise ValueError(msg or "رابط غير صالح.")
        cleaned.append(
            {
                "platform": plat,
                "label_ar": label[:120],
                "url": url[:500],
                "is_visible": coerce_bool01(raw.get("is_visible"), 0),
                "sort_order": i,
            }
        )

    cur = conn.cursor()
    cur.execute(
        "DELETE FROM course_group_links WHERE teaching_group_id = ?",
        (int(teaching_group_id),),
    )
    for item in cleaned:
        cur.execute(
            """
            INSERT INTO course_group_links
            (teaching_group_id, semester, platform, label_ar, url, is_visible, sort_order,
             created_by_instructor_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                int(teaching_group_id),
                sem,
                item["platform"],
                item["label_ar"],
                item["url"],
                int(item["is_visible"]),
                int(item["sort_order"]),
                int(created_by_instructor_id) if created_by_instructor_id else None,
            ),
        )
    return list_group_links(conn, teaching_group_id, visible_only=False)


def resolve_course_instructor_id(
    conn,
    *,
    course_name: str,
    teaching_group_id: int | None,
) -> int | None:
    cur = conn.cursor()
    if teaching_group_id:
        row = cur.execute(
            "SELECT instructor_id FROM teaching_groups WHERE id = ? LIMIT 1",
            (int(teaching_group_id),),
        ).fetchone()
        if row and row[0] not in (None, ""):
            try:
                return int(row[0])
            except (TypeError, ValueError):
                pass
    cn = (course_name or "").strip()
    if not cn:
        return None
    if table_exists(conn, "course_section_pages"):
        row = cur.execute(
            """
            SELECT instructor_id FROM course_section_pages
            WHERE lower(trim(course_name))=lower(trim(?))
            ORDER BY updated_at DESC LIMIT 1
            """,
            (cn,),
        ).fetchone()
        if row and row[0] not in (None, ""):
            try:
                return int(row[0])
            except (TypeError, ValueError):
                pass
    cols = set(fetch_table_columns(conn, "schedule") or [])
    if "instructor_id" in cols:
        row = cur.execute(
            """
            SELECT instructor_id FROM schedule
            WHERE lower(trim(course_name))=lower(trim(?)) AND instructor_id IS NOT NULL
            LIMIT 1
            """,
            (cn,),
        ).fetchone()
        if row and row[0] not in (None, ""):
            try:
                return int(row[0])
            except (TypeError, ValueError):
                pass
    return None


def build_student_visible_contact(
    conn,
    *,
    course_name: str,
    teaching_group_id: int | None,
) -> dict:
    """حمولة التواصل الظاهرة للطالب المسجّل فقط (بدون حقول مخفية)."""
    iid = resolve_course_instructor_id(
        conn, course_name=course_name, teaching_group_id=teaching_group_id
    )
    payload: dict[str, Any] = {
        "instructor_id": iid,
        "instructor_name": "",
        "email": None,
        "whatsapp_phone_link": None,
        "whatsapp_username": None,
        "whatsapp_username_key": None,
        "group_links": [],
        "has_any": False,
    }
    if iid:
        full = load_instructor_contact_row(conn, iid)
        payload["instructor_name"] = full.get("name") or ""
        if int(full.get("contact_email_visible") or 0) == 1 and (full.get("email") or "").strip():
            payload["email"] = (full.get("email") or "").strip()
        if int(full.get("whatsapp_phone_visible") or 0) == 1:
            link = whatsapp_phone_link(full.get("whatsapp_phone"))
            if link:
                payload["whatsapp_phone_link"] = link
        if int(full.get("whatsapp_username_visible") or 0) == 1 and full.get("whatsapp_username"):
            payload["whatsapp_username"] = f"@{full['whatsapp_username']}"
            if full.get("whatsapp_username_key"):
                payload["whatsapp_username_key"] = full["whatsapp_username_key"]
    if teaching_group_id:
        links = list_group_links(conn, int(teaching_group_id), visible_only=True)
        payload["group_links"] = [
            {
                "platform": x["platform"],
                "label_ar": x["label_ar"],
                "url": x["url"],
            }
            for x in links
        ]
    payload["has_any"] = bool(
        payload["email"]
        or payload["whatsapp_phone_link"]
        or payload["whatsapp_username"]
        or payload["group_links"]
    )
    return payload


def course_has_visible_contact(
    conn,
    *,
    course_name: str,
    teaching_group_id: int | None,
) -> bool:
    return bool(
        build_student_visible_contact(
            conn, course_name=course_name, teaching_group_id=teaching_group_id
        ).get("has_any")
    )
