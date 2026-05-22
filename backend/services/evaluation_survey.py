"""إدارة بنود استبيان تقييم المقررات (ديناميكي)."""

from __future__ import annotations

import datetime
import logging
from typing import Any

from backend.database.database import is_postgresql, table_exists

logger = logging.getLogger(__name__)

LEGACY_EVAL_KEYS = frozenset(
    {
        "instructor_punctuality",
        "course_clarity",
        "assessment_fairness",
        "material_relevance",
        "communication_quality",
    }
)

# 10 بنود — مستوحاة من إطار IDEA/SERU لتقييم التدريس والمقرر
DEFAULT_SURVEY_SEED: list[tuple[str | None, str, int]] = [
    ("instructor_punctuality", "التزام الأستاذ بمواعيد المحاضرات والحضور الفعلي", 10),
    ("communication_quality", "وضوح الشرح وإتقان توصيل المفاهيم الأساسية", 20),
    ("course_clarity", "وضوح أهداف المقرر وتوافق المحتوى مع ما يُدرَّس", 30),
    ("assessment_fairness", "عدالة التقييم وشفافية معاييره وتطبيقها", 40),
    ("material_relevance", "ملاءمة المواد التعليمية والمراجع لمخرجات المقرر", 50),
    ("student_engagement", "تحفيز التفاعل والمشاركة الصفية النشطة", 60),
    ("feedback_timeliness", "تقديم تغذية راجعة بنّاءة في وقت مناسب", 70),
    ("critical_thinking", "تعزيز التفكير النقدي وحل المشكلات", 80),
    ("instructor_professionalism", "الاحترافية والالتزام بأخلاقيات التعليم", 90),
    ("learning_contribution", "المساهمة الإجمالية في تحقيق مخرجات التعلم للمقرر", 100),
]


def _row_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return dict(row)
    return {}


def ensure_survey_questions_seeded(conn) -> None:
    if not table_exists(conn, "evaluation_survey_questions"):
        return
    cur = conn.cursor()
    n = cur.execute("SELECT COUNT(*) FROM evaluation_survey_questions").fetchone()
    count = int((n[0] if n else 0) or 0)
    now = datetime.datetime.utcnow().isoformat()
    if count == 0:
        for legacy_key, label_ar, sort_order in DEFAULT_SURVEY_SEED:
            cur.execute(
                """
                INSERT INTO evaluation_survey_questions
                    (legacy_key, label_ar, sort_order, is_active, question_type, created_at, updated_at)
                VALUES (?, ?, ?, 1, 'likert_5', ?, ?)
                """,
                (legacy_key, label_ar, sort_order, now, now),
            )
        conn.commit()
        logger.info("Seeded %s default evaluation survey questions", len(DEFAULT_SURVEY_SEED))
        return
    _upgrade_course_eval_questions(conn)


def _upgrade_course_eval_questions(conn) -> None:
    """إضافة بنود البذر الناقصة دون المساس بالبنود المخصّصة أو التي لها إجابات."""
    from backend.core.survey_platform import SURVEY_QUESTIONS_TARGET_COUNT

    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, legacy_key, label_ar FROM evaluation_survey_questions"
    ).fetchall()
    if len(rows) >= SURVEY_QUESTIONS_TARGET_COUNT:
        return
    existing_keys = {
        (r[1] if not hasattr(r, "keys") else r["legacy_key"] or "").strip()
        for r in rows
    }
    existing_labels = {
        (r[2] if not hasattr(r, "keys") else r["label_ar"] or "").strip()
        for r in rows
    }
    max_sort = cur.execute(
        "SELECT COALESCE(MAX(sort_order), 0) FROM evaluation_survey_questions"
    ).fetchone()
    sort_order = int((max_sort[0] if max_sort else 0) or 0)
    added = 0
    now = datetime.datetime.utcnow().isoformat()
    for legacy_key, label_ar, seed_sort in DEFAULT_SURVEY_SEED:
        label = label_ar.strip()
        lk = (legacy_key or "").strip() or None
        if lk and lk in existing_keys:
            continue
        if label in existing_labels:
            continue
        sort_order = max(sort_order + 10, seed_sort)
        cur.execute(
            """
            INSERT INTO evaluation_survey_questions
                (legacy_key, label_ar, sort_order, is_active, question_type, created_at, updated_at)
            VALUES (?, ?, ?, 1, 'likert_5', ?, ?)
            """,
            (lk, label, sort_order, now, now),
        )
        if lk:
            existing_keys.add(lk)
        existing_labels.add(label)
        added += 1
    if added:
        conn.commit()
        logger.info("Upgraded course evaluation survey: added %s questions", added)


def list_survey_questions(conn, *, active_only: bool = False) -> list[dict]:
    ensure_survey_questions_seeded(conn)
    cur = conn.cursor()
    q = """
        SELECT id, legacy_key, label_ar, sort_order, is_active, question_type,
               created_at, updated_at
        FROM evaluation_survey_questions
    """
    if active_only:
        q += " WHERE is_active = 1"
    q += " ORDER BY sort_order ASC, id ASC"
    rows = cur.execute(q).fetchall()
    out = []
    for r in rows or []:
        d = _row_dict(r)
        d["id"] = int(d.get("id") or 0)
        d["sort_order"] = int(d.get("sort_order") or 0)
        d["is_active"] = int(d.get("is_active") or 0)
        d["legacy_key"] = (d.get("legacy_key") or "") or ""
        d["label_ar"] = (d.get("label_ar") or "").strip()
        d["question_type"] = (d.get("question_type") or "likert_5").strip()
        out.append(d)
    return out


def get_question_by_id(conn, question_id: int) -> dict | None:
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id, legacy_key, label_ar, sort_order, is_active, question_type
        FROM evaluation_survey_questions WHERE id = ? LIMIT 1
        """,
        (int(question_id),),
    ).fetchone()
    if not row:
        return None
    d = _row_dict(row)
    d["id"] = int(d["id"])
    d["is_active"] = int(d.get("is_active") or 0)
    return d


def _next_sort_order(cur) -> int:
    row = cur.execute("SELECT COALESCE(MAX(sort_order), 0) FROM evaluation_survey_questions").fetchone()
    return int((row[0] if row else 0) or 0) + 10


def create_survey_question(conn, label_ar: str, *, legacy_key: str | None = None) -> dict:
    ensure_survey_questions_seeded(conn)
    label = (label_ar or "").strip()
    if not label:
        raise ValueError("نص البند مطلوب")
    lk = (legacy_key or "").strip() or None
    if lk and lk not in LEGACY_EVAL_KEYS:
        raise ValueError("مفتاح قديم غير صالح")
    cur = conn.cursor()
    if lk:
        dup = cur.execute(
            "SELECT 1 FROM evaluation_survey_questions WHERE legacy_key = ? LIMIT 1",
            (lk,),
        ).fetchone()
        if dup:
            raise ValueError("يوجد بند مرتبط بهذا المفتاح مسبقاً")
    now = datetime.datetime.utcnow().isoformat()
    sort_order = _next_sort_order(cur)
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO evaluation_survey_questions
                (legacy_key, label_ar, sort_order, is_active, question_type, created_at, updated_at)
            VALUES (?, ?, ?, 1, 'likert_5', ?, ?)
            RETURNING id
            """,
            (lk, label, sort_order, now, now),
        )
        qid = int(cur.fetchone()[0])
    else:
        cur.execute(
            """
            INSERT INTO evaluation_survey_questions
                (legacy_key, label_ar, sort_order, is_active, question_type, created_at, updated_at)
            VALUES (?, ?, ?, 1, 'likert_5', ?, ?)
            """,
            (lk, label, sort_order, now, now),
        )
        qid = int(cur.lastrowid or 0)
    conn.commit()
    return get_question_by_id(conn, qid) or {"id": qid, "label_ar": label}


def update_survey_question(
    conn,
    question_id: int,
    *,
    label_ar: str | None = None,
    is_active: int | None = None,
) -> dict | None:
    q = get_question_by_id(conn, question_id)
    if not q:
        return None
    cur = conn.cursor()
    label = (label_ar if label_ar is not None else q.get("label_ar") or "").strip()
    if not label:
        raise ValueError("نص البند مطلوب")
    active = int(is_active) if is_active is not None else int(q.get("is_active") or 0)
    if active not in (0, 1):
        active = 1
    now = datetime.datetime.utcnow().isoformat()
    cur.execute(
        """
        UPDATE evaluation_survey_questions
        SET label_ar = ?, is_active = ?, updated_at = ?
        WHERE id = ?
        """,
        (label, active, now, int(question_id)),
    )
    conn.commit()
    return get_question_by_id(conn, question_id)


def reorder_survey_questions(conn, ordered_ids: list[int]) -> list[dict]:
    ensure_survey_questions_seeded(conn)
    ids = [int(x) for x in ordered_ids if int(x) > 0]
    if not ids:
        raise ValueError("قائمة الترتيب فارغة")
    cur = conn.cursor()
    now = datetime.datetime.utcnow().isoformat()
    order_val = 10
    for qid in ids:
        cur.execute(
            "UPDATE evaluation_survey_questions SET sort_order = ?, updated_at = ? WHERE id = ?",
            (order_val, now, qid),
        )
        order_val += 10
    conn.commit()
    return list_survey_questions(conn)


def delete_survey_question(conn, question_id: int) -> tuple[bool, str]:
    cur = conn.cursor()
    qid = int(question_id)
    used = cur.execute(
        "SELECT COUNT(*) FROM evaluation_survey_answers WHERE question_id = ?",
        (qid,),
    ).fetchone()
    if int((used[0] if used else 0) or 0) > 0:
        return False, "لا يمكن حذف بند لديه إجابات محفوظة — استخدم «إيقاف» بدلاً من الحذف"
    cur.execute("DELETE FROM evaluation_survey_questions WHERE id = ?", (qid,))
    conn.commit()
    return True, "ok"


def legacy_column_values(questions: list[dict], answers: dict[int, int]) -> dict[str, int | None]:
    """قيم الأعمدة القديمة في course_evaluations من الإجابات الديناميكية."""
    out: dict[str, int | None] = {k: None for k in LEGACY_EVAL_KEYS}
    for q in questions:
        qid = int(q.get("id") or 0)
        lk = (q.get("legacy_key") or "").strip()
        if lk in LEGACY_EVAL_KEYS and qid in answers:
            out[lk] = answers[qid]
    return out


def parse_answers_payload(data: dict, active_questions: list[dict]) -> dict[int, int]:
    """استخراج التقييمات من JSON/form: answers[id] أو q_<id>."""
    raw_answers = data.get("answers")
    if isinstance(raw_answers, dict):
        parsed: dict[int, int] = {}
        for k, v in raw_answers.items():
            try:
                qid = int(k)
                rating = int(v)
            except (TypeError, ValueError):
                continue
            if 1 <= rating <= 5:
                parsed[qid] = rating
        if parsed:
            return _validate_required_answers(active_questions, parsed)

    parsed = {}
    for q in active_questions:
        qid = int(q["id"])
        key = f"q_{qid}"
        val = data.get(key, data.get(str(qid)))
        try:
            rating = int(val)
        except (TypeError, ValueError):
            rating = 0
        if 1 <= rating <= 5:
            parsed[qid] = rating
    return _validate_required_answers(active_questions, parsed)


def _validate_required_answers(active_questions: list[dict], parsed: dict[int, int]) -> dict[int, int]:
    missing = [q for q in active_questions if int(q["id"]) not in parsed]
    if missing:
        labels = "، ".join((m.get("label_ar") or "")[:40] for m in missing[:3])
        raise ValueError(f"يرجى الإجابة على جميع بنود التقييم ({labels})")
    return parsed


def insert_evaluation_with_answers(
    conn,
    *,
    student_id: str,
    section_id: int,
    course_name: str,
    instructor_id: int,
    semester: str,
    comments: str,
    answers: dict[int, int],
    active_questions: list[dict],
) -> int:
    legacy = legacy_column_values(active_questions, answers)
    now = datetime.datetime.utcnow().isoformat()
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO course_evaluations (
                student_id, section_id, course_name, instructor_id, semester,
                instructor_punctuality, course_clarity, assessment_fairness,
                material_relevance, communication_quality, comments, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            RETURNING id
            """,
            (
                student_id,
                section_id,
                course_name,
                instructor_id,
                semester,
                legacy.get("instructor_punctuality"),
                legacy.get("course_clarity"),
                legacy.get("assessment_fairness"),
                legacy.get("material_relevance"),
                legacy.get("communication_quality"),
                comments,
                now,
            ),
        )
        eval_id = int(cur.fetchone()[0])
    else:
        cur.execute(
            """
            INSERT INTO course_evaluations (
                student_id, section_id, course_name, instructor_id, semester,
                instructor_punctuality, course_clarity, assessment_fairness,
                material_relevance, communication_quality, comments, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                student_id,
                section_id,
                course_name,
                instructor_id,
                semester,
                legacy.get("instructor_punctuality"),
                legacy.get("course_clarity"),
                legacy.get("assessment_fairness"),
                legacy.get("material_relevance"),
                legacy.get("communication_quality"),
                comments,
                now,
            ),
        )
        eval_id = int(cur.lastrowid or 0)

    if table_exists(conn, "evaluation_survey_answers") and eval_id:
        for qid, rating in answers.items():
            cur.execute(
                """
                INSERT INTO evaluation_survey_answers (evaluation_id, question_id, rating)
                VALUES (?, ?, ?)
                """,
                (eval_id, int(qid), int(rating)),
            )
    return eval_id


def likert_labels_ar() -> list[tuple[int, str]]:
    return [(5, "ممتاز"), (4, "جيد جداً"), (3, "جيد"), (2, "مقبول"), (1, "ضعيف")]
