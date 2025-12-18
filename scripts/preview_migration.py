import sqlite3
import json

DB = r"backend/database/mechanical.db"
STUDENT = '3279'
SEMESTER = 'Fall'
YEAR = '2025'
SEM_LABEL = f"{SEMESTER} {YEAR}".strip()

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
q = '''
SELECT r.course_name, r.course_code, r.units
FROM registrations r
LEFT JOIN grades g ON g.student_id = r.student_id AND g.course_name = r.course_name AND g.semester = ?
WHERE r.student_id = ?
  AND g.course_name IS NULL
'''
rows = cur.execute(q, (SEM_LABEL, STUDENT)).fetchall()
output = [dict(r) for r in rows]
print(json.dumps({"student_id": STUDENT, "semester_label": SEM_LABEL, "count": len(output), "rows": output}, ensure_ascii=False, indent=2))
conn.close()
