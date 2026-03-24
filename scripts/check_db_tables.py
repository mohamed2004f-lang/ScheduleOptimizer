import sqlite3
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.utilities import DB_FILE


def main():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    print("DB_FILE:", DB_FILE)
    print("tables:", tables)
    print("users_exists:", "users" in tables)
    if "users" in tables:
        cols = cur.execute("PRAGMA table_info('users')").fetchall()
        print("users_cols:", cols)
    conn.close()


if __name__ == "__main__":
    main()

