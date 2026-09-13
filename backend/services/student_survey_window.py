"""
نافذة ملء استبيانات الطلبة مرتبطة بالتقويم الأكاديمي:

- تُفتح في اليوم التالي لـ «آخر موعد لإسقاط المقررات» (drop_courses).
- تُغلق مع «بداية الدراسة» للفصل التالي (instruction_start)،
  أو عند اعتماد فصل جاري لاحق إن لم يُضبط تقويم الفصل التالي.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any

from backend.services.term_engine import (
    SEASON_FALL,
    SEASON_SPRING,
    WINDOW_SCHEDULED,
    _load_window_rows,
    _parse_date,
    canonical_term_key,
    hydrate_term_windows_from_calendar,
    normalize_academic_year,
    normalize_season,
    parse_ops_term,
    parse_semester_label,
    season_name_ar,
)
from backend.services.quality_metrics import term_label_from_conn

logger = logging.getLogger(__name__)

MSG_BEFORE_OPEN = (
    "يُفتح ملء الاستبيانات بعد آخر موعد لإسقاط المقررات في التقويم الأكاديمي."
)
MSG_AFTER_CLOSE = (
    "أُغلق ملء استبيانات هذا الفصل مع بداية الفصل الجديد."
)
MSG_NO_DROP = (
    "يُفتح ملء الاستبيانات بعد ضبط «آخر موعد لإسقاط المقررات» في التقويم الأكاديمي."
)
MSG_UNPARSED = (
    "تعذر تحديد الفصل الحالي لنافذة الاستبيانات. راجع إعداد الفصل في المنظومة."
)


def next_ops_term(season: str, academic_year: str) -> dict[str, str] | None:
    """الفصل التالي تشغيلياً: خريف→ربيع (نفس العام)، ربيع→خريف (العام التالي)."""
    season_n = normalize_season(season)
    year_n = normalize_academic_year(academic_year)
    if not season_n or not year_n:
        return None
    m = re.match(r"^(20\d{2})/(20\d{2})$", year_n)
    if not m:
        return None
    y0, y1 = int(m.group(1)), int(m.group(2))
    if season_n == SEASON_FALL:
        return parse_ops_term(season_name_ar(SEASON_SPRING), year_n)
    if season_n == SEASON_SPRING:
        nxt_year = f"{y0 + 1}/{y1 + 1}"
        return parse_ops_term(season_name_ar(SEASON_FALL), nxt_year)
    return None


def term_sort_key(season: str, academic_year: str) -> int | None:
    season_n = normalize_season(season)
    year_n = normalize_academic_year(academic_year)
    if not season_n or not year_n:
        return None
    m = re.match(r"^(20\d{2})/", year_n)
    if not m:
        return None
    y0 = int(m.group(1))
    return y0 * 2 + (0 if season_n == SEASON_FALL else 1)


def _ensure_windows(conn, parsed: dict[str, str]) -> None:
    try:
        hydrate_term_windows_from_calendar(
            conn,
            academic_year=parsed["academic_year"],
            season=parsed["season"],
            ops_label=parsed.get("ops_label") or "",
            ops_year_label=parsed.get("ops_year_label") or parsed["academic_year"],
            actor="student_survey_window",
        )
    except Exception:
        logger.exception("hydrate_term_windows_from_calendar failed for survey window")


def _window_row(conn, term_key: str, window_key: str) -> dict[str, Any] | None:
    rows = _load_window_rows(conn, term_key, (window_key,))
    for r in rows or []:
        if (r.get("window_key") or "") == window_key:
            return r
    return None


def _resolve_semester_parsed(conn, semester: str | None) -> dict[str, str] | None:
    label = " ".join((semester or "").split()).strip() or term_label_from_conn(conn)
    parsed = parse_semester_label(label)
    if parsed:
        return parsed
    # محاولة فصل الاسم/السنة إن فشل المُحلّل المركّب
    parts = label.split(None, 1)
    if len(parts) == 2:
        return parse_ops_term(parts[0], parts[1])
    return None


def student_survey_fill_gate(
    conn,
    semester: str | None = None,
    *,
    today: datetime.date | None = None,
) -> dict[str, Any]:
    """
    هل يُسمح للطالب بملء استبيانات الفصل؟

    open=True فقط بعد انتهاء يوم الإسقاط وقبل بداية دراسة الفصل التالي.
    """
    day = today or datetime.date.today()
    parsed = _resolve_semester_parsed(conn, semester)
    if not parsed:
        return {
            "open": False,
            "reason": "unparsed_term",
            "message_ar": MSG_UNPARSED,
            "semester": semester or "",
            "drop_ends_at": None,
            "closes_at": None,
            "term_key": None,
            "next_term_key": None,
        }

    _ensure_windows(conn, parsed)
    term_key = parsed["term_key"]
    drop = _window_row(conn, term_key, "drop_courses")
    drop_end = _parse_date((drop or {}).get("ends_at")) if drop else None
    drop_scheduled = bool(drop) and (drop.get("status") or "") == WINDOW_SCHEDULED and drop_end is not None

    nxt = next_ops_term(parsed["season"], parsed["academic_year"])
    closes_at = None
    next_term_key = None
    if nxt:
        next_term_key = nxt["term_key"]
        _ensure_windows(conn, nxt)
        instr = _window_row(conn, next_term_key, "instruction_start")
        if instr and (instr.get("status") or "") == WINDOW_SCHEDULED:
            closes_at = _parse_date(instr.get("starts_at")) or _parse_date(instr.get("ends_at"))

    # إغلاق: بداية دراسة الفصل التالي
    if closes_at is not None and day >= closes_at:
        return {
            "open": False,
            "reason": "closed_new_term_started",
            "message_ar": MSG_AFTER_CLOSE,
            "semester": parsed.get("ops_label") or "",
            "drop_ends_at": drop_end.isoformat() if drop_end else None,
            "closes_at": closes_at.isoformat(),
            "term_key": term_key,
            "next_term_key": next_term_key,
        }

    # احتياطي: الفصل الجاري في المنظومة أصبح لاحقاً ولم يُضبط بداية الدراسة التالية
    if closes_at is None:
        try:
            from backend.services.utilities import get_current_term

            cur_name, cur_year = get_current_term(conn=conn)
            cur_parsed = parse_ops_term(cur_name, cur_year)
            if cur_parsed:
                sk_survey = term_sort_key(parsed["season"], parsed["academic_year"])
                sk_current = term_sort_key(cur_parsed["season"], cur_parsed["academic_year"])
                if (
                    sk_survey is not None
                    and sk_current is not None
                    and sk_current > sk_survey
                ):
                    return {
                        "open": False,
                        "reason": "closed_current_term_advanced",
                        "message_ar": MSG_AFTER_CLOSE,
                        "semester": parsed.get("ops_label") or "",
                        "drop_ends_at": drop_end.isoformat() if drop_end else None,
                        "closes_at": None,
                        "term_key": term_key,
                        "next_term_key": next_term_key or cur_parsed.get("term_key"),
                    }
        except Exception:
            logger.exception("current term fallback for survey close failed")

    if not drop_scheduled:
        return {
            "open": False,
            "reason": "drop_deadline_unset",
            "message_ar": MSG_NO_DROP,
            "semester": parsed.get("ops_label") or "",
            "drop_ends_at": None,
            "closes_at": closes_at.isoformat() if closes_at else None,
            "term_key": term_key,
            "next_term_key": next_term_key,
        }

    if day <= drop_end:
        return {
            "open": False,
            "reason": "before_drop_deadline",
            "message_ar": MSG_BEFORE_OPEN,
            "semester": parsed.get("ops_label") or "",
            "drop_ends_at": drop_end.isoformat(),
            "closes_at": closes_at.isoformat() if closes_at else None,
            "term_key": term_key,
            "next_term_key": next_term_key,
        }

    return {
        "open": True,
        "reason": "open",
        "message_ar": "",
        "semester": parsed.get("ops_label") or "",
        "drop_ends_at": drop_end.isoformat(),
        "closes_at": closes_at.isoformat() if closes_at else None,
        "term_key": term_key,
        "next_term_key": next_term_key,
    }


def assert_student_survey_fill_allowed(conn, semester: str | None = None) -> dict[str, Any]:
    """يرفع ValueError برسالة عربية إن كان الملء مغلقاً؛ وإلا يعيد بوابة مفتوحة."""
    gate = student_survey_fill_gate(conn, semester)
    if not gate.get("open"):
        raise ValueError(gate.get("message_ar") or MSG_BEFORE_OPEN)
    return gate
