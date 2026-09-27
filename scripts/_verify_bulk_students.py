from backend.services.utilities import get_connection
from werkzeug.security import check_password_hash

checks = [
    ("student23197", "23197", "23197FA"),
    ("student24338", "24338", "24338EB"),
    ("student25545", "25545", "25545M"),
]

with get_connection() as conn:
    cur = conn.cursor()
    for u, sid, pw in checks:
        row = cur.execute(
            "SELECT username, role, student_id, department_id, password_hash, is_active "
            "FROM users WHERE lower(username)=lower(?) LIMIT 1",
            (u,),
        ).fetchone()
        ok = bool(row) and check_password_hash(row[4], pw)
        print(u, "ok=", ok, "role=", row[1] if row else None, "sid=", row[2] if row else None, "dept=", row[3] if row else None, "active=", row[5] if row else None)
    n = cur.execute(
        "SELECT COUNT(1) FROM users WHERE role='student' AND student_id IN ("
        "SELECT CAST(student_id AS TEXT) FROM students WHERE department_id=3)"
    ).fetchone()
    print("civil_student_users_approx", n[0] if n else None)
