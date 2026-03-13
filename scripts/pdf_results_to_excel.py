"""
تحويل نتيجة فصل من ملف PDF (أو عدة صفحات) إلى ملف Excel
متوافق مع قالب الاستيراد في المنظومة (استيراد نتيجة فصل كاملة).

الاعتماد الأساسي على tabula-py لاستخراج الجداول من PDF.

المتوقع من شكل الورقة (كما في المثال المرفق):
- جدول أفقي؛ الصفوف = طلبة، الأعمدة = مقررات + أعمدة إضافية (نسبة، حالة، ...).
- أول عمودين في كل جدول: اسم الطالب رباعاً، الرقم الدراسي.
- الأعمدة التالية: درجات المقررات، وبعض الأعمدة في اليسار قد تكون معدل/نسبة/حالة.
- القيم "//" تعني أن الطالب لم يسجل المقرر (تُترك كخانة فارغة في ملف الاستيراد).

الخوارزمية:
1) نقرأ كل الجداول من صفحات الـ PDF باستخدام tabula.
2) نطبّع كل جدول إلى DataFrame موحّد (اسم الطالب، الرقم، وأعمدة الدرجات).
3) ندمج كل الدُفعات (الصفحات) في DataFrame واحد.
4) نبني ملف Excel على هيئة:
   - الصف الأول: عناوين الأعمدة: "الاسم الرباعي", "الرقم الدراسي", <أسماء المقررات ...>
   - الصف الثاني: الوحدات (يتم تعيينها رقم ثابت افتراضياً ويمكن تعديلها لاحقاً في Excel).
   - من الصف الثالث: بيانات الطلبة.

ملاحظات مهمة:
- تحتاج إلى تثبيت tabula-py و Java على جهازك:
    pip install tabula-py pandas
  وتثبيت Java Runtime (JRE) أو OpenJDK حتى تعمل tabula.

- هذا السكربت نقطة انطلاق، وقد تحتاج إلى ضبط أسماء الأعمدة العربية بالضبط
  (حسب ما يظهر في ملف الـ PDF الفعلي) عبر الثوابت أدناه.
"""

from __future__ import annotations

import os
from typing import List

import pandas as pd

try:
    import tabula  # type: ignore
except ImportError:
    raise SystemExit(
        "tabula-py غير مثبتة.\n"
        "رجاءً ثبّتها بالأمر:\n\n"
        "    pip install tabula-py pandas\n\n"
        "وتأكّد من وجود Java على الجهاز."
    )


# -----------------------------
# إعدادات يمكن تعديلها
# -----------------------------

# مسار ملف الـ PDF المصدر
PDF_PATH = "results.pdf"

# ملف الإخراج (Excel) المتوافق مع الاستيراد
OUT_XLSX = "results_for_import.xlsx"

# أسماء الأعمدة التي تمثل اسم الطالب ورقمه كما تظهر في PDF بعد الاستخراج
# يمكن أن تضطر لتعديلها بحسب النص الفعلي الذي يخرجه tabula.
POSSIBLE_NAME_COLUMNS = [
    "اسم الطالب رباعاً",
    "اسم الطالب رباعا",
    "اسم الطالب رباعى",
    "اسم الطالب",
]

POSSIBLE_ID_COLUMNS = [
    "الرقم الدراسي",
    "الرقم الجامعي",
    "الرقم الجامعى",
    "الرقم",
]

# عدد الوحدات الافتراضي للمقررات (يمكنك تعديله أو تعديله لاحقاً في Excel)
DEFAULT_UNITS = 3


def _normalize_column_name(col: str) -> str:
    """تبسيط اسم العمود للتطابق العددي/الحرفي البسيط."""
    if col is None:
        return ""
    text = str(col)
    for ch in ["\n", "\r", "\t"]:
        text = text.replace(ch, " ")
    # إزالة تكرار المسافات
    text = " ".join(text.split())
    return text.strip()


def _find_first_matching_column(cols: List[str], candidates: List[str]) -> str | None:
    """إيجاد أول عمود من cols يطابق أياً من candidates (بعد التطبيع البسيط)."""
    norm_cols = { _normalize_column_name(c): c for c in cols }
    norm_candidates = [_normalize_column_name(c) for c in candidates]
    for cand in norm_candidates:
        for norm_col, original in norm_cols.items():
            if cand and cand in norm_col:
                return original
    return None


def extract_tables_from_pdf(pdf_path: str) -> List[pd.DataFrame]:
    """استخراج جميع الجداول من جميع الصفحات باستخدام tabula."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"لم يتم العثور على ملف PDF: {pdf_path}")

    # lattice=True لمحاولة اكتشاف حدود الجداول، stream=True للنص الحر
    # نجرب lattice أولاً لأنه غالباً مناسب للجداول الواضحة
    print(f"قراءة الجداول من {pdf_path} باستخدام tabula.lattice ...")
    tables = tabula.read_pdf(pdf_path, pages="all", multiple_tables=True, lattice=True)

    if not tables:
        print("لم يتم العثور على جداول بـ lattice، المحاولة باستخدام stream ...")
        tables = tabula.read_pdf(pdf_path, pages="all", multiple_tables=True, stream=True)

    if not tables:
        raise RuntimeError("لم يتم العثور على أي جداول في ملف الـ PDF.")

    print(f"تم العثور على {len(tables)} جدول/جداول في ملف الـ PDF.")
    return tables


def normalize_single_table(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    تطبيع جدول واحد من PDF إلى DataFrame يضم:
    - أعمدة: اسم الطالب، الرقم، وكل أعمدة الدرجات كما هي.
    """
    # 1) أول صف غالباً هو رؤوس الأعمدة
    df = df_raw.copy()
    df = df.dropna(how="all")  # إزالة الصفوف الفارغة بالكامل
    if df.empty:
        return pd.DataFrame()

    # اجعل الصف الأول كرؤوس
    df.columns = [ _normalize_column_name(c) for c in df.iloc[0].tolist() ]
    df = df.iloc[1:].reset_index(drop=True)

    # استبدال قيم '//' وما شابهها بقيم فارغة
    df = df.replace({"///": None, "//": None})

    # البحث عن أعمدة الاسم والرقم
    cols = list(df.columns)
    name_col = _find_first_matching_column(cols, POSSIBLE_NAME_COLUMNS)
    id_col = _find_first_matching_column(cols, POSSIBLE_ID_COLUMNS)

    if not name_col or not id_col:
        print("تحذير: لم يتم العثور على عمود اسم/رقم الطالب في هذا الجدول، سيتم تجاوزه.")
        return pd.DataFrame()

    # أعمدة الدرجات = بقية الأعمدة بعد الاسم والرقم
    grade_cols = [c for c in cols if c not in (name_col, id_col)]
    if not grade_cols:
        print("تحذير: لا توجد أعمدة مقررات في هذا الجدول، سيتم تجاوزه.")
        return pd.DataFrame()

    useful_cols = [name_col, id_col] + grade_cols
    df = df[useful_cols].copy()

    # إعادة تسمية الأعمدة الرئيسية إلى أسماء ثابتة
    df = df.rename(columns={name_col: "الاسم الرباعي", id_col: "الرقم الدراسي"})

    # إزالة الصفوف التي لا تحتوي رقم دراسي على الأقل
    df["الرقم الدراسي"] = df["الرقم الدراسي"].astype(str).str.strip()
    df["الاسم الرباعي"] = df["الاسم الرباعي"].astype(str).str.strip()
    df = df[df["الرقم الدراسي"].astype(bool)]

    return df.reset_index(drop=True)


def build_import_excel(tables: List[pd.DataFrame]) -> pd.DataFrame:
    """
    دمج الجداول المطبوعة وتحويلها إلى DataFrame بالصيغة النهائية
    المتوافقة مع استيراد نتيجة فصل كاملة.
    """
    normalized: List[pd.DataFrame] = []
    for i, t in enumerate(tables, start=1):
        print(f"تطبيع الجدول رقم {i} ...")
        df_norm = normalize_single_table(t)
        if not df_norm.empty:
            normalized.append(df_norm)

    if not normalized:
        raise RuntimeError("لم يتم استخراج أي بيانات صالحة من الجداول.")

    all_df = pd.concat(normalized, ignore_index=True)

    # كشف أسماء المقررات (كل الأعمدة بعد أول عمودين)
    all_cols = list(all_df.columns)
    course_cols = all_cols[2:]
    if not course_cols:
        raise RuntimeError("لم يتم التعرف على أعمدة مقررات بعد دمج الجداول.")

    header = ["الاسم الرباعي", "الرقم الدراسي"] + course_cols
    units = ["", ""] + [DEFAULT_UNITS for _ in course_cols]

    rows = []
    rows.append(header)
    rows.append(units)

    for _, row in all_df.iterrows():
        name = row["الاسم الرباعي"]
        sid = row["الرقم الدراسي"]
        grades = [row[c] for c in course_cols]
        rows.append([name, sid] + grades)

    df_out = pd.DataFrame(rows)
    return df_out


def main() -> None:
    print("بدء تحويل نتائج الفصل من PDF إلى Excel متوافق مع الاستيراد ...")
    print(f"ملف المصدر: {PDF_PATH}")
    tables = extract_tables_from_pdf(PDF_PATH)
    df_out = build_import_excel(tables)

    df_out.to_excel(OUT_XLSX, index=False, header=False)
    print(f"تم إنشاء الملف: {OUT_XLSX}")
    print("يمكنك الآن مراجعته في Excel (الوحدات، أسماء الأعمدة)، ثم استيراده من شاشة 'استيراد نتيجة فصل كاملة'.")


if __name__ == "__main__":
    main()

