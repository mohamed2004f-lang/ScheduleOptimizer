#!/usr/bin/env python3
"""تعبئة/تحديث بنود لائحة المسار لكل قسم (وحدات التخرج وما قبل الشعبة)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.pathway_regulations import (  # noqa: E402
    DEPT_GRADUATION_TARGETS,
    ensure_pathway_regulation_defaults,
    get_pathway_regulation_value,
)
from backend.services.utilities import get_connection, close_pool


def main() -> int:
    with get_connection() as conn:
        ensure_pathway_regulation_defaults(conn)
        cur = conn.cursor()
        print("Synced pathway regulation defaults:")
        for code, grad in sorted(DEPT_GRADUATION_TARGETS.items()):
            row = cur.execute(
                "SELECT id FROM departments WHERE UPPER(TRIM(code)) = ? LIMIT 1",
                (code,),
            ).fetchone()
            if not row:
                print(f"  SKIP {code} — department not found")
                continue
            did = int(row[0] if not hasattr(row, "keys") else row["id"])
            g = get_pathway_regulation_value(cur, did, "dept_graduation_min_units")
            p = get_pathway_regulation_value(cur, did, "dept_pre_track_min_units")
            s = get_pathway_regulation_value(cur, did, "dept_specialization_min_units")
            print(f"  OK {code}: grad={int(g or grad)} pre_track={int(p or 0)} spec={int(s or 0)}")
    close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
