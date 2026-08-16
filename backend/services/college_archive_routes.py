"""مسارات أرشيف الكلية + المشاركة."""

from __future__ import annotations

from functools import wraps
from typing import Any

from flask import abort, jsonify, render_template, request, send_file, session

from backend.core.auth import (
    _normalize_role,
    is_college_quality_lead_session,
    role_required,
)
from backend.core.college_archive_catalog import ARCHIVE_RECORD_TYPES, catalog_payload
from backend.services.archive_shares import (
    SOURCE_COLLEGE,
    SOURCE_DEPT,
    list_item_shares,
    list_shared_item_ids_for_user,
    replace_item_shares,
)
from backend.services.college_archive import (
    can_access_college_archive_portal,
    can_read_college_item,
    can_write_cabinet,
    create_college_archive_item,
    ensure_college_archive_table,
    get_college_archive_item,
    is_college_archive_admin,
    list_college_archive_items,
    list_items_by_ids,
    session_cabinet_owner,
    soft_delete_college_archive_item,
    visible_cabinets_for_user,
)
from backend.services.department_archive import get_archive_item, list_archive_items
from backend.services.quality_metrics import term_label_from_conn
from backend.services.utilities import get_connection

_PORTAL_ROLES = (
    "admin",
    "admin_main",
    "system_admin",
    "college_dean",
    "academic_vice_dean",
    # instructor/staff may enter only if college quality lead — gated inside
    "instructor",
    "staff",
    "head_of_department",
)

_SHARE_PICKER_ROLES = (
    "admin",
    "admin_main",
    "system_admin",
    "college_dean",
    "academic_vice_dean",
    "head_of_department",
    "instructor",
    "staff",
)


def _actor() -> str:
    return (session.get("user") or "").strip()


def _role() -> str:
    return _normalize_role((session.get("user_role") or "").strip())


def _cq() -> bool:
    return is_college_quality_lead_session()


def _home_dept(conn) -> int | None:
    try:
        from backend.services.academic_quality import _resolve_department_scope

        scoped = _resolve_department_scope(conn)
        if scoped is not None:
            return int(scoped)
    except Exception:
        pass
    cur = conn.cursor()
    row = cur.execute(
        "SELECT department_id FROM users WHERE username = ? LIMIT 1",
        (_actor(),),
    ).fetchone()
    if not row:
        return None
    from backend.services.quality_metrics import _row_val

    val = _row_val(row, 0, "department_id")
    try:
        return int(val) if val not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _require_college_portal():
    if not can_access_college_archive_portal(_role(), is_college_quality_lead=_cq()):
        abort(403)


def college_portal_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        _require_college_portal()
        return f(*args, **kwargs)

    return wrapped


def register_college_archive_routes(bp) -> None:
    @bp.route("/college-archive", methods=["GET"])
    @role_required(*_PORTAL_ROLES)
    @college_portal_required
    def college_archive_page():
        role = _role()
        cq = _cq()
        with get_connection() as conn:
            ensure_college_archive_table(conn)
            semester = (request.args.get("semester") or term_label_from_conn(conn) or "").strip()
            default_cab = session_cabinet_owner(role, is_college_quality_lead=cq) or "shared"
            if is_college_archive_admin(role):
                default_cab = (request.args.get("cabinet") or "shared").strip() or "shared"
            cabinet = (request.args.get("cabinet") or default_cab).strip() or default_cab
            view = (request.args.get("view") or "mine").strip().lower()
            cabinets = visible_cabinets_for_user(role, is_college_quality_lead=cq)
            items: list[dict[str, Any]] = []
            can_write = False
            if view == "shared_with_me":
                ids = list_shared_item_ids_for_user(
                    conn,
                    source=SOURCE_COLLEGE,
                    username=_actor(),
                    user_role=role,
                    is_college_quality_lead=cq,
                    home_department_id=_home_dept(conn),
                )
                items = list_items_by_ids(conn, ids)
                for it in items:
                    it["shared_with_me"] = True
            else:
                allowed_codes = {c["code"] for c in cabinets}
                if cabinet not in allowed_codes:
                    cabinet = default_cab if default_cab in allowed_codes else (
                        cabinets[0]["code"] if cabinets else "shared"
                    )
                items = list_college_archive_items(
                    conn, cabinet=cabinet, semester=semester or None
                )
                can_write = can_write_cabinet(cabinet, role, is_college_quality_lead=cq)

            depts = []
            cur = conn.cursor()
            rows = cur.execute(
                """
                SELECT id, code, name_ar FROM departments
                WHERE COALESCE(is_active, 1) = 1 ORDER BY code
                """
            ).fetchall() or []
            for r in rows:
                if hasattr(r, "keys"):
                    depts.append(
                        {"id": int(r["id"]), "code": r["code"], "name_ar": r["name_ar"] or r["code"]}
                    )
                else:
                    depts.append({"id": int(r[0]), "code": r[1], "name_ar": r[2] or r[1]})

            instructors = []
            try:
                irows = cur.execute(
                    """
                    SELECT username, department_id, role
                    FROM users
                    WHERE COALESCE(is_active, 1) = 1
                      AND role IN ('instructor', 'head_of_department', 'staff')
                    ORDER BY username
                    LIMIT 400
                    """
                ).fetchall() or []
                for r in irows:
                    if hasattr(r, "keys"):
                        instructors.append(
                            {
                                "username": r["username"],
                                "full_name": r["username"],
                                "department_id": r["department_id"],
                                "role": r["role"],
                            }
                        )
                    else:
                        instructors.append(
                            {
                                "username": r[0],
                                "full_name": r[0],
                                "department_id": r[1],
                                "role": r[2],
                            }
                        )
            except Exception:
                instructors = []

        return render_template(
            "college_archive.html",
            page_error=None,
            catalog=catalog_payload(),
            cabinets=cabinets,
            cabinet=cabinet,
            view=view,
            items=items,
            can_write=can_write,
            semester=semester,
            record_types=list(ARCHIVE_RECORD_TYPES.values()),
            departments=depts,
            instructors=instructors,
            default_cabinet=default_cab,
            is_admin=is_college_archive_admin(role),
        )

    @bp.route("/api/college-archive/items", methods=["GET"])
    @role_required(*_PORTAL_ROLES)
    @college_portal_required
    def college_archive_items_list():
        role = _role()
        cq = _cq()
        with get_connection() as conn:
            cabinet = (request.args.get("cabinet") or "").strip()
            view = (request.args.get("view") or "").strip()
            if view == "shared_with_me":
                ids = list_shared_item_ids_for_user(
                    conn,
                    source=SOURCE_COLLEGE,
                    username=_actor(),
                    user_role=role,
                    is_college_quality_lead=cq,
                    home_department_id=_home_dept(conn),
                )
                items = list_items_by_ids(conn, ids)
            else:
                if not can_write_cabinet(cabinet, role, is_college_quality_lead=cq) and not any(
                    c["code"] == cabinet
                    for c in visible_cabinets_for_user(role, is_college_quality_lead=cq)
                ):
                    return jsonify({"status": "error", "message": "خزينة غير متاحة"}), 403
                items = list_college_archive_items(
                    conn,
                    cabinet=cabinet,
                    semester=(request.args.get("semester") or "").strip() or None,
                    record_type=(request.args.get("record_type") or "").strip() or None,
                    q=(request.args.get("q") or "").strip() or None,
                )
        return jsonify({"status": "ok", "items": items}), 200

    @bp.route("/api/college-archive/items", methods=["POST"])
    @role_required(*_PORTAL_ROLES)
    @college_portal_required
    def college_archive_items_create():
        data = request.get_json(silent=True) or {}
        if request.content_type and "multipart/form-data" in (request.content_type or ""):
            data = {k: request.form.get(k) for k in request.form.keys()}
        role = _role()
        cq = _cq()
        cabinet = str(data.get("cabinet") or data.get("cabinet_code") or "")
        try:
            if not can_write_cabinet(cabinet, role, is_college_quality_lead=cq):
                return jsonify({"status": "error", "message": "لا صلاحية الكتابة على هذه الخزينة"}), 403
            raw = None
            oname = ""
            mime = ""
            f = request.files.get("file") if request.files else None
            if f and f.filename:
                raw = f.read()
                oname = f.filename
                mime = f.mimetype or ""
            with get_connection() as conn:
                item = create_college_archive_item(
                    conn,
                    cabinet=cabinet,
                    record_type=str(data.get("record_type") or ""),
                    title_ar=str(data.get("title_ar") or ""),
                    actor=_actor(),
                    actor_role=role if not cq else (role or "college_quality_lead"),
                    ref_number=str(data.get("ref_number") or ""),
                    doc_date=str(data.get("doc_date") or ""),
                    semester=str(data.get("semester") or "") or None,
                    party_ar=str(data.get("party_ar") or ""),
                    tags=str(data.get("tags") or ""),
                    body_text=str(data.get("body_text") or ""),
                    follow_up_status=str(data.get("follow_up_status") or "na"),
                    raw=raw,
                    original_name=oname,
                    mime_type=mime,
                )
            return jsonify({"status": "ok", "item": item}), 200
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    @bp.route("/api/college-archive/items/<int:item_id>", methods=["DELETE"])
    @role_required(*_PORTAL_ROLES)
    @college_portal_required
    def college_archive_items_delete(item_id: int):
        role = _role()
        cq = _cq()
        with get_connection() as conn:
            item = get_college_archive_item(conn, item_id)
            if not item:
                return jsonify({"status": "error", "message": "غير موجود"}), 404
            if not can_write_cabinet(
                str(item.get("cabinet_code") or ""), role, is_college_quality_lead=cq
            ):
                return jsonify({"status": "error", "message": "لا صلاحية"}), 403
            soft_delete_college_archive_item(conn, item_id, actor=_actor())
        return jsonify({"status": "ok"}), 200

    @bp.route("/api/college-archive/file/<int:item_id>", methods=["GET"])
    @role_required(*_SHARE_PICKER_ROLES)
    def college_archive_file_download(item_id: int):
        role = _role()
        cq = _cq()
        with get_connection() as conn:
            item = get_college_archive_item(conn, item_id)
            if not item:
                return jsonify({"status": "error", "message": "غير موجود"}), 404
            if not can_read_college_item(
                conn,
                item,
                username=_actor(),
                role=role,
                is_college_quality_lead=cq,
                home_department_id=_home_dept(conn),
            ):
                return jsonify({"status": "error", "message": "لا صلاحية"}), 403
            from backend.core.security import resolve_safe_upload_path
            from backend.services.college_archive import archive_upload_dir

            cab = str(item.get("cabinet_code") or "")
            safe = resolve_safe_upload_path(
                item.get("stored_path"),
                allowed_root=archive_upload_dir(cab),
            )
            if not safe:
                return jsonify({"status": "error", "message": "لا يوجد ملف"}), 404
            return send_file(
                safe,
                as_attachment=True,
                download_name=item.get("original_name") or safe.name,
            )

    @bp.route("/api/college-archive/items/<int:item_id>/shares", methods=["GET", "PUT"])
    @role_required(*_PORTAL_ROLES)
    @college_portal_required
    def college_archive_item_shares(item_id: int):
        role = _role()
        cq = _cq()
        with get_connection() as conn:
            item = get_college_archive_item(conn, item_id)
            if not item:
                return jsonify({"status": "error", "message": "غير موجود"}), 404
            cab = str(item.get("cabinet_code") or "")
            if not can_write_cabinet(cab, role, is_college_quality_lead=cq):
                return jsonify({"status": "error", "message": "لا صلاحية مشاركة هذا البند"}), 403
            if request.method == "GET":
                return jsonify(
                    {"status": "ok", "shares": list_item_shares(conn, source=SOURCE_COLLEGE, item_id=item_id)}
                ), 200
            data = request.get_json(force=True) or {}
            grants = data.get("grants") if isinstance(data.get("grants"), list) else []
            try:
                saved = replace_item_shares(
                    conn,
                    source=SOURCE_COLLEGE,
                    item_id=item_id,
                    grants=grants,
                    shared_by=_actor(),
                )
            except ValueError as e:
                return jsonify({"status": "error", "message": str(e)}), 400
            return jsonify({"status": "ok", "shares": saved}), 200

    # ——— مشاركة أرشيف القسم + مشارَك معي (قسم / كلية للمستلمين الأوسع) ———

    @bp.route("/archive/shared", methods=["GET"])
    @role_required(*_SHARE_PICKER_ROLES)
    def archive_shared_with_me_page():
        role = _role()
        cq = _cq()
        with get_connection() as conn:
            from backend.services.archive_shares import ensure_archive_share_tables
            from backend.services.department_archive import ensure_department_archive_table

            ensure_archive_share_tables(conn)
            ensure_department_archive_table(conn)
            ensure_college_archive_table(conn)
            home = _home_dept(conn)
            college_ids = list_shared_item_ids_for_user(
                conn,
                source=SOURCE_COLLEGE,
                username=_actor(),
                user_role=role,
                is_college_quality_lead=cq,
                home_department_id=home,
            )
            dept_ids = list_shared_item_ids_for_user(
                conn,
                source=SOURCE_DEPT,
                username=_actor(),
                user_role=role,
                is_college_quality_lead=cq,
                home_department_id=home,
            )
            college_items = list_items_by_ids(conn, college_ids)
            for it in college_items:
                it["source"] = "college"
                it["shared_with_me"] = True
            dept_items = []
            for iid in dept_ids:
                it = get_archive_item(conn, iid)
                if it:
                    it["source"] = "department"
                    it["shared_with_me"] = True
                    dept_items.append(it)
        return render_template(
            "archive_shared_with_me.html",
            college_items=college_items,
            dept_items=dept_items,
            can_open_college=can_access_college_archive_portal(role, is_college_quality_lead=cq),
        )

    @bp.route("/api/archive/items/<int:item_id>/shares", methods=["GET", "PUT"])
    @role_required(
        "admin",
        "admin_main",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
        "head_of_department",
    )
    def department_archive_item_shares(item_id: int):
        role = _role()
        with get_connection() as conn:
            item = get_archive_item(conn, item_id)
            if not item:
                return jsonify({"status": "error", "message": "غير موجود"}), 404
            scoped = None
            try:
                from backend.services.academic_quality import _resolve_department_scope

                scoped = _resolve_department_scope(conn)
            except Exception:
                pass
            if scoped is not None and int(item["department_id"]) != int(scoped):
                return jsonify({"status": "error", "message": "خارج نطاق قسمك"}), 403
            # الكتابة على المشاركة: رئيس القسم لقسمه، أو قيادة/أدمن
            if role == "head_of_department" and scoped is None:
                home = _home_dept(conn)
                if home is None or int(item["department_id"]) != int(home):
                    return jsonify({"status": "error", "message": "خارج نطاق قسمك"}), 403
            if request.method == "GET":
                return jsonify(
                    {"status": "ok", "shares": list_item_shares(conn, source=SOURCE_DEPT, item_id=item_id)}
                ), 200
            data = request.get_json(force=True) or {}
            grants = data.get("grants") if isinstance(data.get("grants"), list) else []
            # لـ dept_all_instructors املأ القسم من البند إن نقص
            for g in grants:
                if (g.get("target_kind") or "") == "dept_all_instructors" and not g.get(
                    "target_department_id"
                ):
                    g["target_department_id"] = item["department_id"]
            try:
                saved = replace_item_shares(
                    conn,
                    source=SOURCE_DEPT,
                    item_id=item_id,
                    grants=grants,
                    shared_by=_actor(),
                )
            except ValueError as e:
                return jsonify({"status": "error", "message": str(e)}), 400
            return jsonify({"status": "ok", "shares": saved}), 200

    @bp.route("/api/archive/share-targets", methods=["GET"])
    @role_required(*_SHARE_PICKER_ROLES)
    def archive_share_targets():
        """قائمة أهداف للمشاركة: قيادات + أعضاء قسم."""
        dept_id = request.args.get("department_id")
        with get_connection() as conn:
            cur = conn.cursor()
            users = []
            sql = """
                SELECT username, department_id, role
                FROM users
                WHERE COALESCE(is_active, 1) = 1
            """
            params: list[Any] = []
            if dept_id not in (None, "", "null"):
                sql += " AND department_id = ?"
                params.append(int(dept_id))
            sql += " ORDER BY username LIMIT 400"
            try:
                rows = cur.execute(sql, tuple(params)).fetchall() or []
            except Exception:
                rows = []
            for r in rows:
                if hasattr(r, "keys"):
                    users.append(
                        {
                            "username": r["username"],
                            "full_name": r["username"],
                            "department_id": r["department_id"],
                            "role": r["role"],
                        }
                    )
                else:
                    users.append(
                        {
                            "username": r[0],
                            "full_name": r[0],
                            "department_id": r[1],
                            "role": r[2],
                        }
                    )
            depts = []
            drows = cur.execute(
                "SELECT id, code, name_ar FROM departments WHERE COALESCE(is_active, 1) = 1 ORDER BY code"
            ).fetchall() or []
            for r in drows:
                if hasattr(r, "keys"):
                    depts.append(
                        {"id": int(r["id"]), "code": r["code"], "name_ar": r["name_ar"] or r["code"]}
                    )
                else:
                    depts.append({"id": int(r[0]), "code": r[1], "name_ar": r[2] or r[1]})
        return jsonify(
            {
                "status": "ok",
                "leadership_roles": [
                    {"code": "college_dean", "label_ar": "عميد الكلية"},
                    {"code": "academic_vice_dean", "label_ar": "الوكيل العلمي"},
                    {"code": "college_quality_lead", "label_ar": "رئيس قسم جودة بالكلية"},
                    {"code": "head_of_department", "label_ar": "رئيس قسم"},
                ],
                "users": users,
                "departments": depts,
            }
        ), 200
