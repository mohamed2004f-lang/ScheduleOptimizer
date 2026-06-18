from backend.services.utilities import get_connection
from backend.core.auth import _fetch_user_session_row

with get_connection() as conn:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT username, role, instructor_id, is_supervisor, COALESCE(is_supervisor,0) AS sup2 FROM users WHERE username=?",
        ("ABDULJAWAD ASHOUR",),
    ).fetchone()
    print("explicit columns:", tuple(row))
    if hasattr(row, "keys"):
        print("keys:", list(row.keys()))

    row2 = _fetch_user_session_row(cur, "ABDULJAWAD ASHOUR")
    print("_fetch_user_session_row:", list(row2) if row2 else None)

    # all columns
    cols = cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='users' ORDER BY ordinal_position"
    ).fetchall()
    print("users columns:", [tuple(c) for c in cols])
