"""
Attach-based fast migration from backup DB files into central DB.
Creates an extra backup of central before modifying. Uses INSERT OR REPLACE with common columns.
Usage: run from project root: python backend/database/attach_migrate.py
"""
import os
import sqlite3
import shutil
import datetime
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
CENTRAL = os.path.abspath(os.path.join(os.path.dirname(__file__), 'mechanical.db'))
BACKUP_DIR = os.path.join(ROOT, 'backups')
SPECIFIC_BACKUP = os.path.join(BACKUP_DIR, '20251110_225006')

if (os.environ.get("ALLOW_SQLITE_LEGACY") or "").strip().lower() not in ("1", "true", "yes"):
    print("This legacy SQLite migration tool is disabled by default.")
    print("Set ALLOW_SQLITE_LEGACY=1 to run it intentionally.")
    sys.exit(2)

if not os.path.exists(SPECIFIC_BACKUP):
    print('Backup folder not found:', SPECIFIC_BACKUP)
    sys.exit(1)

# find mechanical.db files inside that backup folder
backup_dbs = []
for dirpath, dirnames, filenames in os.walk(SPECIFIC_BACKUP):
    for fn in filenames:
        if fn.lower() == 'mechanical.db':
            backup_dbs.append(os.path.abspath(os.path.join(dirpath, fn)))

if not backup_dbs:
    print('No mechanical.db found in', SPECIFIC_BACKUP)
    sys.exit(1)

print('Central DB:', CENTRAL)
print('Backup DBs to process:')
for p in backup_dbs:
    print(' -', p)

# extra backup of central
now = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
central_backup = os.path.join(BACKUP_DIR, f'central_pre_attach_{now}.db')
shutil.copy2(CENTRAL, central_backup)
print('Made extra backup of central at', central_backup)

TABLES = [
    'students','courses','schedule','registrations','optimized_schedule',
    'conflict_report','proposed_moves','grades','prereqs','grade_audit'
]

def get_cols(conn, table):
    cur = conn.execute(f"PRAGMA table_info('{table}')")
    return [r[1] for r in cur.fetchall()]

# Connect central
conn = sqlite3.connect(CENTRAL)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# counts before
print('\nCounts BEFORE:')
for t in TABLES:
    try:
        c = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    except Exception:
        c = None
    print(f" {t}: {c}")

for src in backup_dbs:
    if os.path.abspath(src) == os.path.abspath(CENTRAL):
        print('Skipping central itself:', src)
        continue
    tag = 'src'
    print('\nProcessing backup DB:', src)
    try:
        cur.execute(f"ATTACH DATABASE ? AS {tag}", (src,))
    except Exception as e:
        print('Attach failed:', e)
        continue
    try:
        conn.execute('BEGIN')
        for t in TABLES:
            # check src has table
            try:
                src_cols = [r[1] for r in conn.execute(f"PRAGMA {tag}.table_info('{t}')")]
            except Exception:
                src_cols = []
            if not src_cols:
                print(f"  {t}: not present in source")
                continue
            tgt_cols = [r[1] for r in conn.execute(f"PRAGMA main.table_info('{t}')")]
            common = [c for c in src_cols if c in tgt_cols]
            if not common:
                print(f"  {t}: no common columns, skipping")
                continue
            col_list = ','.join(common)
            sql = f"INSERT OR REPLACE INTO main.{t} ({col_list}) SELECT {col_list} FROM {tag}.{t};"
            try:
                cur.execute(sql)
                print(f"  {t}: migrated via INSERT SELECT")
            except Exception as e:
                print(f"  {t}: error during INSERT SELECT: {e}")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print('Transaction failed:', e)
    finally:
        try:
            cur.execute(f"DETACH DATABASE {tag}")
        except Exception as e:
            print('Detach failed:', e)

# counts after
print('\nCounts AFTER:')
for t in TABLES:
    try:
        c = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    except Exception:
        c = None
    print(f" {t}: {c}")

print('\nRunning VACUUM on central DB (may take a moment)')
try:
    cur.execute('VACUUM')
    print('VACUUM completed')
except Exception as e:
    print('VACUUM failed:', e)

conn.close()
print('\nAttach-based migration finished.')
