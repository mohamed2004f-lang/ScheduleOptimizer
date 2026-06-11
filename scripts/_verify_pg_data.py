"""تحقق سريع: PostgreSQL نشطة وبياناتها."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database.database import get_connection, is_postgresql, table_exists
from backend.services.quality_metrics import term_label_from_conn


def main() -> None:
    if not is_postgresql():
        print("ERROR: DATABASE_URL is not PostgreSQL.")
        sys.exit(1)
    print("Backend: PostgreSQL")

    with get_connection() as conn:
        print("Current term:", term_label_from_conn(conn))
        cur = conn.cursor()
        for t in (
            "students",
            "registrations",
            "grades",
            "course_evaluations",
            "survey_responses",
            "accreditation_evidence",
            "users",
        ):
            if table_exists(conn, t):
                row = cur.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()
                n = row["n"] if hasattr(row, "keys") else row[0]
                print(f"  {t}: {n}")


if __name__ == "__main__":
    main()
