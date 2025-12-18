# small inspector to debug why student 'هناء' conflict didn't appear
import sys
import os
import sqlite3
# ensure project root is on sys.path so 'backend' package can be imported
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from backend.services import utilities

DB = utilities.DB_FILE
print('Using DB:', DB)
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

name_like = '%هناء%'
cur.execute("SELECT * FROM students WHERE student_name LIKE ?", (name_like,))
students = [dict(r) for r in cur.fetchall()]
print('\nSTUDENTS matching هناء:')
for s in students:
    print(s)

if not students:
    print('\nNo student named هناء found. Stopping.')
    conn.close()
    exit(0)

student_id = students[0]['student_id']
print('\nUsing student_id:', student_id)

cur.execute("SELECT * FROM registrations WHERE student_id=?", (student_id,))
regs = [dict(r) for r in cur.fetchall()]
print('\nREGISTRATIONS:')
for r in regs:
    print(r)

# show schedule rows for any course with ميكانيكا in name
cur.execute("SELECT * FROM schedule WHERE course_name LIKE '%ميكانيكا%'")
sched = [dict(r) for r in cur.fetchall()]
print('\nSCHEDULE rows for courses with ميكانيكا:')
for r in sched:
    print(r)

# optimized schedule
cur.execute('SELECT * FROM optimized_schedule')
opt = [dict(r) for r in cur.fetchall()]
print('\noptimized_schedule (first 50 if large):')
for r in opt[:50]:
    print(r)

# conflict_report rows for this student
cur.execute('SELECT * FROM conflict_report WHERE student_id=?', (student_id,))
conf = [dict(r) for r in cur.fetchall()]
print('\nconflict_report rows for student:')
for r in conf:
    print(r)

# additionally, check per-student computed conflicts by grouping optimized_schedule by day/time and looking for multiple registrations
print('\nPer-student computed conflicts check (from optimized_schedule):')
# build mapping section_id->(course_name,day,time)
sections = {}
for row in opt:
    sid = row.get('section_id')
    sections[sid] = (row.get('course_name'), row.get('day'), row.get('time'))

# get student's registered section_ids in optimized_schedule (if registrations store course_name only, we match by course_name)
# first try matching by course_name: collect optimized sections whose course_name matches student's registrations
reg_course_names = [r['course_name'] for r in regs]
student_sections = [row for row in opt if row.get('course_name') in reg_course_names]
print('Student sections in optimized_schedule by course_name match:')
for s in student_sections:
    print(s)

# group student's sections by day+time
from collections import defaultdict
by_slot = defaultdict(list)
for s in student_sections:
    key = (s.get('day'), s.get('time'))
    by_slot[key].append(s)

conflicts_found = []
for k,v in by_slot.items():
    if len(v) > 1:
        conflicts_found.append((k, v))

print('\nConflicts computed from optimized_schedule for student:')
for k,v in conflicts_found:
    print('slot',k)
    for item in v:
        print('  ', item)

conn.close()
print('\nDone')

# Also call compute_per_student_conflicts to see what it now returns
from backend.services.students import compute_per_student_conflicts
from backend.services.utilities import get_connection
with get_connection() as c:
    conflicts_all = compute_per_student_conflicts(c)
    print('\ncompute_per_student_conflicts returned (filtered for هناء):')
    for row in conflicts_all:
        if row.get('student_id') == student_id:
            print(row)
