from backend.services.utilities import get_connection

with get_connection() as conn:
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT username, role, instructor_id, COALESCE(is_supervisor,0), COALESCE(is_active,1) FROM users WHERE instructor_id = ?",
        (1,),
    ).fetchall()
    print("users for instructor_id=1:")
    for r in rows:
        print(tuple(r))

    rows = cur.execute(
        "SELECT username, role, instructor_id, COALESCE(is_supervisor,0) FROM users WHERE role IN ('instructor','head_of_department','supervisor') ORDER BY username"
    ).fetchall()
    print("\nall faculty users:")
    for r in rows:
        print(tuple(r))
