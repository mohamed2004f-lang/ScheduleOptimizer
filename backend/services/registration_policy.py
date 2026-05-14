"""سياسات التسجيل المرتبطة بالخطة والشُّعب (Sprint B)."""
from __future__ import annotations

from typing import Any
from backend.services.utilities import get_current_term


PASS_TEXT = {"p", "pass", "نجاح", "مقبول", "a", "b", "c"}


def _passes_grade(v: Any) -> bool:
    try:
        return float(v) >= 50.0
    except Exception:
        return isinstance(v, str) and v.strip().lower() in PASS_TEXT


def student_program_id(cur, student_id: str) -> int | None:
    row = cur.execute(
        """
        SELECT current_program_id, admission_program_id
        FROM students
        WHERE student_id = ?
        LIMIT 1
        """,
        (student_id,),
    ).fetchone()
    if not row:
        return None
    for v in (row[0], row[1]):
        try:
            if v not in (None, ""):
                return int(v)
        except Exception:
            pass
    return None


def student_graduation_plan(cur, student_id: str) -> str:
    row = cur.execute(
        """
        SELECT COALESCE(graduation_plan, '')
        FROM students
        WHERE student_id = ?
        LIMIT 1
        """,
        (student_id,),
    ).fetchone()
    plan = ((row[0] if row else "") or "").strip()
    if plan in ("150", "155"):
        return plan

    # fallback: سياسة القسم المعتمدة (إن لم تحدد خطة الطالب مباشرة)
    try:
        def _term_order(term_name: str) -> int:
            t = (term_name or "").strip()
            if t == "ربيع":
                return 1
            if t == "صيف":
                return 2
            if t == "خريف":
                return 3
            return 0

        def _parse_year_token(y: str) -> int:
            s = (y or "").strip()
            if not s:
                return -1
            try:
                return int(s)
            except Exception:
                pass
            for sep in ("/", "-", " "):
                if sep in s:
                    parts = [p for p in s.split(sep) if p.strip()]
                    for p in parts:
                        try:
                            return int(p.strip())
                        except Exception:
                            continue
            return -1

        def _effective_now(eff_term: str, eff_year: str, cur_term: str, cur_year: str) -> bool:
            if not (eff_term or eff_year):
                return True
            cy = _parse_year_token(cur_year)
            ey = _parse_year_token(eff_year)
            if ey >= 0 and cy < 0:
                return False
            if ey >= 0 and cy >= 0:
                if ey < cy:
                    return True
                if ey > cy:
                    return False
            if eff_term and cur_term:
                return _term_order(eff_term) <= _term_order(cur_term)
            if eff_term and not cur_term:
                return False
            return True

        dep_row = cur.execute(
            """
            SELECT department_id, current_program_id, admission_program_id
            FROM students
            WHERE student_id = ?
            LIMIT 1
            """,
            (student_id,),
        ).fetchone()
        dep_id = None
        if dep_row:
            raw_dep = dep_row[0]
            if raw_dep not in (None, ""):
                dep_id = int(raw_dep)
            if dep_id is None:
                for pid in (dep_row[1], dep_row[2]):
                    if pid in (None, ""):
                        continue
                    pr = cur.execute(
                        "SELECT department_id FROM programs WHERE id = ? LIMIT 1",
                        (int(pid),),
                    ).fetchone()
                    if pr and pr[0] not in (None, ""):
                        dep_id = int(pr[0])
                        break
        if dep_id is None:
            return ""
        pol_rows = cur.execute(
            """
            SELECT plan_code,
                   COALESCE(effective_from_term, ''),
                   COALESCE(effective_from_year, '')
            FROM department_graduation_policies
            WHERE department_id = ?
              AND status = 'approved'
            ORDER BY COALESCE(approved_at, created_at) DESC, id DESC
            """,
            (int(dep_id),),
        ).fetchall()
        cur_term, cur_year = get_current_term(conn=cur.connection)
        chosen = ""
        for r in pol_rows or []:
            code = (r[0] or "").strip()
            eff_t = (r[1] or "").strip()
            eff_y = (r[2] or "").strip()
            if code in ("150", "155") and _effective_now(eff_t, eff_y, cur_term, str(cur_year or "")):
                chosen = code
                break
        if not chosen and pol_rows:
            for r in pol_rows:
                codex = (r[0] or "").strip()
                eff_t = (r[1] or "").strip()
                eff_y = (r[2] or "").strip()
                if codex in ("150", "155") and (not eff_t and not eff_y):
                    chosen = codex
                    break
        if not chosen and pol_rows:
            code0 = ((pol_rows[-1][0] if pol_rows[-1] else "") or "").strip()
            chosen = code0 if code0 in ("150", "155") else ""
        p = chosen
        return p if p in ("150", "155") else ""
    except Exception:
        return ""


def map_courses_to_program_courses(cur, student_id: str, course_names: list[str]) -> tuple[dict[str, int], list[str]]:
    """
    ربط أسماء المقررات بـ program_course_id للطالب حسب برنامجه الحالي.
    """
    p_id = student_program_id(cur, student_id)
    if not p_id:
        return {}, ["لا يوجد برنامج حالي/قبول للطالب."]
    plan = student_graduation_plan(cur, student_id)
    out: dict[str, int] = {}
    warns: list[str] = []
    for cn in course_names:
        name = (cn or "").strip()
        if not name:
            continue
        crow = cur.execute(
            "SELECT course_master_id, COALESCE(course_code,'') FROM courses WHERE course_name = ? LIMIT 1",
            (name,),
        ).fetchone()
        if not crow:
            warns.append(f"المقرر «{name}» غير موجود في جدول courses.")
            continue
        cm_id = crow[0]
        ccode = (crow[1] or "").strip()
        prow = None
        if cm_id not in (None, ""):
            if plan:
                prow = cur.execute(
                    """
                    SELECT id FROM program_courses
                    WHERE program_id = ? AND course_master_id = ?
                      AND (
                        COALESCE(plan_applicability, 'both') = 'both'
                        OR COALESCE(plan_applicability, 'both') = ?
                      )
                    LIMIT 1
                    """,
                    (int(p_id), int(cm_id), plan),
                ).fetchone()
            else:
                prow = cur.execute(
                    """
                    SELECT id FROM program_courses
                    WHERE program_id = ? AND course_master_id = ?
                    LIMIT 1
                    """,
                    (int(p_id), int(cm_id)),
                ).fetchone()
        if not prow and ccode:
            if plan:
                prow = cur.execute(
                    """
                    SELECT id FROM program_courses
                    WHERE program_id = ? AND lower(COALESCE(course_code,'')) = lower(?)
                      AND (
                        COALESCE(plan_applicability, 'both') = 'both'
                        OR COALESCE(plan_applicability, 'both') = ?
                      )
                    LIMIT 1
                    """,
                    (int(p_id), ccode, plan),
                ).fetchone()
            else:
                prow = cur.execute(
                    """
                    SELECT id FROM program_courses
                    WHERE program_id = ? AND lower(COALESCE(course_code,'')) = lower(?)
                    LIMIT 1
                    """,
                    (int(p_id), ccode),
                ).fetchone()
        if not prow:
            if plan:
                warns.append(f"المقرر «{name}» غير مربوط بخطة البرنامج الحالية أو غير مفعّل لنظام {plan}.")
            else:
                warns.append(f"المقرر «{name}» غير مربوط بخطة البرنامج الحالية.")
            continue
        out[name] = int(prow[0])
    return out, warns


def check_program_prereqs(cur, student_id: str, selected_pc_map: dict[str, int]) -> list[str]:
    """
    تحقق خفيف للمتطلبات السابقة على مستوى الخطة (program_course_prereqs.required_program_course_id).
    """
    if not selected_pc_map:
        return []
    selected_ids = set(int(v) for v in selected_pc_map.values())
    rows = cur.execute(
        f"""
        SELECT program_course_id, required_program_course_id
        FROM program_course_prereqs
        WHERE required_program_course_id IS NOT NULL
          AND program_course_id IN ({",".join("?" for _ in selected_ids)})
        """,
        tuple(selected_ids),
    ).fetchall()
    if not rows:
        return []

    # مقرات ناجحة سابقًا (بالاسم) → نحاول تحويلها إلى program_course_id ضمن البرنامج الحالي
    passed_names: set[str] = set()
    grows = cur.execute(
        "SELECT course_name, grade FROM grades WHERE student_id = ?",
        (student_id,),
    ).fetchall()
    for g in grows:
        if _passes_grade(g[1]):
            passed_names.add((g[0] or "").strip())
    passed_map, _ = map_courses_to_program_courses(cur, student_id, list(passed_names))
    passed_ids = set(int(v) for v in passed_map.values())

    blocked: list[str] = []
    for r in rows:
        dep_id = int(r[0])
        req_id = int(r[1])
        if req_id in selected_ids or req_id in passed_ids:
            continue
        blocked.append(
            f"متطلب خطة مفقود: program_course_id={req_id} مطلوب قبل {dep_id}."
        )
    return blocked


def check_general_sections_capacity(
    cur,
    *,
    selected_pc_map: dict[str, int],
    old_pc_ids: set[int],
    term_label: str | None,
) -> list[str]:
    """
    تحقق من سعة شُعب البرنامج للمقررات المضافة حديثًا.
    """
    if not selected_pc_map:
        return []
    warns: list[str] = []
    sem = (term_label or "").strip()
    for _, pcid in selected_pc_map.items():
        if int(pcid) in old_pc_ids:
            continue
        sec_rows = cur.execute(
            """
            SELECT COALESCE(capacity_max,0), COALESCE(semester,'')
            FROM program_course_sections
            WHERE program_course_id = ? AND is_active = 1
            """,
            (int(pcid),),
        ).fetchall()
        if not sec_rows:
            continue
        total_cap = 0
        for sr in sec_rows:
            cap = int(sr[0] or 0)
            ssem = (sr[1] or "").strip()
            if sem and ssem and ssem != sem:
                continue
            if cap > 0:
                total_cap += cap
        if total_cap <= 0:
            continue
        cnt = cur.execute(
            "SELECT COUNT(DISTINCT student_id) FROM registrations WHERE program_course_id = ?",
            (int(pcid),),
        ).fetchone()
        cur_count = int((cnt[0] if cnt else 0) or 0)
        if cur_count + 1 > total_cap:
            warns.append(
                f"لا توجد سعة كافية في شُعب المقرر program_course_id={pcid} (المتاح {total_cap}, الحالي {cur_count})."
            )
    return warns
