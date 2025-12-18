import sqlite3, json
DB = r'backend/database/mechanical.db'
STUDENT = '3279'
SEMESTER = 'Fall'
YEAR = '2025'
SEM_LABEL = f"{SEMESTER} {YEAR}".strip()

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print('--- registrations schema ---')
for row in cur.execute("PRAGMA table_info('registrations')"):
    print(dict(row))

print('\n--- grades schema ---')
for row in cur.execute("PRAGMA table_info('grades')"):
    print(dict(row))

print('\n--- preview registrations to migrate (using available columns) ---')
# build a query that only references columns that exist in registrations
cols = [c['name'] for c in cur.execute("PRAGMA table_info('registrations')")]
print('registrations columns:', cols)
query = None
if 'course_name' in cols and 'units' in cols:
    query = '''
    SELECT r.course_name, r.units
    FROM registrations r
    LEFT JOIN grades g ON g.student_id = r.student_id AND g.course_name = r.course_name AND g.semester = ?
    WHERE r.student_id = ?
      AND g.course_name IS NULL
    '''
elif 'course_name' in cols:
    query = '''
    SELECT r.course_name
    FROM registrations r
    LEFT JOIN grades g ON g.student_id = r.student_id AND g.course_name = r.course_name AND g.semester = ?
    WHERE r.student_id = ?
      AND g.course_name IS NULL
    '''
else:
    print('registrations table lacks expected course_name column; cannot preview')

if query:
    rows = cur.execute(query, (SEM_LABEL, STUDENT)).fetchall()
    out = [dict(r) for r in rows]
    print(json.dumps({'student_id': STUDENT, 'semester': SEM_LABEL, 'count': len(out), 'rows': out}, ensure_ascii=False, indent=2))

conn.close()
