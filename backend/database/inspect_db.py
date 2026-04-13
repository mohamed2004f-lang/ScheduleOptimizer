import sqlite3
import os
db='mechanical.db'
print('DB file:', os.path.abspath(db))
with sqlite3.connect(db) as conn:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    print('Tables:', [r[0] for r in cur.fetchall()])
    try:
        cur.execute("PRAGMA table_info('courses')")
        print('courses schema:', cur.fetchall())
    except Exception as e:
        print('courses schema error:', e)
    try:
        rows = cur.execute("SELECT course_name, course_code, units FROM courses").fetchall()
        print('courses rows count:', len(rows))
        for r in rows:
            print('COURSE ROW:', r)
    except Exception as e:
        print('courses select error:', e)
    try:
        rows = cur.execute("SELECT * FROM registrations LIMIT 20").fetchall()
        print('registrations sample count:', len(rows))
        for r in rows:
            print('REG:', r)
    except Exception as e:
        print('registrations select error:', e)
