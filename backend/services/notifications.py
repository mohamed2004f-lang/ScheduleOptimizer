from flask import Blueprint, jsonify, request, session

from backend.core.auth import login_required
from .utilities import get_connection

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("/", methods=["GET"])
@login_required
def list_notifications():
    """
    إرجاع إشعارات المستخدم الحالي.
    query params:
      - unread=1 لاختيار غير المقروء فقط
    """
    user = session.get("user")
    if not user:
        return jsonify({"notifications": []})
    unread_only = (request.args.get("unread") == "1")

    with get_connection() as conn:
        cur = conn.cursor()
        q = "SELECT id, title, body, is_read, created_at FROM notifications WHERE user = ?"
        params = [user]
        if unread_only:
            q += " AND is_read = 0"
        q += " ORDER BY created_at DESC, id DESC"
        rows = cur.execute(q, params).fetchall()
        items = []
        for r in rows:
            items.append(
                {
                    "id": r[0],
                    "title": r[1],
                    "body": r[2],
                    "is_read": bool(r[3]),
                    "created_at": r[4],
                }
            )
    return jsonify({"notifications": items})


@notifications_bp.route("/mark_read", methods=["POST"])
@login_required
def mark_read():
    """
    تعيين مجموعة من الإشعارات كمقروءة.
    body: { ids: [1,2,3] }
    """
    user = session.get("user")
    data = request.get_json(force=True) or {}
    ids = data.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"status": "error", "message": "ids يجب أن تكون قائمة"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in ids)
        params = ids + [user]
        cur.execute(
            f"UPDATE notifications SET is_read = 1 WHERE id IN ({placeholders}) AND user = ?",
            params,
        )
        conn.commit()
    return jsonify({"status": "ok"})

