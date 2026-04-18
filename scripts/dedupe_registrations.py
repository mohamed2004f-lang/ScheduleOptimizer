"""
Script to remove duplicate registrations (and optionally create a unique index)
- Removes duplicates keeping the lowest id per (student_id, course_name)
- Creates a UNIQUE index on (student_id, course_name) to prevent future duplicates

Run: python scripts/dedupe_registrations.py
"""
import sqlite3
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from backend.services import utilities

DB = utilities.DB_FILE
print('Using DB:', DB)

def run():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    try:
        # counts before
        cur.execute("SELECT COUNT(*) FROM registrations")
        before = cur.fetchone()[0]
        print('registrations before:', before)

        # delete duplicates, keeping the first (min id)
        cur.execute("BEGIN")
        cur.execute("DELETE FROM registrations WHERE id NOT IN (SELECT MIN(id) FROM registrations GROUP BY student_id, course_name)")
        cur.execute("COMMIT")

        cur.execute("SELECT COUNT(*) FROM registrations")
        after = cur.fetchone()[0]
        print('registrations after dedupe:', after)

        # create unique index to prevent future duplicates
        try:
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_registrations_student_course ON registrations(student_id, course_name)")
            conn.commit()
            print('Unique index created (or already exists).')
        except sqlite3.IntegrityError as e:
            print('Could not create unique index due to existing duplicates. Please inspect DB. Error:', e)
    except Exception as e:
        print('Error during dedupe:', e)
    finally:
        conn.close()

if __name__ == '__main__':
    run()
