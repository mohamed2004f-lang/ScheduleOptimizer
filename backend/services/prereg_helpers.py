"""
تقييم موحّد لمتطلبات المقررات (التسجيل الفعلي + خطط التسجيل).

سياسة:
- مصدر تشخيص المتطلب: جدول grades + التسجيل الفعلي الحالي (registrations) + المقررات المقترحة في الخطة/القائمة.
- المطابقة: اسم المقرر، رمز المقرر (course_code)، التكافؤ بين الأقسام، وتطبيع بسيط للاسم.
- رسوب سابق: مسموح بتنبيه للمشرف؛ لا يُمنع إرسال الخطة.
- متطلب مفقود من الكشف وغير ضمن المقترح مع التابع: يُوسَم blocking للمشرف؛ الإرسال مسموح.
- زوج متطلب+تابع مسجّلان معاً: لا إسقاط المتطلب وحده (يُمنع حفظ/اعتماد إن انتهك).
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Callable

PASS_TEXT = {"p", "pass", "نجاح", "مقبول", "a", "b", "c"}
PASS_NUM_THRESHOLD = 50.0

# حالات موحّدة لواجهات API
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_MISSING = "missing"
STATUS_NO_GRADE = "no_grade"
STATUS_IN_PROGRESS = "in_progress"
STATUS_IN_PLAN = "in_plan"  # ضمن المقترح (شيفرة مع التابع)


def _normalize_course_key(name: str) -> str:
    """تطبيع بسيط لاسم المقرر لتقليل مشاكل المطابقة النصية."""
    s = str(name or "").strip().lower()
    s = s.replace("ـ", "")
    for ch in ("-", "_", "/", "\\"):
        s = s.replace(ch, " ")
    return " ".join(s.split())


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


def _grade_numeric_key(value: Any) -> float:
    if value is None:
        return -1.0
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and value.strip().lower() in PASS_TEXT:
        return PASS_NUM_THRESHOLD
    return -1.0


def _load_catalog_maps(cur) -> tuple[dict[str, str], dict[str, str]]:
    """name (والمفتاح المُطبّع) -> code؛ code_lower -> canonical name."""
    name_to_code: dict[str, str] = {}
    code_to_name: dict[str, str] = {}
    try:
        rows = cur.execute(
            "SELECT COALESCE(course_name,'') AS course_name, COALESCE(course_code,'') AS course_code FROM courses"
        ).fetchall()
    except Exception:
        return name_to_code, code_to_name
    for row in rows or []:
        cname = (row[0] if not hasattr(row, "keys") else row["course_name"] or "").strip()
        ccode = (row[1] if not hasattr(row, "keys") else row["course_code"] or "").strip()
        if not cname:
            continue
        if ccode:
            name_to_code[cname] = ccode
            nk = _normalize_course_key(cname)
            if nk:
                name_to_code[nk] = ccode
            code_to_name[ccode.lower()] = cname
    return name_to_code, code_to_name


def _student_department_id(cur, student_id: str) -> int | None:
    sid = (student_id or "").strip()
    if not sid:
        return None
    try:
        row = cur.execute(
            "SELECT department_id FROM students WHERE student_id = ? LIMIT 1",
            (sid,),
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    raw = row[0] if not hasattr(row, "keys") else row["department_id"]
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _build_prereq_match_context(cur, student_id: str) -> dict[str, Any]:
    """سياق مطابقة يُبنى مرة واحدة لكل تقييم."""
    name_to_code, code_to_name = _load_catalog_maps(cur)
    dept_id = _student_department_id(cur, student_id)
    grade_rows: list[tuple[str, str, Any]] = []
    try:
        rows = cur.execute(
            """
            SELECT COALESCE(course_name,'') AS course_name,
                   COALESCE(course_code,'') AS course_code,
                   grade
            FROM grades
            WHERE student_id = ?
            """,
            ((student_id or "").strip(),),
        ).fetchall()
        for row in rows or []:
            cn = (row[0] if not hasattr(row, "keys") else row["course_name"] or "").strip()
            cc = (row[1] if not hasattr(row, "keys") else row["course_code"] or "").strip()
            g = row[2] if not hasattr(row, "keys") else row["grade"]
            grade_rows.append((cn, cc, g))
    except Exception:
        pass

    alias_cache: dict[str, set[str]] = {}
    conn = getattr(cur, "connection", None)

    def aliases_for(course_name: str) -> set[str]:
        cn = (course_name or "").strip()
        if not cn:
            return set()
        if cn in alias_cache:
            return alias_cache[cn]

        out: set[str] = {cn}
        nk = _normalize_course_key(cn)
        if nk:
            out.add(nk)

        code = name_to_code.get(cn) or name_to_code.get(nk)
        if code:
            out.add(code)
            out.add(code.lower())
            canon = code_to_name.get(code.lower())
            if canon:
                out.add(canon)
                cnk = _normalize_course_key(canon)
                if cnk:
                    out.add(cnk)

        if conn is not None:
            try:
                from backend.repositories.course_equivalence_repo import (
                    expand_course_names_for_department,
                    expand_course_names_global,
                )

                if dept_id is not None:
                    out.update(expand_course_names_for_department(conn, dept_id, {cn}))
                out.update(expand_course_names_global(conn, {cn}))
            except Exception:
                pass

        norm_aliases: set[str] = set()
        for a in list(out):
            if len(a) > 2 or not a.replace(".", "").isalnum():
                na = _normalize_course_key(a)
                if na:
                    norm_aliases.add(na)
        out.update(norm_aliases)

        alias_cache[cn] = out
        return out

    return {
        "name_to_code": name_to_code,
        "code_to_name": code_to_name,
        "grade_rows": grade_rows,
        "aliases_for": aliases_for,
        "department_id": dept_id,
    }


def _grade_row_matches_prereq(
    row_name: str,
    row_code: str,
    aliases: set[str],
    name_to_code: dict[str, str],
    code_to_name: dict[str, str],
) -> bool:
    rn = (row_name or "").strip()
    rc = (row_code or "").strip().lower()
    if rn and rn in aliases:
        return True
    rnk = _normalize_course_key(rn)
    if rnk and rnk in aliases:
        return True
    if rc and rc in aliases:
        return True
    if rc and code_to_name.get(rc) in aliases:
        return True
    cat_code = name_to_code.get(rn) or name_to_code.get(rnk)
    if cat_code and (cat_code in aliases or cat_code.lower() in aliases):
        return True
    return False


def _resolve_prereq_grade(
    ctx: dict[str, Any],
    prereq_name: str,
) -> tuple[str, Any, str | None]:
    """
    يُرجع (raw: passed|failed|no_grade_val|no_row, grade_val, matched_course_name أو None).
    يختار أفضل درجة ناجحة عبر كل أشكال المطابقة.
    """
    aliases = ctx["aliases_for"](prereq_name)
    name_to_code = ctx["name_to_code"]
    code_to_name = ctx["code_to_name"]

    best_pass_grade: Any = None
    best_pass_key = -1.0
    best_pass_course: str | None = None
    best_fail: tuple[Any, str | None] | None = None
    saw_row = False

    for cn, cc, g in ctx["grade_rows"]:
        if not _grade_row_matches_prereq(cn, cc, aliases, name_to_code, code_to_name):
            continue
        saw_row = True
        matched = cn or code_to_name.get((cc or "").lower()) or prereq_name
        if g is None or (isinstance(g, str) and not str(g).strip()):
            if best_fail is None:
                best_fail = (None, matched)
            continue
        if _grade_passes(g):
            gk = _grade_numeric_key(g)
            if gk > best_pass_key:
                best_pass_key = gk
                best_pass_grade = g
                best_pass_course = matched if matched != prereq_name else None
        elif best_fail is None or best_fail[0] is None:
            best_fail = (g, matched)

    if best_pass_grade is not None:
        return "passed", best_pass_grade, best_pass_course
    if not saw_row:
        return "no_row", None, None
    if best_fail and best_fail[0] is None:
        return "no_grade_val", None, best_fail[1]
    if best_fail:
        return "failed", best_fail[0], best_fail[1]
    return "no_row", None, None


def _set_covers_prereq(prereq_name: str, name_set: set[str], ctx: dict[str, Any]) -> bool:
    """هل مجموعة أسماء (تسجيل/خطة) تغطي المتطلب (اسم/رمز/معادلة)؟"""
    if prereq_name in name_set:
        return True
    prereq_aliases = ctx["aliases_for"](prereq_name)
    if name_set & prereq_aliases:
        return True
    for n in name_set:
        if n and (ctx["aliases_for"](n) & prereq_aliases):
            return True
    return False


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
    *,
    matched_course: str | None = None,
    match_ctx: dict[str, Any] | None = None,
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

    ctx = match_ctx or {}
    aliases_fn: Callable[[str], set[str]] | None = ctx.get("aliases_for")
    if aliases_fn:
        in_prop = _set_covers_prereq(prereq_name, proposed, ctx)
        in_reg = _set_covers_prereq(prereq_name, registered_now, ctx)
    else:
        in_prop = prereq_name in proposed
        in_reg = prereq_name in registered_now

    if raw == "passed":
        ar = f"منجز (الدرجة: {grade_val})"
        if matched_course:
            ar += f" — مطابق عبر «{matched_course}»"
        return lbl(STATUS_PASSED, ar)

    if raw == "failed":
        via = f" («{matched_course}»)" if matched_course else ""
        if in_prop:
            return lbl(
                STATUS_IN_PLAN,
                f"رسوب سابق ({grade_val}){via} — «{prereq_name}» مُدرَج في القائمة مع «{dependent_course}»",
            )
        return lbl(
            STATUS_FAILED,
            f"راسب في المتطلب (الدرجة: {grade_val}){via} — مسموح باستثناء بتقدير المشرف",
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

    match_ctx = _build_prereq_match_context(cur, student_id)
    prereq_map = _load_prereq_map_for_courses(cur, seen)
    courses_out: dict[str, Any] = {}
    blocking_count = 0
    warning_count = 0
    courses_with_any_issue: list[str] = []

    for course in seen:
        reqs_out: list[dict[str, Any]] = []
        for p in prereq_map.get(course, []):
            raw, grade_val, matched_course = _resolve_prereq_grade(match_ctx, p)

            st, sev, ar = _finalize_prereq_status(
                raw,
                grade_val,
                course,
                p,
                prop_set,
                registered_now,
                matched_course=matched_course,
                match_ctx=match_ctx,
            )
            if st != STATUS_PASSED:
                if course not in courses_with_any_issue:
                    courses_with_any_issue.append(course)
                if sev == "blocking":
                    blocking_count += 1
                elif sev == "warning":
                    warning_count += 1

            req_entry: dict[str, Any] = {
                "prereq": p,
                "status": st,
                "severity": sev,
                "grade": grade_val,
                "label_ar": ar,
            }
            if matched_course:
                req_entry["matched_course"] = matched_course
            reqs_out.append(req_entry)
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


def format_unmet_prereqs_student_ar(eval_result: dict[str, Any]) -> str:
    """نص قصير للطالب: كل مقرر وما ينقصه من متطلبات."""
    lines: list[str] = []
    courses = eval_result.get("courses") or {}
    skip = {STATUS_PASSED, STATUS_IN_PLAN}
    for cname, data in courses.items():
        bits: list[str] = []
        for req in data.get("requirements") or []:
            st = (req.get("status") or "").strip()
            if st in skip:
                continue
            pname = (req.get("prereq") or "").strip()
            if not pname:
                continue
            label = (req.get("label_ar") or "").strip()
            bits.append(f"«{pname}»" + (f" ({label})" if label else ""))
        if bits:
            lines.append(f"• المقرر «{cname}» يحتاج: " + "، ".join(bits))
    return "\n".join(lines)


def prereq_ack_required(eval_result: dict[str, Any]) -> bool:
    """إقرار المخالفة فقط عند متطلب ناقص/راسب/بدون درجة — وليس عند تسجيل المتطلب معه في الخطة."""
    summ = eval_result.get("summary") or {}
    return bool(summ.get("has_blocking") or summ.get("has_warnings"))


def format_supervisor_prereq_summary(student_id: str, semester: str, eval_result: dict[str, Any]) -> str:
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


def _student_completed_courses(cur, student_id: str) -> set[str]:
    """مقررات منجزة في الكشف — مع مطابقة الرمز والمعادلات."""
    ctx = _build_prereq_match_context(cur, student_id)
    completed: set[str] = set()
    for cn, cc, g in ctx["grade_rows"]:
        if not _grade_passes(g):
            continue
        if cn:
            completed.add(cn)
        canon = ctx["code_to_name"].get((cc or "").lower())
        if canon:
            completed.add(canon)
    # توسيع بأسماء المعادلات لكل مقرر منجز
    expanded: set[str] = set()
    for c in completed:
        expanded.update(ctx["aliases_for"](c))
    return expanded


def planning_course_hints(cur, student_id: str) -> dict[str, Any]:
    """
    أولوية بسيطة: لكل مقرر لم يُنجَز بعد، عدد المقررات التي يفتحها مباشرةً إن نجح الطالب فيه.
    """
    completed = _student_completed_courses(cur, student_id)

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
