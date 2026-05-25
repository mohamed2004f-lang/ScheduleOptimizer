"""تصدير أهداف البرنامج + مخرجات التعلم + مصفوفة الربط."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd


def export_program_goals_outcomes_xlsx(
    goals: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    matrix: dict[str, Any] | None = None,
) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        if goals:
            gdf = pd.DataFrame(goals)
            cols_g = [
                c
                for c in (
                    "code",
                    "title_ar",
                    "title_en",
                    "description",
                    "sort_order",
                    "governance_status",
                    "is_active",
                )
                if c in gdf.columns
            ]
            gdf[cols_g].to_excel(writer, index=False, sheet_name="أهداف_البرنامج")
        else:
            pd.DataFrame([{"ملاحظة": "لا أهداف"}]).to_excel(
                writer, index=False, sheet_name="أهداف_البرنامج"
            )

        if outcomes:
            odf = pd.DataFrame(outcomes)
            cols_o = [
                c
                for c in (
                    "code",
                    "title_ar",
                    "title_en",
                    "description",
                    "domain",
                    "bloom_level",
                    "parent_glo_code",
                    "accreditation_tag",
                    "sort_order",
                    "governance_status",
                    "is_active",
                )
                if c in odf.columns
            ]
            odf[cols_o].to_excel(writer, index=False, sheet_name="مخرجات_SO")
        else:
            pd.DataFrame([{"ملاحظة": "لا مخرجات"}]).to_excel(
                writer, index=False, sheet_name="مخرجات_SO"
            )

        if matrix and matrix.get("goals") and matrix.get("outcomes"):
            goal_codes = [g["code"] for g in matrix["goals"]]
            outcome_codes = [o["code"] for o in matrix["outcomes"]]
            cells = {
                (c["goal_id"], c["outcome_id"]): True
                for c in (matrix.get("cells") or [])
            }
            goal_ids = {g["id"]: g["code"] for g in matrix["goals"]}
            outcome_ids = {o["id"]: o["code"] for o in matrix["outcomes"]}
            rows = []
            for gid, gcode in goal_ids.items():
                row = {"الهدف": gcode}
                for oid, ocode in outcome_ids.items():
                    row[ocode] = "✓" if cells.get((gid, oid)) else ""
                rows.append(row)
            pd.DataFrame(rows).to_excel(
                writer, index=False, sheet_name="مصفوفة_هدف_مخرج"
            )

        note = writer.book.add_worksheet("تعليمات")
        note.write(0, 0, "أهداف البرنامج (PG) ومخرجات الطالب (SO/PLO)")
        note.write(1, 0, "مصفوفة الربط: ✓ = يدعم الهدف هذا المخرج")
    return buf.getvalue()
