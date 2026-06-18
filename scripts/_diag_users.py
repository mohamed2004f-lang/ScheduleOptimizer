"""Check users/roles for notification routing."""
from backend.services.utilities import get_connection
from backend.services.course_workflow import department_id_for_course, usernames_for_department_hods

with get_connection() as conn:
    cur = conn.cursor()
    print("=== users with roles ===")
    rows = cur.execute(
        "SELECT username, role, department_id, instructor_id, COALESCE(is_active,1) FROM users ORDER BY role, username"
    ).fetchall()
    for r in rows:
        print(r)

    cn = "مقاومة المواد II"
    dept = department_id_for_course(conn, cn)
    print(f"\ncourse '{cn}' dept_id:", dept)
    print("hods for dept:", usernames_for_department_hods(conn, dept))

    print("\n=== recent notifications ===")
    rows = cur.execute(
        'SELECT id, "user", title, created_at FROM notifications ORDER BY id DESC LIMIT 10'
    ).fetchall()
    for r in rows:
        print(r)

    print("\n=== instructor 2 schedule row ===")
    row = cur.execute(
        "SELECT id, course_name, department_id, instructor_id FROM schedule WHERE id=21 OR rowid=21 LIMIT 1"
    ).fetchone()
    print("section 21:", row)
