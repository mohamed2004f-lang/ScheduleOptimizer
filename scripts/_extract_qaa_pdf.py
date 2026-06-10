# -*- coding: utf-8 -*-
from pathlib import Path
from pypdf import PdfReader

upd = Path("backend/uploads/accreditation_evidence")
out = Path("scripts/qaa_standards_extract.txt")
pdfs = sorted([p for p in upd.glob("*.pdf") if p.stat().st_size > 1000000], key=lambda p: p.stat().st_size)

with out.open("w", encoding="utf-8") as f:
    for pdf in pdfs:
        r = PdfReader(str(pdf))
        f.write(f"\n{'='*60}\n{pdf.name}\npages={len(r.pages)}\nsize={pdf.stat().st_size}\n{'='*60}\n")
        for i, page in enumerate(r.pages):
            t = page.extract_text() or ""
            f.write(f"\n--- page {i+1} ---\n{t}\n")

print("written", out)
