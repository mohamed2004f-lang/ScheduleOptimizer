"""الموجة 4: لوحة تشغيل الفصل — حالة، نوافذ، تقويم، أقفال، محاكاة."""
from __future__ import annotations

import datetime

from flask import Blueprint, jsonify, render_template, request, session

from backend.core.auth import _normalize_role, login_required, role_required
from backend.services.term_engine import (
    OP_ADD_COURSE,
    WINDOW_CATALOG,
    WINDOW_SCHEDULED,
    ensure_term_engine_tables,
    parse_ops_term,
    upsert_term_master,
    window_mapped_for_season,
    window_open_on,
)
from backend.services.utilities import get_connection, get_current_term

term_ops_bp = Blueprint("term_ops", __name__)

_OPS_ROLES = (
    "admin",
    "admin_main",
    "system_admin",
    "college_dean",
    "academic_vice_dean",
    "head_of_department",
)


def _named_row(row, names: tuple[str, ...]) -> dict:
    if row is None:
        return {}
    out = {}
    keys_l = {}
    if hasattr(row, "keys"):
        try:
            keys_l = {str(k).lower(): k for k in row.keys()}
        except Exception:
            keys_l = {}
    for i, name in enumerate(names):
        val = None
        src = keys_l.get(name.lower())
        if src is not None:
            try:
                val = row[src]
            except Exception:
                val = None
        if val is None:
            try:
                val = row[i]
            except Exception:
                val = None
        out[name] = val
    return out


def _actor() -> str:
    return (session.get("user") or session.get("username") or "").strip()


def _role() -> str:
    return _normalize_role((session.get("user_role") or "").strip())


def build_ops_dashboard(conn, *, academic_year: str = "", season: str = "") -> dict:
    from backend.services.quality_metrics import term_label_from_conn
    from backend.services.term_basket import live_basket_summary
    from backend.services.term_closure import get_term_closure_status
    from backend.services.term_engine import (
        load_calendar_item_rows,
        hydrate_term_windows_from_calendar,
        list_stored_calendars,
        normalize_academic_year,
        normalize_season,
        season_name_ar,
    )
    from backend.services.term_policy import _load_all_windows, window_has_begun

    ensure_term_engine_tables(conn)
    name, year = get_current_term(conn=conn)
    parsed = parse_ops_term(name, year)
    if academic_year and season:
        season_n = normalize_season(season)
        year_n = normalize_academic_year(academic_year)
        term_key = f"{season_n}:{year_n}" if season_n and year_n else (parsed or {}).get("term_key")
        ops_label = f"{season_name_ar(season_n)} {year_n}" if season_n and year_n else (parsed or {}).get("ops_label")
    else:
        term_key = (parsed or {}).get("term_key") or ""
        ops_label = (parsed or {}).get("ops_label") or f"{name} {year}".strip()
        season_n = (parsed or {}).get("season") or ""
        year_n = (parsed or {}).get("academic_year") or ""

    hydrate = None
    if term_key and season_n and year_n:
        hydrate = hydrate_term_windows_from_calendar(
            conn,
            academic_year=year_n,
            season=season_n,
            ops_label=ops_label or "",
            ops_year_label=(parsed or {}).get("ops_year_label") or year or year_n,
            actor="term_ops",
        )

    today = datetime.date.today()
    master = {}
    if term_key:
        row = conn.cursor().execute(
            """
            SELECT term_key, status, is_current, ops_label, academic_year, season
            FROM term_master WHERE term_key = ? LIMIT 1
            """,
            (term_key,),
        ).fetchone()
        master = _named_row(
            row, ("term_key", "status", "is_current", "ops_label", "academic_year", "season")
        )
        if not master.get("term_key") and season_n and year_n:
            master = upsert_term_master(
                conn,
                season=season_n,
                academic_year=year_n,
                term_name_ar=season_name_ar(season_n),
                ops_year_label=(parsed or {}).get("ops_year_label") or year or year_n,
                ops_label=ops_label or "",
                make_current=not (academic_year and season),
            )
    windows_raw = _load_all_windows(conn, term_key) if term_key else {}
    windows = []
    for spec in WINDOW_CATALOG:
        row = windows_raw.get(spec.window_key) or {}
        starts, ends = row.get("starts_at"), row.get("ends_at")
        status = row.get("status") or "unset"
        mapped = window_mapped_for_season(spec, season_n or "")
        ops_only = spec.window_key in ("schedule_freeze", "surveys")
        if ops_only:
            date_kind = "stage_lock"
        elif not mapped:
            date_kind = "not_applicable"
        elif spec.kind == "milestone":
            date_kind = "milestone"
        elif spec.duration_days:
            date_kind = "range"
        elif starts and ends:
            date_kind = "range"
        elif ends or starts:
            date_kind = "deadline"
        else:
            date_kind = "unset"
        open_now = status == WINDOW_SCHEDULED and window_open_on(starts, ends, today)
        windows.append(
            {
                "window_key": spec.window_key,
                "label_ar": spec.label_ar,
                "closure_stage": spec.closure_stage,
                "kind": spec.kind,
                "date_kind": date_kind,
                "mapped": mapped,
                "starts_at": starts,
                "ends_at": ends,
                "status": status,
                "open_now": open_now,
                "begun": window_has_begun(starts, ends, today) if status == WINDOW_SCHEDULED else False,
                "grace_until": row.get("grace_until"),
            }
        )

    version = None
    if term_key:
        vrow = conn.cursor().execute(
            """
            SELECT version_no, status, reason, created_at, created_by
            FROM academic_calendar_versions
            WHERE term_key = ? ORDER BY version_no DESC LIMIT 1
            """,
            (term_key,),
        ).fetchone()
        if vrow:
            version = _named_row(
                vrow, ("version_no", "status", "reason", "created_at", "created_by")
            )

    closure = get_term_closure_status(
        conn, semester=ops_label or term_label_from_conn(conn), department_id=None
    )
    basket = live_basket_summary(conn)
    cal_items = []
    if year_n and season_n:
        from backend.services.academic_calendar import assemble_calendar_items

        existing = load_calendar_item_rows(conn, year_n, season_n)
        cal_items = assemble_calendar_items(
            academic_year=year_n, term=season_n, existing=existing
        )
    stored = list_stored_calendars(conn)
    dated_windows = any(w.get("starts_at") or w.get("ends_at") for w in windows)
    viewing_current = True
    if parsed and year_n and season_n:
        viewing_current = (
            year_n == parsed.get("academic_year") and season_n == parsed.get("season")
        )
    other = [s for s in stored if (s.get("term_key") or "") != (term_key or "")]
    notice_ar = ""
    if not dated_windows and other:
        labels = "، ".join(s["label_ar"] for s in other[:6])
        notice_ar = (
            "اللوحة تعرض الفصل الحالي فقط. التواريخ محفوظة تحت: "
            + labels
            + ". اختر ذلك التقويم أدناه، أو حمّل في التقويم الأكاديمي العام نفسه المكتوب في الفصل الحالي."
        )
    elif hydrate and hydrate.get("filled"):
        notice_ar = "تم ربط تواريخ التقويم المحفوظ بنوافذ هذا الفصل."
    return {
        "status": "ok",
        "today": today.isoformat(),
        "current_term": {"term_name": name, "term_year": year, "ops_label": ops_label},
        "term_master": master,
        "term_key": term_key,
        "academic_year": year_n,
        "season": season_n,
        "windows": windows,
        "calendar_version": version,
        "calendar_items": cal_items,
        "closure": closure,
        "basket": basket,
        "stored_calendars": stored,
        "viewing_current": viewing_current,
        "notice_ar": notice_ar,
        "hydrate": hydrate,
    }


@term_ops_bp.route("/term_ops")
@login_required
@role_required(*_OPS_ROLES)
def term_ops_page():
    return render_template("term_ops.html", active_page="term_ops")


@term_ops_bp.route("/term_ops/dashboard", methods=["GET"])
@login_required
@role_required(*_OPS_ROLES)
def term_ops_dashboard():
    with get_connection() as conn:
        payload = build_ops_dashboard(
            conn,
            academic_year=(request.args.get("academic_year") or "").strip(),
            season=(request.args.get("term") or request.args.get("season") or "").strip(),
        )
    return jsonify(payload)


@term_ops_bp.route("/term_ops/preview", methods=["POST"])
@login_required
@role_required(*_OPS_ROLES)
def term_ops_preview():
    data = request.get_json(force=True) or {}
    from backend.services.term_policy import preview_calendar_amendment, preview_single_item_move

    with get_connection() as conn:
        if data.get("item_no") is not None:
            preview = preview_single_item_move(
                conn,
                academic_year=(data.get("academic_year") or "").strip(),
                season=(data.get("term") or data.get("season") or "").strip(),
                item_no=int(data.get("item_no") or 0),
                new_date=(data.get("event_date") or data.get("new_date") or "").strip(),
            )
        else:
            preview = preview_calendar_amendment(
                conn,
                academic_year=(data.get("academic_year") or "").strip(),
                season=(data.get("term") or data.get("season") or "").strip(),
                items=data.get("items") or [],
            )
    return jsonify(preview)


@term_ops_bp.route("/term_ops/unmigrated", methods=["GET"])
@login_required
@role_required(*_OPS_ROLES)
def term_ops_unmigrated():
    from backend.services.term_basket import live_basket_summary, unmigrated_students

    new_label = (request.args.get("new_ops_label") or "").strip()
    with get_connection() as conn:
        if not new_label:
            name, year = get_current_term(conn=conn)
            new_label = f"{name} {year}".strip()
        return jsonify(
            {
                "status": "ok",
                "new_ops_label": new_label,
                "summary": live_basket_summary(conn),
                "unmigrated": unmigrated_students(conn, new_label),
            }
        )


@term_ops_bp.route("/term_ops/archive_basket", methods=["POST"])
@login_required
@role_required("admin_main", "system_admin", "college_dean", "academic_vice_dean")
def term_ops_archive_basket():
    data = request.get_json(force=True) or {}
    from backend.services.term_basket import archive_live_basket

    with get_connection() as conn:
        try:
            result = archive_live_basket(
                conn,
                actor=_actor(),
                reason=(data.get("reason") or "").strip(),
            )
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify(result)


@term_ops_bp.route("/term_ops/exceptions", methods=["POST"])
@login_required
@role_required(*_OPS_ROLES, "supervisor")
def term_ops_propose_exception():
    data = request.get_json(force=True) or {}
    sid = (data.get("student_id") or "").strip()
    operation = (data.get("operation") or OP_ADD_COURSE).strip()
    reason = (data.get("reason") or "").strip()
    if not sid or len(reason) < 5:
        return jsonify({"status": "error", "message": "student_id وسبب ≥٥ أحرف مطلوبان"}), 400
    from backend.services.term_engine import _now_iso, ensure_term_engine_tables

    with get_connection() as conn:
        ensure_term_engine_tables(conn)
        name, year = get_current_term(conn=conn)
        parsed = parse_ops_term(name, year) or {}
        term_key = (data.get("term_key") or parsed.get("term_key") or "").strip()
        now = _now_iso()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO term_operation_exceptions (
                student_id, term_key, operation, status, reason,
                proposed_by, created_at, updated_at
            ) VALUES (?, ?, ?, 'proposed', ?, ?, ?, ?)
            """,
            (sid, term_key, operation, reason, _actor(), now, now),
        )
        eid = int(cur.lastrowid or 0)
        conn.commit()
    return jsonify({"status": "ok", "id": eid, "state": "proposed"})


@term_ops_bp.route("/term_ops/exceptions/<int:exc_id>/approve", methods=["POST"])
@login_required
@role_required("admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def term_ops_approve_exception(exc_id: int):
    data = request.get_json(silent=True) or {}
    days = int(data.get("days") or 7)
    from backend.services.term_engine import _now_iso

    expires = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=max(days, 1))
    ).replace(microsecond=0).isoformat()
    with get_connection() as conn:
        row = conn.cursor().execute(
            "SELECT id, status FROM term_operation_exceptions WHERE id = ?",
            (exc_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "الاستثناء غير موجود"}), 404
        conn.cursor().execute(
            """
            UPDATE term_operation_exceptions
            SET status = 'approved', approved_by = ?, expires_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (_actor(), expires, _now_iso(), exc_id),
        )
        conn.commit()
    return jsonify({"status": "ok", "id": exc_id, "expires_at": expires})
