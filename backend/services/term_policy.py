"""الموجة 2: سياسة تعديل مواعيد التقويم دون فتح تشغيلي تلقائي."""
from __future__ import annotations

import datetime
import logging
from typing import Any

from backend.database.database import table_exists
from backend.services.term_engine import (
    WINDOW_CATALOG,
    WINDOW_SCHEDULED,
    WINDOW_UNSET,
    _now_iso,
    _parse_date,
    _window_dates_for_spec,
    canonical_term_key,
    ensure_term_engine_tables,
    normalize_academic_year,
    normalize_season,
    season_name_ar,
    upsert_term_master,
    window_open_on,
)

logger = logging.getLogger("backend.services.term_policy")

GRACE_MINUTES = 15

EFFECT_UNCHANGED = "unchanged"
EFFECT_INITIAL = "initial_schedule"
EFFECT_EXTEND = "extend_open"
EFFECT_SHORTEN = "shorten_future"
EFFECT_IMMEDIATE_CLOSE = "immediate_close"
EFFECT_REOPEN = "reopen_window"
EFFECT_ADJUST = "adjust"
EFFECT_CALENDAR_ONLY = "calendar_only"
EFFECT_REJECT = "reject_regression"

APPLY_OPS_EFFECTS = frozenset(
    {
        EFFECT_INITIAL,
        EFFECT_EXTEND,
        EFFECT_SHORTEN,
        EFFECT_IMMEDIATE_CLOSE,
        EFFECT_REOPEN,
        EFFECT_ADJUST,
    }
)
NEEDS_CONFIRM_EFFECTS = frozenset(
    {EFFECT_SHORTEN, EFFECT_IMMEDIATE_CLOSE, EFFECT_REOPEN}
)
REGISTRATION_WINDOW_KEYS = frozenset(
    {"registration_renewal", "registration_new", "add_courses", "drop_courses"}
)

EFFECT_LABELS_AR = {
    EFFECT_UNCHANGED: "بدون تغيير تشغيلي",
    EFFECT_INITIAL: "جدولة أولية للنافذة",
    EFFECT_EXTEND: "تمديد نافذة مفتوحة — يُطبَّق على التشغيل",
    EFFECT_SHORTEN: "تقصير نافذة — يُطبَّق بعد التأكيد مع مهلة الجلسات",
    EFFECT_IMMEDIATE_CLOSE: "إغلاق فوري — التقويم + التشغيل بعد تأكيد العميد/الأدمن",
    EFFECT_REOPEN: "إعادة فتح نافذة منتهية — يتطلب تأكيداً والمرحلة غير مقفلة",
    EFFECT_ADJUST: "تصحيح تاريخ دون إعادة فتح",
    EFFECT_CALENDAR_ONLY: "تقويم فقط — المرحلة مقفلة ولن يُفتح التشغيل",
    EFFECT_REJECT: "مرفوض: رجوع لمرحلة سابقة بعد بدء ما يليها",
}


class AmendmentRejected(ValueError):
    """حفظ التقويم رُفض لأن التعديل يعيد مرحلة سابقة."""

    def __init__(self, message: str, preview: dict[str, Any]):
        super().__init__(message)
        self.preview = preview


class AmendmentNeedsConfirm(ValueError):
    """التعديل يحتاج تأكيداً وسبباً قبل تطبيق التشغيل."""

    def __init__(self, message: str, preview: dict[str, Any]):
        super().__init__(message)
        self.preview = preview


def _catalog_index(window_key: str) -> int:
    for i, spec in enumerate(WINDOW_CATALOG):
        if spec.window_key == window_key:
            return i
    return 10_000


def window_has_begun(
    starts_at: Any,
    ends_at: Any,
    today: datetime.date,
) -> bool:
    start = _parse_date(starts_at)
    end = _parse_date(ends_at)
    if start is not None and today >= start:
        return True
    if start is None and end is not None:
        return True
    return False


def classify_window_change(
    *,
    old_starts: Any,
    old_ends: Any,
    new_starts: Any,
    new_ends: Any,
    today: datetime.date,
    stage_closed: bool,
    later_started: bool,
    old_status: str = "",
) -> str:
    old_s, old_e = _parse_date(old_starts), _parse_date(old_ends)
    new_s, new_e = _parse_date(new_starts), _parse_date(new_ends)
    if old_s == new_s and old_e == new_e:
        return EFFECT_UNCHANGED
    had_dates = bool(old_s or old_e) or (old_status == WINDOW_SCHEDULED)
    old_open = window_open_on(old_starts, old_ends, today) if had_dates else False
    new_open = window_open_on(new_starts, new_ends, today) if (new_s or new_e) else False

    if stage_closed:
        return EFFECT_CALENDAR_ONLY

    if not had_dates and (new_s or new_e):
        return EFFECT_INITIAL

    if not old_open and new_open:
        if later_started:
            return EFFECT_REJECT
        return EFFECT_REOPEN

    if old_open and new_e is not None and new_e < today:
        return EFFECT_IMMEDIATE_CLOSE

    if old_open and old_e is not None and new_e is not None and new_e < old_e and new_e >= today:
        return EFFECT_SHORTEN

    if old_open and (
        (new_e is not None and old_e is not None and new_e > old_e)
        or (old_e is None and new_e is not None)
        or (new_s is not None and old_s is not None and new_s < old_s)
    ):
        return EFFECT_EXTEND

    return EFFECT_ADJUST


def _load_all_windows(conn, term_key: str) -> dict[str, dict[str, Any]]:
    if not term_key or not table_exists(conn, "term_windows"):
        return {}
    cur = conn.cursor()
    try:
        rows = cur.execute(
            """
            SELECT window_key, starts_at, ends_at, status, kind, grace_until, closure_stage
            FROM term_windows WHERE term_key = ?
            """,
            (term_key,),
        ).fetchall()
    except Exception:
        rows = cur.execute(
            """
            SELECT window_key, starts_at, ends_at, status, kind, NULL, closure_stage
            FROM term_windows WHERE term_key = ?
            """,
            (term_key,),
        ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows or []:
        if hasattr(r, "keys"):
            d = {k: r[k] for k in r.keys()}
        else:
            d = {
                "window_key": r[0],
                "starts_at": r[1],
                "ends_at": r[2],
                "status": r[3],
                "kind": r[4],
                "grace_until": r[5],
                "closure_stage": r[6],
            }
        out[str(d.get("window_key") or "")] = d
    return out


def _stage_closed(conn, ops_label: str, stage: str) -> bool:
    if not stage:
        return False
    try:
        from backend.services.term_closure import is_stage_closed

        return bool(is_stage_closed(conn, ops_label, stage, None, include_college=True))
    except Exception:
        return False


def _later_started(
    windows: dict[str, dict[str, Any]],
    window_key: str,
    today: datetime.date,
) -> bool:
    idx = _catalog_index(window_key)
    for spec in WINDOW_CATALOG:
        if _catalog_index(spec.window_key) <= idx:
            continue
        row = windows.get(spec.window_key) or {}
        if (row.get("status") or "") != WINDOW_SCHEDULED:
            continue
        if window_has_begun(row.get("starts_at"), row.get("ends_at"), today):
            return True
    return False


def preview_calendar_amendment(
    conn,
    *,
    academic_year: str,
    season: str,
    items: list[dict[str, Any]],
    now: datetime.date | None = None,
) -> dict[str, Any]:
    """فروقات النوافذ المتوقعة دون كتابة."""
    ensure_term_engine_tables(conn)
    today = now or datetime.date.today()
    season_n = normalize_season(season)
    year_n = normalize_academic_year(academic_year)
    if not season_n or not year_n:
        return {"status": "error", "message": "عام/فصل غير صالح", "changes": []}
    term_key = canonical_term_key(season_n, year_n)
    ops_label = f"{season_name_ar(season_n)} {year_n}"
    master = conn.cursor().execute(
        "SELECT ops_label FROM term_master WHERE term_key = ? LIMIT 1",
        (term_key,),
    ).fetchone()
    if master is not None:
        ops_label = str(master["ops_label"] if hasattr(master, "keys") else master[0] or ops_label)

    windows = _load_all_windows(conn, term_key)
    changes: list[dict[str, Any]] = []
    for spec in WINDOW_CATALOG:
        has_map = (
            (season_n == "fall" and (spec.fall_end_item or spec.fall_start_item))
            or (season_n == "spring" and (spec.spring_end_item or spec.spring_start_item))
        )
        if not has_map:
            continue
        new_s, new_e, item_no = _window_dates_for_spec(spec, season_n, items)
        old = windows.get(spec.window_key) or {}
        effect = classify_window_change(
            old_starts=old.get("starts_at"),
            old_ends=old.get("ends_at"),
            new_starts=new_s,
            new_ends=new_e,
            today=today,
            stage_closed=_stage_closed(conn, ops_label, spec.closure_stage),
            later_started=_later_started(windows, spec.window_key, today),
            old_status=str(old.get("status") or ""),
        )
        if effect == EFFECT_UNCHANGED:
            continue
        apply_ops = effect in APPLY_OPS_EFFECTS
        changes.append(
            {
                "window_key": spec.window_key,
                "label_ar": spec.label_ar,
                "closure_stage": spec.closure_stage,
                "calendar_item_no": item_no,
                "effect": effect,
                "effect_ar": EFFECT_LABELS_AR.get(effect, effect),
                "apply_ops": apply_ops,
                "needs_confirm": effect in NEEDS_CONFIRM_EFFECTS,
                "old_starts_at": old.get("starts_at"),
                "old_ends_at": old.get("ends_at"),
                "new_starts_at": new_s,
                "new_ends_at": new_e,
                "sets_grace": effect in (EFFECT_SHORTEN, EFFECT_IMMEDIATE_CLOSE),
            }
        )
    return {
        "status": "ok",
        "term_key": term_key,
        "ops_label": ops_label,
        "season": season_n,
        "academic_year": year_n,
        "today": today.isoformat(),
        "changes": changes,
        "has_reject": any(c["effect"] == EFFECT_REJECT for c in changes),
        "needs_confirm": any(c["needs_confirm"] for c in changes),
        "has_calendar_only": any(c["effect"] == EFFECT_CALENDAR_ONLY for c in changes),
        "never_reopens_locked_stage": True,
    }


def _grace_until_iso(now_dt: datetime.datetime | None = None) -> str:
    dt = now_dt or datetime.datetime.now(datetime.timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return (dt + datetime.timedelta(minutes=GRACE_MINUTES)).replace(microsecond=0).isoformat()


def apply_window_dates(
    conn,
    *,
    term_key: str,
    window_key: str,
    starts_at: str | None,
    ends_at: str | None,
    grace_until: str | None = None,
    source: str = "policy",
) -> None:
    ensure_term_engine_tables(conn)
    now = _now_iso()
    status = WINDOW_SCHEDULED if (starts_at or ends_at) else WINDOW_UNSET
    spec = next((s for s in WINDOW_CATALOG if s.window_key == window_key), None)
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM term_windows WHERE term_key = ? AND window_key = ? LIMIT 1",
        (term_key, window_key),
    )
    row = cur.fetchone()
    cols = ""
    try:
        from backend.database.database import fetch_table_columns

        cols = fetch_table_columns(conn, "term_windows")
    except Exception:
        cols = []
    has_grace = "grace_until" in (cols or [])
    if row:
        if has_grace:
            cur.execute(
                """
                UPDATE term_windows
                SET starts_at = ?, ends_at = ?, status = ?, source = ?,
                    grace_until = ?, updated_at = ?
                WHERE term_key = ? AND window_key = ?
                """,
                (starts_at, ends_at, status, source, grace_until, now, term_key, window_key),
            )
        else:
            cur.execute(
                """
                UPDATE term_windows
                SET starts_at = ?, ends_at = ?, status = ?, source = ?, updated_at = ?
                WHERE term_key = ? AND window_key = ?
                """,
                (starts_at, ends_at, status, source, now, term_key, window_key),
            )
        return
    cur.execute(
        """
        INSERT INTO term_windows (
            term_key, window_key, kind, label_ar, closure_stage,
            starts_at, ends_at, status, source, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            term_key,
            window_key,
            spec.kind if spec else "window",
            spec.label_ar if spec else window_key,
            spec.closure_stage if spec else "",
            starts_at,
            ends_at,
            status,
            source,
            now,
        ),
    )
    if has_grace and grace_until:
        cur.execute(
            "UPDATE term_windows SET grace_until = ? WHERE term_key = ? AND window_key = ?",
            (grace_until, term_key, window_key),
        )


def _log_amendment(conn, term_key: str, change: dict[str, Any], actor: str, reason: str) -> None:
    if not table_exists(conn, "term_amendment_log"):
        return
    conn.cursor().execute(
        """
        INSERT INTO term_amendment_log (
            term_key, window_key, effect, apply_ops,
            old_starts_at, old_ends_at, new_starts_at, new_ends_at,
            reason, actor, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            term_key,
            change.get("window_key") or "",
            change.get("effect") or "",
            1 if change.get("applied_ops") else 0,
            change.get("old_starts_at"),
            change.get("old_ends_at"),
            change.get("new_starts_at"),
            change.get("new_ends_at"),
            reason or "",
            actor or "",
            _now_iso(),
        ),
    )


def notify_amendment(conn, preview: dict[str, Any], actor: str) -> int:
    """إشعار الكادر، والطلبة إن مسّت نوافذ التسجيل."""
    changes = preview.get("changes") or []
    if not changes:
        return 0
    lines = []
    touch_reg = False
    for c in changes:
        lines.append(f"- {c.get('label_ar')}: {c.get('effect_ar')}")
        if c.get("window_key") in REGISTRATION_WINDOW_KEYS:
            touch_reg = True
        if c.get("effect") == EFFECT_CALENDAR_ONLY:
            lines.append("  التشغيل لم يُفتح لأن المرحلة مقفلة.")
    title = "تعديل مواعيد الفصل"
    body = (
        f"الفصل: {preview.get('ops_label') or preview.get('term_key')}\n"
        + "\n".join(lines)
        + (f"\nالمنفّذ: {actor}" if actor else "")
    )
    roles = (
        "admin_main",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
        "head_of_department",
        "supervisor",
    )
    if touch_reg:
        roles = roles + ("student",)
    try:
        rows = conn.cursor().execute(
            f"SELECT username FROM users WHERE role IN ({','.join('?' for _ in roles)})",
            roles,
        ).fetchall()
    except Exception:
        return 0
    from backend.services.utilities import create_notification

    n = 0
    for r in rows[:1500]:
        user = r[0] if not hasattr(r, "keys") else r["username"]
        try:
            create_notification(str(user or ""), title, body)
            n += 1
        except Exception:
            continue
    return n


def apply_calendar_amendment(
    conn,
    *,
    academic_year: str,
    season: str,
    items: list[dict[str, Any]],
    actor: str = "",
    reason: str = "",
    confirm: bool = False,
    now: datetime.date | None = None,
    notify: bool = True,
) -> dict[str, Any]:
    """يطبق سياسة النوافذ بعد حفظ التقويم. لا يفتح مرحلة مقفلة."""
    preview = preview_calendar_amendment(
        conn, academic_year=academic_year, season=season, items=items, now=now
    )
    if preview.get("status") != "ok":
        return preview
    if preview.get("has_reject"):
        raise AmendmentRejected(
            "لا يمكن إرجاع نافذة سابقة بعد بدء ما يليها في التقويم التشغيلي.",
            preview,
        )
    if preview.get("needs_confirm") and not confirm:
        raise AmendmentNeedsConfirm(
            "هذا التعديل يقصّر أو يغلق أو يعيد فتح نافذة — أرسل confirm=true وسبباً.",
            preview,
        )
    reason = (reason or "").strip()
    if preview.get("needs_confirm") and len(reason) < 5:
        raise AmendmentNeedsConfirm("سبب التعديل مطلوب (٥ أحرف على الأقل).", preview)

    term_key = preview["term_key"]
    upsert_term_master(
        conn,
        season=preview["season"],
        academic_year=preview["academic_year"],
        term_name_ar=season_name_ar(preview["season"]),
        ops_year_label=preview["academic_year"],
        make_current=False,
    )
    applied = []
    for change in preview.get("changes") or []:
        row = dict(change)
        if change["effect"] in (EFFECT_REJECT, EFFECT_CALENDAR_ONLY):
            row["applied_ops"] = False
            applied.append(row)
            _log_amendment(conn, term_key, row, actor, reason)
            continue
        grace = None
        if change.get("sets_grace"):
            grace = _grace_until_iso()
        apply_window_dates(
            conn,
            term_key=term_key,
            window_key=change["window_key"],
            starts_at=change.get("new_starts_at"),
            ends_at=change.get("new_ends_at"),
            grace_until=grace,
            source="policy",
        )
        row["applied_ops"] = True
        row["grace_until"] = grace
        applied.append(row)
        _log_amendment(conn, term_key, row, actor, reason)

    preview["applied"] = applied
    preview["reason"] = reason
    if notify:
        try:
            preview["notified"] = notify_amendment(conn, preview, actor)
        except Exception:
            logger.exception("term amendment notify failed")
            preview["notified"] = 0
    return preview


def preview_single_item_move(
    conn,
    *,
    academic_year: str,
    season: str,
    item_no: int,
    new_date: str,
    now: datetime.date | None = None,
) -> dict[str, Any]:
    """محاكاة تحريك بند واحد مع الإبقاء على بقية التواريخ."""
    from backend.services.academic_calendar import assemble_calendar_items
    from backend.services.term_engine import load_calendar_item_rows

    season_n = normalize_season(season)
    existing = load_calendar_item_rows(conn, academic_year, season_n or season)
    items = assemble_calendar_items(
        academic_year=academic_year, term=season_n or season, existing=existing
    )
    for it in items:
        if int(it.get("item_no") or 0) == int(item_no):
            it["event_date"] = (new_date or "").strip() or None
            break
    else:
        items.append(
            {
                "item_no": int(item_no),
                "title": "",
                "event_date": (new_date or "").strip() or None,
                "is_deleted": 0,
                "is_custom": True,
            }
        )
    return preview_calendar_amendment(
        conn, academic_year=academic_year, season=season_n or season, items=items, now=now
    )
