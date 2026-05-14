from pathlib import Path
path = Path("backend/services/users.py")
t = path.read_text(encoding="utf-8")

# invite_status
a = """        if not user_row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404

        inv_rows = cur.execute("""
b = """        if not user_row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404
        if not target_username_allowed_for_actor(conn, _current_actor(), username):
            return jsonify({"status": "error", "message": "غير مسموح بعرض حالة الدعوة لهذا المستخدم."}), 403

        inv_rows = cur.execute("""
if a not in t:
    raise SystemExit("invite_status anchor missing")
t = t.replace(a, b, 1)

# resend_invite
a2 = """        if not row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404

        role = (row["role"]"""
b2 = """        if not row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404
        if not target_username_allowed_for_actor(conn, _current_actor(), username):
            return jsonify({"status": "error", "message": "غير مسموح بإعادة إرسال الدعوة لهذا المستخدم."}), 403

        role = (row["role"]"""
if a2 not in t:
    raise SystemExit("resend anchor missing")
t = t.replace(a2, b2, 1)

# delete_user
a3 = """    actor = _current_actor()
    with get_connection() as conn:
        cur = conn.cursor()
        before = cur.execute("""
b3 = """    actor = _current_actor()
    with get_connection() as conn:
        if not target_username_allowed_for_actor(conn, actor, username):
            return jsonify({"status": "error", "message": "غير مسموح بحذف هذا المستخدم خارج نطاق القسم الحالي."}), 403
        cur = conn.cursor()
        before = cur.execute("""
if a3 not in t:
    raise SystemExit("delete anchor missing")
t = t.replace(a3, b3, 1)

# toggle_active
a4 = """    actor = _current_actor()
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT username, role, student_id, instructor_id, COALESCE(is_supervisor,0), COALESCE(is_active,1) "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not row:"""
b4 = """    actor = _current_actor()
    with get_connection() as conn:
        if not target_username_allowed_for_actor(conn, actor, username):
            return jsonify({"status": "error", "message": "غير مسموح بتعديل هذا المستخدم خارج نطاق القسم الحالي."}), 403
        cur = conn.cursor()
        row = cur.execute(
            "SELECT username, role, student_id, instructor_id, COALESCE(is_supervisor,0), COALESCE(is_active,1) "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not row:"""
if a4 not in t:
    raise SystemExit("toggle anchor missing")
t = t.replace(a4, b4, 1)

# set_supervisor
a5 = """    actor = _current_actor()
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT username, role, student_id, instructor_id, COALESCE(is_supervisor,0), COALESCE(is_active,1) "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404
        before_user = _user_dict_from_row(row)
        role = _normalize_role(row[1])"""
# toggle and set_supervisor share same opening - need more unique

raise SystemExit("manual set_supervisor needed")
