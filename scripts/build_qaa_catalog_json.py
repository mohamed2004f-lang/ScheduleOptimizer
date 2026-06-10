# -*- coding: utf-8 -*-
"""استخراج كتالوج معايير المركز (إصدار 4، 2023) من نص PDF المستخرج."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRACT = ROOT / "scripts" / "qaa_standards_extract.txt"
OUT_DIR = ROOT / "backend" / "data"

IND_RE = re.compile(r"^(\d+)\.\s+(.+)$")
STD_BLOCK_RE = re.compile(r"(?=^المعيار\s)", re.MULTILINE)
IND_COUNT_RE = re.compile(r"\(\s*(\d+)\s*مؤش", re.DOTALL)
IND_MARKER_RE = re.compile(r"المؤش.{0,48}هذا المعيار")


def _split_pdf_blocks(text: str) -> tuple[str, str]:
    chunks = re.split(r"=+\ncollege__[^\n]+\n", text)
    if len(chunks) < 3:
        raise ValueError("تعذر تقسيم ملف الاستخراج إلى جزء برامجي ومؤسسي")
    return chunks[1], chunks[2]


def _slice_program_ug(prog_text: str) -> str:
    start = prog_text.find("الجزء الأولمعايير الاعتماد لبرامج")
    if start < 0:
        start = prog_text.find("الجزء الأول")
        m = re.search(r"الجزء الأول\s*معايير الاعتماد لبرامج", prog_text)
        if m:
            start = m.start()
    if start < 0:
        start = prog_text.find("المعيار الأوّ ل -  التّ خطيط")
    end = len(prog_text)
    for marker in ("الجزء الثاني: برامج", "الجزء الثانيمعايير", "الجزء الثاني-"):
        pos = prog_text.find(marker, max(start, 0) + 200)
        if pos > start:
            end = min(end, pos)
    return prog_text[start:end]


def _slice_mq(inst_text: str) -> str:
    start = inst_text.find("أولاا:  معايير اعتماد جودة الإدارة")
    if start < 0:
        start = inst_text.find("أولاً: معايير")
    end = inst_text.find("ثانياا: معايير الاعتماد المؤسسي")
    if end < 0:
        end = inst_text.find("ثانياًمعايير")
    if start < 0 or end <= start:
        return ""
    return inst_text[start:end]


def _slice_institutional(inst_text: str) -> str:
    start = inst_text.find("ثانياا: معايير الاعتماد المؤسسي")
    if start < 0:
        start = inst_text.find("ثانياًمعايير")
    if start < 0:
        return ""
    body = inst_text[start:]
    # جدول المحتويات فقط — نبدأ من أول «معيار» تفصيلي بعد الجدول
    detail = body.find("المعيار الأوّ ل - التّ خطيط")
    if detail < 0:
        detail = body.find("المعيار الأوّل - التّخطيط")
    if detail > 0:
        return body[detail:]
    return body


def _extract_std_title(block: str) -> str:
    for ln in block.splitlines():
        ln = ln.strip()
        if not ln.startswith("المعيار"):
            continue
        m = re.search(r"المعيار\s+.+?-\s*(.+?)(?:\s*\(|$)", ln)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()[:200]
        return ln[:200]
    return ""


def _extract_indicators(block: str) -> list[str]:
    marker = IND_MARKER_RE.search(block)
    if not marker:
        return []
    tail = block[marker.end() :]
    items: list[str] = []
    collecting = False
    for ln in tail.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("--- page"):
            continue
        if STD_BLOCK_RE.match(ln) or ln.startswith("الجزء") or re.match(r"^\d+\s+المعيار", ln):
            if collecting:
                break
            continue
        m = IND_RE.match(ln)
        if m:
            collecting = True
            items.append(re.sub(r"\s+", " ", m.group(2)).strip())
            continue
        if collecting and items and not re.match(r"^\d", ln):
            items[-1] = (items[-1] + " " + ln).strip()
    return items


def _parse_sections(
    text: str,
    *,
    catalog_version: str,
    scope: str,
    domain_code: str,
    std_prefix: str,
) -> list[dict]:
    if not text.strip():
        return []
    blocks = [b for b in STD_BLOCK_RE.split(text) if b.strip().startswith("المعيار")]
    rows: list[dict] = []
    std_order = 0
    for block in blocks:
        count_m = IND_COUNT_RE.search(block[:900])
        if not count_m:
            continue
        expected = int(count_m.group(1))
        std_title = _extract_std_title(block) or f"معيار {std_order + 1}"
        indicators = _extract_indicators(block)
        if expected and len(indicators) > expected:
            indicators = indicators[:expected]
        if len(indicators) < expected and expected <= 40:
            if not indicators:
                indicators = [f"مؤشر {j}" for j in range(1, expected + 1)]
        std_order += 1
        std_code = f"{std_prefix}-{std_order:02d}"
        weight = round(100.0 / max(len(blocks), 1), 2)
        for j, ind_title in enumerate(indicators, start=1):
            rows.append(
                {
                    "catalog_version": catalog_version,
                    "scope": scope,
                    "domain_code": domain_code,
                    "standard_code": std_code,
                    "standard_title_ar": std_title,
                    "standard_description": "",
                    "weight_percent": weight,
                    "indicator_code": f"{std_code}-{j:02d}",
                    "indicator_title_ar": ind_title[:500],
                    "source_type": "qaa_center",
                    "target_hint_ar": "دليل معايير المركز — الإصدار الرابع 2023",
                    "sort_order_std": std_order,
                    "sort_order_ind": j,
                }
            )
    return rows


def build_institutional() -> list[dict]:
    text = EXTRACT.read_text(encoding="utf-8")
    _, inst = _split_pdf_blocks(text)
    mq = _parse_sections(
        _slice_mq(inst),
        catalog_version="QAA-2023.4-INST",
        scope="institutional",
        domain_code="qaa_mq",
        std_prefix="INST-MQ",
    )
    inst_rows = _parse_sections(
        _slice_institutional(inst),
        catalog_version="QAA-2023.4-INST",
        scope="institutional",
        domain_code="qaa_inst",
        std_prefix="INST",
    )
    return mq + inst_rows


def build_program_ug() -> list[dict]:
    text = EXTRACT.read_text(encoding="utf-8")
    prog, _ = _split_pdf_blocks(text)
    return _parse_sections(
        _slice_program_ug(prog),
        catalog_version="QAA-2023.4-PROG-UG",
        scope="program_ug",
        domain_code="qaa_prog_ug",
        std_prefix="PROG-UG",
    )


def main() -> None:
    if not EXTRACT.exists():
        raise SystemExit(f"Missing {EXTRACT} — run PDF extract first")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    inst = build_institutional()
    prog = build_program_ug()
    inst_path = OUT_DIR / "qaa_catalog_inst_2023.json"
    prog_path = OUT_DIR / "qaa_catalog_prog_ug_2023.json"
    inst_path.write_text(json.dumps(inst, ensure_ascii=False, indent=2), encoding="utf-8")
    prog_path.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"INST: {len(inst)} indicators -> {inst_path}")
    print(f"PROG-UG: {len(prog)} indicators -> {prog_path}")
    inst_std = len({r["standard_code"] for r in inst})
    prog_std = len({r["standard_code"] for r in prog})
    print(f"INST standards: {inst_std}, PROG-UG standards: {prog_std}")


if __name__ == "__main__":
    main()
