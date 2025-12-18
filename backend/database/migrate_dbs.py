"""
مهمة: نسخ/ترحيل البيانات من جميع نسخ mechanical.db إلى النسخة المركزية backend/database/mechanical.db
ما يقوم به السكربت:
- يجد كل ملفات mechanical.db في المشروع
- يأخذ نسخًا احتياطية في مجلد backups/<timestamp>/
- يتأكد من وجود جداول في النسخة المركزية (استدعاء ensure_tables من utilities)
- لكل ملف مصدر (غير المركزي) ينسخ صفوف كل جدول إلى النسخة المركزية باستخدام INSERT OR REPLACE عندما يكون ذلك ممكنًا
- يطبع ملخصًا (أعداد الصفوف لكل جدول في كل ملف قبل وبعد)

ملاحظة: نفّذ هذا السكربت محليًا. يأخذ احتياطًا بسيطًا (نسخ ملفات) قبل التعديل.
"""
import os, shutil, sqlite3, datetime, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
CENTRAL = os.path.abspath(os.path.join(os.path.dirname(__file__), 'mechanical.db'))

print('Root:', ROOT)
print('Central DB path:', CENTRAL)

# find all mechanical.db
found = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    for fn in filenames:
        if fn.lower()=='mechanical.db':
            found.append(os.path.abspath(os.path.join(dirpath, fn)))

if not found:
    print('No mechanical.db files found; nothing to do')
    sys.exit(0)

print('Found DB files:')
for p in found:
    print(' -', p)

# prepare backup
now = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
backup_dir = os.path.join(ROOT, 'backups', now)
os.makedirs(backup_dir, exist_ok=True)

for p in found:
    shutil.copy2(p, os.path.join(backup_dir, os.path.relpath(p, ROOT).replace(os.sep, '_')))
print('Backups written to', backup_dir)

# Ensure central DB exists and has tables (use utilities.ensure_tables)
sys.path.append(os.path.abspath(os.path.join(ROOT, 'backend', 'services')))
try:
    from backend.services.utilities import ensure_tables
    ensure_tables()
    print('ensure_tables executed on central DB (if needed)')
except Exception as e:
    print('Warning: ensure_tables failed:', e)

# tables to migrate (from utilities.ensure_tables)
tables = [
    'students','courses','schedule','registrations','optimized_schedule',
    'conflict_report','proposed_moves','grades','prereqs','grade_audit'
]

# function to get columns for a table
def get_columns(conn, table):
    cur = conn.cursor()
    try:
        cur.execute(f"PRAGMA table_info('{table}')")
        cols = [r[1] for r in cur.fetchall()]
        return cols
    except Exception:
        return []

# open central connection
central_conn = sqlite3.connect(CENTRAL)
central_conn.row_factory = sqlite3.Row
central_cur = central_conn.cursor()

# report counts before
def counts(conn, table):
    try:
        c=conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return c
    except Exception:
        return None

print('\nCounts BEFORE migration (central):')
for t in tables:
    print(f" {t}: {counts(central_conn,t)}")

# perform migration from each source (skip central itself)
for src in found:
    if os.path.abspath(src)==os.path.abspath(CENTRAL):
        continue
    print('\nMigrating from', src)
    src_conn = sqlite3.connect(src)
    src_conn.row_factory = sqlite3.Row
    for t in tables:
        cols = get_columns(src_conn, t)
        if not cols:
            # table missing
            print(f"  {t}: missing in source")
            continue
        # fetch rows
        rows = src_conn.execute(f"SELECT * FROM {t}").fetchall()
        print(f"  {t}: {len(rows)} rows in source")
        if not rows:
            continue
        # ensure target has same columns (get columns from central)
        tgt_cols = get_columns(central_conn, t)
        if not tgt_cols:
            print(f"  {t}: missing in central, attempting to create via copying schema")
            # attempt to copy schema (simple approach)
            try:
                ddl = ''.join(line for line in src_conn.iterdump() if f'CREATE TABLE "{t}"' in line or f'CREATE TABLE {t}' in line)
                if ddl:
                    central_conn.executescript(ddl)
                    central_conn.commit()
                    tgt_cols = get_columns(central_conn, t)
                    print(f"   created {t} in central")
                else:
                    print(f"   cannot find DDL for {t}; skipping")
                    continue
            except Exception as e:
                print('   create table failed:', e)
                continue
        # prepare insert - use INSERT OR REPLACE when possible
        common = [c for c in cols if c in tgt_cols]
        if not common:
            print(f"   no common columns for {t}; skipping")
            continue
        placeholders = ','.join('?' for _ in common)
        col_list = ','.join(common)
        sql = f"INSERT OR REPLACE INTO {t} ({col_list}) VALUES ({placeholders})"
        # do in transaction
        count=0
        try:
            for r in rows:
                vals = [r[c] for c in common]
                central_conn.execute(sql, vals)
                count+=1
            central_conn.commit()
            print(f"   migrated {count} rows into central.{t}")
        except Exception as e:
            central_conn.rollback()
            print('   error migrating', t, e)
    src_conn.close()

print('\nCounts AFTER migration (central):')
for t in tables:
    print(f" {t}: {counts(central_conn,t)}")

central_conn.close()
print('\nMigration complete. Backups are in', backup_dir)
