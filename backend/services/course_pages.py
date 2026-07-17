"""
صفحة المقرر + مكتبي + نشر المواد/المحاضرات + طلبات التعديل.

الطبقات:
  - course_catalog_pages: أهداف/مخرجات/مفردات (قفل بعد أول إدخال)
  - course_section_pages: تقييم ومراجع الشعبة
  - instructor_library_files: مكتبة الأستاذ الشخصية
  - course_published_materials: منشورات الشعبة (ملفات + محاضرات)
  - course_content_change_requests: طلب تعديل حقول مقفلة
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
from typing import Any
from urllib.parse import urlencode

from flask import Blueprint, jsonify, request, send_file, session

from backend.core.auth import login_required, role_required
from backend.core.department_scope_policy import (
    assert_hod_for_course_operation,
    hod_may_operate_on_course,
    resolve_effective_department_scope_id,
)
from backend.database.database import fetch_table_columns, is_postgresql, table_exists
from backend.services.utilities import get_connection, get_current_term

course_pages_bp = Blueprint("course_pages", __name__)

STATUS_EMPTY = "empty"
STATUS_DRAFT = "draft"
STATUS_LOCKED = "locked"
LOCKABLE_FIELDS = ("objectives", "outcomes", "topics")

MATERIAL_TYPES = frozenset(
    {
        "lecture_recorded",
        "lecture_live",
        "notes",
        "past_exam",
        "reference",
        "other",
    }
)

ALLOWED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".mp4",
        ".webm",
        ".txt",
        ".zip",
    }
)
MAX_FILE_BYTES = 100 * 1024 * 1024  # 100MB
MAX_TAG_LEN = 80


def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _row_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return {}


def _json_list(raw: Any) -> list:
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
            return val if isinstance(val, list) else []
        except Exception:
            return []
    return []


def _dumps(val: Any) -> str:
    return json.dumps(val if val is not None else [], ensure_ascii=False)


def library_upload_dir() -> str:
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "uploads", "instructor_library")
    )
    os.makedirs(base, exist_ok=True)
    return base


def ensure_course_pages_schema(conn) -> None:
    cur = conn.cursor()
    stmts = [
        """
        CREATE TABLE IF NOT EXISTS course_catalog_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            course_master_id INTEGER,
            objectives_json TEXT DEFAULT '[]',
            outcomes_json TEXT DEFAULT '[]',
            topics_json TEXT DEFAULT '[]',
            objectives_status TEXT NOT NULL DEFAULT 'empty',
            outcomes_status TEXT NOT NULL DEFAULT 'empty',
            topics_status TEXT NOT NULL DEFAULT 'empty',
            assessment_template TEXT DEFAULT '',
            references_template TEXT DEFAULT '',
            first_entered_by TEXT DEFAULT '',
            first_entered_at TEXT,
            locked_by TEXT DEFAULT '',
            locked_at TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            UNIQUE (course_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS course_section_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            teaching_group_id INTEGER,
            section_id INTEGER,
            instructor_id INTEGER NOT NULL,
            semester TEXT DEFAULT '',
            assessment_text TEXT DEFAULT '',
            references_text TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            UNIQUE (teaching_group_id, instructor_id, semester)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS instructor_library_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instructor_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            file_type TEXT NOT NULL DEFAULT 'other',
            folder TEXT DEFAULT '',
            tags_json TEXT DEFAULT '[]',
            storage_path TEXT DEFAULT '',
            external_url TEXT DEFAULT '',
            original_name TEXT DEFAULT '',
            mime_type TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            is_archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS course_published_materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            teaching_group_id INTEGER,
            section_id INTEGER,
            instructor_id INTEGER NOT NULL,
            semester TEXT DEFAULT '',
            library_file_id INTEGER,
            external_url TEXT DEFAULT '',
            display_title TEXT NOT NULL DEFAULT '',
            material_type TEXT NOT NULL DEFAULT 'other',
            week_no INTEGER,
            live_starts_at TEXT,
            live_ends_at TEXT,
            meeting_passcode TEXT DEFAULT '',
            platform TEXT DEFAULT '',
            is_published INTEGER NOT NULL DEFAULT 1,
            published_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT ''
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS course_weekly_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            semester TEXT DEFAULT '',
            instructor_id INTEGER NOT NULL,
            weeks_json TEXT DEFAULT '[]',
            source_plan_id INTEGER,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            UNIQUE (course_name, semester, instructor_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS course_content_change_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            catalog_page_id INTEGER NOT NULL,
            course_name TEXT NOT NULL,
            field_name TEXT NOT NULL,
            proposed_json TEXT DEFAULT '[]',
            note TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            requested_by_instructor_id INTEGER,
            requested_by TEXT DEFAULT '',
            reviewed_by TEXT DEFAULT '',
            reviewed_at TEXT,
            review_note TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assessment_method_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            label_ar TEXT NOT NULL,
            default_weight REAL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS course_section_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            teaching_group_id INTEGER,
            section_id INTEGER,
            instructor_id INTEGER NOT NULL,
            semester TEXT DEFAULT '',
            method_id INTEGER NOT NULL,
            weight_pct REAL,
            notes TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (teaching_group_id, instructor_id, semester, method_id)
        )
        """,
    ]
    if is_postgresql():
        stmts = [
            s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
            .replace("INTEGER NOT NULL", "BIGINT NOT NULL")
            .replace("INTEGER,", "BIGINT,")
            .replace("INTEGER ", "BIGINT ")
            for s in stmts
        ]
        for i in range(len(stmts)):
            stmts[i] = stmts[i].replace("BIGINT PRIMARY KEY", "BIGSERIAL PRIMARY KEY", 1)
    for stmt in stmts:
        try:
            cur.execute(stmt)
        except Exception:
            pass
    try:
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ilib_instructor ON instructor_library_files(instructor_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_cpub_tg ON course_published_materials(teaching_group_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ccat_course ON course_catalog_pages(course_name)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_csa_tg ON course_section_assessments(teaching_group_id)"
        )
    except Exception:
        pass
    try:
        conn.commit()
    except Exception:
        pass
    try:
        cols = {c.lower() for c in (fetch_table_columns(conn, "course_section_pages") or [])}
        if "assessment_plan_json" not in cols:
            cur = conn.cursor()
            if is_postgresql():
                cur.execute(
                    "ALTER TABLE course_section_pages ADD COLUMN IF NOT EXISTS assessment_plan_json TEXT DEFAULT ''"
                )
            else:
                cur.execute(
                    "ALTER TABLE course_section_pages ADD COLUMN assessment_plan_json TEXT DEFAULT ''"
                )
            conn.commit()
    except Exception:
        pass
    try:
        cols = {c.lower() for c in (fetch_table_columns(conn, "course_catalog_pages") or [])}
        if "outcome_links_json" not in cols:
            cur = conn.cursor()
            if is_postgresql():
                cur.execute(
                    "ALTER TABLE course_catalog_pages ADD COLUMN IF NOT EXISTS outcome_links_json TEXT DEFAULT '[]'"
                )
            else:
                cur.execute(
                    "ALTER TABLE course_catalog_pages ADD COLUMN outcome_links_json TEXT DEFAULT '[]'"
                )
            conn.commit()
    except Exception:
        pass
    try:
        cur = conn.cursor()
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_cwp_course ON course_weekly_plans(course_name, semester)"
        )
        conn.commit()
    except Exception:
        pass
    _seed_assessment_catalog(conn)


DEFAULT_ASSESSMENT_METHODS = (
    ("coursework", "أعمال سنة", 20.0, 10),
    ("quiz", "اختبار قصير", 10.0, 20),
    ("assignment", "واجب / تقرير", 10.0, 30),
    ("project", "مشروع", 15.0, 40),
    ("midterm", "اختبار جزئي", 20.0, 50),
    ("final", "اختبار نهائي", 40.0, 60),
    ("lab", "عملي / مختبر", 15.0, 70),
    ("participation", "مشاركة", 5.0, 80),
    ("presentation", "عرض تقديمي", 10.0, 90),
    ("other", "أخرى", None, 100),
)


def _seed_assessment_catalog(conn) -> None:
    cur = conn.cursor()
    try:
        n = cur.execute("SELECT COUNT(*) FROM assessment_method_catalog").fetchone()
        count = int(n[0] if n and not hasattr(n, "keys") else (n[0] if n else 0) or 0)
    except Exception:
        return
    if count > 0:
        return
    for code, label, weight, order in DEFAULT_ASSESSMENT_METHODS:
        try:
            cur.execute(
                """
                INSERT INTO assessment_method_catalog (code, label_ar, default_weight, sort_order, is_active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (code, label, weight, order),
            )
        except Exception:
            pass
    try:
        conn.commit()
    except Exception:
        pass


def list_assessment_catalog(conn) -> list[dict]:
    from backend.services.assessment_plan import assessment_schema_payload

    schema = assessment_schema_payload()
    return list(schema["main"]) + [{**x, "category": "coursework"} for x in schema["coursework"]]


def list_section_assessments(
    conn,
    *,
    teaching_group_id: int | None,
    instructor_id: int,
    semester: str | None = None,
    course_name: str | None = None,
) -> list[dict]:
    from backend.services.assessment_plan import (
        assessment_plan_to_methods,
        normalize_assessment_plan,
    )

    ensure_course_pages_schema(conn)
    page = _get_or_create_section_page(
        conn,
        course_name=_normalize_course(course_name or ""),
        instructor_id=int(instructor_id),
        teaching_group_id=teaching_group_id,
        section_id=None,
        semester=semester,
    )
    plan = normalize_assessment_plan((page or {}).get("assessment_plan_json"))
    return assessment_plan_to_methods(plan)


def get_section_assessment_plan_dict(
    conn,
    *,
    teaching_group_id: int | None,
    instructor_id: int,
    semester: str | None = None,
    course_name: str | None = None,
) -> dict:
    from backend.services.assessment_plan import normalize_assessment_plan

    ensure_course_pages_schema(conn)
    page = _get_or_create_section_page(
        conn,
        course_name=_normalize_course(course_name or ""),
        instructor_id=int(instructor_id),
        teaching_group_id=teaching_group_id,
        section_id=None,
        semester=semester,
    )
    return normalize_assessment_plan((page or {}).get("assessment_plan_json"))


def save_section_assessments(
    conn,
    *,
    course_name: str,
    teaching_group_id: int | None,
    section_id: int | None,
    instructor_id: int,
    semester: str | None,
    selections: list[dict] | None = None,
    plan: dict | None = None,
) -> dict:
    from backend.services.assessment_plan import (
        assessment_plan_to_methods,
        assessment_plan_total,
        dumps_plan,
        normalize_assessment_plan,
        validate_assessment_plan,
    )

    ensure_course_pages_schema(conn)
    if plan is None:
        raise ValueError("أرسل assessment_plan (التصنيفات الأربعة)")
    plan = normalize_assessment_plan(plan)
    ok, msg = validate_assessment_plan(plan)
    if not ok:
        raise ValueError(msg)
    page = _get_or_create_section_page(
        conn,
        course_name=_normalize_course(course_name),
        instructor_id=int(instructor_id),
        teaching_group_id=teaching_group_id,
        section_id=section_id,
        semester=semester,
    )
    methods = assessment_plan_to_methods(plan)
    summary = " · ".join(f"{m['method_label']} {m['weight_pct']}%" for m in methods)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE course_section_pages
        SET assessment_plan_json=?, assessment_text=?, updated_at=?, updated_by=?
        WHERE id=?
        """,
        (dumps_plan(plan), summary, _now_iso(), _username(), int(page["id"])),
    )
    conn.commit()
    return {
        "assessment_plan": plan,
        "assessment_methods": methods,
        "assessment_selections": methods,
        "total": assessment_plan_total(plan),
    }


def parse_references_text(text: str) -> list[dict]:
    """تحويل نص المراجع سطراً سطراً إلى بنية تقرير."""
    out = []
    for i, line in enumerate((text or "").splitlines()):
        title = line.strip()
        if not title:
            continue
        ref_type = "book"
        low = title.lower()
        if low.startswith("http://") or low.startswith("https://"):
            ref_type = "website"
        out.append(
            {
                "ref_type": ref_type,
                "title": title,
                "publication_date": "",
                "url_or_isbn": title if ref_type == "website" else "",
                "sort_order": i,
            }
        )
    return out


def delivery_source_bundle(
    conn,
    *,
    course_name: str,
    teaching_group_id: int | None = None,
    section_id: int | None = None,
    instructor_id: int | None = None,
    semester: str | None = None,
) -> dict:
    """حزمة مصدر التقرير من صفحة المقرر."""
    ensure_course_pages_schema(conn)
    cn = _normalize_course(course_name)
    catalog = _get_or_create_catalog(conn, cn)
    sem = (semester or "").strip() or _current_semester_label(conn)
    # إن وُجدت مفردات مقفلة بلا baseline معتمد — زامن
    fs = catalog.get("field_status") or {}
    if (fs.get("topics") or "") == STATUS_LOCKED and catalog.get("topics"):
        try:
            from backend.services.course_delivery import get_active_baseline

            bl = get_active_baseline(conn, cn)
            if not bl or not bl.get("topics"):
                _sync_topics_baseline(conn, cn, catalog.get("topics") or [], instructor_id)
                conn.commit()
        except Exception:
            pass

    from backend.services.assessment_plan import (
        assessment_plan_to_methods,
        assessment_plan_total,
        normalize_assessment_plan,
    )

    section = None
    if instructor_id:
        section = _get_or_create_section_page(
            conn,
            course_name=cn,
            instructor_id=int(instructor_id),
            teaching_group_id=teaching_group_id,
            section_id=section_id,
            semester=sem,
        )
    else:
        cur = conn.cursor()
        if teaching_group_id:
            row = cur.execute(
                """
                SELECT * FROM course_section_pages
                WHERE teaching_group_id=? ORDER BY updated_at DESC LIMIT 1
                """,
                (int(teaching_group_id),),
            ).fetchone()
            section = _row_dict(row) if row else None

    plan = normalize_assessment_plan((section or {}).get("assessment_plan_json"))
    methods_for_report = assessment_plan_to_methods(plan)

    refs_text = ""
    if section:
        refs_text = (section.get("references_text") or "").strip()
    if not refs_text:
        refs_text = (catalog.get("references_template") or "").strip()

    topics_locked = (fs.get("topics") or "") == STATUS_LOCKED
    blockers = []
    if not topics_locked or not (catalog.get("topics") or []):
        blockers.append("أكمل واحفظ نهائياً مفردات المقرر في صفحة المقرر")
    if abs(assessment_plan_total(plan) - 100.0) > 0.01 or not methods_for_report:
        blockers.append("أكمل طرق التقييم في صفحة المقرر بحيث يكون المجموع 100%")

    q = {"course_name": cn}
    if teaching_group_id:
        q["teaching_group_id"] = teaching_group_id
    if section_id:
        q["section_id"] = section_id
    from urllib.parse import urlencode

    return {
        "course_name": cn,
        "objectives": catalog.get("objectives") or [],
        "outcomes": catalog.get("outcomes") or [],
        "topics": catalog.get("topics") or [],
        "field_status": fs,
        "topics_locked": topics_locked,
        "assessment_plan": plan,
        "assessment_methods": methods_for_report,
        "references_text": refs_text,
        "references_parsed": parse_references_text(refs_text),
        "section": section,
        "ready_for_report": len(blockers) == 0,
        "blockers": blockers,
        "course_page_url": "/course_page?" + urlencode({k: v for k, v in q.items() if v}),
        "source": "course_page",
    }


def _fetch_catalog_row(conn, course_name: str) -> dict | None:
    """قراءة كتالوج المقرر دون إنشاء سجل جديد."""
    cn = _normalize_course(course_name)
    if not cn:
        return None
    ensure_course_pages_schema(conn)
    row = conn.cursor().execute(
        """
        SELECT * FROM course_catalog_pages
        WHERE lower(trim(course_name)) = lower(trim(?))
        LIMIT 1
        """,
        (cn,),
    ).fetchone()
    return _serialize_catalog(_row_dict(row)) if row else None


def _fetch_section_page_row(
    conn,
    *,
    course_name: str,
    instructor_id: int,
    teaching_group_id: int | None = None,
    section_id: int | None = None,
    semester: str | None = None,
) -> dict | None:
    """قراءة صفحة الشعبة دون إنشاء سجل جديد."""
    cn = _normalize_course(course_name)
    if not cn or not instructor_id:
        return None
    ensure_course_pages_schema(conn)
    cur = conn.cursor()
    sem = (semester or "").strip() or _current_semester_label(conn)
    if teaching_group_id:
        row = cur.execute(
            """
            SELECT * FROM course_section_pages
            WHERE instructor_id=? AND teaching_group_id=?
              AND lower(trim(course_name))=lower(trim(?))
            ORDER BY updated_at DESC LIMIT 1
            """,
            (int(instructor_id), int(teaching_group_id), cn),
        ).fetchone()
        if row:
            return _row_dict(row)
    if section_id:
        row = cur.execute(
            """
            SELECT * FROM course_section_pages
            WHERE instructor_id=? AND section_id=?
              AND lower(trim(course_name))=lower(trim(?))
            ORDER BY updated_at DESC LIMIT 1
            """,
            (int(instructor_id), int(section_id), cn),
        ).fetchone()
        if row:
            return _row_dict(row)
    row = cur.execute(
        """
        SELECT * FROM course_section_pages
        WHERE instructor_id=? AND lower(trim(course_name))=lower(trim(?))
          AND (semester=? OR COALESCE(semester,'')='')
        ORDER BY updated_at DESC LIMIT 1
        """,
        (int(instructor_id), cn, sem),
    ).fetchone()
    return _row_dict(row) if row else None


def count_published_materials(
    conn,
    *,
    instructor_id: int,
    course_name: str,
    teaching_group_id: int | None = None,
    section_id: int | None = None,
) -> int:
    ensure_course_pages_schema(conn)
    cn = _normalize_course(course_name)
    cur = conn.cursor()
    if teaching_group_id:
        row = cur.execute(
            """
            SELECT COUNT(*) FROM course_published_materials
            WHERE instructor_id=? AND teaching_group_id=?
              AND COALESCE(is_published,1)=1
            """,
            (int(instructor_id), int(teaching_group_id)),
        ).fetchone()
        return int(row[0] or 0) if row else 0
    if section_id:
        row = cur.execute(
            """
            SELECT COUNT(*) FROM course_published_materials
            WHERE instructor_id=? AND section_id=?
              AND COALESCE(is_published,1)=1
            """,
            (int(instructor_id), int(section_id)),
        ).fetchone()
        return int(row[0] or 0) if row else 0
    if cn:
        row = cur.execute(
            """
            SELECT COUNT(*) FROM course_published_materials
            WHERE instructor_id=? AND lower(trim(course_name))=lower(trim(?))
              AND COALESCE(is_published,1)=1
            """,
            (int(instructor_id), cn),
        ).fetchone()
        return int(row[0] or 0) if row else 0
    return 0


def count_instructor_library_files(conn, instructor_id: int) -> int:
    ensure_course_pages_schema(conn)
    row = conn.cursor().execute(
        """
        SELECT COUNT(*) FROM instructor_library_files
        WHERE instructor_id=? AND COALESCE(is_archived,0)=0
        """,
        (int(instructor_id),),
    ).fetchone()
    return int(row[0] or 0) if row else 0


def course_page_readiness_snapshot(
    conn,
    *,
    course_name: str,
    instructor_id: int,
    teaching_group_id: int | None = None,
    section_id: int | None = None,
    semester: str | None = None,
) -> dict:
    """ملخص جاهزية صفحة المقرر لشعبة/مجموعة تدريس (قراءة فقط)."""
    from backend.services.assessment_plan import assessment_plan_total, normalize_assessment_plan
    from urllib.parse import urlencode

    cn = _normalize_course(course_name)
    catalog = _fetch_catalog_row(conn, cn) or {}
    fs = catalog.get("field_status") or {
        "objectives": STATUS_EMPTY,
        "outcomes": STATUS_EMPTY,
        "topics": STATUS_EMPTY,
    }
    section = _fetch_section_page_row(
        conn,
        course_name=cn,
        instructor_id=int(instructor_id),
        teaching_group_id=teaching_group_id,
        section_id=section_id,
        semester=semester,
    )
    plan = normalize_assessment_plan((section or {}).get("assessment_plan_json"))
    total = assessment_plan_total(plan)
    assessment_ok = abs(total - 100.0) <= 0.01
    materials_n = count_published_materials(
        conn,
        instructor_id=int(instructor_id),
        course_name=cn,
        teaching_group_id=teaching_group_id,
        section_id=section_id,
    )
    obj_st = (fs.get("objectives") or STATUS_EMPTY)
    out_st = (fs.get("outcomes") or STATUS_EMPTY)
    top_st = (fs.get("topics") or STATUS_EMPTY)
    syllabus_locked = all(s == STATUS_LOCKED for s in (obj_st, out_st, top_st))
    topics_locked = top_st == STATUS_LOCKED and bool(catalog.get("topics"))
    score = 0
    if obj_st == STATUS_LOCKED:
        score += 25
    elif obj_st == STATUS_DRAFT:
        score += 10
    if out_st == STATUS_LOCKED:
        score += 25
    elif out_st == STATUS_DRAFT:
        score += 10
    if top_st == STATUS_LOCKED:
        score += 25
    elif top_st == STATUS_DRAFT:
        score += 10
    if assessment_ok:
        score += 25
    elif total > 0:
        score += 10

    blockers: list[str] = []
    if obj_st != STATUS_LOCKED:
        blockers.append("احفظ نهائياً أهداف المقرر")
    if out_st != STATUS_LOCKED:
        blockers.append("احفظ نهائياً مخرجات المقرر")
    if top_st != STATUS_LOCKED:
        blockers.append("احفظ نهائياً مفردات المقرر")
    if not assessment_ok:
        blockers.append("أكمل خطة التقييم إلى 100%")
    if materials_n <= 0:
        blockers.append("انشر مادة واحدة على الأقل للطلاب")

    q = {"course_name": cn}
    if teaching_group_id:
        q["teaching_group_id"] = int(teaching_group_id)
    if section_id:
        q["section_id"] = int(section_id)
    url = "/course_page?" + urlencode({k: v for k, v in q.items() if v})

    ready_core = syllabus_locked and assessment_ok
    return {
        "course_name": cn,
        "objectives_status": obj_st,
        "outcomes_status": out_st,
        "topics_status": top_st,
        "field_status": fs,
        "syllabus_locked": syllabus_locked,
        "topics_locked": topics_locked,
        "assessment_total": total,
        "assessment_ok": assessment_ok,
        "materials_published": materials_n,
        "has_materials": materials_n > 0,
        "ready": ready_core and materials_n > 0,
        "ready_core": ready_core,
        "ready_for_report": topics_locked and assessment_ok,
        "pct": min(100, score),
        "blockers": blockers,
        "course_page_url": url,
        "page_exists": bool(catalog) or bool(section),
    }


def enrich_rows_course_page_readiness(
    conn,
    rows: list[dict],
    *,
    instructor_id: int,
    semester: str | None = None,
) -> None:
    """إرفاق course_page_readiness بكل صف مقرراتي."""
    if not rows or not instructor_id:
        return
    try:
        ensure_course_pages_schema(conn)
    except Exception:
        return
    for row in rows:
        try:
            tgid = int(row.get("teaching_group_id") or 0) or None
        except (TypeError, ValueError):
            tgid = None
        try:
            sid = int(row.get("section_id") or 0) or None
        except (TypeError, ValueError):
            sid = None
        try:
            row["course_page_readiness"] = course_page_readiness_snapshot(
                conn,
                course_name=(row.get("course_name") or "").strip(),
                instructor_id=int(instructor_id),
                teaching_group_id=tgid,
                section_id=sid,
                semester=semester or (row.get("semester") or "").strip() or None,
            )
        except Exception:
            row["course_page_readiness"] = {
                "ready": False,
                "ready_core": False,
                "pct": 0,
                "blockers": ["تعذر قراءة جاهزية صفحة المقرر"],
                "course_page_url": "/course_page",
                "materials_published": 0,
                "has_materials": False,
                "assessment_ok": False,
                "syllabus_locked": False,
            }


def course_page_portal_extras(
    conn,
    rows: list[dict],
    *,
    instructor_id: int,
    semester: str | None = None,
) -> dict:
    """إحصاءات + مهام جاهزية صفحة المقرر لملخص البوابة."""
    enrich_rows_course_page_readiness(conn, rows, instructor_id=instructor_id, semester=semester)
    ready_n = 0
    total = len(rows or [])
    action_items: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        rd = row.get("course_page_readiness") or {}
        if rd.get("ready"):
            ready_n += 1
        cn = (row.get("course_name") or "").strip()
        sid = row.get("section_id")
        tgid = row.get("teaching_group_id")
        key = f"{(cn or '').lower()}:{tgid or sid or ''}"
        if key in seen:
            continue
        seen.add(key)
        href = rd.get("course_page_url") or "/course_page"
        if not rd.get("page_exists") or not rd.get("syllabus_locked"):
            action_items.append(
                {
                    "type": "course_page_incomplete",
                    "section_id": sid,
                    "teaching_group_id": tgid,
                    "course": cn,
                    "tab": "sections",
                    "focus": "course_page",
                    "href": href,
                    "message": f"صفحة المقرر غير مكتملة: {cn}",
                }
            )
        elif not rd.get("assessment_ok"):
            action_items.append(
                {
                    "type": "assessment_plan_incomplete",
                    "section_id": sid,
                    "teaching_group_id": tgid,
                    "course": cn,
                    "tab": "sections",
                    "focus": "course_page",
                    "href": href,
                    "message": f"خطة التقييم ليست 100٪: {cn}",
                }
            )
        elif not rd.get("has_materials"):
            action_items.append(
                {
                    "type": "materials_missing",
                    "section_id": sid,
                    "teaching_group_id": tgid,
                    "course": cn,
                    "tab": "sections",
                    "focus": "course_page",
                    "href": href,
                    "message": f"لا مواد منشورة للطلاب: {cn}",
                }
            )
    try:
        lib_n = count_instructor_library_files(conn, int(instructor_id))
    except Exception:
        lib_n = 0
    return {
        "course_pages_ready": ready_n,
        "course_pages_total": total,
        "library_files_count": lib_n,
        "action_items": action_items,
        "rows": rows,
    }


def _current_semester_label(conn) -> str:
    tname, tyear = get_current_term(conn=conn)
    return f"{(tname or '').strip()} {(tyear or '').strip()}".strip()


def _session_instructor_id() -> int | None:
    raw = session.get("instructor_id")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _is_hod_or_admin() -> bool:
    role = (session.get("user_role") or "").strip()
    return role in (
        "head_of_department",
        "admin_main",
        "admin",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
    )


def _username() -> str:
    return (session.get("user") or session.get("username") or "").strip()


def _normalize_course(name: str) -> str:
    return (name or "").strip()


def _can_edit_lockable(conn, course_name: str, field: str, status: str) -> tuple[bool, str]:
    """هل يمكن تعديل حقل قابل للقفل؟"""
    if field not in LOCKABLE_FIELDS:
        return False, "حقل غير معروف"
    if status == STATUS_LOCKED:
        if _is_hod_or_admin():
            try:
                assert_hod_for_course_operation(conn, _username(), course_name)
                return True, ""
            except Exception as exc:
                return False, str(exc) or "غير مصرح لرئيس القسم"
        return False, "الحقل مثبت — يعدّله رئيس القسم فقط (أو أرسل طلب تعديل)"
    # empty أو draft: أستاذ مكلّف أو رئيس قسم
    if _is_hod_or_admin():
        try:
            if hod_may_operate_on_course(conn, _username(), course_name):
                return True, ""
        except Exception:
            pass
        if session.get("user_role") in (
            "admin_main",
            "admin",
            "system_admin",
            "college_dean",
            "academic_vice_dean",
        ):
            return True, ""
    iid = _session_instructor_id()
    if iid and _instructor_assigned_to_course(conn, iid, course_name):
        return True, ""
    return False, "غير مصرح"


def _instructor_assigned_to_course(conn, instructor_id: int, course_name: str) -> bool:
    cn = _normalize_course(course_name)
    if not cn or not instructor_id:
        return False
    cur = conn.cursor()
    if table_exists(conn, "teaching_groups"):
        row = cur.execute(
            """
            SELECT 1 FROM teaching_groups
            WHERE instructor_id = ?
              AND lower(trim(course_name)) = lower(trim(?))
              AND COALESCE(is_active, 1) = 1
            LIMIT 1
            """,
            (int(instructor_id), cn),
        ).fetchone()
        if row:
            return True
    # fallback: schedule by instructor_id or name
    try:
        name_row = cur.execute(
            "SELECT COALESCE(TRIM(name),'') FROM instructors WHERE id=?",
            (int(instructor_id),),
        ).fetchone()
        iname = (name_row[0] if name_row and not hasattr(name_row, "keys") else (name_row["name"] if name_row else "")) or ""
    except Exception:
        iname = ""
    cols = set(fetch_table_columns(conn, "schedule") or [])
    if "instructor_id" in cols:
        row = cur.execute(
            """
            SELECT 1 FROM schedule
            WHERE instructor_id = ? AND lower(trim(course_name)) = lower(trim(?))
            LIMIT 1
            """,
            (int(instructor_id), cn),
        ).fetchone()
        if row:
            return True
    if iname and "instructor" in cols:
        row = cur.execute(
            """
            SELECT 1 FROM schedule
            WHERE lower(trim(instructor)) = lower(trim(?))
              AND lower(trim(course_name)) = lower(trim(?))
            LIMIT 1
            """,
            (iname, cn),
        ).fetchone()
        if row:
            return True
    return False


def _instructor_owns_group(conn, instructor_id: int, teaching_group_id: int | None, section_id: int | None = None) -> bool:
    cur = conn.cursor()
    if teaching_group_id:
        row = cur.execute(
            """
            SELECT 1 FROM teaching_groups
            WHERE id = ? AND instructor_id = ? AND COALESCE(is_active, 1) = 1
            LIMIT 1
            """,
            (int(teaching_group_id), int(instructor_id)),
        ).fetchone()
        return bool(row)
    if section_id:
        cols = set(fetch_table_columns(conn, "schedule") or [])
        if "instructor_id" in cols:
            row = cur.execute(
                "SELECT 1 FROM schedule WHERE id=? AND instructor_id=? LIMIT 1",
                (int(section_id), int(instructor_id)),
            ).fetchone()
            return bool(row)
    return False


def _get_or_create_catalog(conn, course_name: str) -> dict:
    ensure_course_pages_schema(conn)
    cn = _normalize_course(course_name)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT * FROM course_catalog_pages
        WHERE lower(trim(course_name)) = lower(trim(?))
        LIMIT 1
        """,
        (cn,),
    ).fetchone()
    if row:
        return _serialize_catalog(_row_dict(row))
    cur.execute(
        """
        INSERT INTO course_catalog_pages (course_name, updated_at, updated_by)
        VALUES (?, ?, ?)
        """,
        (cn, _now_iso(), _username()),
    )
    conn.commit()
    row = cur.execute(
        """
        SELECT * FROM course_catalog_pages
        WHERE lower(trim(course_name)) = lower(trim(?))
        LIMIT 1
        """,
        (cn,),
    ).fetchone()
    return _serialize_catalog(_row_dict(row))


def _serialize_catalog(d: dict) -> dict:
    if not d:
        return {}
    out = dict(d)
    out["objectives"] = _json_list(d.get("objectives_json"))
    out["outcomes"] = _json_list(d.get("outcomes_json"))
    out["topics"] = _json_list(d.get("topics_json"))
    out["outcome_links"] = _json_list(d.get("outcome_links_json"))
    for k in ("objectives_json", "outcomes_json", "topics_json", "outcome_links_json"):
        out.pop(k, None)
    # permissions hints
    out["field_status"] = {
        "objectives": (d.get("objectives_status") or STATUS_EMPTY),
        "outcomes": (d.get("outcomes_status") or STATUS_EMPTY),
        "topics": (d.get("topics_status") or STATUS_EMPTY),
    }
    return out


def _sync_topics_baseline(conn, course_name: str, topics: list, instructor_id: int | None) -> None:
    """عند قفل المفردات: مزامنة قائمة معتمدة في course_syllabus_baselines."""
    try:
        from backend.services.course_delivery import (
            BASELINE_APPROVED,
            BASELINE_SUPERSEDED,
            ensure_course_delivery_schema,
        )
    except Exception:
        return
    ensure_course_delivery_schema(conn)
    cn = _normalize_course(course_name)
    titles = []
    for t in topics or []:
        if isinstance(t, dict):
            title = (t.get("topic_title") or t.get("title") or "").strip()
        else:
            title = str(t or "").strip()
        if title:
            titles.append(title)
    if not titles:
        return
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE course_syllabus_baselines
        SET status = ?, updated_at = ?
        WHERE lower(trim(course_name)) = lower(trim(?)) AND status = ?
        """,
        (BASELINE_SUPERSEDED, _now_iso(), cn, BASELINE_APPROVED),
    )
    ver_row = cur.execute(
        """
        SELECT COALESCE(MAX(version), 0) FROM course_syllabus_baselines
        WHERE lower(trim(course_name)) = lower(trim(?))
        """,
        (cn,),
    ).fetchone()
    ver = int(ver_row[0] if ver_row and not hasattr(ver_row, "keys") else (ver_row["max"] if ver_row else 0) or 0) + 1
    sem = _current_semester_label(conn)
    cur.execute(
        """
        INSERT INTO course_syllabus_baselines
            (course_name, version, status, semester_label, created_by_instructor_id,
             created_by, approved_by, approved_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cn,
            ver,
            BASELINE_APPROVED,
            sem,
            int(instructor_id) if instructor_id else None,
            _username(),
            _username() or "system",
            _now_iso(),
            _now_iso(),
            _now_iso(),
        ),
    )
    if is_postgresql():
        bl_id = cur.execute("SELECT lastval()").fetchone()[0]
    else:
        bl_id = cur.lastrowid
    for i, title in enumerate(titles):
        cur.execute(
            """
            INSERT INTO course_syllabus_topics (baseline_id, sort_order, topic_title, is_active)
            VALUES (?, ?, ?, 1)
            """,
            (int(bl_id), i + 1, title),
        )


def _apply_field_save(
    conn,
    catalog: dict,
    field: str,
    items: list,
    *,
    finalize: bool,
) -> dict:
    status_col = f"{field}_status"
    json_col = f"{field}_json"
    current = (catalog.get(status_col) or catalog.get("field_status", {}).get(field) or STATUS_EMPTY)
    ok, msg = _can_edit_lockable(conn, catalog.get("course_name") or "", field, current)
    if not ok:
        raise PermissionError(msg)

    new_status = current
    if current == STATUS_EMPTY:
        new_status = STATUS_LOCKED if finalize else STATUS_DRAFT
    elif current == STATUS_DRAFT:
        new_status = STATUS_LOCKED if finalize else STATUS_DRAFT
    elif current == STATUS_LOCKED:
        new_status = STATUS_LOCKED  # HOD edit keeps locked

    now = _now_iso()
    user = _username()
    cn = catalog.get("course_name")
    cur = conn.cursor()
    first_by = catalog.get("first_entered_by") or ""
    first_at = catalog.get("first_entered_at")
    locked_by = catalog.get("locked_by") or ""
    locked_at = catalog.get("locked_at")
    if current == STATUS_EMPTY and not first_by:
        first_by = user
        first_at = now
    if new_status == STATUS_LOCKED and current != STATUS_LOCKED:
        locked_by = user
        locked_at = now

    cur.execute(
        f"""
        UPDATE course_catalog_pages
        SET {json_col} = ?, {status_col} = ?,
            first_entered_by = ?, first_entered_at = ?,
            locked_by = ?, locked_at = ?,
            updated_at = ?, updated_by = ?
        WHERE id = ?
        """,
        (
            _dumps(items),
            new_status,
            first_by,
            first_at,
            locked_by,
            locked_at,
            now,
            user,
            int(catalog["id"]),
        ),
    )
    if field == "topics" and new_status == STATUS_LOCKED:
        _sync_topics_baseline(conn, cn, items, _session_instructor_id())
    conn.commit()
    return _get_or_create_catalog(conn, cn)


def _get_or_create_section_page(
    conn,
    *,
    course_name: str,
    instructor_id: int,
    teaching_group_id: int | None,
    section_id: int | None,
    semester: str | None,
) -> dict:
    ensure_course_pages_schema(conn)
    cn = _normalize_course(course_name)
    sem = (semester or "").strip() or _current_semester_label(conn)
    cur = conn.cursor()
    row = None
    if teaching_group_id:
        row = cur.execute(
            """
            SELECT * FROM course_section_pages
            WHERE teaching_group_id = ? AND instructor_id = ?
              AND COALESCE(semester,'') = ?
            LIMIT 1
            """,
            (int(teaching_group_id), int(instructor_id), sem),
        ).fetchone()
    if not row and section_id:
        row = cur.execute(
            """
            SELECT * FROM course_section_pages
            WHERE section_id = ? AND instructor_id = ?
              AND COALESCE(semester,'') = ?
            LIMIT 1
            """,
            (int(section_id), int(instructor_id), sem),
        ).fetchone()
    if row:
        d = _row_dict(row)
    else:
        catalog = _get_or_create_catalog(conn, cn)
        cur.execute(
            """
            INSERT INTO course_section_pages
                (course_name, teaching_group_id, section_id, instructor_id, semester,
                 assessment_text, references_text, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cn,
                int(teaching_group_id) if teaching_group_id else None,
                int(section_id) if section_id else None,
                int(instructor_id),
                sem,
                catalog.get("assessment_template") or "",
                catalog.get("references_template") or "",
                _now_iso(),
                _username(),
            ),
        )
        conn.commit()
        if teaching_group_id:
            row = cur.execute(
                """
                SELECT * FROM course_section_pages
                WHERE teaching_group_id = ? AND instructor_id = ?
                  AND COALESCE(semester,'') = ?
                LIMIT 1
                """,
                (int(teaching_group_id), int(instructor_id), sem),
            ).fetchone()
        else:
            row = cur.execute(
                """
                SELECT * FROM course_section_pages
                WHERE section_id = ? AND instructor_id = ?
                  AND COALESCE(semester,'') = ?
                LIMIT 1
                """,
                (int(section_id) if section_id else 0, int(instructor_id), sem),
            ).fetchone()
        d = _row_dict(row)
    return d


def _student_enrolled(conn, student_id: str, course_name: str, teaching_group_id: int | None = None) -> bool:
    cur = conn.cursor()
    cn = _normalize_course(course_name)
    reg_cols = set(fetch_table_columns(conn, "registrations") or [])
    if teaching_group_id and "teaching_group_id" in reg_cols:
        row = cur.execute(
            """
            SELECT 1 FROM registrations
            WHERE student_id = ?
              AND lower(trim(course_name)) = lower(trim(?))
              AND (teaching_group_id = ? OR teaching_group_id IS NULL)
            LIMIT 1
            """,
            (str(student_id), cn, int(teaching_group_id)),
        ).fetchone()
        if row:
            return True
    row = cur.execute(
        """
        SELECT 1 FROM registrations
        WHERE student_id = ? AND lower(trim(course_name)) = lower(trim(?))
        LIMIT 1
        """,
        (str(student_id), cn),
    ).fetchone()
    return bool(row)


def _notify_enrolled_students(conn, course_name: str, teaching_group_id: int | None, title: str, body: str) -> None:
    from backend.services.course_workflow import notify_users

    cur = conn.cursor()
    cn = _normalize_course(course_name)
    reg_cols = set(fetch_table_columns(conn, "registrations") or [])
    params: list[Any] = [cn]
    tg_sql = ""
    if teaching_group_id and "teaching_group_id" in reg_cols:
        tg_sql = " AND (r.teaching_group_id = ? OR r.teaching_group_id IS NULL)"
        params.append(int(teaching_group_id))
    # map student_id -> username if available
    rows = cur.execute(
        f"""
        SELECT DISTINCT COALESCE(u.username, r.student_id) AS uname
        FROM registrations r
        LEFT JOIN users u ON (
            CAST(u.student_id AS TEXT) = CAST(r.student_id AS TEXT)
            OR u.username = r.student_id
        ) AND COALESCE(u.is_active, 1) = 1
        WHERE lower(trim(r.course_name)) = lower(trim(?)) {tg_sql}
        """,
        tuple(params),
    ).fetchall()
    users = []
    for r in rows or []:
        u = str(r[0] if not hasattr(r, "keys") else r["uname"] or "").strip()
        if u:
            users.append(u)
    notify_users(users[:500], title=title, body=body)


def _safe_filename_part(text: str, max_len: int = 40) -> str:
    t = re.sub(r"[^\w\-]+", "_", (text or "").strip(), flags=re.UNICODE)
    return (t[:max_len] or "file").strip("_") or "file"


def _save_upload(file_storage, instructor_id: int) -> dict:
    orig = (file_storage.filename or "file").strip()
    _, ext = os.path.splitext(orig.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"امتداد غير مسموح: {ext or '(بدون)'}")
    data = file_storage.read()
    if not data:
        raise ValueError("ملف فارغ")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("حجم الملف يتجاوز الحد المسموح (100MB)")
    digest = hashlib.sha256(data).hexdigest()[:16]
    stored = f"ins{int(instructor_id)}__{_safe_filename_part(os.path.splitext(orig)[0])}__{digest}{ext}"
    path = os.path.join(library_upload_dir(), stored)
    with open(path, "wb") as f:
        f.write(data)
    return {
        "storage_path": stored,
        "original_name": orig,
        "mime_type": getattr(file_storage, "mimetype", None) or "",
        "file_size": len(data),
    }


# ─── Catalog APIs ───────────────────────────────────────────────


@course_pages_bp.route("/catalog", methods=["GET"])
@login_required
def api_catalog_get():
    course_name = _normalize_course(request.args.get("course_name") or "")
    if not course_name:
        return jsonify({"status": "error", "message": "course_name مطلوب"}), 400
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        # seed topics from approved baseline if catalog topics empty
        catalog = _get_or_create_catalog(conn, course_name)
        if (catalog.get("topics_status") or STATUS_EMPTY) == STATUS_EMPTY:
            try:
                from backend.services.course_delivery import get_active_baseline

                bl = get_active_baseline(conn, course_name)
                if bl and bl.get("topics"):
                    topics = [
                        {"topic_title": t.get("topic_title") or "", "sort_order": t.get("sort_order") or i + 1}
                        for i, t in enumerate(bl["topics"])
                    ]
                    cur = conn.cursor()
                    cur.execute(
                        """
                        UPDATE course_catalog_pages
                        SET topics_json=?, topics_status=?, locked_by=?, locked_at=?, updated_at=?
                        WHERE id=?
                        """,
                        (
                            _dumps(topics),
                            STATUS_LOCKED,
                            bl.get("approved_by") or "baseline",
                            bl.get("approved_at") or _now_iso(),
                            _now_iso(),
                            int(catalog["id"]),
                        ),
                    )
                    conn.commit()
                    catalog = _get_or_create_catalog(conn, course_name)
            except Exception:
                pass

        can_map = {}
        for f in LOCKABLE_FIELDS:
            st = catalog.get("field_status", {}).get(f) or STATUS_EMPTY
            ok, _ = _can_edit_lockable(conn, course_name, f, st)
            can_map[f] = ok
        catalog["can_edit"] = can_map
        catalog["is_hod"] = _is_hod_or_admin()
        return jsonify({"status": "ok", "catalog": catalog})


@course_pages_bp.route("/catalog/<field>", methods=["PUT"])
@login_required
def api_catalog_save_field(field: str):
    field = (field or "").strip().lower()
    if field not in LOCKABLE_FIELDS:
        return jsonify({"status": "error", "message": "حقل غير مدعوم"}), 400
    data = request.get_json(silent=True) or {}
    course_name = _normalize_course(data.get("course_name") or "")
    items = data.get("items")
    if items is None:
        items = data.get(field) or []
    if not isinstance(items, list):
        return jsonify({"status": "error", "message": "items يجب أن تكون قائمة"}), 400
    finalize = bool(data.get("finalize") or data.get("lock"))
    if not course_name:
        return jsonify({"status": "error", "message": "course_name مطلوب"}), 400
    with get_connection() as conn:
        catalog = _get_or_create_catalog(conn, course_name)
        try:
            updated = _apply_field_save(conn, catalog, field, items, finalize=finalize)
        except PermissionError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 403
        return jsonify({"status": "ok", "catalog": updated})


@course_pages_bp.route("/catalog/templates", methods=["PUT"])
@login_required
def api_catalog_templates():
    """تحديث قوالب التقييم/المراجع على مستوى الكتالوج (رئيس قسم أو أستاذ عند empty)."""
    data = request.get_json(silent=True) or {}
    course_name = _normalize_course(data.get("course_name") or "")
    if not course_name:
        return jsonify({"status": "error", "message": "course_name مطلوب"}), 400
    with get_connection() as conn:
        catalog = _get_or_create_catalog(conn, course_name)
        iid = _session_instructor_id()
        allowed = _is_hod_or_admin() or (
            iid and _instructor_assigned_to_course(conn, iid, course_name)
        )
        if not allowed:
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        assessment = data.get("assessment_template")
        references = data.get("references_template")
        cur = conn.cursor()
        if assessment is not None:
            cur.execute(
                "UPDATE course_catalog_pages SET assessment_template=?, updated_at=?, updated_by=? WHERE id=?",
                (str(assessment), _now_iso(), _username(), int(catalog["id"])),
            )
        if references is not None:
            cur.execute(
                "UPDATE course_catalog_pages SET references_template=?, updated_at=?, updated_by=? WHERE id=?",
                (str(references), _now_iso(), _username(), int(catalog["id"])),
            )
        conn.commit()
        return jsonify({"status": "ok", "catalog": _get_or_create_catalog(conn, course_name)})


def _normalize_outcome_links(raw: Any, outcomes: list | None = None) -> list[dict]:
    """قائمة روابط CLO → أهداف المقرر + PLO البرنامج."""
    items = _json_list(raw) if not isinstance(raw, list) else raw
    out: list[dict] = []
    seen: set[str] = set()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        code = str(it.get("clo_code") or it.get("code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        obj_idx = []
        for x in it.get("objective_indexes") or it.get("objectives") or []:
            try:
                obj_idx.append(int(x))
            except (TypeError, ValueError):
                pass
        plo_ids = []
        for x in it.get("plo_ids") or []:
            try:
                plo_ids.append(int(x))
            except (TypeError, ValueError):
                pass
        out.append(
            {
                "clo_code": code,
                "objective_indexes": sorted(set(obj_idx)),
                "plo_ids": sorted(set(plo_ids)),
            }
        )
    # تأكد من وجود صف لكل مخرج محفوظ
    for o in outcomes or []:
        if not isinstance(o, dict):
            continue
        code = str(o.get("code") or "").strip()
        if code and code not in seen:
            seen.add(code)
            out.append({"clo_code": code, "objective_indexes": [], "plo_ids": []})
    return out


def _program_context_for_instructor(conn, instructor_id: int | None = None) -> dict:
    """برامج القسم + أهداف/مخرجات للاختيار والقراءة."""
    from backend.services.learning_outcomes import _resolve_instructor_department, _rows_to_dicts

    cur = conn.cursor()
    dep_id = None
    try:
        dep_id = _resolve_instructor_department(conn)
    except Exception:
        dep_id = None
    programs = []
    if dep_id is not None:
        rows = cur.execute(
            """
            SELECT id, code, name_ar FROM programs
            WHERE department_id = ? AND COALESCE(is_active,1)=1
            ORDER BY code
            """,
            (int(dep_id),),
        ).fetchall()
        programs = _rows_to_dicts(cur, rows)
    elif instructor_id:
        # احتياط: كل البرامج النشطة إن لم يُعرف القسم
        try:
            rows = cur.execute(
                """
                SELECT id, code, name_ar FROM programs
                WHERE COALESCE(is_active,1)=1 ORDER BY code LIMIT 20
                """
            ).fetchall()
            programs = _rows_to_dicts(cur, rows)
        except Exception:
            programs = []
    plos = []
    goals = []
    program_id = int(programs[0]["id"]) if programs else None
    if program_id:
        try:
            from backend.core.plo_schema import ensure_plo_enhancement_schema

            ensure_plo_enhancement_schema(conn)
        except Exception:
            pass
        try:
            rows = cur.execute(
                """
                SELECT id, code, title_ar, COALESCE(domain,'') AS domain
                FROM program_learning_outcomes
                WHERE program_id = ? AND COALESCE(is_active,1)=1
                ORDER BY sort_order, code
                """,
                (program_id,),
            ).fetchall()
            plos = _rows_to_dicts(cur, rows)
        except Exception:
            plos = []
        try:
            rows = cur.execute(
                """
                SELECT id, code, title_ar
                FROM program_goals
                WHERE program_id = ? AND COALESCE(is_active,1)=1
                ORDER BY sort_order, code
                """,
                (program_id,),
            ).fetchall()
            goals = _rows_to_dicts(cur, rows)
        except Exception:
            goals = []
    return {
        "department_id": dep_id,
        "programs": programs,
        "program_id": program_id,
        "program_goals": goals,
        "program_outcomes": plos,
    }


def _normalize_weeks(raw: Any) -> list[dict]:
    items = _json_list(raw) if not isinstance(raw, list) else raw
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            week_no = int(it.get("week_no") or 0)
        except (TypeError, ValueError):
            continue
        if week_no < 1 or week_no > 52:
            continue
        status = str(it.get("lecture_status") or it.get("status") or "planned").strip() or "planned"
        if status not in ("planned", "done", "postponed", "compensated"):
            status = "planned"
        out.append(
            {
                "week_no": week_no,
                "week_topic": str(it.get("week_topic") or it.get("topic") or "").strip(),
                "lecture_status": status,
                "linked_clo": str(it.get("linked_clo") or "").strip(),
                "topic_index": it.get("topic_index"),
            }
        )
    out.sort(key=lambda x: x["week_no"])
    return out


def _instructor_display_name(conn, instructor_id: int) -> str:
    cur = conn.cursor()
    for sql in (
        "SELECT name FROM instructors WHERE id = ? LIMIT 1",
        "SELECT full_name FROM instructors WHERE id = ? LIMIT 1",
    ):
        try:
            row = cur.execute(sql, (int(instructor_id),)).fetchone()
            if row and row[0]:
                return str(row[0]).strip()
        except Exception:
            continue
    return f"أستاذ #{instructor_id}"


def get_weekly_plan_bundle(
    conn,
    *,
    course_name: str,
    instructor_id: int,
    semester: str | None = None,
) -> dict:
    ensure_course_pages_schema(conn)
    cn = _normalize_course(course_name)
    sem = (semester or "").strip() or _current_semester_label(conn)
    cur = conn.cursor()
    mine = cur.execute(
        """
        SELECT id, weeks_json, source_plan_id, updated_at, updated_by, instructor_id
        FROM course_weekly_plans
        WHERE lower(trim(course_name))=lower(trim(?)) AND semester=? AND instructor_id=?
          AND COALESCE(is_active,1)=1
        LIMIT 1
        """,
        (cn, sem, int(instructor_id)),
    ).fetchone()
    my_plan = None
    if mine:
        d = _row_dict(mine)
        my_plan = {
            "id": int(d["id"]),
            "weeks": _normalize_weeks(d.get("weeks_json")),
            "source_plan_id": d.get("source_plan_id"),
            "updated_at": d.get("updated_at") or "",
            "updated_by": d.get("updated_by") or "",
            "instructor_id": int(d["instructor_id"]),
            "instructor_name": _instructor_display_name(conn, int(d["instructor_id"])),
        }
    peers = []
    rows = cur.execute(
        """
        SELECT id, weeks_json, updated_at, updated_by, instructor_id
        FROM course_weekly_plans
        WHERE lower(trim(course_name))=lower(trim(?)) AND semester=?
          AND instructor_id <> ? AND COALESCE(is_active,1)=1
        ORDER BY updated_at DESC
        LIMIT 10
        """,
        (cn, sem, int(instructor_id)),
    ).fetchall()
    for r in rows or []:
        d = _row_dict(r)
        weeks = _normalize_weeks(d.get("weeks_json"))
        if not weeks:
            continue
        peers.append(
            {
                "id": int(d["id"]),
                "weeks": weeks,
                "weeks_count": len(weeks),
                "updated_at": d.get("updated_at") or "",
                "updated_by": d.get("updated_by") or "",
                "instructor_id": int(d["instructor_id"]),
                "instructor_name": _instructor_display_name(conn, int(d["instructor_id"])),
            }
        )
    return {"my_plan": my_plan, "peer_plans": peers, "semester": sem, "course_name": cn}


def save_weekly_plan(
    conn,
    *,
    course_name: str,
    instructor_id: int,
    weeks: list,
    semester: str | None = None,
    source_plan_id: int | None = None,
    section_id: int | None = None,
) -> dict:
    ensure_course_pages_schema(conn)
    cn = _normalize_course(course_name)
    sem = (semester or "").strip() or _current_semester_label(conn)
    weeks_n = _normalize_weeks(weeks)
    cur = conn.cursor()
    now = _now_iso()
    by = _username()
    existing = cur.execute(
        """
        SELECT id FROM course_weekly_plans
        WHERE lower(trim(course_name))=lower(trim(?)) AND semester=? AND instructor_id=?
        LIMIT 1
        """,
        (cn, sem, int(instructor_id)),
    ).fetchone()
    if existing:
        pid = int(existing[0] if not hasattr(existing, "keys") else existing["id"])
        cur.execute(
            """
            UPDATE course_weekly_plans
            SET weeks_json=?, source_plan_id=?, is_active=1, updated_at=?, updated_by=?
            WHERE id=?
            """,
            (_dumps(weeks_n), source_plan_id, now, by, pid),
        )
    else:
        cur.execute(
            """
            INSERT INTO course_weekly_plans
                (course_name, semester, instructor_id, weeks_json, source_plan_id, is_active, created_at, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (cn, sem, int(instructor_id), _dumps(weeks_n), source_plan_id, now, now, by),
        )
    # مزامنة مع faculty_course_plans لعرض مقرراتي إن وُجدت شعبة
    if section_id:
        try:
            for w in weeks_n:
                cur.execute(
                    """
                    INSERT INTO faculty_course_plans
                        (section_id, instructor_id, week_no, week_topic, lecture_status, resources_text, linked_clo, updated_at, updated_by)
                    VALUES (?, ?, ?, ?, ?, '', ?, ?, ?)
                    ON CONFLICT (section_id, instructor_id, week_no)
                    DO UPDATE SET week_topic = EXCLUDED.week_topic,
                                  lecture_status = EXCLUDED.lecture_status,
                                  linked_clo = EXCLUDED.linked_clo,
                                  updated_at = EXCLUDED.updated_at,
                                  updated_by = EXCLUDED.updated_by
                    """,
                    (
                        int(section_id),
                        int(instructor_id),
                        int(w["week_no"]),
                        w.get("week_topic") or "",
                        w.get("lecture_status") or "planned",
                        w.get("linked_clo") or "",
                        now,
                        by,
                    ),
                )
        except Exception:
            pass
    conn.commit()
    return get_weekly_plan_bundle(conn, course_name=cn, instructor_id=int(instructor_id), semester=sem)


@course_pages_bp.route("/catalog/outcome_links", methods=["PUT"])
@login_required
@role_required("instructor", "head_of_department")
def api_outcome_links_save():
    data = request.get_json(silent=True) or {}
    course_name = _normalize_course(data.get("course_name") or "")
    if not course_name:
        return jsonify({"status": "error", "message": "course_name مطلوب"}), 400
    iid = _session_instructor_id()
    with get_connection() as conn:
        if not _is_hod_or_admin():
            if not iid or not _instructor_assigned_to_course(conn, iid, course_name):
                return jsonify({"status": "error", "message": "غير مصرح"}), 403
        catalog = _get_or_create_catalog(conn, course_name)
        links = _normalize_outcome_links(data.get("links") or data.get("outcome_links"), catalog.get("outcomes"))
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE course_catalog_pages
            SET outcome_links_json=?, updated_at=?, updated_by=?
            WHERE id=?
            """,
            (_dumps(links), _now_iso(), _username(), int(catalog["id"])),
        )
        conn.commit()
        updated = _get_or_create_catalog(conn, course_name)
        return jsonify({"status": "ok", "catalog": updated, "outcome_links": updated.get("outcome_links") or []})


@course_pages_bp.route("/weekly_plan", methods=["GET"])
@login_required
@role_required("instructor", "head_of_department")
def api_weekly_plan_get():
    course_name = _normalize_course(request.args.get("course_name") or "")
    semester = (request.args.get("semester") or "").strip()
    iid = _session_instructor_id()
    if not course_name or not iid:
        return jsonify({"status": "error", "message": "بيانات ناقصة"}), 400
    with get_connection() as conn:
        if not _instructor_assigned_to_course(conn, iid, course_name) and not _is_hod_or_admin():
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        bundle = get_weekly_plan_bundle(conn, course_name=course_name, instructor_id=iid, semester=semester or None)
        return jsonify({"status": "ok", **bundle})


@course_pages_bp.route("/weekly_plan", methods=["PUT"])
@login_required
@role_required("instructor", "head_of_department")
def api_weekly_plan_save():
    data = request.get_json(silent=True) or {}
    course_name = _normalize_course(data.get("course_name") or "")
    semester = (data.get("semester") or "").strip()
    iid = _session_instructor_id()
    if not course_name or not iid:
        return jsonify({"status": "error", "message": "بيانات ناقصة"}), 400
    with get_connection() as conn:
        if not _instructor_assigned_to_course(conn, iid, course_name) and not _is_hod_or_admin():
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        bundle = save_weekly_plan(
            conn,
            course_name=course_name,
            instructor_id=iid,
            weeks=data.get("weeks") or [],
            semester=semester or None,
            source_plan_id=data.get("source_plan_id"),
            section_id=int(data["section_id"]) if data.get("section_id") else None,
        )
        return jsonify({"status": "ok", **bundle})


@course_pages_bp.route("/weekly_plan/adopt", methods=["POST"])
@login_required
@role_required("instructor", "head_of_department")
def api_weekly_plan_adopt():
    data = request.get_json(silent=True) or {}
    course_name = _normalize_course(data.get("course_name") or "")
    try:
        source_id = int(data.get("source_plan_id") or data.get("plan_id") or 0)
    except (TypeError, ValueError):
        source_id = 0
    iid = _session_instructor_id()
    if not course_name or not iid or not source_id:
        return jsonify({"status": "error", "message": "بيانات ناقصة"}), 400
    with get_connection() as conn:
        if not _instructor_assigned_to_course(conn, iid, course_name) and not _is_hod_or_admin():
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT * FROM course_weekly_plans WHERE id=? LIMIT 1",
            (source_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "الخطة غير موجودة"}), 404
        src = _row_dict(row)
        if _normalize_course(src.get("course_name") or "") != course_name:
            return jsonify({"status": "error", "message": "الخطة ليست لنفس المقرر"}), 400
        bundle = save_weekly_plan(
            conn,
            course_name=course_name,
            instructor_id=iid,
            weeks=_normalize_weeks(src.get("weeks_json")),
            semester=(src.get("semester") or "").strip() or None,
            source_plan_id=source_id,
            section_id=int(data["section_id"]) if data.get("section_id") else None,
        )
        return jsonify({"status": "ok", "adopted_from": source_id, **bundle})


@course_pages_bp.route("/catalog/change_request", methods=["POST"])
@login_required
@role_required("instructor", "head_of_department")
def api_change_request_create():
    data = request.get_json(silent=True) or {}
    course_name = _normalize_course(data.get("course_name") or "")
    field = (data.get("field") or data.get("field_name") or "").strip().lower()
    items = data.get("items") or []
    note = (data.get("note") or "").strip()
    if field not in LOCKABLE_FIELDS or not course_name:
        return jsonify({"status": "error", "message": "بيانات غير مكتملة"}), 400
    iid = _session_instructor_id()
    with get_connection() as conn:
        catalog = _get_or_create_catalog(conn, course_name)
        st = catalog.get("field_status", {}).get(field) or STATUS_EMPTY
        if st != STATUS_LOCKED:
            return jsonify({"status": "error", "message": "الحقل غير مقفل — عدّله مباشرة"}), 400
        if not iid or not _instructor_assigned_to_course(conn, iid, course_name):
            if not _is_hod_or_admin():
                return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO course_content_change_requests
                (catalog_page_id, course_name, field_name, proposed_json, note,
                 status, requested_by_instructor_id, requested_by, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                int(catalog["id"]),
                course_name,
                field,
                _dumps(items),
                note,
                int(iid) if iid else None,
                _username(),
                _now_iso(),
            ),
        )
        conn.commit()
        try:
            from backend.services.course_workflow import department_id_for_course, notify_department_hods

            dept_id = department_id_for_course(conn, course_name)
            notify_department_hods(
                conn,
                dept_id,
                title=f"طلب تعديل {field} لمقرر {course_name}",
                body=note or "راجع طلب التعديل من لوحة صفحات المقررات.",
            )
        except Exception:
            pass
        return jsonify({"status": "ok", "message": "تم إرسال طلب التعديل لرئيس القسم"})


# ─── Section page ───────────────────────────────────────────────


@course_pages_bp.route("/section", methods=["GET"])
@login_required
def api_section_get():
    course_name = _normalize_course(request.args.get("course_name") or "")
    tgid = request.args.get("teaching_group_id", type=int)
    sid = request.args.get("section_id", type=int)
    semester = (request.args.get("semester") or "").strip()
    if not course_name:
        return jsonify({"status": "error", "message": "course_name مطلوب"}), 400
    iid = _session_instructor_id()
    with get_connection() as conn:
        catalog = _get_or_create_catalog(conn, course_name)
        section = None
        if iid:
            if tgid and not _instructor_owns_group(conn, iid, tgid, sid):
                if not _is_hod_or_admin():
                    return jsonify({"status": "error", "message": "غير مكلّف بهذه المجموعة"}), 403
            section = _get_or_create_section_page(
                conn,
                course_name=course_name,
                instructor_id=iid,
                teaching_group_id=tgid,
                section_id=sid,
                semester=semester,
            )
        can_map = {}
        for f in LOCKABLE_FIELDS:
            st = catalog.get("field_status", {}).get(f) or STATUS_EMPTY
            ok, _ = _can_edit_lockable(conn, course_name, f, st)
            can_map[f] = ok
        catalog["can_edit"] = can_map
        catalog["is_hod"] = _is_hod_or_admin()
        assessments = []
        assessment_plan = None
        if iid:
            assessments = list_section_assessments(
                conn,
                teaching_group_id=tgid,
                instructor_id=iid,
                semester=semester or None,
                course_name=course_name,
            )
            assessment_plan = get_section_assessment_plan_dict(
                conn,
                teaching_group_id=tgid,
                instructor_id=iid,
                semester=semester or None,
                course_name=course_name,
            )
        from backend.services.assessment_plan import assessment_schema_payload

        catalog["outcome_links"] = _normalize_outcome_links(
            catalog.get("outcome_links"), catalog.get("outcomes")
        )
        program_ctx = _program_context_for_instructor(conn, iid)
        weekly = None
        if iid:
            try:
                weekly = get_weekly_plan_bundle(
                    conn,
                    course_name=course_name,
                    instructor_id=iid,
                    semester=semester or None,
                )
            except Exception:
                weekly = {"my_plan": None, "peer_plans": [], "semester": semester or ""}

        return jsonify(
            {
                "status": "ok",
                "catalog": catalog,
                "section": section,
                "semester": semester or _current_semester_label(conn),
                "assessment_schema": assessment_schema_payload(),
                "assessment_plan": assessment_plan,
                "assessment_selections": assessments,
                "assessment_methods": assessments,
                "program_context": program_ctx,
                "weekly_plan": weekly,
            }
        )


@course_pages_bp.route("/assessment_catalog", methods=["GET"])
@login_required
def api_assessment_catalog():
    from backend.services.assessment_plan import assessment_schema_payload

    return jsonify({"status": "ok", "schema": assessment_schema_payload(), "total_required": 100})


@course_pages_bp.route("/section/assessments", methods=["PUT"])
@login_required
@role_required("instructor", "head_of_department")
def api_section_assessments_save():
    data = request.get_json(silent=True) or {}
    course_name = _normalize_course(data.get("course_name") or "")
    tgid = data.get("teaching_group_id")
    sid = data.get("section_id")
    try:
        tgid = int(tgid) if tgid else None
        sid = int(sid) if sid else None
    except (TypeError, ValueError):
        tgid = sid = None
    iid = _session_instructor_id()
    plan = data.get("assessment_plan") or data.get("plan")
    if not iid or not course_name:
        return jsonify({"status": "error", "message": "بيانات غير مكتملة"}), 400
    if not isinstance(plan, dict):
        return jsonify({"status": "error", "message": "assessment_plan مطلوب"}), 400
    with get_connection() as conn:
        if not _instructor_owns_group(conn, iid, tgid, sid) and not _is_hod_or_admin():
            if not _instructor_assigned_to_course(conn, iid, course_name):
                return jsonify({"status": "error", "message": "غير مصرح"}), 403
        try:
            result = save_section_assessments(
                conn,
                course_name=course_name,
                teaching_group_id=tgid,
                section_id=sid,
                instructor_id=iid,
                semester=data.get("semester"),
                plan=plan,
            )
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify({"status": "ok", **result})


@course_pages_bp.route("/section", methods=["PUT"])
@login_required
@role_required("instructor", "head_of_department")
def api_section_update():
    data = request.get_json(silent=True) or {}
    course_name = _normalize_course(data.get("course_name") or "")
    tgid = data.get("teaching_group_id")
    sid = data.get("section_id")
    try:
        tgid = int(tgid) if tgid else None
        sid = int(sid) if sid else None
    except (TypeError, ValueError):
        tgid, sid = None, None
    iid = _session_instructor_id()
    if not iid or not course_name:
        return jsonify({"status": "error", "message": "بيانات غير مكتملة"}), 400
    with get_connection() as conn:
        if not _instructor_owns_group(conn, iid, tgid, sid) and not _is_hod_or_admin():
            if not _instructor_assigned_to_course(conn, iid, course_name):
                return jsonify({"status": "error", "message": "غير مصرح"}), 403
        page = _get_or_create_section_page(
            conn,
            course_name=course_name,
            instructor_id=iid,
            teaching_group_id=tgid,
            section_id=sid,
            semester=data.get("semester"),
        )
        assessment = data.get("assessment_text")
        references = data.get("references_text")
        cur = conn.cursor()
        if assessment is not None:
            cur.execute(
                "UPDATE course_section_pages SET assessment_text=?, updated_at=?, updated_by=? WHERE id=?",
                (str(assessment), _now_iso(), _username(), int(page["id"])),
            )
        if references is not None:
            cur.execute(
                "UPDATE course_section_pages SET references_text=?, updated_at=?, updated_by=? WHERE id=?",
                (str(references), _now_iso(), _username(), int(page["id"])),
            )
        conn.commit()
        page = _get_or_create_section_page(
            conn,
            course_name=course_name,
            instructor_id=iid,
            teaching_group_id=tgid,
            section_id=sid,
            semester=data.get("semester"),
        )
        return jsonify({"status": "ok", "section": page})


# ─── Library ─────────────────────────────────────────────────────


@course_pages_bp.route("/library", methods=["GET"])
@login_required
@role_required("instructor", "head_of_department")
def api_library_list():
    iid = _session_instructor_id()
    if not iid:
        return jsonify({"status": "error", "message": "لا يوجد ربط بعضو هيئة تدريس"}), 400
    q = (request.args.get("q") or "").strip().lower()
    folder = (request.args.get("folder") or "").strip()
    include_archived = request.args.get("archived") == "1"
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT id, title, file_type, folder, tags_json, external_url, original_name,
                   mime_type, file_size, is_archived, created_at, updated_at,
                   CASE WHEN COALESCE(storage_path,'') <> '' THEN 1 ELSE 0 END AS has_file
            FROM instructor_library_files
            WHERE instructor_id = ?
              AND (? = 1 OR COALESCE(is_archived, 0) = 0)
            ORDER BY updated_at DESC, id DESC
            """,
            (int(iid), 1 if include_archived else 0),
        ).fetchall()
        items = []
        for r in rows or []:
            d = _row_dict(r)
            d["tags"] = _json_list(d.pop("tags_json", None))
            if folder and (d.get("folder") or "") != folder:
                continue
            if q:
                blob = f"{d.get('title')} {d.get('original_name')} {' '.join(d.get('tags') or [])}".lower()
                if q not in blob:
                    continue
            d["download_url"] = f"/course_pages/library/{d['id']}/file" if d.get("has_file") else None
            items.append(d)
        folders = sorted({(it.get("folder") or "").strip() for it in items if (it.get("folder") or "").strip()})
        return jsonify({"status": "ok", "items": items, "folders": folders})


@course_pages_bp.route("/library/upload", methods=["POST"])
@login_required
@role_required("instructor", "head_of_department")
def api_library_upload():
    iid = _session_instructor_id()
    if not iid:
        return jsonify({"status": "error", "message": "لا يوجد ربط بعضو هيئة تدريس"}), 400
    f = request.files.get("file")
    if not f:
        return jsonify({"status": "error", "message": "الملف مطلوب"}), 400
    title = (request.form.get("title") or f.filename or "ملف").strip()
    file_type = (request.form.get("file_type") or "other").strip() or "other"
    folder = (request.form.get("folder") or "").strip()
    tags_raw = request.form.get("tags") or "[]"
    try:
        tags = json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or [])
        if not isinstance(tags, list):
            tags = []
    except Exception:
        tags = [t.strip() for t in str(tags_raw).split(",") if t.strip()]
    try:
        meta = _save_upload(f, iid)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO instructor_library_files
                (instructor_id, title, file_type, folder, tags_json, storage_path,
                 original_name, mime_type, file_size, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(iid),
                title,
                file_type,
                folder,
                _dumps([str(t)[:MAX_TAG_LEN] for t in tags]),
                meta["storage_path"],
                meta["original_name"],
                meta["mime_type"],
                meta["file_size"],
                _now_iso(),
                _now_iso(),
            ),
        )
        conn.commit()
        new_id = cur.lastrowid if not is_postgresql() else cur.execute("SELECT lastval()").fetchone()[0]
        return jsonify({"status": "ok", "id": int(new_id)})


@course_pages_bp.route("/library/link", methods=["POST"])
@login_required
@role_required("instructor", "head_of_department")
def api_library_link():
    iid = _session_instructor_id()
    if not iid:
        return jsonify({"status": "error", "message": "لا يوجد ربط بعضو هيئة تدريس"}), 400
    data = request.get_json(silent=True) or {}
    url = (data.get("external_url") or data.get("url") or "").strip()
    title = (data.get("title") or url or "رابط").strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        return jsonify({"status": "error", "message": "رابط غير صالح"}), 400
    file_type = (data.get("file_type") or "other").strip() or "other"
    folder = (data.get("folder") or "").strip()
    tags = data.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO instructor_library_files
                (instructor_id, title, file_type, folder, tags_json, external_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(iid),
                title,
                file_type,
                folder,
                _dumps([str(t)[:MAX_TAG_LEN] for t in tags]),
                url,
                _now_iso(),
                _now_iso(),
            ),
        )
        conn.commit()
        new_id = cur.lastrowid if not is_postgresql() else cur.execute("SELECT lastval()").fetchone()[0]
        return jsonify({"status": "ok", "id": int(new_id)})


@course_pages_bp.route("/library/<int:file_id>", methods=["PUT"])
@login_required
@role_required("instructor", "head_of_department")
def api_library_update(file_id: int):
    iid = _session_instructor_id()
    if not iid:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    data = request.get_json(silent=True) or {}
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT * FROM instructor_library_files WHERE id=? AND instructor_id=?",
            (int(file_id), int(iid)),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        title = data.get("title")
        folder = data.get("folder")
        file_type = data.get("file_type")
        tags = data.get("tags")
        archived = data.get("is_archived")
        sets = ["updated_at=?"]
        params: list[Any] = [_now_iso()]
        if title is not None:
            sets.append("title=?")
            params.append(str(title).strip())
        if folder is not None:
            sets.append("folder=?")
            params.append(str(folder).strip())
        if file_type is not None:
            sets.append("file_type=?")
            params.append(str(file_type).strip())
        if tags is not None and isinstance(tags, list):
            sets.append("tags_json=?")
            params.append(_dumps([str(t)[:MAX_TAG_LEN] for t in tags]))
        if archived is not None:
            sets.append("is_archived=?")
            params.append(1 if archived else 0)
        params.extend([int(file_id), int(iid)])
        cur.execute(
            f"UPDATE instructor_library_files SET {', '.join(sets)} WHERE id=? AND instructor_id=?",
            tuple(params),
        )
        conn.commit()
        return jsonify({"status": "ok"})


@course_pages_bp.route("/library/<int:file_id>", methods=["DELETE"])
@login_required
@role_required("instructor", "head_of_department")
def api_library_delete(file_id: int):
    iid = _session_instructor_id()
    if not iid:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        cur.execute(
            "UPDATE instructor_library_files SET is_archived=1, updated_at=? WHERE id=? AND instructor_id=?",
            (_now_iso(), int(file_id), int(iid)),
        )
        conn.commit()
        return jsonify({"status": "ok"})


@course_pages_bp.route("/library/<int:file_id>/file", methods=["GET"])
@login_required
def api_library_file(file_id: int):
    iid = _session_instructor_id()
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT * FROM instructor_library_files WHERE id=?",
            (int(file_id),),
        ).fetchone()
        d = _row_dict(row)
        if not d:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        owner = int(d.get("instructor_id") or 0)
        # owner or student via published material
        allowed = iid and owner == int(iid)
        if not allowed:
            role = (session.get("user_role") or "").strip()
            if role == "student":
                # allow if published to an enrolled course
                pub = cur.execute(
                    """
                    SELECT course_name, teaching_group_id FROM course_published_materials
                    WHERE library_file_id=? AND COALESCE(is_published,1)=1
                    """,
                    (int(file_id),),
                ).fetchall()
                sid = str(session.get("student_id") or "").strip()
                for p in pub or []:
                    pd = _row_dict(p)
                    if _student_enrolled(conn, sid, pd.get("course_name") or "", pd.get("teaching_group_id")):
                        allowed = True
                        break
            elif _is_hod_or_admin():
                allowed = True
        if not allowed:
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        stored = (d.get("storage_path") or "").strip()
        if not stored:
            return jsonify({"status": "error", "message": "لا يوجد ملف"}), 404
        path = os.path.join(library_upload_dir(), os.path.basename(stored))
        if not os.path.isfile(path):
            return jsonify({"status": "error", "message": "الملف غير موجود على الخادم"}), 404
        return send_file(
            path,
            as_attachment=True,
            download_name=d.get("original_name") or os.path.basename(stored),
        )


# ─── Materials / lectures ────────────────────────────────────────


def _serialize_material(d: dict) -> dict:
    out = dict(d)
    out["is_published"] = bool(int(out.get("is_published") or 0))
    if out.get("library_file_id"):
        out["file_url"] = f"/course_pages/materials/{out['id']}/file"
    return out


@course_pages_bp.route("/materials", methods=["GET"])
@login_required
def api_materials_list():
    course_name = _normalize_course(request.args.get("course_name") or "")
    tgid = request.args.get("teaching_group_id", type=int)
    published_only = request.args.get("published_only") == "1"
    role = (session.get("user_role") or "").strip()
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        params: list[Any] = []
        where = ["1=1"]
        if course_name:
            where.append("lower(trim(course_name)) = lower(trim(?))")
            params.append(course_name)
        if tgid:
            where.append("teaching_group_id = ?")
            params.append(int(tgid))
        if published_only or role == "student":
            where.append("COALESCE(is_published,1) = 1")
        if role == "student":
            sid = str(session.get("student_id") or "").strip()
            if not course_name or not _student_enrolled(conn, sid, course_name, tgid):
                return jsonify({"status": "error", "message": "غير مسجّل في المقرر"}), 403
        elif role not in ("admin", "admin_main", "system_admin", "head_of_department", "college_dean", "academic_vice_dean"):
            iid = _session_instructor_id()
            if iid:
                where.append("instructor_id = ?")
                params.append(int(iid))
        rows = cur.execute(
            f"""
            SELECT * FROM course_published_materials
            WHERE {' AND '.join(where)}
            ORDER BY
              CASE WHEN material_type = 'lecture_live' THEN 0 ELSE 1 END,
              COALESCE(week_no, 999), id DESC
            """,
            tuple(params),
        ).fetchall()
        items = [_serialize_material(_row_dict(r)) for r in rows or []]
        return jsonify({"status": "ok", "items": items})


@course_pages_bp.route("/materials/publish", methods=["POST"])
@login_required
@role_required("instructor", "head_of_department")
def api_materials_publish():
    data = request.get_json(silent=True) or {}
    iid = _session_instructor_id()
    if not iid:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    course_name = _normalize_course(data.get("course_name") or "")
    tgid = data.get("teaching_group_id")
    sid = data.get("section_id")
    try:
        tgid = int(tgid) if tgid else None
        sid = int(sid) if sid else None
    except (TypeError, ValueError):
        tgid = sid = None
    if not course_name:
        return jsonify({"status": "error", "message": "course_name مطلوب"}), 400
    with get_connection() as conn:
        if not _instructor_owns_group(conn, iid, tgid, sid):
            if not _instructor_assigned_to_course(conn, iid, course_name):
                return jsonify({"status": "error", "message": "غير مكلّف"}), 403
        lib_id = data.get("library_file_id")
        external_url = (data.get("external_url") or "").strip()
        material_type = (data.get("material_type") or "other").strip()
        if material_type not in MATERIAL_TYPES:
            material_type = "other"
        display_title = (data.get("display_title") or data.get("title") or "").strip()
        week_no = data.get("week_no")
        try:
            week_no = int(week_no) if week_no not in (None, "") else None
        except (TypeError, ValueError):
            week_no = None
        notify = bool(data.get("notify_students"))
        if lib_id:
            cur = conn.cursor()
            lib = cur.execute(
                "SELECT * FROM instructor_library_files WHERE id=? AND instructor_id=? AND COALESCE(is_archived,0)=0",
                (int(lib_id), int(iid)),
            ).fetchone()
            if not lib:
                return jsonify({"status": "error", "message": "الملف غير موجود في مكتبي"}), 404
            ld = _row_dict(lib)
            if not display_title:
                display_title = ld.get("title") or ld.get("original_name") or "مادة"
            if not external_url:
                external_url = ld.get("external_url") or ""
        if not display_title:
            display_title = "مادة منشورة"
        if material_type == "lecture_live":
            if not (data.get("meeting_url") or external_url):
                return jsonify({"status": "error", "message": "رابط الاجتماع مطلوب"}), 400
            external_url = (data.get("meeting_url") or external_url).strip()
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        sem = (data.get("semester") or "").strip() or _current_semester_label(conn)
        cur.execute(
            """
            INSERT INTO course_published_materials
                (course_name, teaching_group_id, section_id, instructor_id, semester,
                 library_file_id, external_url, display_title, material_type, week_no,
                 live_starts_at, live_ends_at, meeting_passcode, platform,
                 is_published, published_at, created_at, updated_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                course_name,
                tgid,
                sid,
                int(iid),
                sem,
                int(lib_id) if lib_id else None,
                external_url,
                display_title,
                material_type,
                week_no,
                (data.get("live_starts_at") or "").strip() or None,
                (data.get("live_ends_at") or "").strip() or None,
                (data.get("meeting_passcode") or "").strip(),
                (data.get("platform") or "").strip(),
                _now_iso(),
                _now_iso(),
                _now_iso(),
                _username(),
            ),
        )
        conn.commit()
        new_id = cur.lastrowid if not is_postgresql() else cur.execute("SELECT lastval()").fetchone()[0]
        if notify:
            try:
                _notify_enrolled_students(
                    conn,
                    course_name,
                    tgid,
                    title=f"مادة جديدة: {display_title}",
                    body=f"نُشرت مادة في مقرر {course_name}.",
                )
            except Exception:
                pass
        if material_type == "lecture_live" and data.get("create_announcement") and sid:
            try:
                from backend.services.schedule import schedule_bp  # noqa: F401

                cur.execute(
                    """
                    INSERT INTO faculty_course_announcements
                        (section_id, instructor_id, title, body, announcement_type,
                         lecture_date, published_to_students, created_at, created_by)
                    VALUES (?, ?, ?, ?, 'extra_lecture', ?, 1, ?, ?)
                    """,
                    (
                        int(sid),
                        int(iid),
                        f"محاضرة مباشرة: {display_title}",
                        f"رابط الانضمام: {external_url}"
                        + (f"\nكلمة المرور: {data.get('meeting_passcode')}" if data.get("meeting_passcode") else ""),
                        (data.get("live_starts_at") or "")[:10] or None,
                        _now_iso(),
                        _username(),
                    ),
                )
                conn.commit()
            except Exception:
                pass
        return jsonify({"status": "ok", "id": int(new_id)})


@course_pages_bp.route("/materials/<int:mid>", methods=["PUT"])
@login_required
@role_required("instructor", "head_of_department")
def api_materials_update(mid: int):
    iid = _session_instructor_id()
    if not iid:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    data = request.get_json(silent=True) or {}
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT * FROM course_published_materials WHERE id=? AND instructor_id=?",
            (int(mid), int(iid)),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        d = _row_dict(row)
        sets = ["updated_at=?"]
        params: list[Any] = [_now_iso()]
        for key, col in (
            ("display_title", "display_title"),
            ("external_url", "external_url"),
            ("material_type", "material_type"),
            ("week_no", "week_no"),
            ("live_starts_at", "live_starts_at"),
            ("live_ends_at", "live_ends_at"),
            ("meeting_passcode", "meeting_passcode"),
            ("platform", "platform"),
            ("library_file_id", "library_file_id"),
        ):
            if key in data:
                sets.append(f"{col}=?")
                params.append(data.get(key))
        if "is_published" in data:
            sets.append("is_published=?")
            pub = 1 if data.get("is_published") else 0
            params.append(pub)
            if pub and not d.get("published_at"):
                sets.append("published_at=?")
                params.append(_now_iso())
        params.extend([int(mid), int(iid)])
        cur.execute(
            f"UPDATE course_published_materials SET {', '.join(sets)} WHERE id=? AND instructor_id=?",
            tuple(params),
        )
        conn.commit()
        return jsonify({"status": "ok"})


@course_pages_bp.route("/materials/<int:mid>/unpublish", methods=["POST"])
@login_required
@role_required("instructor", "head_of_department")
def api_materials_unpublish(mid: int):
    iid = _session_instructor_id()
    if not iid:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE course_published_materials
            SET is_published=0, updated_at=?
            WHERE id=? AND instructor_id=?
            """,
            (_now_iso(), int(mid), int(iid)),
        )
        conn.commit()
        return jsonify({"status": "ok"})


@course_pages_bp.route("/materials/<int:mid>/attach-recording", methods=["POST"])
@login_required
@role_required("instructor", "head_of_department")
def api_attach_recording(mid: int):
    """بعد محاضرة مباشرة: إرفاق تسجيل (ملف مكتبي أو رابط) وتحويل النوع لمسجّلة إن رُغب."""
    iid = _session_instructor_id()
    data = request.get_json(silent=True) or {}
    if not iid:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT * FROM course_published_materials WHERE id=? AND instructor_id=?",
            (int(mid), int(iid)),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        lib_id = data.get("library_file_id")
        url = (data.get("external_url") or "").strip()
        convert = bool(data.get("convert_to_recorded", True))
        sets = ["updated_at=?"]
        params: list[Any] = [_now_iso()]
        if lib_id:
            sets.append("library_file_id=?")
            params.append(int(lib_id))
        if url:
            sets.append("external_url=?")
            params.append(url)
        if convert:
            sets.append("material_type=?")
            params.append("lecture_recorded")
        params.extend([int(mid), int(iid)])
        cur.execute(
            f"UPDATE course_published_materials SET {', '.join(sets)} WHERE id=? AND instructor_id=?",
            tuple(params),
        )
        conn.commit()
        return jsonify({"status": "ok"})


@course_pages_bp.route("/materials/<int:mid>/file", methods=["GET"])
@login_required
def api_materials_file(mid: int):
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT * FROM course_published_materials WHERE id=?",
            (int(mid),),
        ).fetchone()
        d = _row_dict(row)
        if not d:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        role = (session.get("user_role") or "").strip()
        iid = _session_instructor_id()
        allowed = False
        if iid and int(d.get("instructor_id") or 0) == int(iid):
            allowed = True
        elif role == "student" and d.get("is_published"):
            sid = str(session.get("student_id") or "").strip()
            allowed = _student_enrolled(conn, sid, d.get("course_name") or "", d.get("teaching_group_id"))
        elif _is_hod_or_admin():
            allowed = True
        if not allowed:
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        lib_id = d.get("library_file_id")
        if not lib_id:
            return jsonify({"status": "error", "message": "لا يوجد ملف مرفوع — استخدم الرابط الخارجي"}), 404
        lib = cur.execute(
            "SELECT * FROM instructor_library_files WHERE id=?",
            (int(lib_id),),
        ).fetchone()
        ld = _row_dict(lib)
        stored = (ld.get("storage_path") or "").strip()
        if not stored:
            return jsonify({"status": "error", "message": "لا يوجد ملف"}), 404
        path = os.path.join(library_upload_dir(), os.path.basename(stored))
        if not os.path.isfile(path):
            return jsonify({"status": "error", "message": "الملف غير موجود"}), 404
        return send_file(
            path,
            as_attachment=True,
            download_name=ld.get("original_name") or os.path.basename(stored),
        )


# ─── Student ─────────────────────────────────────────────────────


@course_pages_bp.route("/student/my_courses", methods=["GET"])
@login_required
@role_required("student")
def api_student_my_courses():
    sid = str(session.get("student_id") or "").strip()
    if not sid:
        return jsonify({"status": "error", "message": "لا يوجد رقم طالب"}), 400
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        reg_cols = set(fetch_table_columns(conn, "registrations") or [])
        tg_sel = "r.teaching_group_id" if "teaching_group_id" in reg_cols else "NULL AS teaching_group_id"
        rows = cur.execute(
            f"""
            SELECT DISTINCT r.course_name, {tg_sel}
            FROM registrations r
            WHERE r.student_id = ?
            ORDER BY r.course_name
            """,
            (sid,),
        ).fetchall()
        items = []
        for r in rows or []:
            d = _row_dict(r)
            cn = d.get("course_name") or ""
            cat = _get_or_create_catalog(conn, cn)
            items.append(
                {
                    "course_name": cn,
                    "teaching_group_id": d.get("teaching_group_id"),
                    "has_objectives": (cat.get("objectives_status") == STATUS_LOCKED),
                    "has_outcomes": (cat.get("outcomes_status") == STATUS_LOCKED),
                    "has_topics": (cat.get("topics_status") == STATUS_LOCKED),
                    "page_url": "/my_course_page?"
                    + urlencode({"course_name": cn, "teaching_group_id": d.get("teaching_group_id") or ""}),
                }
            )
        return jsonify({"status": "ok", "items": items})


@course_pages_bp.route("/student/course", methods=["GET"])
@login_required
@role_required("student")
def api_student_course():
    sid = str(session.get("student_id") or "").strip()
    course_name = _normalize_course(request.args.get("course_name") or "")
    tgid = request.args.get("teaching_group_id", type=int)
    if not sid or not course_name:
        return jsonify({"status": "error", "message": "بيانات ناقصة"}), 400
    with get_connection() as conn:
        if not _student_enrolled(conn, sid, course_name, tgid):
            return jsonify({"status": "error", "message": "غير مسجّل في هذا المقرر"}), 403
        catalog = _get_or_create_catalog(conn, course_name)
        # section page: latest for this course/tg
        cur = conn.cursor()
        section = None
        if tgid:
            row = cur.execute(
                """
                SELECT * FROM course_section_pages
                WHERE teaching_group_id=? AND lower(trim(course_name))=lower(trim(?))
                ORDER BY updated_at DESC LIMIT 1
                """,
                (int(tgid), course_name),
            ).fetchone()
            section = _row_dict(row) if row else None
        if not section:
            row = cur.execute(
                """
                SELECT * FROM course_section_pages
                WHERE lower(trim(course_name))=lower(trim(?))
                ORDER BY updated_at DESC LIMIT 1
                """,
                (course_name,),
            ).fetchone()
            section = _row_dict(row) if row else None
        mats = cur.execute(
            """
            SELECT * FROM course_published_materials
            WHERE lower(trim(course_name))=lower(trim(?))
              AND COALESCE(is_published,1)=1
              AND (? IS NULL OR teaching_group_id = ? OR teaching_group_id IS NULL)
            ORDER BY
              CASE WHEN material_type='lecture_live' THEN 0 ELSE 1 END,
              COALESCE(week_no, 999), id DESC
            """,
            (course_name, tgid, tgid),
        ).fetchall()
        materials = [_serialize_material(_row_dict(m)) for m in mats or []]
        assessments = []
        if section:
            from backend.services.assessment_plan import (
                assessment_plan_to_methods,
                normalize_assessment_plan,
            )

            plan = normalize_assessment_plan(section.get("assessment_plan_json"))
            assessments = assessment_plan_to_methods(plan)
        elif tgid:
            # fallback: أحدث صفحة للشعبة
            row = cur.execute(
                """
                SELECT assessment_plan_json FROM course_section_pages
                WHERE teaching_group_id=? ORDER BY updated_at DESC LIMIT 1
                """,
                (int(tgid),),
            ).fetchone()
            if row:
                from backend.services.assessment_plan import (
                    assessment_plan_to_methods,
                    normalize_assessment_plan,
                )

                d = _row_dict(row)
                assessments = assessment_plan_to_methods(
                    normalize_assessment_plan(d.get("assessment_plan_json"))
                )
        # announcements if section_id known
        anns = []
        try:
            sec_id = section.get("section_id") if section else None
            if sec_id:
                arows = cur.execute(
                    """
                    SELECT id, title, body, announcement_type, lecture_date, created_at
                    FROM faculty_course_announcements
                    WHERE section_id=? AND COALESCE(published_to_students,1)=1
                    ORDER BY id DESC LIMIT 30
                    """,
                    (int(sec_id),),
                ).fetchall()
                anns = [_row_dict(a) for a in arows or []]
        except Exception:
            pass
        return jsonify(
            {
                "status": "ok",
                "catalog": catalog,
                "section": section
                or {
                    "assessment_text": catalog.get("assessment_template") or "",
                    "references_text": catalog.get("references_template") or "",
                },
                "assessment_methods": assessments,
                "materials": materials,
                "announcements": anns,
            }
        )


# ─── HOD board ───────────────────────────────────────────────────


@course_pages_bp.route("/hod/board", methods=["GET"])
@login_required
@role_required("head_of_department", "admin_main", "admin", "system_admin", "college_dean", "academic_vice_dean")
def api_hod_board():
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        # courses from teaching groups / catalog / baselines
        names: set[str] = set()
        if table_exists(conn, "teaching_groups"):
            for r in cur.execute(
                "SELECT DISTINCT course_name FROM teaching_groups WHERE COALESCE(is_active,1)=1"
            ).fetchall() or []:
                n = (r[0] if not hasattr(r, "keys") else r["course_name"]) or ""
                if n.strip():
                    names.add(n.strip())
        for r in cur.execute("SELECT course_name FROM course_catalog_pages").fetchall() or []:
            n = (r[0] if not hasattr(r, "keys") else r["course_name"]) or ""
            if n.strip():
                names.add(n.strip())
        uname = _username()
        scope = resolve_effective_department_scope_id(conn, uname)
        items = []
        for cn in sorted(names, key=lambda x: x.lower()):
            if scope is not None and not _is_hod_or_admin():
                pass
            try:
                if not hod_may_operate_on_course(conn, uname, cn) and session.get("user_role") == "head_of_department":
                    continue
            except Exception:
                if session.get("user_role") == "head_of_department":
                    continue
            cat = _get_or_create_catalog(conn, cn)
            fs = cat.get("field_status") or {}
            missing = [f for f in LOCKABLE_FIELDS if (fs.get(f) or STATUS_EMPTY) == STATUS_EMPTY]
            draft = [f for f in LOCKABLE_FIELDS if (fs.get(f) or "") == STATUS_DRAFT]
            locked = [f for f in LOCKABLE_FIELDS if (fs.get(f) or "") == STATUS_LOCKED]
            items.append(
                {
                    "course_name": cn,
                    "field_status": fs,
                    "missing": missing,
                    "draft": draft,
                    "locked": locked,
                    "completeness": round(100 * len(locked) / 3) if LOCKABLE_FIELDS else 0,
                }
            )
        pending = cur.execute(
            """
            SELECT * FROM course_content_change_requests
            WHERE status='pending'
            ORDER BY id DESC
            """
        ).fetchall()
        reqs = []
        for r in pending or []:
            d = _row_dict(r)
            d["proposed"] = _json_list(d.pop("proposed_json", None))
            try:
                if session.get("user_role") == "head_of_department" and not hod_may_operate_on_course(
                    conn, uname, d.get("course_name") or ""
                ):
                    continue
            except Exception:
                continue
            reqs.append(d)
        return jsonify({"status": "ok", "courses": items, "change_requests": reqs})


@course_pages_bp.route("/hod/change_requests/<int:rid>/review", methods=["POST"])
@login_required
@role_required("head_of_department", "admin_main", "admin", "system_admin", "college_dean", "academic_vice_dean")
def api_hod_review_request(rid: int):
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    if action not in ("approve", "reject"):
        return jsonify({"status": "error", "message": "action=approve|reject"}), 400
    with get_connection() as conn:
        ensure_course_pages_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT * FROM course_content_change_requests WHERE id=?",
            (int(rid),),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        d = _row_dict(row)
        if d.get("status") != "pending":
            return jsonify({"status": "error", "message": "الطلب ليس معلقاً"}), 400
        cn = d.get("course_name") or ""
        try:
            assert_hod_for_course_operation(conn, _username(), cn)
        except Exception as exc:
            if session.get("user_role") == "head_of_department":
                return jsonify({"status": "error", "message": str(exc)}), 403
        note = (data.get("review_note") or "").strip()
        if action == "approve":
            catalog = _get_or_create_catalog(conn, cn)
            field = d.get("field_name")
            items = _json_list(d.get("proposed_json"))
            # force HOD save on locked field
            try:
                _apply_field_save(conn, catalog, field, items, finalize=True)
            except PermissionError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 403
        cur.execute(
            """
            UPDATE course_content_change_requests
            SET status=?, reviewed_by=?, reviewed_at=?, review_note=?
            WHERE id=?
            """,
            (
                "approved" if action == "approve" else "rejected",
                _username(),
                _now_iso(),
                note,
                int(rid),
            ),
        )
        conn.commit()
        try:
            from backend.services.course_workflow import notify_instructor

            notify_instructor(
                conn,
                d.get("requested_by_instructor_id"),
                title=f"{'اعتُمد' if action == 'approve' else 'رُفض'} طلب تعديل {d.get('field_name')} — {cn}",
                body=note or "",
            )
        except Exception:
            pass
        return jsonify({"status": "ok"})


@course_pages_bp.route("/meta", methods=["GET"])
@login_required
def api_meta():
    return jsonify(
        {
            "status": "ok",
            "lockable_fields": list(LOCKABLE_FIELDS),
            "material_types": sorted(MATERIAL_TYPES),
            "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
            "max_file_bytes": MAX_FILE_BYTES,
        }
    )
