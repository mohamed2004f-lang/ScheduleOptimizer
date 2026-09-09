# -*- coding: utf-8 -*-
from __future__ import annotations
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass
os.environ.setdefault("ADMIN_PASSWORD", "x")
os.environ.setdefault("SECRET_KEY", "x")

from backend.database.database import close_pool, get_connection
from backend.core.department_scope_policy import courses_department_scope_filter

with get_connection() as conn:
    cur = conn.cursor()
    print("departments:")
    for r in cur.execute("SELECT id, code, name_ar FROM departments ORDER BY id").fetchall():
        print(" ", dict(r))
    r = cur.execute(
        "SELECT course_name, course_code, units, owning_department_id, "
        "COALESCE(is_archived, 0) AS is_archived FROM courses "
        "WHERE course_name LIKE ?",
        ("%قياسات%",),
    ).fetchone()
    print("course", dict(r) if r is not None else None)
    if r is not None:
        oid = r["owning_department_id"]
        for dep_id in (1, 2, 3, 4, 5):
            sql, params = courses_department_scope_filter(conn, dep_id)
            q = (
                "SELECT course_name FROM courses WHERE course_name LIKE ?"
                + sql
            )
            hits = cur.execute(q, ("%قياسات%",) + tuple(params)).fetchall()
            print(f" visible under scope dep={dep_id}:", [dict(h) for h in hits])
close_pool()
