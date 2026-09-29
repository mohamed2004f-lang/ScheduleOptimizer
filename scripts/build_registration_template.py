"""
بناء قالب Word لاستمارة التسجيل ليطابق تنسيق طباعة المستعرض (عربي RTL).
يشغّل: python scripts/build_registration_template.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from lxml import etree

OUTPUT_PATH = os.path.join(ROOT, "frontend", "templates", "registration_form_template.docx")
LOGO_PATH = os.path.join(ROOT, "frontend", "static", "images", "college_logo_white.png")
LOGO_FALLBACK = os.path.join(ROOT, "frontend", "static", "images", "college_logo.png")


def _set_rtl_para(p) -> None:
    try:
        pPr = p._p.get_or_add_pPr()
        bidi = pPr.find(qn("w:bidi"))
        if bidi is None:
            bidi = etree.SubElement(pPr, qn("w:bidi"))
        bidi.set(qn("w:val"), "1")
    except Exception:
        pass


def _compact_para(p, *, before: float = 0, after: float = 2) -> None:
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    try:
        pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    except Exception:
        pass


def _set_cell_text(cell, text: str, *, bold: bool = False, center: bool = False, size_pt: float = 11):
    text = "" if text is None else str(text)
    p = cell.paragraphs[0]
    for paragraph in cell.paragraphs[1:]:
        paragraph._element.getparent().remove(paragraph._element)
    p.clear()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.RIGHT
    _compact_para(p, before=0, after=0)
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size_pt)
    _set_rtl_para(p)


def _clear_cell_borders(cell) -> None:
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    old = tcPr.find(qn("w:tcBorders"))
    if old is not None:
        tcPr.remove(old)
    borders = etree.SubElement(tcPr, qn("w:tcBorders"))
    for edge in ("top", "left", "bottom", "right"):
        el = etree.SubElement(borders, qn(f"w:{edge}"))
        el.set(qn("w:val"), "none")
        el.set(qn("w:sz"), "0")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "auto")


def _set_table_rtl(table) -> None:
    """
    عرض أعمدة الجدول من اليمين لليسار في Word.
    العمود 0 يظهر يميناً → ت / اسم الطالب على اليمين كما في الطباعة العربية.
    """
    tbl = table._tbl
    tblPr = tbl.tblPr
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)
    if tblPr.find(qn("w:bidiVisual")) is None:
        tblPr.append(OxmlElement("w:bidiVisual"))


def _add_center(doc: Document, text: str, *, bold=False, size=12, underline=False, after=2) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _compact_para(p, before=0, after=after)
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    run.underline = underline
    _set_rtl_para(p)


def _add_right_line(doc: Document, text: str, *, size=10, after=3) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _compact_para(p, before=0, after=after)
    run = p.add_run(text)
    run.font.size = Pt(size)
    _set_rtl_para(p)


def build_template() -> Document:
    doc = Document()
    for section in doc.sections:
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(1.0)
        section.bottom_margin = Cm(1.0)
        section.left_margin = Cm(1.2)
        section.right_margin = Cm(1.2)

    # ترويسة LTR بصرياً: شعار يسار + جامعة/كلية يمين (بدون bidiVisual)
    brand = doc.add_table(rows=1, cols=2)
    brand.style = "Table Grid"
    left, right = brand.rows[0].cells
    _clear_cell_borders(left)
    _clear_cell_borders(right)

    lp = left.paragraphs[0]
    lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _compact_para(lp)
    logo = LOGO_PATH if os.path.isfile(LOGO_PATH) else (LOGO_FALLBACK if os.path.isfile(LOGO_FALLBACK) else None)
    if logo:
        lp.add_run().add_picture(logo, width=Cm(2.3))

    right.paragraphs[0].clear()
    rp1 = right.paragraphs[0]
    rp1.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _compact_para(rp1, after=1)
    r1 = rp1.add_run("جامعة درنة")
    r1.bold = True
    r1.font.size = Pt(15)
    _set_rtl_para(rp1)
    rp2 = right.add_paragraph()
    rp2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _compact_para(rp2, after=0)
    r2 = rp2.add_run("كلية الهندسة")
    r2.bold = True
    r2.font.size = Pt(12)
    _set_rtl_para(rp2)

    _add_center(doc, "مكتب التسجيل والقبول", bold=True, size=12, after=1)
    _add_center(doc, "قسم {{ department }}", bold=True, size=13, after=1)
    _add_center(doc, "نموذج تسجيل مقررات دراسية", bold=True, size=13, underline=True, after=4)

    # بيانات الطالب — RTL: يمين=الاسم/العام ، يسار=الرقم/الفصل
    info = doc.add_table(rows=2, cols=2)
    info.style = "Table Grid"
    _set_table_rtl(info)
    _set_cell_text(info.rows[0].cells[0], "اسم الطالب/ ــــة: {{ student_name }}", size_pt=11)
    _set_cell_text(info.rows[0].cells[1], "الرقم الدراسي: {{ student_id }}", size_pt=11)
    _set_cell_text(info.rows[1].cells[0], "العام الجامعي: {{ academic_year }}", size_pt=11)
    _set_cell_text(info.rows[1].cells[1], "الفصل الدراسي: {{ term_season }}", size_pt=11)

    _add_center(doc, "(المقررات المسجلة)", bold=True, size=11, after=2)

    # جدول المقررات — RTL:
    # يمين → يسار: ت | اسم المقرر | رمز المقرر | الوحدات | ملاحظات المشرف
    courses = doc.add_table(rows=13, cols=5)
    courses.style = "Table Grid"
    _set_table_rtl(courses)

    headers = ["ت", "اسم المقرر", "رمز المقرر", "الوحدات", "ملاحظات المشرف الأكاديمي"]
    for i, h in enumerate(headers):
        _set_cell_text(courses.rows[0].cells[i], h, bold=True, center=True, size_pt=10)

    for i in range(10):
        row = courses.rows[i + 1].cells
        _set_cell_text(row[0], "{{ courses[" + str(i) + "].index }}", center=True, size_pt=10)
        _set_cell_text(row[1], "{{ courses[" + str(i) + "].name }}", size_pt=10)
        _set_cell_text(row[2], "{{ courses[" + str(i) + "].code }}", center=True, size_pt=10)
        _set_cell_text(row[3], "{{ courses[" + str(i) + "].units }}", center=True, size_pt=10)
        _set_cell_text(row[4], "", size_pt=10)

    # صف المجموع — النص تحت عمود الوحدات (cells[3]) وليس تحت عمود ت
    for c in courses.rows[11].cells:
        _set_cell_text(c, "", size_pt=10)
    _set_cell_text(
        courses.rows[11].cells[3],
        "مجموع الوحدات = {{ total_units }}",
        bold=True,
        center=True,
        size_pt=10,
    )

    _set_cell_text(courses.rows[12].cells[0], "عدد الوحدات المنجزة = {{ completed_units }}", bold=True, size_pt=10)
    _set_cell_text(courses.rows[12].cells[1], "", size_pt=10)
    _set_cell_text(courses.rows[12].cells[2], "المعدل التراكمي = {{ cumulative_gpa }} %", bold=True, size_pt=10)
    _set_cell_text(courses.rows[12].cells[3], "", size_pt=10)
    _set_cell_text(courses.rows[12].cells[4], "التقدير / الحالة: {{ status }}", bold=True, size_pt=10)

    # التوقيعات: 3 أعمدة (يمين اسم | وسط تاريخ | يسار توقيع)
    # التسمية والنقاط كمقطعين منفصلين حتى لا يعكس Word ترتيب النقاط
    _add_center(doc, "(التوقيعات)", bold=True, size=11, after=2)

    def _set_run_rtl(run, *, rtl: bool) -> None:
        rPr = run._element.get_or_add_rPr()
        existing = rPr.find(qn("w:rtl"))
        if existing is not None:
            rPr.remove(existing)
        el = OxmlElement("w:rtl")
        el.set(qn("w:val"), "1" if rtl else "0")
        rPr.append(el)

    def _set_label_dots(cell, label: str, *, size_pt: float = 10) -> None:
        """تسمية عربية ثم نقاط — ترتيب بصري صحيح: التسمية يمينًا ثم الخط للنقاط."""
        p = cell.paragraphs[0]
        for paragraph in cell.paragraphs[1:]:
            paragraph._element.getparent().remove(paragraph._element)
        p.clear()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _compact_para(p, before=0, after=0)
        _set_rtl_para(p)
        r1 = p.add_run(f"{label}: ")
        r1.font.size = Pt(size_pt)
        _set_run_rtl(r1, rtl=True)
        r2 = p.add_run("........................")
        r2.font.size = Pt(size_pt)
        _set_run_rtl(r2, rtl=False)

    def _set_date_line(cell, *, size_pt: float = 10) -> None:
        p = cell.paragraphs[0]
        for paragraph in cell.paragraphs[1:]:
            paragraph._element.getparent().remove(paragraph._element)
        p.clear()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _compact_para(p, before=0, after=0)
        _set_rtl_para(p)
        r1 = p.add_run("التاريخ: ")
        r1.font.size = Pt(size_pt)
        _set_run_rtl(r1, rtl=True)
        r2 = p.add_run("..../..../20")
        r2.font.size = Pt(size_pt)
        _set_run_rtl(r2, rtl=False)
        r3 = p.add_run(" م")
        r3.font.size = Pt(size_pt)
        _set_run_rtl(r3, rtl=True)

    def _add_sign_row(label: str) -> None:
        t = doc.add_table(rows=1, cols=3)
        t.style = "Table Grid"
        _set_table_rtl(t)
        for cell in t.rows[0].cells:
            _clear_cell_borders(cell)
        _set_label_dots(t.rows[0].cells[0], label, size_pt=10)
        _set_date_line(t.rows[0].cells[1], size_pt=10)
        _set_label_dots(t.rows[0].cells[2], "التوقيع", size_pt=10)

    _add_sign_row("اسم الطالب / ــــة")
    _add_sign_row("المشرف الأكاديمي")

    note = doc.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _compact_para(note, after=4)
    nr = note.add_run("(((ملاحظة هامة: - علي الطالب / ــة احضار هذا النموذج طيلة فترة الامتحانات)))")
    nr.bold = True
    nr.font.size = Pt(10)
    _set_rtl_para(note)

    approvals = doc.add_table(rows=2, cols=2)
    approvals.style = "Table Grid"
    _set_table_rtl(approvals)
    for cell in list(approvals.rows[0].cells) + list(approvals.rows[1].cells):
        _clear_cell_borders(cell)
    _set_cell_text(approvals.rows[0].cells[0], "رئيس القسم", bold=True, center=True, size_pt=11)
    _set_cell_text(approvals.rows[0].cells[1], "رئيس قسم الدراسة والامتحانات", bold=True, center=True, size_pt=11)
    _set_cell_text(approvals.rows[1].cells[0], "____________________", center=True, size_pt=11)
    _set_cell_text(approvals.rows[1].cells[1], "____________________", center=True, size_pt=11)

    _add_center(doc, "يعتمد", bold=True, size=11, after=1)
    _add_center(doc, "مسجل الكلية", bold=True, size=11, after=1)
    _add_center(doc, "____________________", size=11, after=3)

    copies = doc.add_paragraph()
    copies.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _compact_para(copies, after=0)
    cr = copies.add_run(
        "يعد هذا النموذج من ثلاث نسخ: 1) نسخة القسم العلمي 2) نسخة مكتب التسجيل وشؤون الطلبة 3) نسخة الطالب / ــــة"
    )
    cr.font.size = Pt(9)
    _set_rtl_para(copies)

    return doc


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    doc = build_template()
    doc.save(OUTPUT_PATH)
    print("تم بناء قالب Word بترتيب أعمدة عربي (RTL):", OUTPUT_PATH)


if __name__ == "__main__":
    main()
