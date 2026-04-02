"""
تقييم موحّد لمتطلبات المقررات (التسجيل الفعلي + خطط التسجيل).

سياسة:
- مصدر تشخيص المتطلب: جدول grades + التسجيل الفعلي الحالي (registrations) + المقررات المقترحة في الخطة/القائمة.
- رسوب سابق: مسموح بتنبيه للمشرف؛ لا يُمنع إرسال الخطة.
- متطلب مفقود من الكشف وغير ضمن المقترح مع التابع: يُوسَم blocking للمشرف؛ الإرسال مسموح.
- زوج متطلب+تابع مسجّلان معاً: لا إسقاط المتطلب وحده (يُمنع حفظ/اعتماد إن انتهك).
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

PASS_TEXT = {"p", "pass", "نجاح", "مقبول", "a", "b", "c"}
PASS_NUM_THRESHOLD = 50.0

# حالات موحّدة لواجهات API
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_MISSING = "missing"
STATUS_NO_GRADE = "no_grade"
STATUS_IN_PROGRESS = "in_progress"
STATUS_IN_PLAN = "in_plan"  # ضمن المقترح (شيفرة مع التابع)


def _grade_passes(value: Any) -> bool:
    if value is None:
        return False
    try:
        if float(value) >= PASS_NUM_THRESHOLD:
            return True
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and value.strip().lower() in PASS_TEXT:
        return True
    return False


def _raw_grade_row(cur, student_id: str, course_name: str) -> tuple[Any, Any] | None:
    row = cur.execute(
        "SELECT grade FROM grades WHERE student_id = ? AND course_name = ? LIMIT 1",
        (student_id, course_name),
    ).fetchone()
    if row is None:
        return None
    return row[0]


def _load_registered_courses(cur, student_id: str) -> set[str]:
    rows = cur.execute(
        "SELECT course_name FROM registrations WHERE student_id = ?",
        (student_id,),
    ).fetchall()
    return {r[0] for r in rows if r and r[0]}


def _load_prereq_map_for_courses(cur, course_names: list[str]) -> dict[str, list[str]]:
    if not course_names:
        return {}
    placeholders = ",".join("?" for _ in course_names)
    try:
        rows = cur.execute(
            f"SELECT course_name, required_course_name FROM prereqs WHERE course_name IN ({placeholders})",
            course_names,
        ).fetchall()
    except Exception:
        return {}
    m: dict[str, list[str]] = defaultdict(list)
    for c, r in rows or []:
        if c and r:
            m[c].append(r)
    return dict(m)


def _finalize_prereq_status(
    raw: str,
    grade_val: Any,
    dependent_course: str,
    prereq_name: str,
    proposed: set[str],
    registered_now: set[str],
) -> tuple[str, str, str]:
    """
    يرجع (status للـ API, severity: passed|info|warning|blocking, وصف عربي قصير).
    raw: no_row | no_grade_val | passed | failed
    """
    def lbl(s: str, ar: str) -> tuple[str, str, str]:
        if s == STATUS_PASSED:
            return STATUS_PASSED, "passed", ar
        if s == STATUS_IN_PLAN:
            return STATUS_IN_PLAN, "info", ar
        if s == STATUS_IN_PROGRESS:
            return STATUS_IN_PROGRESS, "info", ar
        if s == STATUS_NO_GRADE:
            return STATUS_NO_GRADE, "warning", ar
        if s == STATUS_FAILED:
            return STATUS_FAILED, "warning", ar
        if s == STATUS_MISSING:
            return STATUS_MISSING, "blocking", ar
        return s, "warning", ar

    in_prop = prereq_name in proposed
    in_reg = prereq_name in registered_now

    if raw == "passed":
        return lbl(STATUS_PASSED, f"منجز (الدرجة: {grade_val})")

    if raw == "failed":
        if in_prop:
            return lbl(
                STATUS_IN_PLAN,
                f"رسوب سابق ({grade_val}) — «{prereq_name}» مُدرَج في القائمة مع «{dependent_course}»",
            )
        return lbl(
            STATUS_FAILED,
            f"راسب في المتطلب (الدرجة: {grade_val}) — مسموح باستثناء بتقدير المشرف",
        )

    if raw == "no_grade_val":
        if in_prop:
            return lbl(STATUS_IN_PLAN, "ضمن القائمة المقترحة (سجل درجة بدون تقدير نهائي بعد)")
        if in_reg:
            return lbl(STATUS_IN_PROGRESS, "مسجّل حالياً بدون درجة نهائية في الكشف")
        return lbl(STATUS_NO_GRADE, "سطر في كشف الدرجات دون درجة نهائية — يحتاج مراجعة")

    # raw == no_row
    if in_prop:
        return lbl(STATUS_IN_PLAN, "مُدرَج في الخطة/القائمة مع المقرر التابع (شيفرة مع تسجيل المتطلب)")
    if in_reg:
        return lbl(STATUS_IN_PROGRESS, "مسجّل فعلياً هذا الفصل — لا يظهر سطر كامل في الكشف بعد")
    return lbl(STATUS_MISSING, "غير موجود في كشف الدرجات وغير مُدرَج مع المقرر التابع")


def evaluate_prereqs_for_student(
    cur,
    student_id: str,
    course_names: list[str],
    *,
    proposed_courses: list[str] | None = None,
    old_registered: set[str] | None = None,
    registered_now: set[str] | None = None,
) -> dict[str, Any]:
    """
    لكل مقرر في course_names يعيد متطلباته مع حالة موحّدة.

    proposed_courses: القائمة المقترحة (خطة أو تسجيل بعد الحفظ) لاكتشاف الشيفرة والإسقاط المقترن.
    old_registered: للتحقق من إسقاط متطلب وحده (قاعدة co-drop).
    registered_now: إن لم يُمرَّر، يُجلب من جدول registrations.
    """
    old_registered = set(old_registered or [])
    if registered_now is None:
        registered_now = _load_registered_courses(cur, student_id)

    seen: list[str] = []
    pset: set[str] = set()
    for c in course_names or []:
        c = (c or "").strip()
        if c and c not in pset:
            pset.add(c)
            seen.append(c)

    prop_set = set(
        (x or "").strip()
        for x in (proposed_courses if proposed_courses is not None else seen)
        if (x or "").strip()
    )

    prereq_map = _load_prereq_map_for_courses(cur, seen)
    courses_out: dict[str, Any] = {}
    blocking_count = 0
    warning_count = 0
    courses_with_any_issue: list[str] = []

    for course in seen:
        reqs_out: list[dict[str, Any]] = []
        for p in prereq_map.get(course, []):
            g_raw = _raw_grade_row(cur, student_id, p)
            if g_raw is None:
                raw = "no_row"
                grade_val = None
            else:
                grade_val = g_raw
                if grade_val is None or (isinstance(grade_val, str) and not str(grade_val).strip()):
                    raw = "no_grade_val"
                elif _grade_passes(grade_val):
                    raw = "passed"
                else:
                    raw = "failed"

            st, sev, ar = _finalize_prereq_status(raw, grade_val, course, p, prop_set, registered_now)
            if st != STATUS_PASSED:
                if course not in courses_with_any_issue:
                    courses_with_any_issue.append(course)
                if sev == "blocking":
                    blocking_count += 1
                elif sev == "warning":
                    warning_count += 1

            reqs_out.append(
                {
                    "prereq": p,
                    "status": st,
                    "severity": sev,
                    "grade": grade_val,
                    "label_ar": ar,
                }
            )
        courses_out[course] = {"requirements": reqs_out}

    drop_violations: list[dict[str, Any]] = []
    new_set = prop_set
    for course in seen:
        for p in prereq_map.get(course, []):
            if p in old_registered and course in old_registered and p not in new_set and course in new_set:
                drop_violations.append(
                    {
                        "dependent": course,
                        "prereq": p,
                        "message_ar": (
                            f"لا يمكن إبقاء «{course}» وإسقاط «{p}» فقط لأنهما مسجّلان معاً "
                            f"(المتطلب وما يعتمد عليه). أبقِهما معاً أو أسقطهما معاً."
                        ),
                    }
                )

    legacy = _legacy_from_detailed(courses_out, seen, prereq_map, cur, student_id, prop_set)

    return {
        "student_id": student_id,
        "courses": courses_out,
        "summary": {
            "total_courses_checked": len(seen),
            "courses_with_issues": courses_with_any_issue,
            "courses_with_unmet_count": len(courses_with_any_issue),
            "blocking_prereq_count": blocking_count,
            "warning_prereq_count": warning_count,
            "has_blocking": blocking_count > 0,
            "has_warnings": warning_count > 0,
        },
        "drop_violations": drop_violations,
        "blocked": legacy["blocked"],
        "warnings": legacy["warnings"],
        "coregister_pairs": legacy["coregister_pairs"],
    }


def _legacy_from_detailed(
    courses_out: dict[str, Any],
    seen: list[str],
    prereq_map: dict[str, list[str]],
    cur,
    student_id: str,
    prop_set: set[str],
) -> dict[str, Any]:
    """Compatibility مع evaluate_courses_prereqs السابقة."""
    blocked: dict[str, list[str]] = {}
    warnings: list[dict[str, Any]] = []
    coregister_pairs: list[dict[str, Any]] = []

    for course in seen:
        for req in courses_out.get(course, {}).get("requirements", []):
            p = req["prereq"]
            st = req["status"]
            if st == STATUS_PASSED:
                continue
            if st == STATUS_IN_PLAN:
                gk = "coregister_retry" if req.get("grade") is not None and not _grade_passes(req.get("grade")) else "coregister_new"
                coregister_pairs.append(
                    {
                        "prereq": p,
                        "dependent": course,
                        "kind": gk,
                        "prereq_grade": req.get("grade"),
                    }
                )
                continue
            if st == STATUS_MISSING:
                blocked.setdefault(course, []).append(p)
                continue
            if st == STATUS_FAILED:
                warnings.append(
                    {
                        "course": course,
                        "prereq": p,
                        "kind": "failed_prereq_not_retaking",
                        "prereq_grade": req.get("grade"),
                        "message_ar": (
                            f"المقرر «{course}» يتطلب «{p}» والطالب راسب فيه (الدرجة: {req.get('grade')}). "
                            "مسموح حسب اللائحة مع مراجعة المشرف."
                        ),
                    }
                )
            # in_progress, no_grade: لا تُضاف لمسار المنع القديم؛ المشرف يراها في التفصيل
    for k in list(blocked.keys()):
        blocked[k] = sorted(set(blocked[k]))
    return {"blocked": blocked, "warnings": warnings, "coregister_pairs": coregister_pairs}


def evaluate_courses_prereqs(
    cur,
    student_id: str,
    proposed_courses: list[str],
    old_registered: set[str] | None = None,
) -> dict[str, Any]:
    """
    نفس الواجهة السابقة؛ تُبنى من evaluate_prereqs_for_student.
    """
    full = evaluate_prereqs_for_student(
        cur,
        student_id,
        proposed_courses,
        proposed_courses=proposed_courses,
        old_registered=old_registered,
    )
    return {
        "blocked": full["blocked"],
        "warnings": full["warnings"],
        "coregister_pairs": full["coregister_pairs"],
        "drop_violations": full["drop_violations"],
        "courses": full["courses"],
        "summary": full["summary"],
    }


def prereq_validation_snapshot(full_eval: dict[str, Any], semester: str) -> dict[str, Any]:
    """للحفظ في قاعدة البيانات وللإشعارات."""
    return {
        "version": 1,
        "semester": semester,
        "summary": full_eval.get("summary"),
        "courses": full_eval.get("courses"),
        "warnings": full_eval.get("warnings"),
        "coregister_pairs": full_eval.get("coregister_pairs"),
        "blocked": full_eval.get("blocked"),
        "drop_violations": full_eval.get("drop_violations"),
    }


def format_supervisor_prereq_summary(student_id: str, semester: str, eval_result: dict[str, Any]) -> str:
    """نص عربي + JSON مختصر في آخر الرسالة للأرشفة السريعة."""
    lines = [
        f"طالب: {student_id} — فصل: {semester}",
    ]
    summ = eval_result.get("summary") or {}
    if summ.get("has_blocking"):
        lines.append(
            f"— تحذير: يوجد {summ.get('blocking_prereq_count', 0)} متطلب غير مستوفٍ (missing) يحتاج قرار مشرف."
        )
    if summ.get("has_warnings"):
        lines.append(
            f"— تنبيهات: {summ.get('warning_prereq_count', 0)} متطلب بحالة رسوب/دون درجة نهائية."
        )
    b = eval_result.get("blocked") or {}
    if b:
        lines.append("— مقررات بمتطلب مفقود من الكشف وغير شائف ضمن الخطة:")
        for c, ps in b.items():
            lines.append(f"  • {c}: يحتاج {', '.join(ps)}")
    w = eval_result.get("warnings") or []
    if w:
        lines.append("— راسب في متطلب ولا يُعاد تسجيله:")
        for it in w[:12]:
            lines.append(f"  • {it.get('message_ar', '')}")
        if len(w) > 12:
            lines.append(f"  … و{len(w) - 12} أخرى")
    cp = eval_result.get("coregister_pairs") or []
    if cp:
        lines.append("— أزواج مسجّلة معاً:")
        for it in cp[:15]:
            lines.append(f"  • «{it['prereq']}» + «{it['dependent']}» ({it.get('kind', '')})")

    cou = eval_result.get("courses") or {}
    if cou and not b and not w and not cp and not summ.get("has_blocking") and not summ.get("has_warnings"):
        lines.append("— لا توجد ملاحظات متطلبات في هذه القائمة.")

    snap = prereq_validation_snapshot(eval_result, semester)
    try:
        lines.append("")
        lines.append("— JSON:")
        lines.append(json.dumps(snap, ensure_ascii=False)[:8000])
    except Exception:
        pass
    return "\n".join(lines)


def planning_course_hints(cur, student_id: str) -> dict[str, Any]:
    """
    أولوية بسيطة: لكل مقرر لم يُنجَز بعد، عدد المقررات التي يفتحها مباشرةً إن نجح الطالب فيه.
    """
    completed: set[str] = set()
    try:
        rows = cur.execute(
            "SELECT course_name, grade FROM grades WHERE student_id = ?",
            (student_id,),
        ).fetchall()
        for cn, g in rows or []:
            if cn and _grade_passes(g):
                completed.add(cn)
    except Exception:
        pass

    try:
        all_rows = cur.execute("SELECT course_name, required_course_name FROM prereqs").fetchall()
    except Exception:
        all_rows = []
    direct_dependents: dict[str, list[str]] = defaultdict(list)
    all_courses_in_graph: set[str] = set()
    for c, r in all_rows or []:
        if c and r:
            direct_dependents[r].append(c)
            all_courses_in_graph.add(c)
            all_courses_in_graph.add(r)

    hints = []
    for base in sorted(all_courses_in_graph):
        if base in completed:
            continue
        unlock = [d for d in direct_dependents.get(base, []) if d not in completed]
        if not unlock:
            continue
        hints.append(
            {
                "course": base,
                "unlocks_count": len(unlock),
                "unlocks_sample": unlock[:12],
            }
        )
    hints.sort(key=lambda x: (-x["unlocks_count"], x["course"]))
    return {"student_id": student_id, "priorities": hints[:80]}
