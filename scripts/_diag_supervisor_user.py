"""Find user عبدالجواد التركاوي and supervisor flags."""
from backend.services.utilities import get_connection

with get_connection() as conn:
    cur = conn.cursor()
    print("=== instructors matching تركاوي / عبدالجواد ===")
    rows = cur.execute(
        "SELECT id, name, department_id FROM instructors WHERE name ILIKE ? OR name ILIKE ?",
        ("%تركاوي%", "%عبدالجواد%"),
    ).fetchall()
    for r in rows:
        print(tuple(r))

    print("\n=== users matching ===")
    rows = cur.execute(
        """
        SELECT username, role, instructor_id, COALESCE(is_supervisor,0), COALESCE(is_active,1), department_id
        FROM users
        WHERE username ILIKE ? OR username ILIKE ?
        """,
        ("%تركاوي%", "%عبدالجواد%"),
    ).fetchall()
    for r in rows:
        print(tuple(r))

    if rows:
        uname = str(rows[0][0])
        iid = rows[0][2]
        print(f"\n=== supervised students for instructor_id={iid} ===")
        try:
            sup = cur.execute(
                "SELECT COUNT(*) FROM instructor_student_assignments WHERE instructor_id = ?",
                (iid,),
            ).fetchone()[0]
            print("assignments count:", sup)
        except Exception as e:
            print("assignments table:", e)
