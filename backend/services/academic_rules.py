from flask import Blueprint, jsonify, request

from backend.core.auth import role_required
from .utilities import get_connection


academic_rules_bp = Blueprint("academic_rules", __name__)


DEFAULT_RULES = [
    {
        "rule_key": "warning_semester_threshold",
        "title": "حد الإنذار الأكاديمي الفصلي",
        "description": "يُعد الطالب في حالة إنذار إذا كان معدله الفصلي أقل من هذه النسبة (بعد أول فصل قُيّد فيه).",
        "category": "warnings",
        "value_number": 50.0,
        "value_text": None,
    },
    {
        "rule_key": "dismissal_cgpa_threshold",
        "title": "حد الفصل بناءً على المعدل التراكمي",
        "description": "إذا انخفض المعدل التراكمي عن هذه النسبة بعد عدد الفصول المحدد في بند (عدد الفصول قبل الفصل)، يُعرض الطالب للفصل وفق المادة 40 أو ما يعادلها، مع إمكانية منحه فرصة استثنائية واحدة.",
        "category": "dismissal",
        "value_number": 35.0,
        "value_text": None,
    },
    {
        "rule_key": "dismissal_min_semesters",
        "title": "عدد الفصول قبل تطبيق الفصل",
        "description": "عدد الفصول الدراسية من تاريخ تحاق الطالب قبل أن يُنظر في فصله بسبب انخفاض المعدل التراكمي عن الحد المسموح (مثال شائع: تجاهل أول فصلين، ثم يُنظر في الفصل بعد ذلك).",
        "category": "dismissal",
        "value_number": 2.0,
        "value_text": None,
    },
    {
        "rule_key": "max_consecutive_warnings",
        "title": "الحد الأقصى لعدد الإنذارات المتتالية",
        "description": "بعد تجاوز هذا العدد من الفصول المتتالية في حالة إنذار، تُعرض حالة الطالب على مجلس الكلية لاتخاذ قرار بالفصل أو منحه فرصة استثنائية.",
        "category": "warnings",
        "value_number": 3.0,
        "value_text": None,
    },
    # حدود مدة الدراسة (حد أدنى/أقصى + فصول إضافية مشروطة)
    {
        "rule_key": "study_min_regular_semesters",
        "title": "الحد الأدنى لفصول الدراسة الاعتيادية",
        "description": "أدنى عدد من الفصول الدراسية الاعتيادية للحصول على الدرجة (مثال: لا يقل عن ثمانية فصول اعتيادية).",
        "category": "duration",
        "value_number": 8.0,
        "value_text": None,
    },
    {
        "rule_key": "study_normal_max_semesters",
        "title": "الحد الأعلى العادي لفصول الدراسة الاعتيادية",
        "description": "المدة النظامية للدراسة في الكلية (مثال: عشرة فصول دراسية اعتيادية منذ بداية التسجيل بالدراسة). بعد هذا الحد يُعد الطالب متأخراً ويُتابع وضعه.",
        "category": "duration",
        "value_number": 10.0,
        "value_text": None,
    },
    {
        "rule_key": "study_absolute_max_semesters",
        "title": "الحد الأقصى المطلق لفصول الدراسة الاعتيادية",
        "description": "أقصى مدة يمكن أن يقضيها الطالب في الدراسة لنيل درجة البكالوريوس (مثال: لا تزيد عن أربعة عشر فصلاً دراسياً اعتيادياً).",
        "category": "duration",
        "value_number": 14.0,
        "value_text": None,
    },
    {
        "rule_key": "study_extra_semesters_once",
        "title": "عدد الفصول الإضافية المسموح بها لمرة واحدة",
        "description": "عدد الفصول الإضافية التي يمكن منحها للطالب لمرة واحدة فقط فوق المدة النظامية، إذا تقدم بعذر مقبول يقره مجلس الكلية (مثال: فصلان إضافيان).",
        "category": "duration",
        "value_number": 2.0,
        "value_text": None,
    },
    {
        "rule_key": "study_extra_semesters_min_units",
        "title": "الحد الأدنى للوحدات لمنح الفصول الإضافية",
        "description": "الحد الأدنى من الوحدات الدراسية التي يجب أن يجتازها الطالب حتى يكون مؤهلاً لمنح الفصول الإضافية (مثال: ألا تمنح هذه الفرصة إلا إذا تجاوز الطالب 130 وحدة دراسية).",
        "category": "duration",
        "value_number": 130.0,
        "value_text": None,
    },
]


def _ensure_default_rules(conn):
    """
    ضمان وجود جميع مفاتيح DEFAULT_RULES في جدول academic_rules.
    لا نعتمد على كون الجدول فارغاً، بل نضيف أي مفتاح مفقود (مثل البنود الجديدة التي تُضاف لاحقاً).
    """
    cur = conn.cursor()
    for r in DEFAULT_RULES:
        cur.execute(
            """
            INSERT INTO academic_rules
            (rule_key, title, description, category, value_number, value_text, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT (rule_key) DO NOTHING
            """,
            (
                r["rule_key"],
                r["title"],
                r.get("description") or "",
                r.get("category") or "",
                r.get("value_number"),
                r.get("value_text"),
            ),
        )
    conn.commit()


@academic_rules_bp.route("/list")
@role_required("admin")
def list_rules():
    """إرجاع جميع بنود لائحة الإنذارات والفصل (للاستخدام في لوحة الإعدادات)."""
    with get_connection() as conn:
        _ensure_default_rules(conn)
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT id, rule_key, title, description, category, value_number, value_text, is_active
            FROM academic_rules
            ORDER BY category, id
            """
        ).fetchall()
        rules = []
        for r in rows:
            desc = r["description"] or ""
            # إضافة جملة توضيحية افتراضية لبند عدد الفصول قبل الفصل (بدون تعديل قاعدة البيانات)
            if r["rule_key"] == "dismissal_min_semesters":
                hint = (
                    " في التطبيق الحالي: إذا كانت القيمة 2 مثلاً، يتم تجاهل أول فصلين دراسيين "
                    "منذ التحاق الطالب عند حساب الفصل بسبب انخفاض المعدل التراكمي، "
                    "ويُكتفى خلالهما بتنبيه الطالب إلى ضرورة التحسين، ثم بعد ذلك إذا استمر "
                    "المعدل أقل من الحد المسموح يُعتبر الطالب معرّضاً للفصل مع إمكانية منحه فرصة استثنائية واحدة."
                )
                if hint.strip() not in desc:
                    desc = (desc + " " + hint).strip()

            rules.append(
                {
                    "id": r["id"],
                    "rule_key": r["rule_key"],
                    "title": r["title"],
                    "description": desc,
                    "category": r["category"],
                    "value_number": r["value_number"],
                    "value_text": r["value_text"],
                    "is_active": bool(r["is_active"]),
                }
            )
    return jsonify({"rules": rules})


@academic_rules_bp.route("/save", methods=["POST"])
@role_required("admin")
def save_rule():
    """
    تحديث بند واحد من بنود اللائحة.

    body:
      - id (اختياري؛ إذا لم يُرسل يُستخدم rule_key)
      - rule_key
      - title
      - description
      - category
      - value_number
      - value_text
      - is_active
    """
    data = request.get_json(force=True) or {}
    rid = data.get("id")
    rule_key = (data.get("rule_key") or "").strip()

    if not rid and not rule_key:
        return jsonify({"status": "error", "message": "id أو rule_key مطلوب"}), 400

    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    category = (data.get("category") or "").strip()

    value_number = data.get("value_number", None)
    if value_number in ("", None):
        value_number = None
    else:
        try:
            value_number = float(value_number)
        except Exception:
            return jsonify({"status": "error", "message": "value_number يجب أن يكون قيمة رقمية"}), 400

    value_text = (data.get("value_text") or "").strip() or None
    is_active = 1 if bool(data.get("is_active", True)) else 0

    with get_connection() as conn:
        cur = conn.cursor()
        if rid:
            cur.execute(
                """
                UPDATE academic_rules
                SET title = ?, description = ?, category = ?, value_number = ?, value_text = ?, is_active = ?
                WHERE id = ?
                """,
                (title, description, category, value_number, value_text, is_active, rid),
            )
        else:
            cur.execute(
                """
                INSERT INTO academic_rules
                (rule_key, title, description, category, value_number, value_text, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (rule_key) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    category = EXCLUDED.category,
                    value_number = EXCLUDED.value_number,
                    value_text = EXCLUDED.value_text,
                    is_active = EXCLUDED.is_active
                """,
                (rule_key, title, description, category, value_number, value_text, is_active),
            )
        conn.commit()

    return jsonify({"status": "ok"})

