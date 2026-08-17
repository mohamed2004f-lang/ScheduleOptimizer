"""محرّك الفصل — الموجات 0–4.

الموجة 0: term_master + نوافذ + نسخ التقويم.
الموجة 1: حارس كتابة موحّد. قفل المرحلة يتقدّم على تواريخ النوافذ.
الموجة 2: سياسة تعديل المواعيد — لا فتح تلقائي لمرحلة مقفلة.
الموجة 3: أرشفة السلة قبل تعيين فصل حالي جديد.
الموجة 4: لوحة التشغيل.
نافذة بلا تواريخ = مسموح. مهلة grace_until تُكمِل الجلسات بعد التقصير/الإغلاق الفوري.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from backend.database.database import is_postgresql, table_exists

logger = logging.getLogger("backend.services.term_engine")

SEASON_FALL = "fall"
SEASON_SPRING = "spring"
TERM_STATUS_PLANNED = "planned"
TERM_STATUS_REGISTRATION = "registration"
TERM_STATUS_INSTRUCTION = "instruction"
TERM_STATUS_EXAMS = "exams"
TERM_STATUS_GRADING = "grading"
TERM_STATUS_CLOSED = "closed"

TERM_STATUS_LABELS_AR: dict[str, str] = {
    TERM_STATUS_PLANNED: "مخطط",
    TERM_STATUS_REGISTRATION: "تسجيل",
    TERM_STATUS_INSTRUCTION: "دراسة",
    TERM_STATUS_EXAMS: "امتحان",
    TERM_STATUS_GRADING: "درجات",
    TERM_STATUS_CLOSED: "مغلق",
}
WINDOW_UNSET = "unset"
WINDOW_SCHEDULED = "scheduled"
VERSION_DRAFT = "draft"
VERSION_PUBLISHED = "published"
VERSION_AMENDED = "amended"

_FALL_ALIASES = frozenset({"fall", "خريف", "فصل الخريف", "autumn"})
_SPRING_ALIASES = frozenset({"spring", "ربيع", "فصل الربيع"})


@dataclass(frozen=True)
class WindowSpec:
    window_key: str
    label_ar: str
    closure_stage: str
    kind: str = "window"
    fall_end_item: int | None = None
    fall_start_item: int | None = None
    spring_end_item: int | None = None
    spring_start_item: int | None = None
    duration_days: int | None = None
    title_hints: tuple[str, ...] = ()


# أرقام البنود تطابق FALL_TITLES / SPRING_TITLES في academic_calendar.py
WINDOW_CATALOG: tuple[WindowSpec, ...] = (
    WindowSpec(
        "registration_renewal",
        "تجديد القيد وتسجيل المقررات",
        "registrations",
        fall_end_item=1,
        spring_end_item=1,
        duration_days=7,
        title_hints=("تجديد القيد",),
    ),
    WindowSpec(
        "registration_new",
        "تسجيل الطلبة المستجدين",
        "registrations",
        fall_end_item=2,
        spring_end_item=2,
        duration_days=7,
        title_hints=("المستجدين", "الطلبة المستجدين"),
    ),
    WindowSpec(
        "instruction_start",
        "بداية الدراسة",
        "schedule",
        kind="milestone",
        fall_end_item=3,
        spring_end_item=3,
        title_hints=("بداية الدراسة",),
    ),
    WindowSpec(
        "add_courses",
        "آخر موعد لإضافة المقررات",
        "registrations",
        fall_end_item=4,
        spring_end_item=4,
        title_hints=("آخر موعد لإضافة",),
    ),
    WindowSpec(
        "midterm_exams",
        "الامتحانات الجزئية",
        "exams",
        fall_start_item=5,
        fall_end_item=6,
        spring_start_item=5,
        spring_end_item=6,
        title_hints=("الامتحانات الجزئية", "التصفية"),
    ),
    WindowSpec(
        "drop_courses",
        "آخر موعد لإسقاط المواد",
        "registrations",
        fall_end_item=7,
        spring_end_item=7,
        title_hints=("آخر موعد لإسقاط",),
    ),
    WindowSpec(
        "instruction_end",
        "انتهاء الدراسة",
        "schedule",
        kind="milestone",
        fall_end_item=8,
        spring_end_item=8,
        title_hints=("انتهاء الدراسة",),
    ),
    WindowSpec(
        "final_exams",
        "الامتحانات النهائية",
        "exams",
        fall_start_item=9,
        fall_end_item=11,
        spring_start_item=9,
        spring_end_item=11,
        title_hints=("الامتحانات النهائية",),
    ),
    WindowSpec(
        "graduation_projects",
        "مناقشة مشاريع التخرج",
        "",
        kind="milestone",
        fall_end_item=12,
        spring_end_item=12,
        duration_days=3,
        title_hints=("مشاريع التخرج",),
    ),
    WindowSpec(
        "grade_entry",
        "إعلان النتيجة",
        "grades",
        fall_end_item=13,
        spring_end_item=13,
        title_hints=("إعلان النتيجة",),
    ),
    WindowSpec(
        "grade_appeals",
        "التظلمات ومراجعة الكراسات",
        "grades",
        fall_start_item=14,
        fall_end_item=15,
        spring_start_item=14,
        spring_end_item=15,
        title_hints=("التظلم", "مراجعة كراسات", "طلبات المراجعة"),
    ),
    WindowSpec(
        "results_final",
        "إعلان النتيجة النهائية",
        "grades",
        kind="milestone",
        fall_end_item=16,
        spring_end_item=16,
        title_hints=("النتيجة النهائية",),
    ),
    WindowSpec(
        "schedule_freeze",
        "تجميد الجدول الدراسي",
        "schedule",
        title_hints=(),
    ),
    WindowSpec(
        "surveys",
        "إغلاق الاستبيانات",
        "surveys",
        title_hints=(),
    ),
)


def window_mapped_for_season(spec: WindowSpec, season: str) -> bool:
    if season == SEASON_FALL:
        return bool(spec.fall_end_item or spec.fall_start_item)
    if season == SEASON_SPRING:
        return bool(spec.spring_end_item or spec.spring_start_item)
    return False


def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def normalize_season(raw: str | None) -> str | None:
    s = (raw or "").strip().lower()
    if not s:
        return None
    if s in _FALL_ALIASES or "خريف" in (raw or ""):
        return SEASON_FALL
    if s in _SPRING_ALIASES or "ربيع" in (raw or ""):
        return SEASON_SPRING
    return None


def season_name_ar(season: str) -> str:
    return "خريف" if season == SEASON_FALL else "ربيع"


def normalize_academic_year(raw: str | None) -> str:
    s = (raw or "").strip().replace("–", "-").replace("—", "-")
    if not s:
        return ""
    m = re.match(r"^(20\d{2})\s*[/\-]\s*(20\d{2})$", s)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.match(r"^(\d{2})\s*[\-/]\s*(\d{2})$", s)
    if m:
        return f"20{int(m.group(1)):02d}/20{int(m.group(2)):02d}"
    m = re.match(r"^(20\d{2})$", s)
    if m:
        y = int(m.group(1))
        return f"{y}/{y + 1}"
    return s


def academic_year_aliases(raw: str | None) -> list[str]:
    """25-26 و 2025/2026 و 2025-2026 تُعدّ العام نفسه عند البحث."""
    s = (raw or "").strip().replace("–", "-").replace("—", "-")
    n = normalize_academic_year(s)
    out: list[str] = []
    for x in (s, n):
        if x and x not in out:
            out.append(x)
    m = re.match(r"^(20)(\d{2})/(20)(\d{2})$", n)
    if m:
        short = f"{m.group(2)}-{m.group(4)}"
        dashed = f"{m.group(1)}{m.group(2)}-{m.group(3)}{m.group(4)}"
        slash_sp = f"{m.group(1)}{m.group(2)} / {m.group(3)}{m.group(4)}"
        for x in (short, dashed, n.replace("/", "-"), slash_sp):
            if x not in out:
                out.append(x)
    return out


def calendar_term_aliases(season: str | None) -> list[str]:
    raw = (season or "").strip()
    n = normalize_season(raw)
    out: list[str] = []
    if raw:
        out.append(raw)
    if n == SEASON_SPRING:
        extras = ("spring", "ربيع", "فصل الربيع")
    elif n == SEASON_FALL:
        extras = ("fall", "خريف", "فصل الخريف")
    else:
        extras = ()
    for x in extras:
        if x not in out:
            out.append(x)
    return out


def canonical_term_key(season: str, academic_year: str) -> str:
    return f"{season}:{academic_year}"


def parse_ops_term(term_name: str | None, term_year: str | None) -> dict[str, str] | None:
    season = normalize_season(term_name)
    academic_year = normalize_academic_year(term_year)
    if not season or not academic_year:
        return None
    name_ar = season_name_ar(season)
    ops_year = (term_year or "").strip() or academic_year
    ops_label = f"{name_ar} {ops_year}".strip()
    return {
        "season": season,
        "academic_year": academic_year,
        "term_key": canonical_term_key(season, academic_year),
        "term_name_ar": name_ar,
        "ops_year_label": ops_year,
        "ops_label": ops_label,
    }


def _collapse_term_ws(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def current_term_match_context(conn) -> dict | None:
    """تسميات الفصل الحالي لمطابقة عمود schedule.semester (خريف 26-27 ≡ خريف 2026/2027)."""
    from backend.services.utilities import get_current_term

    name, year = get_current_term(conn=conn)
    parsed = parse_ops_term(name, year)
    raw = _collapse_term_ws(f"{(name or '').strip()} {(year or '').strip()}")
    if not parsed:
        if not raw:
            return None
        years = academic_year_aliases(year) if year else []
        seasons = [str(name or "").strip().lower()] if name else []
        return {
            "term_key": "",
            "ops_label": raw,
            "raw_label": raw,
            "labels": {raw.lower()} if raw else set(),
            "seasons": [s for s in seasons if s],
            "years": years,
        }
    years: list[str] = []
    for y in (parsed.get("academic_year"), parsed.get("ops_year_label"), year):
        for alias in academic_year_aliases(y):
            if alias and alias not in years:
                years.append(alias)
    seasons = calendar_term_aliases(parsed.get("season"))
    labels: set[str] = set()
    if raw:
        labels.add(raw.lower())
    ops = _collapse_term_ws(parsed.get("ops_label") or "")
    if ops:
        labels.add(ops.lower())
    for s in seasons:
        for y in years:
            lab = _collapse_term_ws(f"{s} {y}")
            if lab:
                labels.add(lab.lower())
    return {
        "term_key": parsed["term_key"],
        "ops_label": parsed["ops_label"],
        "raw_label": raw or parsed["ops_label"],
        "labels": labels,
        "seasons": [str(s).lower() for s in seasons if s],
        "years": years,
    }


def schedule_semester_matches_term_context(semester: str | None, ctx: dict | None) -> bool:
    """صف بلا semester لا يُعدّ من الفصل الحالي (لا يلوّث محرر الفصل الجديد)."""
    if not ctx:
        return False
    sem = _collapse_term_ws(semester or "")
    if not sem:
        return False
    low = sem.lower()
    if low in (ctx.get("labels") or set()):
        return True
    season_ok = any(s and s in low for s in (ctx.get("seasons") or []))
    year_ok = any(y and str(y).lower() in low for y in (ctx.get("years") or []))
    return bool(season_ok and year_ok)


def confirm_term_label_matches(confirm: str | None, ctx: dict | None) -> bool:
    if not ctx:
        return False
    c = _collapse_term_ws(confirm).lower()
    if not c:
        return False
    labels = ctx.get("labels") or set()
    if c in labels:
        return True
    return c == _collapse_term_ws(ctx.get("ops_label") or "").lower()


def _parse_date(raw: Any) -> datetime.date | None:
    s = str(raw or "").strip()
    if not s:
        return None
    token = s.split()[0][:10]
    try:
        return datetime.date.fromisoformat(token)
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.datetime.strptime(s.split()[0], fmt).date()
        except ValueError:
            continue
    return None


def _date_iso(d: datetime.date | None) -> str | None:
    return d.isoformat() if d else None


def ensure_term_engine_tables(conn) -> None:
    missing = not (
        table_exists(conn, "term_master")
        and table_exists(conn, "term_windows")
        and table_exists(conn, "academic_calendar_versions")
    )
    cur = conn.cursor()
    if missing:
        if is_postgresql():
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS term_master (
                    term_key TEXT PRIMARY KEY,
                    season TEXT NOT NULL CHECK (season IN ('fall', 'spring')),
                    academic_year TEXT NOT NULL,
                    term_name_ar TEXT NOT NULL DEFAULT '',
                    ops_year_label TEXT NOT NULL DEFAULT '',
                    ops_label TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'planned',
                    is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1)),
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS term_windows (
                    id BIGSERIAL PRIMARY KEY,
                    term_key TEXT NOT NULL,
                    window_key TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'window',
                    label_ar TEXT NOT NULL DEFAULT '',
                    closure_stage TEXT NOT NULL DEFAULT '',
                    starts_at TEXT,
                    ends_at TEXT,
                    status TEXT NOT NULL DEFAULT 'unset',
                    calendar_item_no INTEGER,
                    source TEXT NOT NULL DEFAULT 'calendar',
                    grace_until TEXT,
                    updated_at TEXT,
                    UNIQUE (term_key, window_key)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS academic_calendar_versions (
                    id BIGSERIAL PRIMARY KEY,
                    term_key TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('draft', 'published', 'amended')),
                    snapshot_json TEXT NOT NULL DEFAULT '[]',
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT,
                    created_by TEXT NOT NULL DEFAULT '',
                    UNIQUE (term_key, version_no)
                )
                """
            )
            for idx in (
                "CREATE INDEX IF NOT EXISTS idx_term_master_current ON term_master(is_current)",
                "CREATE INDEX IF NOT EXISTS idx_term_master_year_season ON term_master(academic_year, season)",
                "CREATE INDEX IF NOT EXISTS idx_term_windows_term ON term_windows(term_key)",
                "CREATE INDEX IF NOT EXISTS idx_cal_versions_term ON academic_calendar_versions(term_key, version_no)",
            ):
                cur.execute(idx)
        else:
            from backend.database.schema_ddl import INDEXES, TABLES_SCHEMA

            for name in ("term_master", "term_windows", "academic_calendar_versions"):
                cur.execute(TABLES_SCHEMA[name])
            for idx in INDEXES:
                if "term_master" in idx or "term_windows" in idx or "academic_calendar_versions" in idx:
                    try:
                        cur.execute(idx)
                    except Exception:
                        pass
    _ensure_wave234_schema(conn)
    try:
        migrate_spring_new_students_item(conn)
    except Exception:
        logger.exception("spring new-students calendar item shift skipped")
        try:
            conn.rollback()
        except Exception:
            pass
    try:
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _exec_ddl_safe(conn, sql: str) -> None:
    """DDL لا يُلغي معاملة فيها بيانات مستخدم (SAVEPOINT على PostgreSQL)."""
    from backend.database.introspection import conn_is_postgresql
    from backend.database.pg_convert import sqlite_ddl_to_postgres

    q = sqlite_ddl_to_postgres(sql) if conn_is_postgresql(conn) else sql
    cur = conn.cursor()
    if conn_is_postgresql(conn):
        try:
            cur.execute("SAVEPOINT so_ddl")
            cur.execute(q)
            cur.execute("RELEASE SAVEPOINT so_ddl")
        except Exception:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT so_ddl")
            except Exception:
                pass
            logger.debug("term_engine ddl skipped")
        return
    try:
        cur.execute(q)
    except Exception:
        pass


def _ensure_wave234_schema(conn) -> None:
    """أعمدة وجداول الموجات 2–4 — آمن على قواعد قديمة."""
    from backend.database.database import fetch_table_columns
    from backend.database.schema_ddl import INDEXES, TABLES_SCHEMA

    for name in (
        "term_amendment_log",
        "term_registration_archives",
        "term_operation_exceptions",
        "term_course_offerings",
        "term_offering_state",
    ):
        _exec_ddl_safe(conn, TABLES_SCHEMA[name])
    for idx in INDEXES:
        if (
            "term_amend_log" in idx
            or "term_reg_arch" in idx
            or "term_op_exc" in idx
            or "term_offerings_" in idx
        ):
            _exec_ddl_safe(conn, idx)
    from backend.database.introspection import conn_is_postgresql

    def _add_if_missing(table: str, column: str, ddl: str) -> None:
        try:
            cols = fetch_table_columns(conn, table) or []
        except Exception:
            if conn_is_postgresql(conn):
                try:
                    conn.cursor().execute("ROLLBACK TO SAVEPOINT so_ddl")
                except Exception:
                    pass
            return
        if column in cols:
            return
        _exec_ddl_safe(conn, f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    _add_if_missing("term_windows", "grace_until", "TEXT")
    _add_if_missing("registrations", "semester", "TEXT DEFAULT ''")
    _add_if_missing("term_offering_state", "department_id", "INTEGER NOT NULL DEFAULT 0")
    _exec_ddl_safe(
        conn,
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_term_offerings_term_course_dept "
        "ON term_course_offerings(term_key, course_name, department_id)",
    )
    _exec_ddl_safe(
        conn,
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_registrations_student_course_sem "
        "ON registrations(student_id, course_name, semester)",
    )
    if conn_is_postgresql(conn):
        _exec_ddl_safe(conn, "ALTER TABLE academic_calendar ADD COLUMN IF NOT EXISTS event_date_start TEXT")
    else:
        _add_if_missing("academic_calendar", "event_date_start", "TEXT")


def _add_column(conn, table: str, column: str, ddl: str) -> None:
    _exec_ddl_safe(conn, f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


_SPRING_TERM_VALUES = ("spring", "ربيع", "فصل الربيع")


def migrate_spring_new_students_item(conn) -> int:
    """يفتح بند رقم 2 في تقويم الربيع لتسجيل المستجدين، ويزيح البنود التالية مرة واحدة."""
    if not table_exists(conn, "academic_calendar"):
        return 0
    cur = conn.cursor()
    placeholders = ",".join(["?"] * len(_SPRING_TERM_VALUES))

    def _titles_at(item_no: int) -> list[str]:
        rows = cur.execute(
            f"""
            SELECT title FROM academic_calendar
            WHERE term IN ({placeholders}) AND item_no = ?
              AND COALESCE(is_deleted, 0) = 0
            """,
            (*_SPRING_TERM_VALUES, item_no),
        ).fetchall()
        out = []
        for r in rows or []:
            title = r["title"] if hasattr(r, "keys") else r[0]
            out.append(str(title or ""))
        return out

    t2 = _titles_at(2)
    t3 = _titles_at(3)
    if any("المستجدين" in t for t in t2):
        return 0
    if any("بداية الدراسة" in t for t in t3) and not any("بداية الدراسة" in t for t in t2):
        return 0
    if not t2 and not t3:
        n = cur.execute(
            f"SELECT COUNT(*) FROM academic_calendar WHERE term IN ({placeholders}) AND item_no >= 2",
            _SPRING_TERM_VALUES,
        ).fetchone()
        count = int(n[0] if not hasattr(n, "keys") else n[0] or 0)
        if count == 0:
            return 0

    cur.execute(
        f"""
        UPDATE academic_calendar SET item_no = item_no + 1000
        WHERE term IN ({placeholders}) AND item_no >= 2
        """,
        _SPRING_TERM_VALUES,
    )
    cur.execute(
        f"""
        UPDATE academic_calendar SET item_no = item_no - 999
        WHERE term IN ({placeholders}) AND item_no >= 1002
        """,
        _SPRING_TERM_VALUES,
    )
    if table_exists(conn, "term_windows"):
        cur.execute(
            """
            UPDATE term_windows
            SET calendar_item_no = calendar_item_no + 1
            WHERE term_key LIKE 'spring:%'
              AND calendar_item_no IS NOT NULL
              AND calendar_item_no >= 2
            """
        )
    return 1



def upsert_term_master(
    conn,
    *,
    season: str,
    academic_year: str,
    term_name_ar: str = "",
    ops_year_label: str = "",
    ops_label: str = "",
    make_current: bool = False,
) -> dict[str, Any]:
    ensure_term_engine_tables(conn)
    year = normalize_academic_year(academic_year)
    season_n = normalize_season(season) or season
    key = canonical_term_key(season_n, year)
    name_ar = (term_name_ar or "").strip() or season_name_ar(season_n)
    year_label = (ops_year_label or "").strip() or year
    label = (ops_label or "").strip() or f"{name_ar} {year_label}".strip()
    now = _now_iso()
    cur = conn.cursor()
    if make_current:
        cur.execute("UPDATE term_master SET is_current = 0, updated_at = ?", (now,))
    existing = cur.execute(
        "SELECT term_key, status, is_current, ops_label FROM term_master WHERE term_key = ? LIMIT 1",
        (key,),
    ).fetchone()
    if existing:
        prev_current = int(
            existing["is_current"] if hasattr(existing, "keys") else existing[2] or 0
        )
        is_cur = 1 if make_current else prev_current
        cur.execute(
            """
            UPDATE term_master
            SET season = ?, academic_year = ?, term_name_ar = ?,
                ops_year_label = ?, ops_label = ?, is_current = ?, updated_at = ?
            WHERE term_key = ?
            """,
            (season_n, year, name_ar, year_label, label, is_cur, now, key),
        )
    else:
        is_cur = 1 if make_current else 0
        cur.execute(
            """
            INSERT INTO term_master (
                term_key, season, academic_year, term_name_ar,
                ops_year_label, ops_label, status, is_current, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (key, season_n, year, name_ar, year_label, label, TERM_STATUS_PLANNED, is_cur, now, now),
        )
    row = cur.execute(
        """
        SELECT term_key, season, academic_year, term_name_ar, ops_year_label,
               ops_label, status, is_current, created_at, updated_at
        FROM term_master WHERE term_key = ? LIMIT 1
        """,
        (key,),
    ).fetchone()
    return _row_dict(row)


def _row_dict(row) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return {
        "term_key": row[0],
        "season": row[1],
        "academic_year": row[2],
        "term_name_ar": row[3],
        "ops_year_label": row[4],
        "ops_label": row[5],
        "status": row[6],
        "is_current": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


def set_term_master_status(conn, term_key: str, status: str, *, actor: str = "") -> dict[str, Any]:
    """تعيين حالة الفصل الرسمية يدوياً."""
    status = (status or "").strip().lower()
    allowed = set(TERM_STATUS_LABELS_AR.keys())
    if status not in allowed:
        raise ValueError(f"حالة غير معروفة. المسموح: {', '.join(sorted(allowed))}")
    ensure_term_engine_tables(conn)
    key = (term_key or "").strip()
    if not key:
        raise ValueError("term_key مطلوب")
    now = _now_iso()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT term_key FROM term_master WHERE term_key = ? LIMIT 1", (key,)
    ).fetchone()
    if not row:
        raise ValueError("الفصل غير موجود في term_master")
    cur.execute(
        "UPDATE term_master SET status = ?, updated_at = ? WHERE term_key = ?",
        (status, now, key),
    )
    try:
        conn.commit()
    except Exception:
        pass
    out = cur.execute(
        """
        SELECT term_key, season, academic_year, term_name_ar, ops_year_label,
               ops_label, status, is_current, created_at, updated_at
        FROM term_master WHERE term_key = ? LIMIT 1
        """,
        (key,),
    ).fetchone()
    data = _row_dict(out)
    data["status_label_ar"] = TERM_STATUS_LABELS_AR.get(status, status)
    data["updated_by"] = actor or ""
    return data


def derive_term_lifecycle_status(
    conn,
    *,
    term_key: str,
    ops_label: str = "",
    today: datetime.date | None = None,
) -> str:
    """يستنتج حالة الفصل من الأقفال والنوافذ دون فرضها إن كان مغلقًا يدويًا."""
    if not term_key:
        return TERM_STATUS_PLANNED
    today = today or datetime.date.today()
    cur = conn.cursor()
    if table_exists(conn, "term_master"):
        row = cur.execute(
            "SELECT status FROM term_master WHERE term_key = ? LIMIT 1",
            (term_key,),
        ).fetchone()
        if row is not None:
            current = str(row["status"] if hasattr(row, "keys") else row[0] or "").strip()
            if current == TERM_STATUS_CLOSED:
                return TERM_STATUS_CLOSED

    try:
        from backend.services.term_closure import get_term_closure_status

        closure = get_term_closure_status(
            conn, semester=ops_label or None, department_id=None
        )
        if closure.get("operational_complete"):
            return TERM_STATUS_CLOSED
        stages = closure.get("stages") or {}
        if (stages.get("exams") or {}).get("closed"):
            return TERM_STATUS_GRADING
        if (stages.get("schedule") or {}).get("closed") and not (
            stages.get("exams") or {}
        ).get("closed"):
            return TERM_STATUS_EXAMS
        if (stages.get("registrations") or {}).get("closed"):
            # بعد إغلاق التسجيلات غالباً دراسة أو امتحان حسب النوافذ
            pass
    except Exception:
        logger.exception("derive lifecycle: closure read failed")

    windows = {}
    if table_exists(conn, "term_windows"):
        rows = cur.execute(
            """
            SELECT window_key, starts_at, ends_at, status
            FROM term_windows WHERE term_key = ?
            """,
            (term_key,),
        ).fetchall()
        for r in rows or []:
            if hasattr(r, "keys"):
                windows[str(r["window_key"])] = {
                    "starts_at": r["starts_at"],
                    "ends_at": r["ends_at"],
                    "status": r["status"],
                }
            else:
                windows[str(r[0])] = {
                    "starts_at": r[1],
                    "ends_at": r[2],
                    "status": r[3],
                }

    def _open(key: str) -> bool:
        w = windows.get(key) or {}
        if (w.get("status") or "") != WINDOW_SCHEDULED:
            return False
        return window_open_on(w.get("starts_at"), w.get("ends_at"), today)

    def _begun(key: str) -> bool:
        w = windows.get(key) or {}
        if (w.get("status") or "") != WINDOW_SCHEDULED:
            return False
        start = _parse_date(w.get("starts_at")) or _parse_date(w.get("ends_at"))
        return start is not None and today >= start

    def _past_end(key: str) -> bool:
        w = windows.get(key) or {}
        end = _parse_date(w.get("ends_at"))
        return end is not None and today > end

    if _open("grade_entry") or _open("grade_appeals") or _begun("results_final"):
        return TERM_STATUS_GRADING
    if _open("midterm_exams") or _open("final_exams"):
        return TERM_STATUS_EXAMS
    if _begun("instruction_start") and not _past_end("instruction_end"):
        return TERM_STATUS_INSTRUCTION
    if _open("registration_renewal") or _open("registration_new") or _open("add_courses"):
        return TERM_STATUS_REGISTRATION
    if _past_end("instruction_end") or _begun("final_exams"):
        return TERM_STATUS_EXAMS
    return TERM_STATUS_PLANNED


def sync_term_master_status(
    conn,
    *,
    term_key: str,
    ops_label: str = "",
    today: datetime.date | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """يحدّث حالة term_master تلقائياً ما لم يكن مغلقاً يدوياً (إلا مع force)."""
    if not term_key or not table_exists(conn, "term_master"):
        return {}
    derived = derive_term_lifecycle_status(
        conn, term_key=term_key, ops_label=ops_label, today=today
    )
    cur = conn.cursor()
    row = cur.execute(
        "SELECT status FROM term_master WHERE term_key = ? LIMIT 1",
        (term_key,),
    ).fetchone()
    if row is None:
        return {}
    current = str(row["status"] if hasattr(row, "keys") else row[0] or "").strip()
    if current == TERM_STATUS_CLOSED and not force and derived != TERM_STATUS_CLOSED:
        # الإغلاق اليدوي/التشغيلي يبقى حتى يُعاد الفتح صراحة
        derived = TERM_STATUS_CLOSED
    if current != derived:
        cur.execute(
            "UPDATE term_master SET status = ?, updated_at = ? WHERE term_key = ?",
            (derived, _now_iso(), term_key),
        )
        try:
            conn.commit()
        except Exception:
            pass
    return {
        "term_key": term_key,
        "status": derived,
        "status_label_ar": TERM_STATUS_LABELS_AR.get(derived, derived),
        "previous": current,
    }


def sync_current_term_from_settings(
    conn,
    *,
    term_name: str | None = None,
    term_year: str | None = None,
) -> dict[str, Any] | None:
    """يملأ term_master من الفصل الحالي دون تغيير system_settings."""
    name = (term_name or "").strip()
    year = (term_year or "").strip()
    if not name or not year:
        from backend.services.utilities import get_current_term

        n, y = get_current_term(conn=conn)
        name = name or (n or "").strip()
        year = year or (y or "").strip()
    parsed = parse_ops_term(name, year)
    if not parsed:
        logger.warning("term_engine: cannot parse current term name=%r year=%r", name, year)
        return None
    row = upsert_term_master(
        conn,
        season=parsed["season"],
        academic_year=parsed["academic_year"],
        term_name_ar=parsed["term_name_ar"],
        ops_year_label=parsed["ops_year_label"],
        ops_label=parsed["ops_label"],
        make_current=True,
    )
    _ensure_catalog_windows(conn, row["term_key"], parsed["season"])
    return row


def _item_date_map(items: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for it in items or []:
        try:
            no = int(it.get("item_no") or 0)
        except (TypeError, ValueError):
            no = 0
        if no <= 0:
            continue
        if int(it.get("is_deleted") or 0):
            continue
        out[no] = it
    return out


def _match_item_by_title(items: list[dict[str, Any]], hints: tuple[str, ...]) -> dict[str, Any] | None:
    if not hints:
        return None
    for it in items or []:
        title = str(it.get("title") or "")
        if int(it.get("is_deleted") or 0):
            continue
        if any(h in title for h in hints):
            return it
    return None


def _window_dates_for_spec(
    spec: WindowSpec,
    season: str,
    items: list[dict[str, Any]],
) -> tuple[str | None, str | None, int | None]:
    by_no = _item_date_map(items)
    start_no = spec.fall_start_item if season == SEASON_FALL else spec.spring_start_item
    end_no = spec.fall_end_item if season == SEASON_FALL else spec.spring_end_item
    start_item = by_no.get(int(start_no)) if start_no else None
    end_item = by_no.get(int(end_no)) if end_no else None
    if not end_item and spec.title_hints:
        end_item = _match_item_by_title(items, spec.title_hints)
    start_d = _parse_date((end_item or {}).get("event_date_start"))
    if start_d is None:
        start_d = _parse_date((start_item or {}).get("event_date_start"))
    if start_d is None:
        start_d = _parse_date((start_item or {}).get("event_date"))
    end_d = _parse_date((end_item or {}).get("event_date"))
    if end_d is None and start_d is not None and spec.duration_days:
        end_d = start_d + datetime.timedelta(days=max(int(spec.duration_days) - 1, 0))
    if start_d is None and end_d is not None and spec.duration_days and start_no is None:
        start_d = end_d - datetime.timedelta(days=max(int(spec.duration_days) - 1, 0))
    item_no = None
    if end_item and end_item.get("item_no") is not None:
        try:
            item_no = int(end_item.get("item_no"))
        except (TypeError, ValueError):
            item_no = None
    elif start_item and start_item.get("item_no") is not None:
        try:
            item_no = int(start_item.get("item_no"))
        except (TypeError, ValueError):
            item_no = None
    return _date_iso(start_d), _date_iso(end_d), item_no


def _ensure_catalog_windows(conn, term_key: str, season: str) -> None:
    """ينشئ صفوف النوافذ من الكتالوج دون تواريخ إن لم تُزامَن بعد."""
    now = _now_iso()
    cur = conn.cursor()
    for spec in WINDOW_CATALOG:
        has_map = (
            (season == SEASON_FALL and (spec.fall_end_item or spec.fall_start_item))
            or (season == SEASON_SPRING and (spec.spring_end_item or spec.spring_start_item))
            or spec.window_key in ("schedule_freeze", "surveys")
        )
        if not has_map:
            continue
        cur.execute(
            "SELECT id FROM term_windows WHERE term_key = ? AND window_key = ? LIMIT 1",
            (term_key, spec.window_key),
        )
        if cur.fetchone():
            continue
        cur.execute(
            """
            INSERT INTO term_windows (
                term_key, window_key, kind, label_ar, closure_stage,
                starts_at, ends_at, status, calendar_item_no, source, updated_at
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, NULL, 'catalog', ?)
            """,
            (
                term_key,
                spec.window_key,
                spec.kind,
                spec.label_ar,
                spec.closure_stage,
                WINDOW_UNSET,
                now,
            ),
        )


def sync_windows_from_calendar_items(
    conn,
    *,
    term_key: str,
    season: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ensure_term_engine_tables(conn)
    _ensure_catalog_windows(conn, term_key, season)
    now = _now_iso()
    cur = conn.cursor()
    synced: list[dict[str, Any]] = []
    for spec in WINDOW_CATALOG:
        has_map = (
            (season == SEASON_FALL and (spec.fall_end_item or spec.fall_start_item))
            or (season == SEASON_SPRING and (spec.spring_end_item or spec.spring_start_item))
        )
        starts_at = ends_at = None
        item_no = None
        source = "catalog"
        if has_map:
            starts_at, ends_at, item_no = _window_dates_for_spec(spec, season, items)
            source = "calendar"
        status = WINDOW_SCHEDULED if (starts_at or ends_at) else WINDOW_UNSET
        cur.execute(
            "SELECT id FROM term_windows WHERE term_key = ? AND window_key = ? LIMIT 1",
            (term_key, spec.window_key),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                UPDATE term_windows
                SET kind = ?, label_ar = ?, closure_stage = ?,
                    starts_at = ?, ends_at = ?, status = ?,
                    calendar_item_no = ?, source = ?, updated_at = ?
                WHERE term_key = ? AND window_key = ?
                """,
                (
                    spec.kind,
                    spec.label_ar,
                    spec.closure_stage,
                    starts_at,
                    ends_at,
                    status,
                    item_no,
                    source,
                    now,
                    term_key,
                    spec.window_key,
                ),
            )
        elif has_map or spec.window_key in ("schedule_freeze", "surveys"):
            cur.execute(
                """
                INSERT INTO term_windows (
                    term_key, window_key, kind, label_ar, closure_stage,
                    starts_at, ends_at, status, calendar_item_no, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    term_key,
                    spec.window_key,
                    spec.kind,
                    spec.label_ar,
                    spec.closure_stage,
                    starts_at,
                    ends_at,
                    status,
                    item_no,
                    source,
                    now,
                ),
            )
        synced.append(
            {
                "window_key": spec.window_key,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "status": status,
                "kind": spec.kind,
            }
        )
    return synced


def fill_unset_windows_from_calendar_items(
    conn,
    *,
    term_key: str,
    season: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """يملأ النوافذ غير المضبوطة من التقويم دون الكتابة فوق نوافذ مجدولة."""
    ensure_term_engine_tables(conn)
    _ensure_catalog_windows(conn, term_key, season)
    now = _now_iso()
    cur = conn.cursor()
    filled: list[dict[str, Any]] = []
    for spec in WINDOW_CATALOG:
        has_map = (
            (season == SEASON_FALL and (spec.fall_end_item or spec.fall_start_item))
            or (season == SEASON_SPRING and (spec.spring_end_item or spec.spring_start_item))
        )
        if not has_map:
            continue
        starts_at, ends_at, item_no = _window_dates_for_spec(spec, season, items)
        if not (starts_at or ends_at):
            continue
        cur.execute(
            """
            SELECT status, starts_at, ends_at FROM term_windows
            WHERE term_key = ? AND window_key = ? LIMIT 1
            """,
            (term_key, spec.window_key),
        )
        row = cur.fetchone()
        old_status = ""
        old_s = old_e = None
        if row is not None:
            if hasattr(row, "keys"):
                old_status = str(row["status"] or "")
                old_s, old_e = row["starts_at"], row["ends_at"]
            else:
                old_status = str(row[0] or "")
                old_s, old_e = row[1], row[2]
        if old_status == WINDOW_SCHEDULED and (old_s or old_e):
            continue
        if row:
            cur.execute(
                """
                UPDATE term_windows
                SET starts_at = ?, ends_at = ?, status = ?,
                    calendar_item_no = ?, source = 'calendar', updated_at = ?
                WHERE term_key = ? AND window_key = ?
                """,
                (starts_at, ends_at, WINDOW_SCHEDULED, item_no, now, term_key, spec.window_key),
            )
        else:
            cur.execute(
                """
                INSERT INTO term_windows (
                    term_key, window_key, kind, label_ar, closure_stage,
                    starts_at, ends_at, status, calendar_item_no, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'calendar', ?)
                """,
                (
                    term_key,
                    spec.window_key,
                    spec.kind,
                    spec.label_ar,
                    spec.closure_stage,
                    starts_at,
                    ends_at,
                    WINDOW_SCHEDULED,
                    item_no,
                    now,
                ),
            )
        filled.append(
            {
                "window_key": spec.window_key,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "status": WINDOW_SCHEDULED,
            }
        )
    return filled


def _latest_version_row(conn, term_key: str):
    cur = conn.cursor()
    return cur.execute(
        """
        SELECT version_no, status FROM academic_calendar_versions
        WHERE term_key = ?
        ORDER BY version_no DESC LIMIT 1
        """,
        (term_key,),
    ).fetchone()


def snapshot_calendar_version(
    conn,
    *,
    term_key: str,
    items: list[dict[str, Any]],
    actor: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """نسخة ظلّية. المسودة تُحدَّث مكانها؛ المنشور يولّد معدَّلاً. لا يغيّر academic_calendar."""
    ensure_term_engine_tables(conn)
    now = _now_iso()
    actor = (actor or "").strip()
    reason = (reason or "").strip() or "حفظ التقويم الأكاديمي"
    snap = json.dumps(items or [], ensure_ascii=False)
    latest = _latest_version_row(conn, term_key)
    cur = conn.cursor()
    if latest is None:
        ver, status = 1, VERSION_PUBLISHED
        cur.execute(
            """
            INSERT INTO academic_calendar_versions
            (term_key, version_no, status, snapshot_json, reason, created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (term_key, ver, status, snap, reason, now, actor),
        )
    else:
        last_no = int(latest["version_no"] if hasattr(latest, "keys") else latest[0])
        last_status = str(latest["status"] if hasattr(latest, "keys") else latest[1] or "")
        if last_status == VERSION_DRAFT:
            ver, status = last_no, VERSION_DRAFT
            cur.execute(
                """
                UPDATE academic_calendar_versions
                SET snapshot_json = ?, reason = ?, created_at = ?, created_by = ?
                WHERE term_key = ? AND version_no = ?
                """,
                (snap, reason, now, actor, term_key, ver),
            )
        else:
            ver, status = last_no + 1, VERSION_AMENDED
            cur.execute(
                """
                INSERT INTO academic_calendar_versions
                (term_key, version_no, status, snapshot_json, reason, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (term_key, ver, status, snap, reason, now, actor),
            )
    return {
        "term_key": term_key,
        "version_no": ver,
        "status": status,
        "created_at": now,
        "created_by": actor,
    }


def _iso_day(raw: Any) -> str | None:
    d = _parse_date(raw)
    return d.isoformat() if d else None


def _item_has_date(row: dict[str, Any]) -> bool:
    return bool(_parse_date(row.get("event_date")) or _parse_date(row.get("event_date_start")))


def load_calendar_item_rows(conn, academic_year: str, season: str) -> dict[int, dict[str, Any]]:
    if not table_exists(conn, "academic_calendar"):
        return {}
    from backend.database.database import fetch_table_columns

    cols = fetch_table_columns(conn, "academic_calendar") or []
    has_start = "event_date_start" in cols
    select_sql = (
        "SELECT item_no, title, event_date, is_deleted, updated_at, event_date_start"
        if has_start
        else "SELECT item_no, title, event_date, is_deleted, updated_at"
    )
    cur = conn.cursor()
    existing: dict[int, dict[str, Any]] = {}

    def _take_row(r) -> tuple[int, dict[str, Any]]:
        if hasattr(r, "keys"):
            no = int(r["item_no"])
            start = r["event_date_start"] if has_start else None
            return no, {
                "title": r["title"],
                "event_date": _iso_day(r["event_date"]) or r["event_date"],
                "event_date_start": _iso_day(start) or start,
                "is_deleted": int(r["is_deleted"] or 0),
                "updated_at": r["updated_at"],
            }
        no = int(r[0])
        start = r[5] if has_start and len(r) > 5 else None
        return no, {
            "title": r[1],
            "event_date": _iso_day(r[2]) or r[2],
            "event_date_start": _iso_day(start) or start,
            "is_deleted": int(r[3] or 0),
            "updated_at": r[4],
        }

    for year in academic_year_aliases(academic_year):
        for term in calendar_term_aliases(season):
            rows = cur.execute(
                f"""
                {select_sql}
                FROM academic_calendar
                WHERE academic_year = ? AND term = ?
                ORDER BY item_no
                """,
                (year, term),
            ).fetchall()
            if not rows:
                continue
            for r in rows:
                no, parsed = _take_row(r)
                old = existing.get(no)
                if old is None:
                    existing[no] = parsed
                elif _item_has_date(parsed) and not _item_has_date(old):
                    existing[no] = parsed
                elif _item_has_date(parsed) and _item_has_date(old):
                    if str(parsed.get("updated_at") or "") >= str(old.get("updated_at") or ""):
                        existing[no] = parsed
    return existing


def backfill_term_engine_from_legacy(conn) -> dict[str, Any]:
    """ترحيل توافقي: الفصل الحالي + بنود التقويم الموجودة. بلا نسخ."""
    ensure_term_engine_tables(conn)
    current = sync_current_term_from_settings(conn)
    terms = 0
    if table_exists(conn, "academic_calendar"):
        cur = conn.cursor()
        pairs = cur.execute(
            "SELECT DISTINCT academic_year, term FROM academic_calendar"
        ).fetchall()
        from backend.services.academic_calendar import assemble_calendar_items

        for p in pairs or []:
            year = p["academic_year"] if hasattr(p, "keys") else p[0]
            term = p["term"] if hasattr(p, "keys") else p[1]
            season = normalize_season(str(term or ""))
            year_n = normalize_academic_year(str(year or ""))
            if not season or not year_n:
                continue
            master = upsert_term_master(
                conn,
                season=season,
                academic_year=year_n,
                term_name_ar=season_name_ar(season),
                ops_year_label=year_n,
                make_current=False,
            )
            existing = load_calendar_item_rows(conn, str(year), season)
            items = assemble_calendar_items(academic_year=str(year), term=season, existing=existing)
            sync_windows_from_calendar_items(
                conn, term_key=master["term_key"], season=season, items=items
            )
            terms += 1
    return {"current": current, "calendar_terms_synced": terms}


def list_stored_calendars(conn) -> list[dict[str, Any]]:
    """التقويمات المحفوظة بتواريخ — لتمييزها عن الفصل الحالي في اللوحة."""
    if not table_exists(conn, "academic_calendar"):
        return []
    rows = conn.cursor().execute(
        """
        SELECT academic_year, term, COUNT(*) AS n
        FROM academic_calendar
        WHERE COALESCE(is_deleted, 0) = 0
          AND event_date IS NOT NULL
          AND TRIM(CAST(event_date AS TEXT)) != ''
        GROUP BY academic_year, term
        ORDER BY academic_year DESC, term
        """
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows or []:
        year = r["academic_year"] if hasattr(r, "keys") else r[0]
        term = r["term"] if hasattr(r, "keys") else r[1]
        n = r["n"] if hasattr(r, "keys") else r[2]
        season = normalize_season(str(term or ""))
        year_n = normalize_academic_year(str(year or ""))
        out.append(
            {
                "academic_year": str(year or ""),
                "term": str(term or ""),
                "season": season or "",
                "canonical_year": year_n,
                "term_key": canonical_term_key(season, year_n) if season and year_n else "",
                "dated_items": int(n or 0),
                "label_ar": f"{season_name_ar(season) if season else term} {year}",
            }
        )
    return out


def hydrate_term_windows_from_calendar(
    conn,
    *,
    academic_year: str,
    season: str,
    ops_label: str = "",
    ops_year_label: str = "",
    actor: str = "hydrate",
) -> dict[str, Any]:
    """إن وُجد تقويم لنفس العام/الفصل بأي كتابة، املأ النوافذ غير المضبوطة."""
    ensure_term_engine_tables(conn)
    season_n = normalize_season(season)
    year_n = normalize_academic_year(academic_year)
    if not season_n or not year_n:
        return {"hydrated": False, "reason": "unparsed"}
    from backend.services.academic_calendar import assemble_calendar_items

    existing = load_calendar_item_rows(conn, academic_year, season_n)
    items = assemble_calendar_items(
        academic_year=academic_year, term=season_n, existing=existing
    )
    has_dates = any(_parse_date(it.get("event_date")) for it in items)
    if not has_dates:
        return {"hydrated": False, "reason": "no_dates", "term_key": canonical_term_key(season_n, year_n)}
    master = upsert_term_master(
        conn,
        season=season_n,
        academic_year=year_n,
        term_name_ar=season_name_ar(season_n),
        ops_year_label=ops_year_label or academic_year or year_n,
        ops_label=ops_label,
        make_current=False,
    )
    filled = fill_unset_windows_from_calendar_items(
        conn, term_key=master["term_key"], season=season_n, items=items
    )
    if filled and _latest_version_row(conn, master["term_key"]) is None:
        snapshot_calendar_version(
            conn,
            term_key=master["term_key"],
            items=items,
            actor=actor,
            reason="مزامنة من التقويم المحفوظ",
        )
    return {
        "hydrated": True,
        "filled": len(filled),
        "term_key": master["term_key"],
    }


def on_calendar_saved(
    conn,
    *,
    academic_year: str,
    season: str,
    actor: str = "",
) -> dict[str, Any] | None:
    """أثر جانبي لحفظ التقويم — لا يغيّر حمولة العرض."""
    try:
        ensure_term_engine_tables(conn)
        season_n = normalize_season(season)
        year_n = normalize_academic_year(academic_year)
        if not season_n or not year_n:
            return None
        master = upsert_term_master(
            conn,
            season=season_n,
            academic_year=year_n,
            term_name_ar=season_name_ar(season_n),
            ops_year_label=year_n,
            make_current=False,
        )
        from backend.services.academic_calendar import assemble_calendar_items

        existing = load_calendar_item_rows(conn, academic_year, season_n)
        items = assemble_calendar_items(
            academic_year=academic_year, term=season_n, existing=existing
        )
        from backend.services.term_policy import apply_calendar_amendment

        try:
            apply_calendar_amendment(
                conn,
                academic_year=academic_year,
                season=season_n,
                items=items,
                actor=actor,
                reason="حفظ التقويم الأكاديمي",
                confirm=True,
                notify=False,
            )
        except Exception:
            logger.exception("term_policy apply after calendar save skipped")
        windows = fill_unset_windows_from_calendar_items(
            conn, term_key=master["term_key"], season=season_n, items=items
        )
        version = snapshot_calendar_version(
            conn,
            term_key=master["term_key"],
            items=items,
            actor=actor,
        )
        return {
            "term_key": master["term_key"],
            "ops_label": master.get("ops_label") or "",
            "calendar_version": version,
            "windows_synced": len(windows),
        }
    except Exception:
        logger.exception("term_engine on_calendar_saved failed (calendar save kept)")
        return None


# ---------------------------------------------------------------------------
# الموجة 1 — حارس الكتابة
# ---------------------------------------------------------------------------

OP_REGISTRATION_WRITE = "registration_write"
OP_ENROLLMENT_PLAN_WRITE = "enrollment_plan_write"
OP_ENROLLMENT_PLAN_APPROVE = "enrollment_plan_approve"
OP_ADD_COURSE = "add_course"
OP_DROP_COURSE = "drop_course"
OP_SCHEDULE_WRITE = "schedule_write"
OP_SCHEDULE_PUBLISH = "schedule_publish"
OP_EXAM_WRITE = "exam_write"
OP_EXAM_PUBLISH = "exam_publish"

OPERATION_WINDOWS: dict[str, tuple[str, ...]] = {
    OP_REGISTRATION_WRITE: ("registration_renewal", "registration_new"),
    OP_ENROLLMENT_PLAN_WRITE: ("registration_renewal", "registration_new"),
    OP_ENROLLMENT_PLAN_APPROVE: ("registration_renewal", "registration_new"),
    OP_ADD_COURSE: ("add_courses", "registration_renewal", "registration_new"),
    OP_DROP_COURSE: ("drop_courses", "registration_renewal", "registration_new"),
    # الجدول/الامتحان: قفل المرحلة هو الضابط الأساسي (لا نوافذ تاريخية إلزامية).
    OP_SCHEDULE_WRITE: (),
    OP_SCHEDULE_PUBLISH: (),
    OP_EXAM_WRITE: (),
    OP_EXAM_PUBLISH: (),
}
OPERATION_STAGE: dict[str, str] = {
    OP_REGISTRATION_WRITE: "registrations",
    OP_ENROLLMENT_PLAN_WRITE: "registrations",
    OP_ENROLLMENT_PLAN_APPROVE: "registrations",
    OP_ADD_COURSE: "registrations",
    OP_DROP_COURSE: "registrations",
    OP_SCHEDULE_WRITE: "schedule",
    OP_SCHEDULE_PUBLISH: "schedule",
    OP_EXAM_WRITE: "exams",
    OP_EXAM_PUBLISH: "exams",
}
OPERATION_LABELS_AR: dict[str, str] = {
    OP_REGISTRATION_WRITE: "التسجيلات",
    OP_ENROLLMENT_PLAN_WRITE: "خطة التسجيل",
    OP_ENROLLMENT_PLAN_APPROVE: "اعتماد خطة التسجيل",
    OP_ADD_COURSE: "إضافة مقرر",
    OP_DROP_COURSE: "إسقاط مقرر",
    OP_SCHEDULE_WRITE: "تعديل الجدول الدراسي",
    OP_SCHEDULE_PUBLISH: "نشر الجدول الدراسي",
    OP_EXAM_WRITE: "تعديل جدول الامتحان",
    OP_EXAM_PUBLISH: "نشر جدول الامتحان",
}

CODE_TERM_CLOSED = "term_closed"
CODE_WINDOW_CLOSED = "term_window_closed"


class TermOperationError(PermissionError):
    """رفض كتابة بسبب قفل مرحلة أو نافذة تشغيل."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_TERM_CLOSED,
        operation: str = "",
        stage: str = "",
        window_key: str = "",
        term_key: str = "",
        semester: str = "",
    ):
        super().__init__(message)
        self.code = code
        self.operation = operation
        self.stage = stage
        self.window_key = window_key
        self.term_key = term_key
        self.semester = semester

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "status": "error",
            "message": str(self),
            "code": self.code or CODE_TERM_CLOSED,
        }
        for key in ("operation", "stage", "window_key", "term_key", "semester"):
            val = getattr(self, key, None)
            if val not in (None, ""):
                payload[key] = val
        return payload


def parse_semester_label(raw: str | None) -> dict[str, str] | None:
    s = " ".join((raw or "").split())
    if not s:
        return None
    if ":" in s:
        head, rest = s.split(":", 1)
        season = normalize_season(head)
        if season and normalize_academic_year(rest):
            return parse_ops_term(season_name_ar(season), rest.strip())
    parts = s.split(None, 1)
    if len(parts) == 2:
        return parse_ops_term(parts[0], parts[1])
    return None


def window_open_on(
    starts_at: Any,
    ends_at: Any,
    today: datetime.date,
) -> bool:
    start = _parse_date(starts_at)
    end = _parse_date(ends_at)
    if start is None and end is None:
        return False
    if start is not None and today < start:
        return False
    if end is not None and today > end:
        return False
    return True


def _ops_semester_label(conn, semester: str | None) -> str:
    raw = (semester or "").strip()
    if raw:
        return raw
    from backend.services.utilities import get_current_term

    name, year = get_current_term(conn=conn)
    return f"{(name or '').strip()} {(year or '').strip()}".strip()


def _window_label(window_key: str) -> str:
    for spec in WINDOW_CATALOG:
        if spec.window_key == window_key:
            return spec.label_ar
    return window_key


def _load_window_rows(conn, term_key: str, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if not term_key or not keys or not table_exists(conn, "term_windows"):
        return []
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in keys)
    try:
        rows = cur.execute(
            f"""
            SELECT window_key, starts_at, ends_at, status, kind, grace_until
            FROM term_windows
            WHERE term_key = ? AND window_key IN ({placeholders})
            """,
            (term_key, *keys),
        ).fetchall()
    except Exception:
        rows = cur.execute(
            f"""
            SELECT window_key, starts_at, ends_at, status, kind
            FROM term_windows
            WHERE term_key = ? AND window_key IN ({placeholders})
            """,
            (term_key, *keys),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if hasattr(r, "keys"):
            out.append({k: r[k] for k in r.keys()})
        else:
            out.append(
                {
                    "window_key": r[0],
                    "starts_at": r[1],
                    "ends_at": r[2],
                    "status": r[3],
                    "kind": r[4],
                    "grace_until": r[5] if len(r) > 5 else None,
                }
            )
    return out


def resolve_guard_department_id(
    conn,
    *,
    actor: str | None = None,
    student_id: str | None = None,
) -> int | None:
    actor = (actor or "").strip()
    if actor:
        try:
            from backend.core.department_scope_policy import resolve_effective_department_scope_id

            scoped = resolve_effective_department_scope_id(conn, actor)
            if scoped is not None:
                return int(scoped)
        except Exception:
            pass
    sid = (student_id or "").strip()
    if not sid or not table_exists(conn, "students"):
        return None
    try:
        from backend.database.database import fetch_table_columns

        cols = fetch_table_columns(conn, "students")
        if "department_id" not in cols:
            return None
        row = conn.cursor().execute(
            "SELECT department_id FROM students WHERE student_id = ? LIMIT 1",
            (sid,),
        ).fetchone()
        if not row:
            return None
        raw = row["department_id"] if hasattr(row, "keys") else row[0]
        if raw in (None, ""):
            return None
        return int(raw)
    except (TypeError, ValueError, Exception):
        return None


def _grace_still_open(raw: Any, now_dt: datetime.datetime) -> bool:
    s = str(raw or "").strip()
    if not s:
        return False
    try:
        gdt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return False
    if gdt.tzinfo is None:
        gdt = gdt.replace(tzinfo=datetime.timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=datetime.timezone.utc)
    return now_dt <= gdt


def _exception_allows(conn, student_id: str, operation: str, term_key: str | None) -> bool:
    if not student_id or not table_exists(conn, "term_operation_exceptions"):
        return False
    now = _now_iso()
    try:
        row = conn.cursor().execute(
            """
            SELECT id FROM term_operation_exceptions
            WHERE student_id = ? AND operation = ? AND status = 'approved'
              AND (term_key = '' OR term_key = ?)
              AND (expires_at IS NULL OR expires_at = '' OR expires_at >= ?)
            LIMIT 1
            """,
            (student_id, operation, term_key or "", now),
        ).fetchone()
        return row is not None
    except Exception:
        return False


def assert_term_operation(
    conn,
    *,
    operation: str,
    semester: str | None = None,
    department_id: int | None = None,
    force: bool = False,
    now: datetime.date | None = None,
    student_id: str | None = None,
) -> None:
    """يرفع TermClosedError أو TermOperationError إذا مُنعت الكتابة.

    الترتيب: قفل المرحلة → حالة الفصل المغلقة → نوافذ مؤرَّخة.
    النوافذ غير المؤرَّخة لا تمنع. المرحلة المقفلة لا تُفتح من تاريخ التقويم.
    """
    if force:
        return
    operation = (operation or "").strip()
    if operation not in OPERATION_WINDOWS:
        raise ValueError(f"عملية غير معروفة: {operation}")
    stage = OPERATION_STAGE[operation]
    ops_sem = _ops_semester_label(conn, semester)
    from backend.services.term_closure import TermClosedError, assert_term_writable

    try:
        assert_term_writable(
            conn,
            stage=stage,
            semester=ops_sem or None,
            department_id=department_id,
            force=False,
        )
    except TermClosedError:
        raise

    parsed = parse_semester_label(ops_sem)
    term_key = parsed["term_key"] if parsed else None
    if term_key and table_exists(conn, "term_master"):
        row = conn.cursor().execute(
            "SELECT status FROM term_master WHERE term_key = ? LIMIT 1",
            (term_key,),
        ).fetchone()
        status = ""
        if row is not None:
            status = str(row["status"] if hasattr(row, "keys") else row[0] or "")
        if status == TERM_STATUS_CLOSED:
            raise TermOperationError(
                f"الفصل «{ops_sem}» مغلق — التعديل غير مسموح.",
                code=CODE_TERM_CLOSED,
                operation=operation,
                stage=stage,
                term_key=term_key,
                semester=ops_sem,
            )

    if not term_key:
        return
    if student_id and _exception_allows(conn, str(student_id), operation, term_key):
        return
    today = now or datetime.date.today()
    keys = OPERATION_WINDOWS[operation]
    rows = _load_window_rows(conn, term_key, keys)
    scheduled = [
        w
        for w in rows
        if (w.get("status") == WINDOW_SCHEDULED)
        and (w.get("starts_at") or w.get("ends_at"))
    ]
    if not scheduled:
        return
    open_rows = [
        w for w in scheduled if window_open_on(w.get("starts_at"), w.get("ends_at"), today)
    ]
    if open_rows:
        return
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    if any(_grace_still_open(w.get("grace_until"), now_dt) for w in scheduled):
        return
    labels = "، ".join(_window_label(str(w.get("window_key") or "")) for w in scheduled)
    first_key = str(scheduled[0].get("window_key") or "")
    op_label = OPERATION_LABELS_AR.get(operation, operation)
    raise TermOperationError(
        f"نافذة «{op_label}» مغلقة للفصل «{ops_sem}» ({labels}).",
        code=CODE_WINDOW_CLOSED,
        operation=operation,
        stage=stage,
        window_key=first_key,
        term_key=term_key,
        semester=ops_sem,
    )


def assert_term_operation_for_request(
    conn,
    *,
    operation: str,
    semester: str | None = None,
    actor: str | None = None,
    student_id: str | None = None,
    force: bool = False,
    now: datetime.date | None = None,
) -> None:
    dept_id = resolve_guard_department_id(conn, actor=actor, student_id=student_id)
    assert_term_operation(
        conn,
        operation=operation,
        semester=semester,
        department_id=dept_id,
        force=force,
        now=now,
        student_id=student_id,
    )


def http_term_blocked(exc: BaseException):
    """استجابة HTTP 423 موحّدة لقفل المرحلة أو النافذة."""
    from flask import jsonify

    if isinstance(exc, TermOperationError):
        return jsonify(exc.as_dict()), 423
    payload = {
        "status": "error",
        "message": str(exc),
        "code": getattr(exc, "code", None) or CODE_TERM_CLOSED,
    }
    stage = getattr(exc, "stage", None)
    semester = getattr(exc, "semester", None)
    if stage:
        payload["stage"] = stage
    if semester:
        payload["semester"] = semester
    return jsonify(payload), 423
