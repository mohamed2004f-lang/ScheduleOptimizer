"""Live diagnostic for announcements + notifications."""
from backend.services.utilities import get_connection, create_notification
from backend.services.schedule import _course_admin_payload
from backend.services.course_workflow import (
    username_for_instructor,
    usernames_for_department_hods,
    notify_baseline_submitted,
)

with get_connection() as conn:
    cur = conn.cursor()
    print("=== _course_admin_payload(2, 21) ===")
    try:
        p = _course_admin_payload(cur, 2, 21)
        print("OK announcements:", len(p["announcements"]))
        for a in p["announcements"][:3]:
            print(" ", a)
        print("closure status:", p["closure_report"].get("status"))
    except Exception:
        import traceback
        traceback.print_exc()

    print("\n=== username lookups ===")
    print("instructor 2:", username_for_instructor(conn, 2))
    print("hod dept 1:", usernames_for_department_hods(conn, 1))

    print("\n=== create_notification ===")
    try:
        create_notification("_diag_x", "اختبار", "نص")
        row = cur.execute(
            'SELECT id, title FROM notifications WHERE "user" = ?', ("_diag_x",)
        ).fetchone()
        print("inserted:", row)
        cur.execute('DELETE FROM notifications WHERE "user" = ?', ("_diag_x",))
        conn.commit()
    except Exception:
        import traceback
        traceback.print_exc()

    print("\n=== notify_baseline_submitted (dry) ===")
    try:
        notify_baseline_submitted(conn, course_name="مقاومة المواد II", baseline_id=999)
        n = cur.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        print("total notifications now:", n)
    except Exception:
        import traceback
        traceback.print_exc()
