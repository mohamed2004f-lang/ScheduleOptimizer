"""خدمة منصة الاستبيانات متعددة الفئات."""

from __future__ import annotations

import datetime
import logging
from typing import Any

from backend.core.survey_platform import (
    ALUMNI_V2_MARKER_PREFIX,
    QUESTION_SEED,
    SURVEY_QUESTIONS_TARGET_COUNT,
    SURVEY_TEMPLATE_SEED,
)
from backend.database.database import is_postgresql, table_exists
from backend.services.evaluation_survey import likert_labels_ar
from backend.services.quality_metrics import term_label_from_conn
from backend.services.survey_eligibility import (
    FACULTY_EXTERNAL_COLLABORATOR_TEMPLATE,
    is_instructor_template_required,
)

logger = logging.getLogger(__name__)

_SURVEY_CUSTOMIZED_KEY_PREFIX = "survey_questions_customized:"
_SURVEY_MIGRATION_ALUMNI_V2 = "survey_migration_alumni_v2"
_SURVEY_MIGRATION_FACULTY_DEAN_DROP = "survey_migration_faculty_dean_drop_resources_v1"


def _survey_customized_setting_key(template_code: str) -> str:
    return f"{_SURVEY_CUSTOMIZED_KEY_PREFIX}{(template_code or '').strip()}"


def _setting_value(conn, key: str) -> str:
    if not table_exists(conn, "system_settings"):
        return ""
    row = conn.cursor().execute(
        "SELECT value FROM system_settings WHERE key = ? LIMIT 1",
        (key.strip(),),
    ).fetchone()
    if not row:
        return ""
    return str((row[0] if not hasattr(row, "keys") else row["value"]) or "").strip()


def _set_setting_value(conn, key: str, value: str) -> None:
    if not table_exists(conn, "system_settings"):
        return
    cur = conn.cursor()
    cur.execute("DELETE FROM system_settings WHERE key = ?", (key.strip(),))
    cur.execute(
        "INSERT INTO system_settings (key, value) VALUES (?, ?)",
        (key.strip(), (value or "").strip()),
    )


def _is_survey_questions_customized(conn, template_code: str) -> bool:
    return _setting_value(conn, _survey_customized_setting_key(template_code)) == "1"


def _mark_survey_questions_customized(conn, template_code: str) -> None:
    code = (template_code or "").strip()
    if not code:
        return
    _set_setting_value(conn, _survey_customized_setting_key(code), "1")
    conn.commit()


def _migration_done(conn, key: str) -> bool:
    return _setting_value(conn, key) == "1"


def _set_migration_done(conn, key: str) -> None:
    _set_setting_value(conn, key, "1")
    conn.commit()


def _run_survey_platform_migrations(conn) -> None:
    """ترحيلات لمرة واحدة — لا تُعاد عند كل طلب."""
    if not _migration_done(conn, _SURVEY_MIGRATION_FACULTY_DEAN_DROP):
        _migrate_faculty_dean_drop_internal_resources(conn)
        _set_migration_done(conn, _SURVEY_MIGRATION_FACULTY_DEAN_DROP)
    if not _migration_done(conn, _SURVEY_MIGRATION_ALUMNI_V2):
        if not _is_survey_questions_customized(conn, "alumni"):
            _migrate_alumni_survey_v2(conn)
        _set_migration_done(conn, _SURVEY_MIGRATION_ALUMNI_V2)


def _row_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return dict(row)
    return {}


def ensure_survey_platform_tables(conn) -> None:
    """يُستدعى عبر ensure_tables في database.py — هنا للتأكد من البذر."""
    if not table_exists(conn, "survey_templates"):
        return
    from backend.services.survey_snapshots import ensure_survey_snapshot_tables

    ensure_survey_snapshot_tables(conn)
    from backend.services.survey_invites import ensure_survey_invite_schema

    ensure_survey_invite_schema(conn)
    ensure_survey_templates_seeded(conn)


def _sync_template_titles_from_seed(conn) -> None:
    """مزامنة عنوان القالب من البذرة عند تغيير التسمية (مثل faculty_dean)."""
    if not table_exists(conn, "survey_templates"):
        return
    cur = conn.cursor()
    now = datetime.datetime.utcnow().isoformat()
    updated = False
    for t in SURVEY_TEMPLATE_SEED:
        code = t["code"]
        title = (t.get("title_ar") or "").strip()
        if not code or not title:
            continue
        row = cur.execute(
            "SELECT id, title_ar FROM survey_templates WHERE code = ? LIMIT 1",
            (code,),
        ).fetchone()
        if not row:
            continue
        current = ((row[1] if not hasattr(row, "keys") else row["title_ar"]) or "").strip()
        if current == title:
            continue
        tid = int(row[0] if not hasattr(row, "keys") else row["id"])
        cur.execute(
            "UPDATE survey_templates SET title_ar = ?, updated_at = ? WHERE id = ?",
            (title, now, tid),
        )
        updated = True
    if updated:
        conn.commit()
        logger.info("Synced survey template titles from seed")


def _migrate_alumni_survey_v2(conn) -> None:
    """ترقية استبيان الخريج إلى نسخة مراجعة البرنامج (١٠ بنود Likert) مع الإبقاء على الردود القديمة."""
    if not table_exists(conn, "survey_questions"):
        return
    cur = conn.cursor()
    tid = _template_id_by_code(cur, "alumni")
    if not tid:
        return
    row = cur.execute(
        """
        SELECT label_ar FROM survey_questions
        WHERE template_id = ? AND is_active = 1 AND sort_order = 10
        LIMIT 1
        """,
        (tid,),
    ).fetchone()
    active_row = cur.execute(
        "SELECT COUNT(*) FROM survey_questions WHERE template_id = ? AND is_active = 1",
        (tid,),
    ).fetchone()
    active_count = int((active_row[0] if active_row else 0) or 0)
    if row and active_count >= 10:
        label = ((row[0] if not hasattr(row, "keys") else row["label_ar"]) or "").strip()
        if label.startswith(ALUMNI_V2_MARKER_PREFIX):
            return
    items = QUESTION_SEED.get("alumni") or []
    if len(items) < 10:
        return
    now = datetime.datetime.utcnow().isoformat()
    cur.execute(
        "UPDATE survey_questions SET is_active = 0, updated_at = ? WHERE template_id = ?",
        (now, tid),
    )
    for label, sort_order in items:
        cur.execute(
            """
            INSERT INTO survey_questions
                (template_id, label_ar, sort_order, question_type, is_active, created_at, updated_at)
            VALUES (?,?,?,?,1,?,?)
            """,
            (tid, label.strip(), int(sort_order), "likert_5", now, now),
        )
    conn.commit()
    logger.info("alumni: migrated to program-review survey v2 (%s active items)", len(items))


def _migrate_faculty_dean_drop_internal_resources(conn) -> None:
    """
    حذف بند «توزيع الموارد/موارد الكلية الداخلية» (sort 20 القديم) وإجاباته،
    والإبقاء على بند «متابعة احتياجات الأقسام لدى الجامعة» في sort 20.
    """
    if not table_exists(conn, "survey_questions") or not table_exists(conn, "survey_answers"):
        return
    internal_markers = (
        "توزيع موارد الكلية الداخلية",
        "توزيع الموارد (ميزانيات",
    )
    seed_label_20 = next(
        (lbl.strip() for lbl, so in (QUESTION_SEED.get("faculty_dean") or []) if int(so) == 20),
        "",
    )
    if not seed_label_20:
        return
    cur = conn.cursor()
    tid = _template_id_by_code(cur, "faculty_dean")
    if not tid:
        return
    now = datetime.datetime.utcnow().isoformat()
    rows = cur.execute(
        """
        SELECT id, label_ar, sort_order
        FROM survey_questions
        WHERE template_id = ?
        ORDER BY sort_order, id
        """,
        (tid,),
    ).fetchall()
    if not rows:
        return

    follow_up_id: int | None = None
    for row in rows:
        qid = int(row[0] if not hasattr(row, "keys") else row["id"])
        label = ((row[1] if not hasattr(row, "keys") else row["label_ar"]) or "").strip()
        sort_order = int(row[2] if not hasattr(row, "keys") else row["sort_order"])
        if "تتابع احتياجات الأقسام" in label and sort_order == 25:
            follow_up_id = qid
    if follow_up_id is None:
        for row in rows:
            qid = int(row[0] if not hasattr(row, "keys") else row["id"])
            label = ((row[1] if not hasattr(row, "keys") else row["label_ar"]) or "").strip()
            if "تتابع احتياجات الأقسام" in label:
                follow_up_id = qid

    changed = False
    for row in rows:
        qid = int(row[0] if not hasattr(row, "keys") else row["id"])
        if follow_up_id is not None and qid == follow_up_id:
            continue
        label = ((row[1] if not hasattr(row, "keys") else row["label_ar"]) or "").strip()
        sort_order = int(row[2] if not hasattr(row, "keys") else row["sort_order"])
        drop = False
        if any(marker in label for marker in internal_markers):
            drop = True
        elif sort_order == 25:
            drop = True
        elif sort_order == 20 and (
            "تتابع احتياجات الأقسام" in label
            or any(marker in label for marker in internal_markers)
        ):
            drop = True
        if not drop:
            continue
        cur.execute("DELETE FROM survey_answers WHERE question_id = ?", (qid,))
        cur.execute("DELETE FROM survey_questions WHERE id = ?", (qid,))
        changed = True

    if follow_up_id is not None:
        cur.execute(
            """
            UPDATE survey_questions
            SET sort_order = 20, label_ar = ?, is_active = 1, updated_at = ?
            WHERE id = ?
            """,
            (seed_label_20, now, follow_up_id),
        )
        changed = True
    else:
        row20 = cur.execute(
            "SELECT id FROM survey_questions WHERE template_id = ? AND sort_order = ? LIMIT 1",
            (tid, 20),
        ).fetchone()
        if not row20:
            cur.execute(
                """
                INSERT INTO survey_questions
                    (template_id, label_ar, sort_order, question_type, is_active, created_at, updated_at)
                VALUES (?,?,?,?,1,?,?)
                """,
                (tid, seed_label_20, 20, "likert_5", now, now),
            )
            changed = True

    if changed:
        conn.commit()
        logger.info("faculty_dean: dropped internal-resources item; follow-up at sort 20")


def ensure_survey_templates_seeded(conn) -> None:
    if not table_exists(conn, "survey_templates"):
        return
    cur = conn.cursor()
    n = cur.execute("SELECT COUNT(*) FROM survey_templates").fetchone()
    if int((n[0] if n else 0) or 0) > 0:
        _ensure_missing_templates_from_seed(conn)
        _sync_template_titles_from_seed(conn)
        _run_survey_platform_migrations(conn)
        return
    now = datetime.datetime.utcnow().isoformat()
    for t in SURVEY_TEMPLATE_SEED:
        cur.execute(
            """
            INSERT INTO survey_templates (
                code, title_ar, respondent_role, subject_type,
                is_anonymous, min_aggregate, department_scoped,
                legacy_course_eval, is_active, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,1,?,?)
            """,
            (
                t["code"],
                t["title_ar"],
                t["respondent_role"],
                t["subject_type"],
                int(t.get("is_anonymous", 1)),
                int(t.get("min_aggregate", 3)),
                int(t.get("department_scoped", 0)),
                int(t.get("legacy_course_eval", 0)),
                now,
                now,
            ),
        )
    conn.commit()
    _seed_questions_for_templates(conn)
    _upgrade_platform_questions_from_seed(conn)
    _run_survey_platform_migrations(conn)
    logger.info("Seeded %s survey templates", len(SURVEY_TEMPLATE_SEED))


def _ensure_missing_templates_from_seed(conn) -> None:
    """إضافة قوالب جديدة (مثل استبيانات المشرف) دون مسح القوالب الحالية."""
    if not table_exists(conn, "survey_templates"):
        return
    cur = conn.cursor()
    now = datetime.datetime.utcnow().isoformat()
    added = False
    for t in SURVEY_TEMPLATE_SEED:
        if _template_id_by_code(cur, t["code"]):
            continue
        cur.execute(
            """
            INSERT INTO survey_templates (
                code, title_ar, respondent_role, subject_type,
                is_anonymous, min_aggregate, department_scoped,
                legacy_course_eval, is_active, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,1,?,?)
            """,
            (
                t["code"],
                t["title_ar"],
                t["respondent_role"],
                t["subject_type"],
                int(t.get("is_anonymous", 1)),
                int(t.get("min_aggregate", 3)),
                int(t.get("department_scoped", 0)),
                int(t.get("legacy_course_eval", 0)),
                now,
                now,
            ),
        )
        added = True
    if added:
        conn.commit()
        logger.info("Added missing survey templates from seed")
        _seed_questions_for_templates(conn)
    _upgrade_platform_questions_from_seed(conn)


def _seed_questions_for_templates(conn) -> None:
    cur = conn.cursor()
    for code, items in QUESTION_SEED.items():
        tid = _template_id_by_code(cur, code)
        if not tid:
            continue
        existing = cur.execute(
            "SELECT COUNT(*) FROM survey_questions WHERE template_id = ?",
            (tid,),
        ).fetchone()
        if int((existing[0] if existing else 0) or 0) > 0:
            continue
        now = datetime.datetime.utcnow().isoformat()
        for label, sort_order in items:
            cur.execute(
                """
                INSERT INTO survey_questions
                    (template_id, label_ar, sort_order, question_type, is_active, created_at, updated_at)
                VALUES (?,?,?,?,1,?,?)
                """,
                (tid, label, sort_order, "likert_5", now, now),
            )
    conn.commit()


def _upgrade_platform_questions_from_seed(conn) -> None:
    """إضافة بنود أكاديمية ناقصة حتى 10 لكل قالب (لا يحذف البنود الحالية)."""
    cur = conn.cursor()
    now = datetime.datetime.utcnow().isoformat()
    total_added = 0
    for code, items in QUESTION_SEED.items():
        if _is_survey_questions_customized(conn, code):
            continue
        tid = _template_id_by_code(cur, code)
        if not tid:
            continue
        rows = cur.execute(
            "SELECT label_ar FROM survey_questions WHERE template_id = ?",
            (tid,),
        ).fetchall()
        if len(rows) >= SURVEY_QUESTIONS_TARGET_COUNT:
            continue
        existing_labels = {
            ((r[0] if not hasattr(r, "keys") else r["label_ar"]) or "").strip() for r in rows
        }
        max_sort_row = cur.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM survey_questions WHERE template_id = ?",
            (tid,),
        ).fetchone()
        sort_order = int((max_sort_row[0] if max_sort_row else 0) or 0)
        for label, seed_sort in items:
            label = label.strip()
            if label in existing_labels:
                continue
            sort_order = max(sort_order + 10, seed_sort)
            cur.execute(
                """
                INSERT INTO survey_questions
                    (template_id, label_ar, sort_order, question_type, is_active, created_at, updated_at)
                VALUES (?,?,?,?,1,?,?)
                """,
                (tid, label, sort_order, "likert_5", now, now),
            )
            existing_labels.add(label)
            total_added += 1
            if len(existing_labels) >= SURVEY_QUESTIONS_TARGET_COUNT:
                break
    if total_added:
        conn.commit()
        logger.info("Upgraded platform survey questions: added %s items", total_added)


def _template_id_by_code(cur, code: str) -> int | None:
    row = cur.execute(
        "SELECT id FROM survey_templates WHERE code = ? LIMIT 1",
        (code.strip(),),
    ).fetchone()
    if not row:
        return None
    return int(row[0] if not hasattr(row, "keys") else row["id"])


def list_templates(conn, *, active_only: bool = True) -> list[dict]:
    ensure_survey_templates_seeded(conn)
    cur = conn.cursor()
    sql = """
        SELECT id, code, title_ar, respondent_role, subject_type,
               is_anonymous, min_aggregate, department_scoped,
               legacy_course_eval, is_active
        FROM survey_templates
    """
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY respondent_role, code"
    return [_row_dict(r) for r in cur.execute(sql).fetchall()]


def get_template_by_code(conn, code: str) -> dict | None:
    ensure_survey_templates_seeded(conn)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id, code, title_ar, respondent_role, subject_type,
               is_anonymous, min_aggregate, department_scoped, legacy_course_eval
        FROM survey_templates WHERE code = ? AND is_active = 1 LIMIT 1
        """,
        (code.strip(),),
    ).fetchone()
    return _row_dict(row) if row else None


def list_template_questions(conn, template_id: int, *, active_only: bool = True) -> list[dict]:
    cur = conn.cursor()
    sql = """
        SELECT id, template_id, label_ar, sort_order, question_type, is_active
        FROM survey_questions WHERE template_id = ?
    """
    params: list[Any] = [int(template_id)]
    if active_only:
        sql += " AND is_active = 1"
    sql += " ORDER BY sort_order, id"
    return [_row_dict(r) for r in cur.execute(sql, tuple(params)).fetchall()]


def _respondent_key(role: str, session_data: dict) -> tuple[str, str]:
    role = (role or "").strip()
    if role == "student":
        sid = (session_data.get("student_id") or session_data.get("user") or "").strip()
        return role, sid
    if role in ("instructor", "head_of_department", "supervisor"):
        iid = session_data.get("instructor_id")
        if iid is not None:
            return role, str(int(iid))
        return role, (session_data.get("user") or "").strip()
    if role == "staff":
        return role, (session_data.get("user") or "").strip()
    return role, (session_data.get("user") or "").strip()


def _resolve_subject(
    conn,
    template: dict,
    *,
    department_id: int | None,
    subject_id_arg: int | None,
) -> tuple[str, int]:
    st = (template.get("subject_type") or "").strip()
    if st in (
        "department_head",
        "educational_process",
        "supervision",
        "supervision_coordination",
    ):
        dept = int(department_id or subject_id_arg or 0)
        return st, dept
    if st == "external_teaching":
        return st, int(subject_id_arg or 0)
    if st == "dean":
        return st, 0
    if st in ("student_services", "facilities", "workplace"):
        return st, 0
    return st, int(subject_id_arg or 0)


def has_submitted(
    conn,
    *,
    template_code: str,
    semester: str,
    respondent_role: str,
    respondent_id: str,
    subject_type: str,
    subject_id: int,
) -> bool:
    if not table_exists(conn, "survey_responses"):
        return False
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT 1 FROM survey_responses
        WHERE template_code = ? AND semester = ?
          AND respondent_role = ? AND respondent_id = ?
          AND subject_type = ? AND subject_id = ?
          AND status = 'submitted'
        LIMIT 1
        """,
        (
            template_code,
            semester,
            respondent_role,
            respondent_id,
            subject_type,
            int(subject_id),
        ),
    ).fetchone()
    return row is not None


def survey_respondent_role(user_role: str, active_mode: str | None = None) -> str:
    """دور المُقيِّم في الاستبيان — يعتمد على الدور في الجلسة ووضع الشريط (active_mode)."""
    r = (user_role or "").strip()
    am = (active_mode or "").strip().lower()
    if r == "supervisor":
        return "supervisor"
    if r == "head_of_department":
        if am == "supervisor":
            return "supervisor"
        return "instructor"
    if r == "college_dean":
        if am == "supervisor":
            return "supervisor"
        return "instructor"
    if r == "academic_vice_dean":
        if am == "supervisor":
            return "supervisor"
        return "instructor"
    if r == "instructor" and am == "supervisor":
        return "supervisor"
    return r


def list_pending_for_respondent_role(
    conn,
    *,
    respondent_role: str,
    session_data: dict,
    semester: str | None = None,
    department_id: int | None = None,
) -> list[dict]:
    """استبيانات معلّقة لدور مُقيِّم محدد (instructor / supervisor / staff …)."""
    ensure_survey_templates_seeded(conn)
    sem = (semester or "").strip() or term_label_from_conn(conn)
    resp_role = (respondent_role or "").strip()
    resp_role, resp_id = _respondent_key(resp_role, session_data)
    if not resp_id:
        return []

    templates = [
        t
        for t in list_templates(conn)
        if t.get("respondent_role") == resp_role and not int(t.get("legacy_course_eval") or 0)
    ]
    pending: list[dict] = []
    instructor_id: int | None = None
    if resp_role == "instructor":
        try:
            instructor_id = int(resp_id)
        except (TypeError, ValueError):
            instructor_id = None
    for t in templates:
        if int(t.get("department_scoped") or 0) and department_id is None and resp_role in (
            "instructor",
            "supervisor",
        ):
            continue
        if instructor_id is not None and not is_instructor_template_required(
            conn,
            template_code=str(t.get("code") or ""),
            instructor_id=instructor_id,
            department_id=department_id,
        ):
            continue
        subj_type, subj_id = _resolve_subject(
            conn, t, department_id=department_id, subject_id_arg=department_id
        )
        if (t.get("code") or "").strip() == FACULTY_EXTERNAL_COLLABORATOR_TEMPLATE and instructor_id:
            subj_type, subj_id = "external_teaching", int(instructor_id)
        if has_submitted(
            conn,
            template_code=t["code"],
            semester=sem,
            respondent_role=resp_role,
            respondent_id=resp_id,
            subject_type=subj_type,
            subject_id=subj_id,
        ):
            continue
        pending.append(
            {
                **t,
                "semester": sem,
                "subject_type": subj_type,
                "subject_id": subj_id,
                "fill_url": f"/academic_quality/surveys/fill/{t['code']}",
            }
        )
    return pending


def list_pending_for_user(
    conn,
    *,
    user_role: str,
    session_data: dict,
    semester: str | None = None,
    department_id: int | None = None,
    active_mode: str | None = None,
) -> list[dict]:
    """استبيانات مطلوبة من المستخدم (غير المكتملة وغير المسار القديم للمقرر)."""
    resp_role = survey_respondent_role(user_role, active_mode)
    return list_pending_for_respondent_role(
        conn,
        respondent_role=resp_role,
        session_data=session_data,
        semester=semester,
        department_id=department_id,
    )


def submit_survey_response(
    conn,
    *,
    template_code: str,
    semester: str,
    respondent_role: str,
    respondent_id: str,
    subject_type: str,
    subject_id: int,
    department_id: int | None,
    answers: dict[int, int],
    comments: str = "",
    submitted_by: str = "",
) -> int:
    template = get_template_by_code(conn, template_code)
    if not template:
        raise ValueError("قالب الاستبيان غير موجود")
    tid = int(template["id"])
    questions = list_template_questions(conn, tid)
    if not questions:
        raise ValueError("لا توجد بنود نشطة لهذا الاستبيان")
    parsed: dict[int, int] = {}
    for q in questions:
        qid = int(q["id"])
        rating = answers.get(qid)
        if rating is None:
            raise ValueError(f"يرجى الإجابة على: {q.get('label_ar', '')}")
        r = int(rating)
        if not 1 <= r <= 5:
            raise ValueError("التقييم يجب أن يكون بين 1 و 5")
        parsed[qid] = r

    if has_submitted(
        conn,
        template_code=template_code,
        semester=semester,
        respondent_role=respondent_role,
        respondent_id=respondent_id,
        subject_type=subject_type,
        subject_id=int(subject_id),
    ):
        raise ValueError("تم إرسال هذا الاستبيان مسبقاً لهذا الفصل")

    now = datetime.datetime.utcnow().isoformat()
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO survey_responses (
                template_id, template_code, semester,
                respondent_role, respondent_id,
                subject_type, subject_id, department_id,
                comments, status, submitted_by, created_at, submitted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,'submitted',?,?,?)
            RETURNING id
            """,
            (
                tid,
                template_code,
                semester,
                respondent_role,
                respondent_id,
                subject_type,
                int(subject_id),
                department_id,
                (comments or "").strip(),
                submitted_by,
                now,
                now,
            ),
        )
        rid = int(cur.fetchone()[0])
    else:
        cur.execute(
            """
            INSERT INTO survey_responses (
                template_id, template_code, semester,
                respondent_role, respondent_id,
                subject_type, subject_id, department_id,
                comments, status, submitted_by, created_at, submitted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,'submitted',?,?,?)
            """,
            (
                tid,
                template_code,
                semester,
                respondent_role,
                respondent_id,
                subject_type,
                int(subject_id),
                department_id,
                (comments or "").strip(),
                submitted_by,
                now,
                now,
            ),
        )
        rid = int(cur.lastrowid or 0)

    for qid, rating in parsed.items():
        cur.execute(
            """
            INSERT INTO survey_answers (response_id, question_id, rating)
            VALUES (?, ?, ?)
            """,
            (rid, int(qid), int(rating)),
        )
    return rid


def parse_answers_payload(data: dict, questions: list[dict]) -> dict[int, int]:
    raw = data.get("answers")
    parsed: dict[int, int] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                r = int(v)
                if 1 <= r <= 5:
                    parsed[int(k)] = r
            except (TypeError, ValueError):
                pass
    for q in questions:
        qid = int(q["id"])
        if qid in parsed:
            continue
        val = data.get(f"q_{qid}", data.get(str(qid)))
        try:
            r = int(val)
            if 1 <= r <= 5:
                parsed[qid] = r
        except (TypeError, ValueError):
            pass
    missing = [q for q in questions if int(q["id"]) not in parsed]
    if missing:
        labels = "، ".join((m.get("label_ar") or "")[:40] for m in missing[:3])
        raise ValueError(f"يرجى الإجابة على جميع البنود ({labels})")
    return parsed


def aggregate_template(
    conn,
    template_code: str,
    *,
    semester: str | None = None,
    department_id: int | None = None,
) -> dict:
    """تجميع نتائج استبيان (مع إخفاء التفاصيل إن لم يبلغ الحد الأدنى)."""
    template = get_template_by_code(conn, template_code)
    if not template:
        return {"status": "error", "message": "غير موجود"}
    sem = (semester or "").strip() or term_label_from_conn(conn)
    min_n = int(template.get("min_aggregate") or 3)
    cur = conn.cursor()
    dept_sql = ""
    dept_params: list[Any] = []
    if department_id is not None and int(template.get("department_scoped") or 0):
        dept_sql = " AND (r.department_id = ? OR r.subject_id = ?)"
        dept_params = [int(department_id), int(department_id)]

    count_row = cur.execute(
        f"""
        SELECT COUNT(*) FROM survey_responses r
        WHERE r.template_code = ? AND r.semester = ? AND r.status = 'submitted'
        {dept_sql}
        """,
        tuple([template_code, sem] + dept_params),
    ).fetchone()
    count = int((count_row[0] if count_row else 0) or 0)

    questions = list_template_questions(conn, int(template["id"]))
    per_question: list[dict] = []
    overall_vals: list[float] = []

    if count >= min_n:
        for q in questions:
            qid = int(q["id"])
            avg_row = cur.execute(
                f"""
                SELECT AVG(a.rating * 1.0)
                FROM survey_answers a
                JOIN survey_responses r ON r.id = a.response_id
                WHERE r.template_code = ? AND r.semester = ? AND r.status = 'submitted'
                  AND a.question_id = ? {dept_sql}
                """,
                tuple([template_code, sem, qid] + dept_params),
            ).fetchone()
            avg5 = float((avg_row[0] if avg_row else 0) or 0)
            pct = round((avg5 / 5.0) * 100.0, 1) if avg5 else 0.0
            if avg5:
                overall_vals.append(avg5)
            per_question.append(
                {
                    "question_id": qid,
                    "sort_order": int(q.get("sort_order") or 0),
                    "label_ar": q.get("label_ar"),
                    "avg_rating": round(avg5, 2) if avg5 else None,
                    "score_percent": pct,
                }
            )
    overall_pct = None
    if overall_vals:
        overall_pct = round((sum(overall_vals) / len(overall_vals) / 5.0) * 100.0, 1)

    return {
        "template_code": template_code,
        "title_ar": template.get("title_ar"),
        "semester": sem,
        "response_count": count,
        "min_aggregate": min_n,
        "aggregated": count >= min_n,
        "overall_score_percent": overall_pct,
        "questions": per_question,
        "likert_labels": likert_labels_ar(),
    }


def survey_metrics_from_aggregates(aggregates_by_code: dict[str, dict]) -> dict:
    """مؤشرات الجودة من تجميعات محسوبة مسبقاً (بدون إعادة aggregate_template)."""
    codes = [
        "student_services",
        "student_facilities",
        "faculty_hod",
        "faculty_dean",
        "faculty_educational_process",
        "supervisor_advising",
        "supervisor_coordination",
        "staff_workplace",
        "staff_student_services",
    ]
    out: dict[str, Any] = {}
    for code in codes:
        agg = aggregates_by_code.get(code) or {}
        out[code] = {
            "score_percent": agg.get("overall_score_percent"),
            "response_count": agg.get("response_count"),
            "aggregated": agg.get("aggregated"),
        }
    return out


def survey_metrics_for_quality(conn, semester: str, department_id: int | None = None) -> dict:
    """مؤشرات و-5 لدمجها في لوحة الجودة والاعتماد."""
    codes = [
        "student_services",
        "student_facilities",
        "faculty_hod",
        "faculty_dean",
        "faculty_educational_process",
        "supervisor_advising",
        "supervisor_coordination",
        "staff_workplace",
        "staff_student_services",
    ]
    out: dict[str, Any] = {}
    for code in codes:
        agg = aggregate_template(conn, code, semester=semester, department_id=department_id)
        out[code] = {
            "score_percent": agg.get("overall_score_percent"),
            "response_count": agg.get("response_count"),
            "aggregated": agg.get("aggregated"),
        }
    return out


def list_questions_admin(conn, template_code: str | None = None) -> list[dict]:
    ensure_survey_templates_seeded(conn)
    cur = conn.cursor()
    if template_code:
        tid = _template_id_by_code(cur, template_code)
        if not tid:
            return []
        return list_template_questions(conn, tid, active_only=False)
    rows = cur.execute(
        """
        SELECT q.id, q.template_id, t.code AS template_code, t.title_ar AS template_title,
               q.label_ar, q.sort_order, q.is_active
        FROM survey_questions q
        JOIN survey_templates t ON t.id = q.template_id
        ORDER BY t.code, q.sort_order
        """
    ).fetchall()
    return [_row_dict(r) for r in rows]


def _template_row(conn, template_code: str) -> dict | None:
    ensure_survey_templates_seeded(conn)
    return get_template_by_code(conn, template_code)


def is_legacy_course_template(template: dict | None) -> bool:
    return bool(template and int(template.get("legacy_course_eval") or 0))


def list_admin_questions(conn, template_code: str) -> list[dict]:
    """بنود استبيان للإدارة — يدعم تقييم المقرر (جدول قديم) وباقي القوالب."""
    from backend.services.evaluation_survey import list_survey_questions

    tpl = _template_row(conn, template_code)
    if not tpl:
        raise ValueError("قالب الاستبيان غير موجود")
    if is_legacy_course_template(tpl):
        return list_survey_questions(conn, active_only=False)
    tid = int(tpl["id"])
    qs = list_template_questions(conn, tid, active_only=False)
    for q in qs:
        q["legacy_key"] = ""
    return qs


def _platform_question_by_id(conn, question_id: int) -> dict | None:
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT q.id, q.template_id, t.code AS template_code, q.label_ar, q.sort_order,
               q.is_active, q.question_type
        FROM survey_questions q
        JOIN survey_templates t ON t.id = q.template_id
        WHERE q.id = ? LIMIT 1
        """,
        (int(question_id),),
    ).fetchone()
    return _row_dict(row) if row else None


def _next_platform_sort_order(cur, template_id: int) -> int:
    row = cur.execute(
        "SELECT COALESCE(MAX(sort_order), 0) FROM survey_questions WHERE template_id = ?",
        (int(template_id),),
    ).fetchone()
    return int((row[0] if row else 0) or 0) + 10


def create_admin_question(conn, template_code: str, label_ar: str) -> dict:
    from backend.services.evaluation_survey import create_survey_question

    tpl = _template_row(conn, template_code)
    if not tpl:
        raise ValueError("قالب الاستبيان غير موجود")
    if is_legacy_course_template(tpl):
        q = create_survey_question(conn, label_ar)
        _mark_survey_questions_customized(conn, template_code)
        return q
    label = (label_ar or "").strip()
    if not label:
        raise ValueError("نص البند مطلوب")
    tid = int(tpl["id"])
    now = datetime.datetime.utcnow().isoformat()
    sort_order = _next_platform_sort_order(conn.cursor(), tid)
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO survey_questions
                (template_id, label_ar, sort_order, question_type, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 'likert_5', 1, ?, ?)
            RETURNING id
            """,
            (tid, label, sort_order, now, now),
        )
        qid = int(cur.fetchone()[0])
    else:
        cur.execute(
            """
            INSERT INTO survey_questions
                (template_id, label_ar, sort_order, question_type, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 'likert_5', 1, ?, ?)
            """,
            (tid, label, sort_order, now, now),
        )
        qid = int(cur.lastrowid or 0)
    conn.commit()
    _mark_survey_questions_customized(conn, template_code)
    return _platform_question_by_id(conn, qid) or {"id": qid, "label_ar": label}


def update_admin_question(
    conn,
    template_code: str,
    question_id: int,
    *,
    label_ar: str | None = None,
    is_active: int | None = None,
) -> dict | None:
    from backend.services.evaluation_survey import update_survey_question

    tpl = _template_row(conn, template_code)
    if not tpl:
        raise ValueError("قالب الاستبيان غير موجود")
    if is_legacy_course_template(tpl):
        result = update_survey_question(conn, question_id, label_ar=label_ar, is_active=is_active)
        if result is not None:
            _mark_survey_questions_customized(conn, template_code)
        return result
    q = _platform_question_by_id(conn, question_id)
    if not q or (q.get("template_code") or "").strip() != template_code.strip():
        return None
    label = (label_ar if label_ar is not None else q.get("label_ar") or "").strip()
    if not label:
        raise ValueError("نص البند مطلوب")
    active = int(is_active) if is_active is not None else int(q.get("is_active") or 0)
    if active not in (0, 1):
        active = 1
    now = datetime.datetime.utcnow().isoformat()
    conn.cursor().execute(
        """
        UPDATE survey_questions SET label_ar = ?, is_active = ?, updated_at = ? WHERE id = ?
        """,
        (label, active, now, int(question_id)),
    )
    conn.commit()
    _mark_survey_questions_customized(conn, template_code)
    return _platform_question_by_id(conn, question_id)


def reorder_admin_questions(conn, template_code: str, ordered_ids: list[int]) -> list[dict]:
    from backend.services.evaluation_survey import reorder_survey_questions

    tpl = _template_row(conn, template_code)
    if not tpl:
        raise ValueError("قالب الاستبيان غير موجود")
    if is_legacy_course_template(tpl):
        result = reorder_survey_questions(conn, ordered_ids)
        _mark_survey_questions_customized(conn, template_code)
        return result
    ids = [int(x) for x in ordered_ids if int(x) > 0]
    if not ids:
        raise ValueError("قائمة الترتيب فارغة")
    cur = conn.cursor()
    now = datetime.datetime.utcnow().isoformat()
    order_val = 10
    for qid in ids:
        cur.execute(
            "UPDATE survey_questions SET sort_order = ?, updated_at = ? WHERE id = ? AND template_id = ?",
            (order_val, now, qid, int(tpl["id"])),
        )
        order_val += 10
    conn.commit()
    _mark_survey_questions_customized(conn, template_code)
    return list_admin_questions(conn, template_code)


def delete_admin_question(conn, template_code: str, question_id: int) -> tuple[bool, str]:
    from backend.services.evaluation_survey import delete_survey_question

    tpl = _template_row(conn, template_code)
    if not tpl:
        return False, "قالب غير موجود"
    if is_legacy_course_template(tpl):
        ok, msg = delete_survey_question(conn, question_id)
        if ok:
            _mark_survey_questions_customized(conn, template_code)
        return ok, msg
    q = _platform_question_by_id(conn, question_id)
    if not q or (q.get("template_code") or "").strip() != template_code.strip():
        return False, "البند غير موجود لهذا القالب"
    cur = conn.cursor()
    used = cur.execute(
        "SELECT COUNT(*) FROM survey_answers WHERE question_id = ?",
        (int(question_id),),
    ).fetchone()
    if int((used[0] if used else 0) or 0) > 0:
        return False, "لا يمكن حذف بند لديه إجابات — استخدم «إيقاف»"
    cur.execute("DELETE FROM survey_questions WHERE id = ?", (int(question_id),))
    conn.commit()
    _mark_survey_questions_customized(conn, template_code)
    return True, "ok"
