"""مساعد الجودة الذكي — اقتراح/مناقشة/تصعيد حسب الدور (بدون اعتماد امتثال)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from backend.core.quality_assistant_catalog import (
    ASSISTANT_MODES,
    ESCALATION_TARGETS,
    GLOBAL_REFERENCE_TIPS,
    POLICY_BANNER_AR,
    ROLE_DISCUSSION_GUIDE,
    SYSTEM_USAGE_TOPICS,
    catalog_for_client,
    exportable_specialty_packs,
    intents_for_mode,
    match_specialty_pack,
    match_system_usage_topic,
    specialty_pack_to_markdown,
)
from backend.database.database import is_postgresql, table_exists
from backend.services.quality_metrics import term_label_from_conn

CHAT_HISTORY_MAX = 5


def ensure_quality_assistant_tables(conn) -> None:
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_assistant_escalations (
                id BIGSERIAL PRIMARY KEY,
                from_mode TEXT NOT NULL,
                to_mode TEXT NOT NULL,
                title_ar TEXT NOT NULL DEFAULT '',
                body_ar TEXT NOT NULL DEFAULT '',
                semester TEXT NOT NULL DEFAULT '',
                department_id BIGINT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_by TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_assistant_feedback (
                id BIGSERIAL PRIMARY KEY,
                reply_id TEXT NOT NULL DEFAULT '',
                rating TEXT NOT NULL DEFAULT '',
                reason_ar TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT '',
                intent TEXT NOT NULL DEFAULT '',
                semester TEXT NOT NULL DEFAULT '',
                department_id BIGINT,
                actor TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    else:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_assistant_escalations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_mode TEXT NOT NULL,
                to_mode TEXT NOT NULL,
                title_ar TEXT NOT NULL DEFAULT '',
                body_ar TEXT NOT NULL DEFAULT '',
                semester TEXT NOT NULL DEFAULT '',
                department_id INTEGER,
                status TEXT NOT NULL DEFAULT 'draft',
                created_by TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_assistant_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reply_id TEXT NOT NULL DEFAULT '',
                rating TEXT NOT NULL DEFAULT '',
                reason_ar TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT '',
                intent TEXT NOT NULL DEFAULT '',
                semester TEXT NOT NULL DEFAULT '',
                department_id INTEGER,
                actor TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    conn.commit()


def normalize_chat_history(raw: Any, *, max_items: int = CHAT_HISTORY_MAX) -> list[dict[str, str]]:
    """آخر N رسائل فقط: role=user|assistant + text."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = (item.get("role") or item.get("who") or "").strip().lower()
        if role in ("أنت", "انت", "me", "user", "human"):
            role = "user"
        elif role in ("المساعد", "bot", "assistant", "system"):
            role = "assistant"
        if role not in ("user", "assistant"):
            continue
        text = (item.get("text") or item.get("content") or item.get("message") or "").strip()
        if not text or text.startswith("جاري التحليل"):
            continue
        out.append({"role": role, "text": text[:2000]})
    return out[-max(1, min(max_items, 8)) :]


def history_context_block(history: list[dict[str, str]]) -> list[str]:
    if not history:
        return []
    lines = ["سياق المحادثة السابقة (مختصر):"]
    for h in history[-CHAT_HISTORY_MAX:]:
        who = "المستخدم" if h["role"] == "user" else "المساعد"
        lines.append(f"• {who}: {h['text'][:280]}")
    lines.append("")
    return lines


def escalate_intent_for_mode(mode: str) -> str | None:
    return {
        "instructor": "escalate_hod",
        "head_of_department": "escalate_committee",
        "academic_vice_dean": "escalate_dean",
        "quality_committee": "minutes_draft",
        "college_dean": "ask_committee",
    }.get((mode or "").strip())


def _enrich_actions(
    *,
    mode: str,
    links: list[dict[str, Any]] | None = None,
    draft_text: str = "",
    message_ar: str = "",
    bullets: list[Any] | None = None,
    actions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = list(actions or [])
    seen_href = {a.get("href") for a in out if a.get("type") == "open_link"}
    for link in links or []:
        href = (link.get("href") or "").strip()
        if not href or href in seen_href:
            continue
        out.append(
            {
                "type": "open_link",
                "label_ar": link.get("label_ar") or "فتح الصفحة",
                "href": href,
            }
        )
        seen_href.add(href)
    copy_body = (draft_text or "").strip()
    if not copy_body and bullets:
        copy_body = "\n".join(str(b) for b in bullets if str(b).strip())[:4000]
    if copy_body:
        out.append(
            {
                "type": "copy_text",
                "label_ar": "انسخ المسودة / الرد",
                "text": ((message_ar + "\n\n") if message_ar else "") + copy_body,
            }
        )
    esc = escalate_intent_for_mode(mode)
    if esc:
        out.append(
            {
                "type": "escalate",
                "label_ar": "أنشئ تصعيداً / مسودة متابعة",
                "intent": esc,
            }
        )
    return out


def build_welcome_brief(
    conn,
    *,
    mode: str,
    semester: str | None = None,
    department_id: int | None = None,
) -> dict[str, Any]:
    """ترحيب حسب الدور + أهم 3 مهام ناقصة من السياق."""
    ctx = build_context(conn, mode=mode, semester=semester, department_id=department_id)
    meta = ASSISTANT_MODES.get(mode) or {}
    tasks: list[dict[str, str]] = []
    arch = ctx.get("archive") or {}
    for tip in (arch.get("tips_ar") or [])[:5]:
        if "لا توجد فجوات" in tip:
            continue
        tasks.append(
            {
                "title_ar": tip[:220],
                "href": "/academic_quality/archive",
                "source": "archive",
            }
        )
    for g in ((ctx.get("prog") or {}).get("top_gaps") or [])[:3]:
        tasks.append(
            {
                "title_ar": f"فجوة PROG: {g.get('code')} — {g.get('title_ar')}",
                "href": "/academic_quality/accreditation/map?scope=prog",
                "source": "prog",
            }
        )
    for g in ((ctx.get("inst") or {}).get("top_gaps") or [])[:3]:
        tasks.append(
            {
                "title_ar": f"فجوة INST: {g.get('code')} — {g.get('title_ar')}",
                "href": "/academic_quality/accreditation/map?scope=inst",
                "source": "inst",
            }
        )
    overview = ctx.get("departments_overview") or []
    late = sorted(overview, key=lambda d: -int(d.get("archive_open_issues") or 0))
    for d in late[:2]:
        if int(d.get("archive_open_issues") or 0) <= 0:
            continue
        tasks.append(
            {
                "title_ar": f"قسم {d.get('name_ar') or d.get('code')}: {d.get('archive_open_issues')} ملاحظة أرشيف",
                "href": "/academic_quality/archive",
                "source": "college_ops",
            }
        )
    # مهام ثابتة حسب الدور إن قلّت الفجوات
    if len(tasks) < 3:
        defaults = {
            "instructor": [
                {"title_ar": "راجع تقييم CLO وإغلاق المقرر", "href": "/my_courses", "source": "default"},
                {"title_ar": "فسّر ضعاف استبيان المقرر إن وُجدت", "href": "/academic_quality/surveys", "source": "default"},
            ],
            "head_of_department": [
                {"title_ar": "أكمل نواقص أرشيف القسم لهذا الفصل", "href": "/academic_quality/archive", "source": "default"},
                {"title_ar": "راجع فجوات PROG واربط الشواهد يدوياً", "href": "/academic_quality/accreditation/map?scope=prog", "source": "default"},
            ],
            "academic_vice_dean": [
                {"title_ar": "راجع التغطية التشغيلية عبر الأقسام", "href": "/academic_quality/dashboard", "source": "default"},
                {"title_ar": "تابع اكتمال الاستبيانات", "href": "/academic_quality/surveys/completion", "source": "default"},
            ],
            "quality_committee": [
                {"title_ar": "حضّر أجندة الجلسة من الفجوات الظاهرة", "href": "/academic_quality/dashboard", "source": "default"},
                {"title_ar": "راجع المراجع العالمية للقسم المختار", "href": "/academic_quality/assistant", "source": "default"},
            ],
            "college_dean": [
                {"title_ar": "اطلع على الموجز التنفيذي للكلية", "href": "/academic_quality/dashboard", "source": "default"},
                {"title_ar": "راجع تقدم الامتثال المؤسسي", "href": "/academic_quality/accreditation/map?scope=inst", "source": "default"},
            ],
        }
        for t in defaults.get(mode, []):
            tasks.append(t)
            if len(tasks) >= 3:
                break
    # إزالة التكرار بالمعنى التقريبي للعنوان
    uniq: list[dict[str, str]] = []
    seen: set[str] = set()
    for t in tasks:
        key = (t.get("title_ar") or "")[:80]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(t)
        if len(uniq) >= 3:
            break
    dept = ctx.get("department") or {}
    greeting = (
        f"مرحباً — أنت في وضع «{meta.get('title_ar') or mode}». "
        f"الفصل: {ctx.get('semester') or '—'}"
        + (f" · القسم: {dept.get('name_ar')}" if dept.get("name_ar") else "")
        + "."
    )
    return {
        "status": "ok",
        "greeting_ar": greeting,
        "tasks": uniq,
        "mode": mode,
        "semester": ctx.get("semester"),
        "department": dept,
        "suggestion_only": True,
        "message_ar": greeting + (" هذه أهم المهام المقترحة الآن:" if uniq else ""),
    }


def save_assistant_feedback(
    conn,
    *,
    reply_id: str,
    rating: str,
    reason_ar: str = "",
    mode: str = "",
    intent: str = "",
    semester: str = "",
    department_id: int | None = None,
    actor: str = "",
) -> dict[str, Any]:
    ensure_quality_assistant_tables(conn)
    r = (rating or "").strip().lower()
    if r in ("up", "good", "1", "+", "positive", "👍"):
        r = "up"
    elif r in ("down", "bad", "0", "-", "negative", "👎"):
        r = "down"
    else:
        raise ValueError("التقييم يجب أن يكون up أو down")
    rid = (reply_id or "").strip()
    if not rid:
        raise ValueError("معرّف الرد مطلوب")
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO quality_assistant_feedback
        (reply_id, rating, reason_ar, mode, intent, semester, department_id, actor)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rid[:80],
            r,
            (reason_ar or "")[:1000],
            (mode or "")[:64],
            (intent or "")[:64],
            (semester or "")[:120],
            int(department_id) if department_id is not None else None,
            (actor or "")[:120],
        ),
    )
    conn.commit()
    return {
        "status": "ok",
        "reply_id": rid,
        "rating": r,
        "message_ar": "شكراً — تم حفظ التقييم لتحسين المساعد.",
        "suggestion_only": True,
    }


def resolve_assistant_mode(
    *,
    role: str,
    requested: str | None = None,
    is_college_quality_lead: bool = False,
    is_dept_quality_coordinator: bool = False,
) -> str:
    """اختيار وضع المساعد المسموح حسب الدور/الأعلام."""
    role_n = (role or "").strip().lower()
    if role_n == "admin":
        role_n = "admin_main"

    allowed: list[str] = []
    for code, meta in ASSISTANT_MODES.items():
        if role_n in meta["session_roles"]:
            allowed.append(code)
            continue
        flags = meta.get("also_flags") or ()
        if "is_college_quality_lead" in flags and is_college_quality_lead:
            allowed.append(code)
        elif "is_dept_quality_coordinator" in flags and is_dept_quality_coordinator:
            allowed.append(code)

    # الأستاذ العادي: وضع instructor فقط
    if role_n == "instructor" and not is_dept_quality_coordinator:
        allowed = ["instructor"]
    elif role_n == "instructor" and is_dept_quality_coordinator:
        allowed = ["instructor", "head_of_department", "quality_committee"]

    if not allowed:
        # افتراضي آمن حسب الدور
        defaults = {
            "instructor": "instructor",
            "head_of_department": "head_of_department",
            "academic_vice_dean": "academic_vice_dean",
            "college_dean": "college_dean",
            "admin_main": "quality_committee",
            "system_admin": "quality_committee",
        }
        return defaults.get(role_n, "instructor")

    req = (requested or "").strip()
    if req in allowed:
        return req
    # الوضع الأساسي حسب الدور أولاً، ثم أوضاع إضافية (لجنة…)
    role_default = {
        "instructor": "instructor",
        "head_of_department": "head_of_department",
        "academic_vice_dean": "academic_vice_dean",
        "college_dean": "college_dean",
        "admin_main": "quality_committee",
        "system_admin": "quality_committee",
    }.get(role_n)
    if role_default and role_default in allowed:
        return role_default
    priority = [
        "college_dean",
        "academic_vice_dean",
        "quality_committee",
        "head_of_department",
        "instructor",
    ]
    for p in priority:
        if p in allowed:
            return p
    return allowed[0]


def allowed_modes_for_user(
    *,
    role: str,
    is_college_quality_lead: bool = False,
    is_dept_quality_coordinator: bool = False,
) -> list[dict[str, Any]]:
    role_n = (role or "").strip().lower()
    if role_n == "admin":
        role_n = "admin_main"
    out = []
    for code, meta in ASSISTANT_MODES.items():
        ok = role_n in meta["session_roles"]
        if not ok and "is_college_quality_lead" in (meta.get("also_flags") or ()) and is_college_quality_lead:
            ok = True
        if not ok and "is_dept_quality_coordinator" in (meta.get("also_flags") or ()) and is_dept_quality_coordinator:
            ok = True
        if role_n == "instructor" and not is_dept_quality_coordinator and code != "instructor":
            ok = False
        if ok:
            out.append(
                {
                    "code": code,
                    "title_ar": meta["title_ar"],
                    "subtitle_ar": meta["subtitle_ar"],
                    "phase": meta["phase"],
                    "intents": intents_for_mode(code),
                }
            )
    # ترتيب حسب المرحلة
    out.sort(key=lambda x: (x.get("phase") or 99, x.get("code") or ""))
    return out


def _dept_row(conn, department_id: int | None) -> dict[str, Any]:
    if not department_id:
        return {}
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id, code, name_ar FROM departments WHERE id = ?",
        (int(department_id),),
    ).fetchone()
    if not row:
        return {}
    if hasattr(row, "keys"):
        return {"id": int(row["id"]), "code": row["code"] or "", "name_ar": row["name_ar"] or ""}
    return {"id": int(row[0]), "code": row[1] or "", "name_ar": row[2] or ""}


def _archive_gaps(conn, department_id: int, semester: str) -> dict[str, Any]:
    try:
        from backend.services.department_archive_assistant import assistant_gap_report

        return assistant_gap_report(conn, department_id=department_id, semester=semester)
    except Exception as ex:
        return {"tips_ar": [f"تعذّر فحص الأرشيف: {ex}"], "suggestion_only": True}


def _compliance_summary(
    conn,
    *,
    semester: str,
    department_id: int | None,
    catalog_version: str,
    program_id: int | None = None,
) -> dict[str, Any]:
    try:
        from backend.services.institutional_accreditation import build_compliance_map

        data = build_compliance_map(
            conn,
            semester=semester,
            department_id=department_id,
            program_id=program_id,
            catalog_version=catalog_version,
        )
        summary = data.get("summary") or {}
        gaps = []
        for dom in data.get("domains") or []:
            for ind in dom.get("indicators") or []:
                st = (ind.get("assessment") or {}).get("compliance_status") or ""
                if st in ("gap", "not_started", "partial"):
                    gaps.append(
                        {
                            "code": ind.get("code"),
                            "title_ar": ind.get("title_ar"),
                            "status": st,
                        }
                    )
                    if len(gaps) >= 12:
                        break
            if len(gaps) >= 12:
                break
        return {
            "catalog_version": data.get("catalog_version") or catalog_version,
            "summary": summary,
            "top_gaps": gaps,
        }
    except Exception as ex:
        return {"error": str(ex), "summary": {}, "top_gaps": []}


def _quality_metrics_safe(conn, semester: str, department_id: int | None) -> dict[str, Any]:
    try:
        from backend.services.quality_metrics import compute_quality_metrics

        return compute_quality_metrics(conn, semester=semester, department_id=department_id) or {}
    except Exception:
        return {}


def build_context(
    conn,
    *,
    mode: str,
    semester: str | None = None,
    department_id: int | None = None,
) -> dict[str, Any]:
    sem = (semester or term_label_from_conn(conn)).strip()
    dept = _dept_row(conn, department_id)
    specialty = match_specialty_pack(dept.get("name_ar") or "", dept.get("code") or "")
    ctx: dict[str, Any] = {
        "semester": sem,
        "department": dept,
        "specialty_pack": {"code": specialty.get("code"), "title_ar": specialty.get("title_ar")},
        "policy_ar": POLICY_BANNER_AR,
        "suggestion_only": True,
    }

    if department_id and mode in (
        "instructor",
        "head_of_department",
        "quality_committee",
        "academic_vice_dean",
        "college_dean",
    ):
        if mode in ("head_of_department", "quality_committee", "instructor"):
            ctx["archive"] = _archive_gaps(conn, int(department_id), sem)

        if mode in ("head_of_department", "quality_committee"):
            from backend.core.accreditation_catalog import QAA_PROG_UG_CATALOG_VERSION

            ctx["prog"] = _compliance_summary(
                conn,
                semester=sem,
                department_id=int(department_id),
                catalog_version=QAA_PROG_UG_CATALOG_VERSION,
            )

        metrics = _quality_metrics_safe(conn, sem, int(department_id) if department_id else None)
        if metrics:
            ctx["metrics"] = {
                "overall_accreditation_score": metrics.get("overall_accreditation_score"),
                "program_score": metrics.get("program_score"),
                "institutional_score": metrics.get("institutional_score"),
                "accreditation_status_ar": metrics.get("accreditation_status_ar"),
            }

    if mode in ("academic_vice_dean", "college_dean", "quality_committee"):
        from backend.core.accreditation_catalog import QAA_INST_CATALOG_VERSION

        ctx["inst"] = _compliance_summary(
            conn,
            semester=sem,
            department_id=None,
            catalog_version=QAA_INST_CATALOG_VERSION,
        )
        college_metrics = _quality_metrics_safe(conn, sem, None)
        if college_metrics:
            ctx["college_metrics"] = {
                "overall_accreditation_score": college_metrics.get("overall_accreditation_score"),
                "program_score": college_metrics.get("program_score"),
                "institutional_score": college_metrics.get("institutional_score"),
                "accreditation_status_ar": college_metrics.get("accreditation_status_ar"),
            }
        # لمحة أقسام
        ctx["departments_overview"] = _departments_overview(conn, sem)

    return ctx


def _departments_overview(conn, semester: str) -> list[dict[str, Any]]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, code, name_ar FROM departments
        WHERE COALESCE(is_active, 1) = 1
        ORDER BY code
        LIMIT 40
        """
    ).fetchall() or []
    out = []
    for r in rows:
        did = int(r["id"] if hasattr(r, "keys") else r[0])
        name = (r["name_ar"] if hasattr(r, "keys") else r[2]) or ""
        code = (r["code"] if hasattr(r, "keys") else r[1]) or ""
        arch = _archive_gaps(conn, did, semester)
        missing = [t for t in (arch.get("tips_ar") or []) if "لا توجد فجوات" not in t]
        out.append(
            {
                "id": did,
                "code": code,
                "name_ar": name,
                "archive_open_issues": len(missing),
            }
        )
    return out


def _lines_from_gaps(gaps: list[dict], limit: int = 8) -> list[str]:
    lines = []
    for g in gaps[:limit]:
        lines.append(f"• {g.get('code')}: {g.get('title_ar')} [{g.get('status')}]")
    return lines


def _reply(mode: str, intent: str, message_ar: str, **extra: Any) -> dict[str, Any]:
    links = list(extra.get("links") or [])
    draft_text = extra.get("draft_text") or ""
    bullets = extra.get("bullets")
    actions_in = extra.pop("actions", None)
    skip_actions = bool(extra.pop("skip_actions", False))
    history_used = int(extra.pop("history_used", 0) or 0)
    reply_id = (extra.pop("reply_id", None) or str(uuid.uuid4()))[:48]
    payload = {
        "status": "ok",
        "mode": mode,
        "intent": intent,
        "message_ar": message_ar,
        "suggestion_only": True,
        "policy_ar": POLICY_BANNER_AR,
        "reply_id": reply_id,
        "history_used": history_used,
        **extra,
    }
    if not skip_actions:
        payload["actions"] = _enrich_actions(
            mode=mode,
            links=links,
            draft_text=str(draft_text or ""),
            message_ar=message_ar,
            bullets=list(bullets) if isinstance(bullets, list) else None,
            actions=list(actions_in) if isinstance(actions_in, list) else None,
        )
    elif actions_in is not None:
        payload["actions"] = list(actions_in)
    return payload


def _run_system_help(
    conn,
    *,
    mode: str,
    topic: str,
    notes: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """دردشة مساعدة استخدام المنظومة — خطوات وروابط صفحات."""
    hist = normalize_chat_history(history or [])
    # إن كان السؤال قصيراً جداً واستُخدم سياق سابق، ألحق آخر سؤال مستخدم
    q = (notes or topic or "").strip()
    if not q and hist:
        for h in reversed(hist):
            if h["role"] == "user":
                q = h["text"]
                break
    matched = None
    if topic and not notes:
        # اختيار موضوع سريع بالرمز أو العنوان
        tcode = topic.strip().lower()
        for t in SYSTEM_USAGE_TOPICS:
            if t.get("code") == tcode or (t.get("label_ar") or "") == topic.strip():
                matched = t
                break
    if matched is None:
        matched = match_system_usage_topic(q) or match_system_usage_topic(topic)

    if not q and matched is None:
        bullets = [
            *history_context_block(hist),
            "اكتب سؤالاً مثل: «كيف أفتح أرشيف القسم؟» أو اختر موضوعاً سريعاً من الأزرار.",
            "",
            "مواضيع جاهزة:",
        ]
        for t in SYSTEM_USAGE_TOPICS:
            bullets.append(f"• {t.get('label_ar')}")
        return _reply(
            mode,
            "system_help",
            "مساعدة استخدام المنظومة — اختر موضوعاً أو اكتب سؤالك.",
            bullets=bullets,
            system_usage_topics=[
                {"code": t["code"], "label_ar": t["label_ar"]} for t in SYSTEM_USAGE_TOPICS
            ],
            knowledge_tag="مساعدة استخدام",
            history_used=len(hist),
            links=[
                {"href": "/academic_quality/assistant", "label_ar": "المساعد"},
                {"href": "/academic_quality/glossary", "label_ar": "المصطلحات"},
            ],
        )

    if matched is None:
        # استرجاع خفيف من المكتبة إن وُجدت وثائق استخدام
        lib_bits: list[str] = []
        try:
            from backend.services.quality_knowledge import retrieve_knowledge

            kr = retrieve_knowledge(
                conn, query=q or topic, category=None, top_k=4, approved_only=True
            )
            for h in kr.get("hits") or []:
                lib_bits.append(f"• {h.get('title_ar')}: {(h.get('excerpt') or '')[:240]}")
        except Exception:
            lib_bits = []
        return _reply(
            mode,
            "system_help",
            "لم أطابق صفحة محددة — جرّب كلمات أوضح أو اختر موضوعاً سريعاً.",
            bullets=[
                *history_context_block(hist),
                f"سؤالك: {q or topic}",
                "",
                "اقتراحات عامة:",
                "• للجودة والاعتماد: لوحة الجودة ← خريطة الاعتماد ← الأرشيف.",
                "• للاستبيانات: إدارة البنود أو مركز التعبئة.",
                "• لمخرجات المقرر: مقرراتي ← تقييم CLO ← تقرير الإغلاق.",
                "",
                "من مكتبة المعرفة:",
                *(lib_bits or ["• لا مقاطع مطابقة حالياً."]),
            ],
            knowledge_tag="مساعدة استخدام",
            history_used=len(hist),
            links=[
                {"href": "/academic_quality/dashboard", "label_ar": "لوحة الجودة"},
                {"href": "/academic_quality/glossary", "label_ar": "المصطلحات"},
                {"href": "/academic_quality/assistant/knowledge", "label_ar": "مكتبة المعرفة"},
            ],
        )

    steps = [f"{i + 1}) {s}" for i, s in enumerate(matched.get("steps_ar") or [])]
    return _reply(
        mode,
        "system_help",
        f"موضوع: {matched.get('label_ar')}",
        bullets=[
            *history_context_block(hist),
            f"سؤالك: {q or matched.get('label_ar')}",
            "",
            "خطوات مقترحة:",
            *steps,
            "",
            "ملاحظة: هذه إرشادات استخدام — ليست اعتماد امتثال.",
        ],
        matched_topic=matched.get("code"),
        knowledge_tag="مساعدة استخدام",
        history_used=len(hist),
        links=list(matched.get("links") or []),
    )


def _run_discuss(
    conn,
    *,
    mode: str,
    topic: str,
    notes: str,
    ctx: dict[str, Any],
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """مناقشة حرة مقيّدة بالدور + استرجاع من مكتبة المعرفة — اقتراح دون اعتماد."""
    hist = normalize_chat_history(history or [])
    q = (notes or topic or "").strip()
    if not q and hist:
        for h in reversed(hist):
            if h["role"] == "user":
                q = h["text"]
                break
    # حوّل لمساعدة الاستخدام فقط إذا ظهر قصد تشغيلي واضح (صفحة/فتح/قائمة)
    # وتجنّب خلط أسئلة الصياغة («كيف أحسّن رسالة…»).
    usage_nav = any(
        k in q
        for k in (
            "أين",
            "وين",
            "افتح",
            "فتح",
            "صفحة",
            "قائمة",
            "القائمة",
            "رابط",
            "استخدام المنظومة",
            "كيف أستخدم",
            "كيف افتح",
            "كيف أفتح",
        )
    )
    if q and usage_nav and match_system_usage_topic(q):
        return _run_system_help(conn, mode=mode, topic=topic, notes=notes)

    if not q:
        guide = ROLE_DISCUSSION_GUIDE.get(mode) or {}
        return _reply(
            mode,
            "discuss",
            "اكتب سؤالك في الدردشة ثم أرسل — أو اختر موضوعاً سريعاً أعلاه.",
            bullets=guide.get("how_ar") or [],
            example_prompts_ar=guide.get("example_prompts_ar") or [],
            discussion_guide=guide,
        )

    dept = ctx.get("department") or {}
    pack = match_specialty_pack(dept.get("name_ar") or "", dept.get("code") or "")
    meta = ASSISTANT_MODES.get(mode) or {}
    ql = q.lower()

    # RAG خفيف من المكتبة المعتمدة
    knowledge_hits: list[dict[str, Any]] = []
    try:
        from backend.services.quality_knowledge import retrieve_knowledge

        dept_id = dept.get("id")
        kr = retrieve_knowledge(
            conn,
            query=" ".join([q] + [h["text"] for h in hist if h["role"] == "user"][-2:]),
            department_id=int(dept_id) if dept_id is not None else None,
            top_k=5,
            approved_only=True,
            prefer_department=True,
        )
        knowledge_hits = list(kr.get("hits") or [])
    except Exception:
        knowledge_hits = []

    focus_bits: list[str] = []
    focus_bits.extend(history_context_block(hist))
    if knowledge_hits:
        focus_bits.append("من مكتبة المعرفة المعتمدة داخل المنظومة:")
        for h in knowledge_hits[:5]:
            focus_bits.append(
                f"• [{h.get('title_ar')}] { (h.get('excerpt') or '')[:320] }"
            )
        focus_bits.append("")

    if any(k in q for k in ("رسالة", "رؤية", "mission", "vision")):
        focus_bits.extend(pack.get("mission_vision_tips_ar") or [])
    if any(k in q for k in ("مخرج", "CLO", "PLO", "GLO", "clo", "plo", "obe")):
        focus_bits.extend(pack.get("outcomes_tips_ar") or pack.get("tips_ar") or [])
    if any(k in q for k in ("أرشيف", "شاهد", "محضر", "دليل")):
        focus_bits.extend(pack.get("evidence_hints_ar") or [])
        arch = (ctx.get("archive") or {}).get("tips_ar") or []
        focus_bits.extend(arch[:4])
    if any(k in q for k in ("استبيان", "رضا", "تقييم")):
        focus_bits.append(
            "استخرج البنود الضعيفة من نتائج الاستبيانات وصِغ توصية قابلة للتنفيذ، ثم اربط الشاهد يدوياً إن لزم."
        )
    if any(k in q for k in ("اعتماد", "QAA", "INST", "PROG", "امتثال")):
        focus_bits.append(
            "الامتثال المحلي عبر INST/PROG فقط؛ المراجع العالمية للصياغة والمناقشة وليست بديلاً عن المركز."
        )
        inst_gaps = _lines_from_gaps((ctx.get("inst") or {}).get("top_gaps") or [], 4)
        prog_gaps = _lines_from_gaps((ctx.get("prog") or {}).get("top_gaps") or [], 4)
        focus_bits.extend(inst_gaps)
        focus_bits.extend(prog_gaps)

    if len(focus_bits) <= 2:
        focus_bits.extend(list(pack.get("tips_ar") or [])[:3])
        focus_bits.extend((pack.get("review_questions_ar") or [])[:3])

    role_next = {
        "instructor": "إن لزم التصعيد: مسودة لرئيس القسم.",
        "head_of_department": "يمكنك طلب موجز لجنة أو تصعيد لوكيل/لجنة.",
        "academic_vice_dean": "يمكنك تصعيد موجز للعميد أو بنود للجنة.",
        "quality_committee": "حوّل النقاش إلى توصية مسودة أو محضر بعد الاتفاق البشري.",
        "college_dean": "اطلب من اللجنة إجابة محددة قبل قرار الموارد.",
    }.get(mode, "")

    bullets = [
        f"وضعي كمساعد ({meta.get('title_ar') or mode}) — عدسة: {meta.get('lens_ar') or '—'}",
        f"سؤالك: {q}",
        "",
        "زاوية النقاش المقترحة:",
        *[f"• {b}" if not str(b).startswith("•") and not str(b).startswith("من ") else str(b) for b in focus_bits[:16]],
        "",
        f"حزمة القسم المرجعية: {pack.get('title_ar')} ({pack.get('code')})",
        pack.get("disclaimer_ar") or POLICY_BANNER_AR,
    ]
    if role_next:
        bullets.extend(["", role_next])

    if "abet" in ql or "cdio" in ql:
        bullets.append("راجع مكتبة المعرفة أو تحميل بطاقات المراجع للاطلاع الرسمي.")

    return _reply(
        mode,
        "discuss",
        "رد مناقشة (من المكتبة + القواعد — غير ملزم):",
        bullets=bullets,
        knowledge_hits=knowledge_hits,
        pack_code=pack.get("code"),
        global_refs=(pack.get("global_refs") or [])[:4],
        example_prompts_ar=(ROLE_DISCUSSION_GUIDE.get(mode) or {}).get("example_prompts_ar") or [],
        knowledge_tag="مناقشة · مكتبة معرفة + مرجع عالمي + سياق منظومة",
        history_used=len(hist),
        draft_text="\n".join(str(b) for b in bullets if str(b).strip())[:3500],
        links=[
            {"href": "/academic_quality/assistant/knowledge", "label_ar": "مكتبة المعرفة"},
            {"href": "/academic_quality/assistant/references.zip", "label_ar": "بطاقات مراجع ZIP"},
            {"href": "/academic_quality/assistant/knowledge/export.zip", "label_ar": "تصدير المعتمد"},
        ],
    )


def _finalize_assistant_result(
    conn,
    result: dict[str, Any],
    *,
    mode: str,
    intent: str,
    department_id: int | None = None,
    actor: str = "",
    notes: str = "",
    page_path: str = "",
    channel: str = "assistant",
    enhance_llm: bool = False,
) -> dict[str, Any]:
    """إثراء LLM اختياري؛ تسجيل الاستخدام يتم من مسار الـ API."""
    _ = (conn, mode, department_id, actor, page_path, channel)
    out = dict(result or {})
    try:
        if enhance_llm and (notes or "").strip():
            from backend.services.quality_assistant_advanced import enhance_with_optional_llm

            out = enhance_with_optional_llm(out, user_question=notes)
    except Exception:
        pass
    if intent in ("committee_summary", "export_committee") and out.get("committee_summary"):
        out["export_ready"] = True
    return out


def build_references_zip_bytes(*, primary_only: bool = True) -> bytes:
    import io
    import zipfile

    payload = exportable_specialty_packs(primary_only=primary_only)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "README_AR.md",
            "\n".join(
                [
                    "# حزم المراجع العالمية — مساعد الجودة",
                    "",
                    payload.get("disclaimer_ar") or "",
                    "",
                    payload.get("note_ar") or "",
                    "",
                    "الملفات التالية لكل قسم معتمد في المنظومة.",
                ]
            ),
        )
        zf.writestr(
            "all_packs.json",
            __import__("json").dumps(payload, ensure_ascii=False, indent=2),
        )
        for pack in payload.get("packs") or []:
            code = pack.get("code") or "pack"
            zf.writestr(f"{code}_references.md", specialty_pack_to_markdown(pack))
    return buf.getvalue()


def run_quality_assistant(
    conn,
    *,
    mode: str,
    intent: str,
    semester: str | None = None,
    department_id: int | None = None,
    topic: str = "",
    notes: str = "",
    actor: str = "",
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    mode_l = (mode or "").strip()
    if mode_l not in ASSISTANT_MODES:
        raise ValueError("وضع المساعد غير معروف")
    intent_l = (intent or "help").strip().lower()
    hist = normalize_chat_history(history or [])
    ctx = build_context(conn, mode=mode_l, semester=semester, department_id=department_id)
    sem = ctx["semester"]
    dept_name = (ctx.get("department") or {}).get("name_ar") or "القسم"

    if intent_l in ("welcome", "brief"):
        welcome = build_welcome_brief(
            conn, mode=mode_l, semester=sem, department_id=department_id
        )
        bullets = ["أهم المهام المقترحة الآن:"]
        actions = []
        for i, t in enumerate(welcome.get("tasks") or [], 1):
            bullets.append(f"{i}) {t.get('title_ar')}")
            if t.get("href"):
                actions.append(
                    {
                        "type": "open_link",
                        "label_ar": f"فتح: {(t.get('title_ar') or '')[:40]}",
                        "href": t["href"],
                    }
                )
        if not (welcome.get("tasks") or []):
            bullets.append("• لا فجوات بارزة حالياً — يمكنك بدء دردشة أو اختيار موضوع سريع.")
        return _reply(
            mode_l,
            "welcome",
            welcome.get("message_ar") or welcome.get("greeting_ar") or "مرحباً",
            bullets=bullets,
            welcome=welcome,
            actions=actions,
            knowledge_tag="ترحيب سياقي",
        )

    if intent_l in ("help", "start", "hi"):
        intents = intents_for_mode(mode_l)
        meta = ASSISTANT_MODES[mode_l]
        welcome = build_welcome_brief(
            conn, mode=mode_l, semester=sem, department_id=department_id
        )
        bullets = [
            "استخدم تبويب «دردشة الجودة» للصياغة والمعايير، أو «مساعدة المنظومة» لأسئلة الاستخدام.",
            "الأزرار أعلاه «مواضيع سريعة» — اختر موضوعاً أو اكتب سؤالك في الدردشة.",
            "",
            "مواضيع سريعة متاحة:",
            *[f"• {it.get('label_ar')}" for it in intents[:12]],
        ]
        if welcome.get("tasks"):
            bullets.extend(["", "أبرز مهام من السياق:"])
            for t in welcome["tasks"]:
                bullets.append(f"• {t.get('title_ar')}")
        return _reply(
            mode_l,
            "help",
            f"{meta['title_ar']}: {meta['subtitle_ar']}. {POLICY_BANNER_AR}",
            topics=intents,
            intents=intents,
            welcome=welcome,
            context_preview={
                "semester": sem,
                "department": ctx.get("department"),
            },
            bullets=bullets,
            history_used=len(hist),
        )

    if intent_l == "global_tips":
        return _reply(
            mode_l,
            intent_l,
            "مبادئ مرجعية مختصرة للصياغة والمناقشة — راجع دائماً معيار QAA المحلي قبل الاعتماد.",
            tips=GLOBAL_REFERENCE_TIPS,
            knowledge_tag="مرجع عالمي",
            history_used=len(hist),
        )

    if intent_l in ("system_help", "usage_help", "how_to"):
        return _finalize_assistant_result(
            conn,
            _run_system_help(
                conn,
                mode=mode_l,
                topic=topic,
                notes=notes,
                history=hist,
            ),
            mode=mode_l,
            intent=intent_l,
            department_id=department_id,
            actor=actor,
            notes=notes,
            enhance_llm=False,
        )

    if intent_l == "discuss":
        return _finalize_assistant_result(
            conn,
            _run_discuss(
                conn,
                mode=mode_l,
                topic=topic,
                notes=notes,
                ctx=ctx,
                history=hist,
            ),
            mode=mode_l,
            intent=intent_l,
            department_id=department_id,
            actor=actor,
            notes=notes,
            enhance_llm=True,
        )

    if intent_l in ("committee_summary", "export_committee"):
        from backend.services.quality_assistant_advanced import build_committee_summary

        summary = build_committee_summary(
            conn,
            mode=mode_l,
            semester=sem,
            department_id=department_id,
            notes=notes,
            history=hist,
        )
        return _finalize_assistant_result(
            conn,
            _reply(
                mode_l,
                "committee_summary",
                summary.get("sections", {}).get("title_ar") or "مسودة ملخص لجنة",
                bullets=[
                    summary.get("sections", {}).get("disclaimer_ar") or POLICY_BANNER_AR,
                    "",
                    "بنود الأجندة:",
                    *[f"• {a}" for a in (summary.get("sections", {}).get("agenda") or [])],
                    "",
                    "للتصدير: استخدم أزرار Word/PDF/Markdown أسفل الرد أو روابط التصدير.",
                ],
                draft_text=summary.get("markdown") or "",
                committee_summary=summary,
                knowledge_tag="ملخص لجنة · مسودة",
                links=[
                    {
                        "href": "/academic_quality/assistant/export/committee.md",
                        "label_ar": "تنزيل Markdown",
                    },
                    {
                        "href": "/academic_quality/assistant/export/committee.docx",
                        "label_ar": "تنزيل Word",
                    },
                    {
                        "href": "/academic_quality/assistant/export/committee.pdf",
                        "label_ar": "تنزيل PDF",
                    },
                ],
                actions=[
                    {
                        "type": "open_link",
                        "label_ar": "Word",
                        "href": "/academic_quality/assistant/export/committee.docx",
                    },
                    {
                        "type": "open_link",
                        "label_ar": "PDF",
                        "href": "/academic_quality/assistant/export/committee.pdf",
                    },
                    {
                        "type": "copy_text",
                        "label_ar": "انسخ الملخص",
                        "text": summary.get("markdown") or "",
                    },
                ],
            ),
            mode=mode_l,
            intent=intent_l,
            department_id=department_id,
            actor=actor,
            notes=notes,
        )

    if intent_l in ("archive_link_suggest", "archive_suggest"):
        from backend.services.quality_assistant_advanced import suggest_archive_links

        sug = suggest_archive_links(
            conn,
            mode=mode_l,
            semester=sem,
            department_id=department_id,
            notes=notes or topic,
        )
        bullets = [sug.get("message_ar") or "", ""]
        for s in sug.get("suggestions") or []:
            bullets.append(
                f"• {s.get('gap_label_ar')} → {s.get('record_type_label_ar')}: {s.get('why_ar')}"
            )
            for qaa in (s.get("qaa_suggestions") or [])[:2]:
                if isinstance(qaa, dict):
                    bullets.append(
                        f"   – مؤشر مرشّح: {qaa.get('indicator_code') or '—'} ({qaa.get('catalog_version') or ''})"
                    )
                else:
                    bullets.append(f"   – مؤشر مرشّح: {qaa}")
        return _finalize_assistant_result(
            conn,
            _reply(
                mode_l,
                "archive_link_suggest",
                "اقتراحات ربط أرشيف (يدوي فقط)",
                bullets=bullets,
                archive_suggestions=sug.get("suggestions") or [],
                knowledge_tag="أرشيف · اقتراح ربط",
                links=sug.get("links") or [],
            ),
            mode=mode_l,
            intent=intent_l,
            department_id=department_id,
            actor=actor,
            notes=notes,
        )

    if intent_l in ("proofread", "writing_coach", "polish"):
        from backend.services.quality_assistant_advanced import proofread_quality_text

        kind = (topic or "auto").strip().lower()
        if kind not in ("auto", "mission", "vision", "clo"):
            kind = "auto"
        pr = proofread_quality_text(text=notes, kind=kind, use_llm=True)
        return _finalize_assistant_result(
            conn,
            _reply(
                mode_l,
                "proofread",
                pr.get("message_ar") or "مدقق صياغة",
                bullets=[
                    pr.get("disclaimer_ar") or "",
                    pr.get("llm_note_ar") or "",
                    "",
                    "ملاحظات:",
                    *[f"• {i}" for i in (pr.get("issues") or [])],
                    "",
                    "نص محسّن مقترح:",
                    pr.get("improved_ar") or "",
                ],
                draft_text=pr.get("improved_ar") or "",
                proofread=pr,
                knowledge_tag="مدقق صياغة",
                links=[
                    {"href": "/academic_quality/college", "label_ar": "هوية الكلية"},
                    {"href": "/academic_quality/glossary", "label_ar": "المصطلحات"},
                ],
            ),
            mode=mode_l,
            intent=intent_l,
            department_id=department_id,
            actor=actor,
            notes=notes,
        )

    if intent_l in ("proactive_alerts", "term_alerts", "alerts"):
        from backend.services.quality_assistant_advanced import proactive_term_alerts

        al = proactive_term_alerts(
            conn, mode=mode_l, semester=sem, department_id=department_id
        )
        bullets = [al.get("message_ar") or "", ""]
        actions = []
        for i, a in enumerate(al.get("alerts") or [], 1):
            bullets.append(f"{i}) [{a.get('severity_ar')}] {a.get('title_ar')}")
            if a.get("href"):
                actions.append(
                    {
                        "type": "open_link",
                        "label_ar": f"فتح {i}",
                        "href": a["href"],
                    }
                )
        return _finalize_assistant_result(
            conn,
            _reply(
                mode_l,
                "proactive_alerts",
                "تنبيهات استباقية قبل إغلاق الفصل",
                bullets=bullets,
                alerts=al.get("alerts") or [],
                actions=actions,
                knowledge_tag="تنبيهات فصلية",
                links=[{"href": "/academic_quality/dashboard", "label_ar": "لوحة الجودة"}],
            ),
            mode=mode_l,
            intent=intent_l,
            department_id=department_id,
            actor=actor,
            notes=notes,
        )

    if intent_l in ("usage_insights", "usage_stats"):
        from backend.services.quality_assistant_advanced import usage_analytics_summary

        # متاح للجنة/عمادة/وكيل/إدارة — وإلا موجز مختصر
        if mode_l not in (
            "quality_committee",
            "college_dean",
            "academic_vice_dean",
        ) and actor:
            pass
        stats = usage_analytics_summary(conn, limit=15)
        bullets = [
            stats.get("note_ar") or "",
            f"إجمالي الأحداث: {stats.get('total_events') or 0}",
            "",
            "الأكثر طلباً:",
        ]
        for row in stats.get("top") or []:
            bullets.append(
                f"• {row.get('intent') or '—'} / {row.get('mode') or '—'} ({row.get('count')})"
            )
        return _finalize_assistant_result(
            conn,
            _reply(
                mode_l,
                "usage_insights",
                "سجل استخدام المساعد (ملخص)",
                bullets=bullets,
                usage=stats,
                knowledge_tag="تحليل استخدام",
                links=[
                    {
                        "href": "/academic_quality/assistant/export/style-pack.zip",
                        "label_ar": "حزمة أسلوب للتدريب لاحقاً",
                    }
                ],
            ),
            mode=mode_l,
            intent=intent_l,
            department_id=department_id,
            actor=actor,
            notes=notes,
        )

    if intent_l == "specialty_pack":
        from backend.core.quality_assistant_catalog import approved_global_refs_for_pack

        pack = match_specialty_pack(
            (ctx.get("department") or {}).get("name_ar") or "",
            (ctx.get("department") or {}).get("code") or "",
        )
        frameworks = [
            f"• {f.get('name')}: {f.get('role_ar')} — {f.get('note_ar')}"
            for f in (pack.get("frameworks") or [])
        ]
        refs = [
            f"• {r.get('label_ar')}: {r.get('cite')} ({r.get('use_ar')})"
            for r in (pack.get("global_refs") or [])
        ]
        approved = approved_global_refs_for_pack(pack.get("code"))
        approved_bits = [
            f"• {r.get('label_ar')} — {r.get('scope_ar')} ({r.get('official_url')})"
            for r in approved[:10]
        ]
        lib_bits: list[str] = []
        try:
            from backend.services.quality_knowledge import retrieve_knowledge

            dept = ctx.get("department") or {}
            kr = retrieve_knowledge(
                conn,
                query=f"{pack.get('title_ar')} {pack.get('title_en') or ''} مخرجات رسالة مراجع ABET EUR-ACE CDIO",
                department_id=int(dept["id"]) if dept.get("id") is not None else None,
                category="global_summary",
                top_k=5,
                approved_only=True,
            )
            for h in kr.get("hits") or []:
                lib_bits.append(f"• من المكتبة — {h.get('title_ar')}: {(h.get('excerpt') or '')[:280]}")
        except Exception:
            lib_bits = []
        return _reply(
            mode_l,
            intent_l,
            f"حزمة مراجع للقسم: {pack.get('title_ar')}",
            disclaimer_ar=pack.get("disclaimer_ar"),
            bullets=[
                pack.get("disclaimer_ar") or "",
                "",
                "مراجع عالمية معتمدة (بطاقات المنظومة):",
                *(approved_bits or ["—"]),
                "",
                "من مكتبة المعرفة المعتمدة:",
                *(lib_bits or ["• لا وثائق معتمدة بعد — افتح مكتبة المعرفة لبذر/رفع وثائق."]),
                "",
                "أطر مقترحة للمناقشة:",
                *(frameworks or ["—"]),
                "",
                "صياغة رسالة/رؤية:",
                *[f"• {t}" for t in (pack.get("mission_vision_tips_ar") or [])],
                "",
                "مخرجات التعلم:",
                *[f"• {t}" for t in (pack.get("outcomes_tips_ar") or pack.get("tips_ar") or [])],
                "",
                "أسئلة مراجعة للجنة/القسم:",
                *[f"؟ {q}" for q in (pack.get("review_questions_ar") or [])],
                "",
                "شواهد محتملة (بعد ربط يدوي):",
                *[f"• {e}" for e in (pack.get("evidence_hints_ar") or [])],
                "",
                "مراجع للاطلاع:",
                *(refs or ["—"]),
            ],
            frameworks=pack.get("frameworks") or [],
            global_refs=pack.get("global_refs") or [],
            approved_global_references=approved,
            review_questions_ar=pack.get("review_questions_ar") or [],
            pack_code=pack.get("code"),
            knowledge_tag="مكتبة معرفة + مرجع عالمي تخصصي",
            links=[
                {"href": "/academic_quality/assistant/knowledge", "label_ar": "مكتبة المعرفة"},
                {"href": "/academic_quality/assistant/knowledge/export.zip", "label_ar": "تصدير المعتمد"},
            ],
        )

    # ——— م1 أستاذ ———
    if mode_l == "instructor":
        if intent_l == "clo_tips":
            return _reply(
                mode_l,
                intent_l,
                "اقتراحات صياغة CLO (للمراجعة):",
                bullets=[
                    "ابدأ بفعل قابل للقياس (يحسب، يصمم، يفسّر، يطبّق).",
                    "اربط كل CLO بمخرج برنامج (PLO) واحد على الأقل.",
                    "حدّد أداة القياس (اختبار، مشروع، تقرير).",
                    "تجنّب الصياغات الفضفاضة مثل «يفهم المقرر جيداً».",
                ],
                knowledge_tag="مرجع عالمي + منظومة",
                escalate_hint="escalate_hod",
            )
        if intent_l == "closure_checklist":
            return _reply(
                mode_l,
                intent_l,
                "قائمة تحقق إغلاق المقرر المقترحة:",
                bullets=[
                    "رصد الدرجات واكتمال الشعب.",
                    "تقييم CLO لكل شعبة مع ملاحظات.",
                    "توصيات تحسين للفصل القادم.",
                    "مراجعة بنود استبيان المقرر الضعيفة إن ظهرت.",
                    "رفع تقرير الإغلاق لرئيس القسم.",
                ],
                links=[
                    {"href": "/my_courses", "label_ar": "مقرراتي"},
                    {"href": "/academic_quality/surveys", "label_ar": "الاستبيانات"},
                ],
            )
        if intent_l == "survey_explain":
            return _reply(
                mode_l,
                intent_l,
                "كيف تقرأ نتائج استبيان المقرر:",
                bullets=[
                    "ابنود تحت ~60% أولوية تحسين فورية.",
                    "اربط كل بند ضعيف بإجراء في خطة المقرر أو أسلوب التقييم.",
                    "بعد التحسين، صدّر التقرير وقدّمه لرئيس القسم كشاهد مقترح — الربط اليدوي يتم من الخريطة/الأرشيف.",
                ],
                links=[
                    {"href": "/academic_quality/surveys/results", "label_ar": "نتائج الاستبيانات"},
                ],
            )
        if intent_l in ("course_report_mine", "course_quality_report"):
            from backend.services import course_delivery as cd

            iid = None
            if actor:
                row = conn.cursor().execute(
                    "SELECT instructor_id FROM users WHERE username = ? LIMIT 1",
                    (actor.strip(),),
                ).fetchone()
                if row:
                    iid = row[0] if not hasattr(row, "keys") else row["instructor_id"]
            idx = cd.build_course_reports_index(
                conn,
                semester=sem,
                instructor_id=int(iid) if iid else -1,
            )
            rows = idx.get("rows") or []
            bullets = [
                f"لديك {len(rows)} مجموعة تدريس في فصل {sem}.",
                "المعاينة/الطباعة من رابط المقرر أدناه — الشاهد المقترح: course_delivery_quality_report (ربط يدوي بعد المراجعة).",
            ]
            links = [
                {"href": "/academic_quality/surveys", "label_ar": "تعبئة الاستبيانات"},
            ]
            for r in rows[:8]:
                links.append(
                    {
                        "href": r.get("preview_url")
                        or f"/academic_quality/course_reports/{r.get('teaching_group_id')}",
                        "label_ar": f"معاينة: {r.get('course_name')}",
                    }
                )
                bullets.append(
                    f"• {r.get('course_name')}: نسبة "
                    f"{r.get('overall_pct') if r.get('overall_pct') is not None else '—'} — "
                    f"جزئي {r.get('partial_status_ar')} / نهائي {r.get('final_status_ar')}"
                )
            if not rows:
                bullets.append("لا مقررات مرتبطة بحسابك حالياً — افتح مقرراتي أولاً.")
                links.append({"href": "/my_courses", "label_ar": "مقرراتي"})
            return _reply(
                mode_l,
                intent_l,
                "تقارير جودة مقرراتك (تنفيذ المفردات)",
                bullets=bullets,
                links=links,
                knowledge_tag="شاهد مقترح · تقرير مقرر",
            )
        if intent_l == "escalate_hod":
            body = notes.strip() or (
                f"مسودة من مساعد الأستاذ — فصل {sem}\n"
                f"الموضوع: {topic or 'متابعة جودة المقرر'}\n"
                "يُرجى مراجعة: اكتمال CLO/الإغلاق وبنود الاستبيان الضعيفة."
            )
            return _draft_escalation(
                conn,
                from_mode=mode_l,
                to_mode="head_of_department",
                title_ar=topic or "رفع من أستاذ إلى رئيس القسم",
                body_ar=body,
                semester=sem,
                department_id=department_id,
                actor=actor,
            )

    # ——— م1 رئيس قسم ———
    if mode_l == "head_of_department":
        if intent_l == "dept_snapshot":
            metrics = ctx.get("metrics") or {}
            arch_tips = (ctx.get("archive") or {}).get("tips_ar") or []
            prog = ctx.get("prog") or {}
            return _reply(
                mode_l,
                intent_l,
                f"موجز {dept_name} — {sem}",
                bullets=[
                    f"مؤشر تشغيلي داخلي: {metrics.get('overall_accreditation_score', '—')} "
                    f"({metrics.get('accreditation_status_ar') or '—'}) — ليس درجة اعتماد رسمية.",
                    f"برامجي: {metrics.get('program_score', '—')}% · مؤسسي ضمن التجميع: {metrics.get('institutional_score', '—')}%",
                    f"تقدم برامجي موثّق: {(prog.get('summary') or {}).get('documented_progress_percent', '—')}%",
                    *(arch_tips[:5] or ["لا ملاحظات أرشيف إضافية."]),
                ],
                top_gaps=_lines_from_gaps(prog.get("top_gaps") or []),
                links=[
                    {"href": "/academic_quality/archive", "label_ar": "أرشيف القسم"},
                    {"href": "/academic_quality/accreditation/map?scope=prog", "label_ar": "امتثال برامجي"},
                ],
            )
        if intent_l == "archive_gaps":
            arch = ctx.get("archive") or {}
            return _reply(
                mode_l,
                intent_l,
                arch.get("assistant_message_ar") or "فحص أرشيف القسم",
                tips_ar=arch.get("tips_ar") or [],
                checklist=arch.get("rows"),
                links=[{"href": "/academic_quality/archive", "label_ar": "فتح الأرشيف"}],
            )
        if intent_l == "prog_gaps":
            prog = ctx.get("prog") or {}
            lines = _lines_from_gaps(prog.get("top_gaps") or [])
            return _reply(
                mode_l,
                intent_l,
                "أبرز فجوات/نواقص الامتثال البرامجي (اقتراح مراجعة):",
                bullets=lines or ["لا فجوات ظاهرة في العيّنة المسترجعة — راجع الخريطة كاملة."],
                summary=prog.get("summary"),
                links=[
                    {"href": "/academic_quality/accreditation/map?scope=prog", "label_ar": "خريطة برامجية"},
                ],
            )
        if intent_l == "survey_weak":
            return _reply(
                mode_l,
                intent_l,
                "ضعاف الاستبيانات — مسار مقترح:",
                bullets=[
                    "افتح نتائج الاستبيانات حسب الفصل والقسم.",
                    "حدّد البنود < 60% وصِغ توصية لكل بند.",
                    "ارفع التوصيات كمسودة للجنة أو وثّقها في الأرشيف ثم اربطها يدوياً بمؤشر PROG/INST.",
                ],
                links=[
                    {"href": "/academic_quality/surveys/results", "label_ar": "نتائج الاستبيانات"},
                ],
            )
        if intent_l in ("course_report_gaps", "course_reports"):
            from backend.services import course_delivery as cd

            idx = cd.build_course_reports_index(
                conn,
                semester=sem,
                department_id=department_id,
                status_filter="low",
            )
            sum_ = idx.get("summary") or {}
            low_rows = (idx.get("rows") or [])[:8]
            bullets = [
                f"ملخص القسم — فصل {sem}: مجموعات {sum_.get('groups_total', 0)} · "
                f"مُرسل {sum_.get('submitted', 0)} · منخفضة {sum_.get('low_completion', 0)} · "
                f"نقص كتب {sum_.get('missing_books', 0)}",
                "الشاهد المقترح للاعتماد: course_delivery_quality_report — اربطه يدوياً بعد المراجعة.",
            ]
            for r in low_rows:
                bullets.append(
                    f"• {r.get('course_name')} ({r.get('instructor_name')}): "
                    f"{r.get('overall_pct') if r.get('overall_pct') is not None else '—'}% — "
                    f"فجوات {r.get('incomplete_count', 0)}"
                )
            if not low_rows:
                bullets.append("لا مقررات بنسبة منخفضة في التصفية الحالية — راجع الفهرس الكامل.")
            return _reply(
                mode_l,
                intent_l,
                "فجوات تقارير جودة المقررات",
                bullets=bullets,
                links=[
                    {"href": "/academic_quality/course_reports", "label_ar": "فهرس تقارير المقررات"},
                    {"href": "/academic_quality/course_reports/package", "label_ar": "حزمة للطباعة"},
                    {"href": "/course_delivery_hod_page", "label_ar": "لوحة رئيس القسم"},
                    {
                        "href": "/academic_quality/accreditation/map?scope=prog",
                        "label_ar": "ربط الشاهد في الاعتماد",
                    },
                ],
                knowledge_tag="شاهد مقترح · تقرير مقرر",
            )
        if intent_l == "brief_for_committee":
            prog = ctx.get("prog") or {}
            arch_tips = (ctx.get("archive") or {}).get("tips_ar") or []
            body_lines = [
                f"موجز جلسة — {dept_name} — {sem}",
                "",
                "1) نواقص الأرشيف:",
                *(arch_tips[:6] or ["لا نواقص ظاهرة."]),
                "",
                "2) أبرز مؤشرات برامجية للمراجعة:",
                *(_lines_from_gaps(prog.get("top_gaps") or []) or ["—"]),
                "",
                "3) مقترح نقاش: ضعاف الاستبيانات وخطة التحسين.",
                "",
                "(مسودة من المساعد — تحتاج اعتماد رئيس القسم قبل الجلسة)",
            ]
            return _reply(
                mode_l,
                intent_l,
                "مسودة موجز لجلسة لجنة الجودة:",
                draft_text="\n".join(body_lines),
                escalate_hint="escalate_committee",
            )
        if intent_l == "escalate_vice":
            return _draft_escalation(
                conn,
                from_mode=mode_l,
                to_mode="academic_vice_dean",
                title_ar=topic or f"متابعة تشغيلية — {dept_name}",
                body_ar=notes.strip()
                or f"مسودة من رئيس القسم ({dept_name}) — فصل {sem}. يُرجى متابعة النواقص الأكاديمية/الجودة.",
                semester=sem,
                department_id=department_id,
                actor=actor,
            )
        if intent_l == "escalate_committee":
            return _draft_escalation(
                conn,
                from_mode=mode_l,
                to_mode="quality_committee",
                title_ar=topic or f"بند أجندة — {dept_name}",
                body_ar=notes.strip()
                or (ctx.get("archive") or {}).get("assistant_message_ar")
                or f"بند مقترح للجنة الجودة من قسم {dept_name} — {sem}",
                semester=sem,
                department_id=department_id,
                actor=actor,
            )

    # ——— م2 وكيل ———
    if mode_l == "academic_vice_dean":
        if intent_l == "college_ops":
            overview = ctx.get("departments_overview") or []
            flagged = [d for d in overview if int(d.get("archive_open_issues") or 0) > 0]
            flag_lines = [
                f"• {d.get('code')} — {d.get('name_ar')}: {d.get('archive_open_issues')} ملاحظة"
                for d in flagged[:10]
            ] or ["لا تنبيهات أرشيف ظاهرة في المسح السريع."]
            return _reply(
                mode_l,
                intent_l,
                f"متابعة تشغيلية — {sem}",
                bullets=[
                    f"عدد الأقسام الممسوحة: {len(overview)}",
                    f"أقسام لديها تنبيهات أرشيف: {len(flagged)}",
                    *flag_lines,
                ],
                departments=overview,
            )
        if intent_l == "closure_coverage":
            return _reply(
                mode_l,
                intent_l,
                "اكتمال الإغلاقات — توجيه تشغيلي:",
                bullets=[
                    "راجع تقارير إغلاق المقررات المتأخرة مع رؤساء الأقسام.",
                    "اربط التأخير بأثره على لوحة المخرجات والشواهد.",
                    "صعّد للعميد فقط البنود التي تتطلب قرار موارد/سياسة.",
                ],
                links=[
                    {"href": "/course_closure_reports_page", "label_ar": "تقارير الإغلاق"},
                    {"href": "/academic_quality/ilo/department/dashboard", "label_ar": "لوحة المخرجات"},
                ],
            )
        if intent_l == "survey_coverage":
            return _reply(
                mode_l,
                intent_l,
                "تغطية الاستبيانات على مستوى الكلية:",
                bullets=[
                    "افتح تغطية التعبئة واتجاهات الفصول.",
                    "حدّد الأقسام ذات الاستجابة المنخفضة.",
                    "حوّل الضعاف المتكررة إلى بنود لجنة أو خطط تحسين أقسام.",
                ],
                links=[
                    {"href": "/academic_quality/surveys/completion", "label_ar": "تغطية التعبئة"},
                    {"href": "/academic_quality/surveys/trends", "label_ar": "مقارنة الفصول"},
                ],
            )
        if intent_l == "course_report_coverage":
            from backend.services import course_delivery as cd

            idx = cd.build_course_reports_index(conn, semester=sem, department_id=None)
            sum_ = idx.get("summary") or {}
            return _reply(
                mode_l,
                intent_l,
                f"تغطية تقارير المقررات — الكلية — {sem}",
                bullets=[
                    f"مجموعات: {sum_.get('groups_total', 0)} · مُرسل: {sum_.get('submitted', 0)} · "
                    f"غير مُرسل: {sum_.get('unsubmitted', 0)}",
                    f"نسبة منخفضة: {sum_.get('low_completion', 0)} · نقص كتب: {sum_.get('missing_books', 0)}",
                    "للطباعة الإجمالية استخدم حزمة PDF. الشاهد المقترح: course_delivery_quality_report (ربط يدوي).",
                ],
                links=[
                    {"href": "/academic_quality/course_reports", "label_ar": "فهرس الكلية"},
                    {"href": "/academic_quality/course_reports/package.pdf", "label_ar": "PDF إجمالي"},
                    {
                        "href": "/academic_quality/accreditation/map?scope=inst",
                        "label_ar": "خريطة الاعتماد",
                    },
                ],
                knowledge_tag="شاهد مقترح · تقرير مقرر",
            )
        if intent_l == "escalate_committee":
            return _draft_escalation(
                conn,
                from_mode=mode_l,
                to_mode="quality_committee",
                title_ar=topic or "بنود متابعة من وكيل الشؤون العلمية",
                body_ar=notes.strip() or f"بنود تشغيلية مقترحة لأجندة اللجنة — {sem}",
                semester=sem,
                department_id=department_id,
                actor=actor,
            )
        if intent_l == "escalate_dean":
            cm = ctx.get("college_metrics") or {}
            body = notes.strip() or (
                f"موجز تنفيذي للعميد — {sem}\n"
                f"مؤشر تشغيلي داخلي: {cm.get('overall_accreditation_score', '—')}\n"
                f"برامجي: {cm.get('program_score', '—')} · مؤسسي: {cm.get('institutional_score', '—')}\n"
                "(ليس درجة اعتماد رسمية)"
            )
            return _draft_escalation(
                conn,
                from_mode=mode_l,
                to_mode="college_dean",
                title_ar=topic or "موجز تنفيذي من وكيل الشؤون العلمية",
                body_ar=body,
                semester=sem,
                department_id=department_id,
                actor=actor,
            )

    # ——— م3 لجنة ———
    if mode_l == "quality_committee":
        if intent_l == "session_agenda":
            inst = ctx.get("inst") or {}
            prog = ctx.get("prog") or {}
            agenda = [
                "افتتاح واعتماد محضر سابق (إن وجد).",
                "مراجعة فجوات INST المؤسسية ذات الأولوية.",
                "مراجعات برامجية من رؤساء الأقسام.",
                "نتائج الاستبيانات وخطط التحسين.",
                "نواقص أرشيف القسم الحرجة.",
                "ما يستوجب رفعه للعميد.",
            ]
            return _reply(
                mode_l,
                intent_l,
                "أجندة جلسة مقترحة:",
                bullets=agenda,
                inst_gaps=_lines_from_gaps(inst.get("top_gaps") or []),
                prog_gaps=_lines_from_gaps(prog.get("top_gaps") or []),
                knowledge_tag="من بيانات المنظومة",
            )
        if intent_l == "discuss_mission":
            return _reply(
                mode_l,
                intent_l,
                "أسئلة مناقشة للجنة حول الرسالة/الرؤية/الأهداف:",
                bullets=[
                    "هل الرسالة تحدد الجمهور والنتيجة بوضوح؟",
                    "هل الرؤية زمنية وقابلة للتوجيه؟",
                    "هل كل PG مربوط بـ IG؟ هل توجد أهداف يتيمة؟",
                    "ما الشاهد المحلي المقترح لكل ادعاء؟",
                ],
                tips=[t for t in GLOBAL_REFERENCE_TIPS if t["topic_ar"] in ("الرسالة والرؤية", "الأهداف الاستراتيجية")],
                knowledge_tag="مرجع عالمي + نقاش لجنة",
            )
        if intent_l == "discuss_outcomes":
            return _reply(
                mode_l,
                intent_l,
                "مناقشة مخرجات التعلم (OBE):",
                bullets=[
                    "هل السلسلة CLO→PLO→GLO مكتملة؟",
                    "هل يوجد PLO بلا مستوى M؟",
                    "هل القياس يعتمد على درجات/مشاريع موثّقة؟",
                    "ما الفجوة الأحق بخطة تحسين هذا الفصل؟",
                ],
                tips=[t for t in GLOBAL_REFERENCE_TIPS if "OBE" in t["topic_ar"] or "مخرجات" in t["topic_ar"]],
                knowledge_tag="مرجع عالمي",
            )
        if intent_l == "evidence_gaps":
            inst = ctx.get("inst") or {}
            prog = ctx.get("prog") or {}
            return _reply(
                mode_l,
                intent_l,
                "فجوات شواهد مقترحة للنقاش (ربط يدوي لاحقاً):",
                bullets=[
                    "مؤسسي:",
                    *(_lines_from_gaps(inst.get("top_gaps") or []) or ["—"]),
                    "برامجي:",
                    *(_lines_from_gaps(prog.get("top_gaps") or []) or ["—"]),
                ],
                links=[
                    {"href": "/academic_quality/accreditation/map?scope=inst", "label_ar": "امتثال مؤسسي"},
                    {"href": "/academic_quality/accreditation/map?scope=prog", "label_ar": "امتثال برامجي"},
                    {"href": "/academic_quality/archive", "label_ar": "أرشيف القسم"},
                ],
            )
        if intent_l == "minutes_draft":
            draft = (
                f"محضر لجنة الجودة العلمية — مسودة\n"
                f"الفصل: {sem}\n"
                f"القسم المعني: {dept_name}\n\n"
                "الحضور: …\n"
                "جدول الأعمال: …\n"
                "المناقشات:\n- …\n"
                "التوصيات (للتصويت):\n1. …\n"
                "البنود المحالة للعميد/الوكيل: …\n\n"
                "ملاحظة: مسودة من المساعد — لا تُعتمد دون تحرير وتوقيع."
            )
            return _reply(mode_l, intent_l, "مسودة محضر:", draft_text=draft)
        if intent_l == "improvement_draft":
            draft = (
                f"خطة تحسين مقترحة — {dept_name} — {sem}\n\n"
                "المشكلة/الفجوة: …\n"
                "الإجراء: …\n"
                "المسؤول: …\n"
                "الموعد: …\n"
                "الشاهد المتوقع (أرشيف/استبيان/ملف): …\n"
                "مؤشر QAA المرشّح للربط اليدوي: …\n"
            )
            return _reply(mode_l, intent_l, "مسودة خطة تحسين:", draft_text=draft)
    # ——— م4 عميد ———
    if mode_l == "college_dean":
        if intent_l == "course_report_coverage":
            from backend.services import course_delivery as cd

            idx = cd.build_course_reports_index(conn, semester=sem, department_id=None)
            sum_ = idx.get("summary") or {}
            return _reply(
                mode_l,
                intent_l,
                f"تغطية تقارير المقررات — الكلية — {sem}",
                bullets=[
                    f"مجموعات: {sum_.get('groups_total', 0)} · مُرسل: {sum_.get('submitted', 0)} · "
                    f"غير مُرسل: {sum_.get('unsubmitted', 0)}",
                    f"نسبة منخفضة: {sum_.get('low_completion', 0)} · نقص كتب: {sum_.get('missing_books', 0)}",
                    "الشاهد المقترح: course_delivery_quality_report — ربط يدوي بعد المراجعة.",
                ],
                links=[
                    {"href": "/academic_quality/course_reports", "label_ar": "فهرس الكلية"},
                    {"href": "/academic_quality/course_reports/package.pdf", "label_ar": "PDF إجمالي"},
                ],
                knowledge_tag="شاهد مقترح · تقرير مقرر",
            )
        if intent_l == "exec_brief":
            cm = ctx.get("college_metrics") or {}
            inst = ctx.get("inst") or {}
            flagged = [
                d
                for d in (ctx.get("departments_overview") or [])
                if int(d.get("archive_open_issues") or 0) > 0
            ]
            return _reply(
                mode_l,
                intent_l,
                f"موجز تنفيذي — {sem}",
                bullets=[
                    f"مؤشر امتثال تشغيلي داخلي: {cm.get('overall_accreditation_score', '—')} "
                    f"({cm.get('accreditation_status_ar') or '—'}) — ليس اعتماداً رسمياً.",
                    f"برامجي مجمّع: {cm.get('program_score', '—')}% · مؤسسي: {cm.get('institutional_score', '—')}%",
                    f"تقدم INST موثّق: {(inst.get('summary') or {}).get('documented_progress_percent', '—')}%",
                    f"أقسام بتنبيهات أرشيف: {len(flagged)}",
                ],
                links=[
                    {"href": "/academic_quality/dashboard", "label_ar": "لوحة الجودة"},
                    {"href": "/academic_quality/accreditation/map?scope=inst", "label_ar": "امتثال مؤسسي"},
                ],
            )
        if intent_l == "risk_flags":
            flagged = [
                d
                for d in (ctx.get("departments_overview") or [])
                if int(d.get("archive_open_issues") or 0) > 0
            ]
            inst_gaps = _lines_from_gaps((ctx.get("inst") or {}).get("top_gaps") or [], 6)
            arch_lines = [
                f"أرشيف: {d.get('code')} — {d.get('name_ar')}" for d in flagged[:8]
            ] or ["لا تنبيهات أرشيف حادة في المسح السريع."]
            return _reply(
                mode_l,
                intent_l,
                "أبرز المخاطر التشغيلية (للإطلاع لا للقرار الآلي):",
                bullets=[
                    *arch_lines,
                    "فجوات INST:",
                    *(inst_gaps or ["—"]),
                ],
            )
        if intent_l == "inst_progress":
            inst = ctx.get("inst") or {}
            return _reply(
                mode_l,
                intent_l,
                "تقدم الامتثال المؤسسي (ملخص):",
                summary=inst.get("summary"),
                bullets=_lines_from_gaps(inst.get("top_gaps") or []) or ["لا فجوات في العيّنة."],
                links=[{"href": "/academic_quality/accreditation/map?scope=inst", "label_ar": "الخريطة المؤسسية"}],
            )
        if intent_l == "ask_committee":
            return _reply(
                mode_l,
                intent_l,
                "أسئلة مقترحة ي طرحها العميد على اللجنة قبل القرار:",
                bullets=[
                    "ما الحد الأدنى من الشواهد لإغلاق أعلى 5 فجوات INST؟",
                    "أي أقسام متأخرة تشغيلياً ولماذا؟",
                    "هل خطط التحسين لها مسؤول وموعد؟",
                    "ما الذي يحتاج قرار موارد من العمادة الآن؟",
                ],
            )

    return _reply(
        mode_l,
        intent_l,
        f"الموضوع «{intent_l}» غير معرّف لهذا الوضع. اختر موضوعاً من القائمة.",
        intents=intents_for_mode(mode_l),
    )


def _draft_escalation(
    conn,
    *,
    from_mode: str,
    to_mode: str,
    title_ar: str,
    body_ar: str,
    semester: str,
    department_id: int | None,
    actor: str,
) -> dict[str, Any]:
    if to_mode not in ESCALATION_TARGETS:
        raise ValueError("وجهة التصعيد غير معروفة")
    ensure_quality_assistant_tables(conn)
    cur = conn.cursor()
    payload = json.dumps({"suggestion_only": True}, ensure_ascii=False)
    target = ESCALATION_TARGETS[to_mode]
    if is_postgresql():
        row = cur.execute(
            """
            INSERT INTO quality_assistant_escalations
            (from_mode, to_mode, title_ar, body_ar, semester, department_id, status, created_by, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            RETURNING id
            """,
            (
                from_mode,
                to_mode,
                title_ar,
                body_ar,
                semester,
                department_id,
                actor or "",
                payload,
            ),
        ).fetchone()
        eid = int(row[0] if not hasattr(row, "keys") else row["id"])
    else:
        cur.execute(
            """
            INSERT INTO quality_assistant_escalations
            (from_mode, to_mode, title_ar, body_ar, semester, department_id, status, created_by, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (
                from_mode,
                to_mode,
                title_ar,
                body_ar,
                semester,
                department_id,
                actor or "",
                payload,
            ),
        )
        eid = int(cur.lastrowid)
    conn.commit()
    return _reply(
        from_mode,
        "escalation",
        f"تم حفظ مسودة تصعيد إلى «{target['label_ar']}» (#{eid}). راجعها وعدّلها قبل الاعتماد.",
        escalation={
            "id": eid,
            "from_mode": from_mode,
            "to_mode": to_mode,
            "to_label_ar": target["label_ar"],
            "title_ar": title_ar,
            "body_ar": body_ar,
            "status": "draft",
        },
    )


def list_escalations(
    conn,
    *,
    to_mode: str | None = None,
    department_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    ensure_quality_assistant_tables(conn)
    cur = conn.cursor()
    sql = """
        SELECT id, from_mode, to_mode, title_ar, body_ar, semester, department_id,
               status, created_by, created_at
        FROM quality_assistant_escalations
        WHERE 1=1
    """
    params: list[Any] = []
    if to_mode:
        sql += " AND to_mode = ?"
        params.append(to_mode)
    if department_id is not None:
        sql += " AND (department_id = ? OR department_id IS NULL)"
        params.append(int(department_id))
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    rows = cur.execute(sql, params).fetchall() or []
    out = []
    for r in rows:
        if hasattr(r, "keys"):
            out.append({k: r[k] for k in r.keys()})
        else:
            out.append(
                {
                    "id": r[0],
                    "from_mode": r[1],
                    "to_mode": r[2],
                    "title_ar": r[3],
                    "body_ar": r[4],
                    "semester": r[5],
                    "department_id": r[6],
                    "status": r[7],
                    "created_by": r[8],
                    "created_at": r[9],
                }
            )
    return out


def mark_escalation_status(conn, escalation_id: int, status: str, actor: str = "") -> dict[str, Any]:
    ensure_quality_assistant_tables(conn)
    st = (status or "").strip().lower()
    if st not in ("draft", "submitted", "acknowledged", "closed"):
        raise ValueError("حالة غير صالحة")
    cur = conn.cursor()
    cur.execute(
        "UPDATE quality_assistant_escalations SET status = ? WHERE id = ?",
        (st, int(escalation_id)),
    )
    conn.commit()
    return {
        "status": "ok",
        "id": int(escalation_id),
        "new_status": st,
        "actor": actor,
        "suggestion_only": True,
    }


def assistant_bootstrap_payload(
    *,
    role: str,
    is_college_quality_lead: bool = False,
    is_dept_quality_coordinator: bool = False,
    active_mode: str | None = None,
) -> dict[str, Any]:
    modes = allowed_modes_for_user(
        role=role,
        is_college_quality_lead=is_college_quality_lead,
        is_dept_quality_coordinator=is_dept_quality_coordinator,
    )
    mode = resolve_assistant_mode(
        role=role,
        requested=active_mode,
        is_college_quality_lead=is_college_quality_lead,
        is_dept_quality_coordinator=is_dept_quality_coordinator,
    )
    return {
        "status": "ok",
        "catalog": catalog_for_client(),
        "allowed_modes": modes,
        "active_mode": mode,
        "discussion_guides": ROLE_DISCUSSION_GUIDE,
        "active_discussion_guide": ROLE_DISCUSSION_GUIDE.get(mode) or {},
        "policy_ar": POLICY_BANNER_AR,
        "suggestion_only": True,
        "references_downloads": {
            "json": "/academic_quality/assistant/references.json",
            "zip": "/academic_quality/assistant/references.zip",
            "note_ar": (
                "تحميل بطاقات المراجع والروابط المعتمدة في المنظومة "
                "(ليس تنزيلاً كاملاً لمحتوى المواقع الخارجية)."
            ),
        },
        "exports": {
            "committee_md": "/academic_quality/assistant/export/committee.md",
            "committee_docx": "/academic_quality/assistant/export/committee.docx",
            "committee_pdf": "/academic_quality/assistant/export/committee.pdf",
            "style_pack": "/academic_quality/assistant/export/style-pack.zip",
        },
        "llm": __import__(
            "backend.services.quality_assistant_advanced", fromlist=["llm_config"]
        ).llm_config(),
    }
