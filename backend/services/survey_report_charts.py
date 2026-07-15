"""بيانات ورسوم بيانية لتقارير الاستبيانات (Chart.js + matplotlib)."""

from __future__ import annotations

import base64
import io
from typing import Any

ITEM_CLASS_BUCKET_ORDER: tuple[str, ...] = (
    "excellent",
    "good",
    "needs_improvement",
    "critical",
    "pending",
)

ITEM_CLASS_CHART_COLORS: dict[str, str] = {
    "excellent": "#198754",
    "good": "#0d6efd",
    "needs_improvement": "#ffc107",
    "critical": "#dc3545",
    "pending": "#6c757d",
}

ITEM_CLASS_DISTRIBUTION_LABELS: dict[str, str] = {
    "excellent": "ممتاز (≥80%)",
    "good": "جيد (70–79%)",
    "needs_improvement": "يحتاج تحسين (50–69%)",
    "critical": "حرج (<50%)",
    "pending": "بلا نتيجة",
}


def _rtl_text(text: str) -> str:
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        txt = str(text or "")
        if not txt:
            return ""
        return get_display(arabic_reshaper.reshape(txt))
    except Exception:
        return str(text or "")


def _truncate_label(text: str, max_len: int = 42) -> str:
    s = str(text or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def item_distribution_buckets(questions: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {k: [] for k in ITEM_CLASS_BUCKET_ORDER}
    for q in questions or []:
        cls = (q.get("classification") or "pending").strip()
        if cls not in buckets:
            cls = "pending"
        buckets[cls].append(q)
    return buckets


def build_chart_data_for_survey(
    report: dict[str, Any],
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """بيانات Chart.js لاستبيان واحد."""
    questions = report.get("questions") or []
    scored = [q for q in questions if q.get("score_percent") is not None]
    if not scored and not (analysis or {}).get("distribution_rows"):
        return {"has_data": False}

    buckets = item_distribution_buckets(questions)
    dist_labels = [
        ITEM_CLASS_DISTRIBUTION_LABELS[k]
        for k in ITEM_CLASS_BUCKET_ORDER
        if buckets[k]
    ]
    dist_values = [len(buckets[k]) for k in ITEM_CLASS_BUCKET_ORDER if buckets[k]]
    dist_colors = [ITEM_CLASS_CHART_COLORS[k] for k in ITEM_CLASS_BUCKET_ORDER if buckets[k]]

    sorted_q = sorted(scored, key=lambda x: float(x["score_percent"]), reverse=True)
    item_labels = [_truncate_label(q.get("label_ar") or f"#{q.get('id')}") for q in sorted_q]
    item_values = [float(q["score_percent"]) for q in sorted_q]

    return {
        "has_data": bool(scored),
        "distribution": {
            "labels": dist_labels,
            "values": dist_values,
            "colors": dist_colors,
        },
        "items": {
            "labels": item_labels,
            "values": item_values,
        },
    }


def build_chart_data_for_combined(
    combined: dict[str, Any],
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """بيانات Chart.js للتقرير الموحّد."""
    from backend.services.survey_analytics import classify_item_score

    reports = combined.get("reports") or []
    aggregated = [r for r in reports if r.get("aggregated") and r.get("overall_score_percent") is not None]
    if not aggregated:
        return {"has_data": False}

    buckets: dict[str, list[dict]] = {k: [] for k in ITEM_CLASS_BUCKET_ORDER}
    for r in aggregated:
        cls = classify_item_score(float(r["overall_score_percent"]))
        buckets[cls].append(r)

    dist_labels = [
        ITEM_CLASS_DISTRIBUTION_LABELS[k]
        for k in ITEM_CLASS_BUCKET_ORDER
        if buckets[k]
    ]
    dist_values = [len(buckets[k]) for k in ITEM_CLASS_BUCKET_ORDER if buckets[k]]
    dist_colors = [ITEM_CLASS_CHART_COLORS[k] for k in ITEM_CLASS_BUCKET_ORDER if buckets[k]]

    sorted_reports = sorted(aggregated, key=lambda x: float(x["overall_score_percent"]), reverse=True)
    survey_labels = [_truncate_label(r.get("title_ar") or r.get("template_code")) for r in sorted_reports]
    survey_values = [float(r["overall_score_percent"]) for r in sorted_reports]

    role_map: dict[str, list[float]] = {}
    for r in aggregated:
        role = (r.get("respondent_label") or "—").strip()
        role_map.setdefault(role, []).append(float(r["overall_score_percent"]))
    role_labels = list(role_map.keys())
    role_values = [
        round(sum(vals) / len(vals), 1) if vals else 0 for vals in role_map.values()
    ]

    return {
        "has_data": True,
        "distribution": {
            "labels": dist_labels,
            "values": dist_values,
            "colors": dist_colors,
        },
        "surveys": {
            "labels": survey_labels,
            "values": survey_values,
        },
        "roles": {
            "labels": role_labels,
            "values": role_values,
        },
    }


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor="white")
    import matplotlib.pyplot as plt

    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _require_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except Exception as exc:
        raise RuntimeError(
            "ميزة الرسوم البيانية تحتاج matplotlib. نفّذ: pip install -r requirements.txt"
        ) from exc


def render_items_bar_png(labels: list[str], values: list[float]) -> str | None:
    if not labels or not values:
        return None
    plt = _require_matplotlib()
    fig, ax = plt.subplots(figsize=(8, max(3.5, len(labels) * 0.35)), dpi=140)
    y_pos = range(len(labels))
    rtl_labels = [_rtl_text(l) for l in labels]
    ax.barh(list(y_pos), values, color="#0d6efd", height=0.65)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(rtl_labels, fontsize=8)
    ax.set_xlim(0, 100)
    ax.set_xlabel(_rtl_text("النسبة %"), fontsize=9)
    ax.set_title(_rtl_text("نسب البنود"), fontsize=11)
    ax.invert_yaxis()
    fig.tight_layout()
    return _fig_to_b64(fig)


def render_distribution_doughnut_png(labels: list[str], values: list[int], colors: list[str]) -> str | None:
    if not labels or not values:
        return None
    plt = _require_matplotlib()
    fig, ax = plt.subplots(figsize=(5.5, 4.5), dpi=140)
    rtl_labels = [_rtl_text(l) for l in labels]
    ax.pie(
        values,
        labels=rtl_labels,
        colors=colors[: len(values)],
        autopct="%1.0f%%",
        startangle=90,
        textprops={"fontsize": 8},
    )
    ax.set_title(_rtl_text("توزيع التصنيف"), fontsize=11)
    fig.tight_layout()
    return _fig_to_b64(fig)


def render_surveys_bar_png(labels: list[str], values: list[float]) -> str | None:
    if not labels or not values:
        return None
    plt = _require_matplotlib()
    fig, ax = plt.subplots(figsize=(8, max(3.5, len(labels) * 0.4)), dpi=140)
    x_pos = range(len(labels))
    rtl_labels = [_rtl_text(l) for l in labels]
    ax.bar(list(x_pos), values, color="#198754", width=0.6)
    ax.set_xticks(list(x_pos))
    ax.set_xticklabels(rtl_labels, rotation=35, ha="right", fontsize=7)
    ax.set_ylim(0, 100)
    ax.set_ylabel(_rtl_text("النسبة %"), fontsize=9)
    ax.set_title(_rtl_text("نتائج الاستبيانات"), fontsize=11)
    fig.tight_layout()
    return _fig_to_b64(fig)


def build_chart_images_for_survey(
    report: dict[str, Any],
    analysis: dict[str, Any] | None = None,
) -> dict[str, str | None]:
    chart_data = build_chart_data_for_survey(report, analysis)
    if not chart_data.get("has_data"):
        return {}
    items = chart_data.get("items") or {}
    dist = chart_data.get("distribution") or {}
    return {
        "items_bar": render_items_bar_png(items.get("labels") or [], items.get("values") or []),
        "distribution": render_distribution_doughnut_png(
            dist.get("labels") or [],
            dist.get("values") or [],
            dist.get("colors") or [],
        ),
    }


def build_chart_images_for_combined(
    combined: dict[str, Any],
    analysis: dict[str, Any] | None = None,
) -> dict[str, str | None]:
    chart_data = build_chart_data_for_combined(combined, analysis)
    if not chart_data.get("has_data"):
        return {}
    dist = chart_data.get("distribution") or {}
    surveys = chart_data.get("surveys") or {}
    return {
        "distribution": render_distribution_doughnut_png(
            dist.get("labels") or [],
            dist.get("values") or [],
            dist.get("colors") or [],
        ),
        "surveys_bar": render_surveys_bar_png(
            surveys.get("labels") or [],
            surveys.get("values") or [],
        ),
    }


def add_chart_sheet_to_workbook(workbook, chart_data: dict[str, Any], *, sheet_name: str = "الرسوم") -> None:
    """إضافة ورقة Excel برسوم xlsxwriter."""
    if not chart_data or not chart_data.get("has_data"):
        return
    ws = workbook.add_worksheet(sheet_name[:31])
    ws.right_to_left()
    row = 0

    dist = chart_data.get("distribution") or {}
    if dist.get("labels") and dist.get("values"):
        ws.write(row, 0, "توزيع التصنيف")
        row += 1
        ws.write_row(row, 0, ["التصنيف", "العدد"])
        row += 1
        start = row
        for lbl, val in zip(dist["labels"], dist["values"]):
            ws.write_row(row, 0, [lbl, val])
            row += 1
        chart = workbook.add_chart({"type": "doughnut"})
        chart.add_series(
            {
                "categories": [sheet_name, start, 0, row - 1, 0],
                "values": [sheet_name, start, 1, row - 1, 1],
            }
        )
        chart.set_title({"name": "توزيع التصنيف"})
        ws.insert_chart(start, 3, chart, {"x_scale": 1.2, "y_scale": 1.2})
        row += 12

    items = chart_data.get("items") or {}
    if items.get("labels") and items.get("values"):
        ws.write(row, 0, "نسب البنود")
        row += 1
        ws.write_row(row, 0, ["البند", "النسبة"])
        row += 1
        start = row
        for lbl, val in zip(items["labels"], items["values"]):
            ws.write_row(row, 0, [_truncate_label(lbl, 60), val])
            row += 1
        chart = workbook.add_chart({"type": "bar"})
        chart.add_series(
            {
                "categories": [sheet_name, start, 0, row - 1, 0],
                "values": [sheet_name, start, 1, row - 1, 1],
            }
        )
        chart.set_title({"name": "نسب البنود"})
        ws.insert_chart(start, 3, chart, {"x_scale": 1.3, "y_scale": 1.3})
        row += 14

    surveys = chart_data.get("surveys") or {}
    if surveys.get("labels") and surveys.get("values"):
        ws.write(row, 0, "نتائج الاستبيانات")
        row += 1
        ws.write_row(row, 0, ["الاستبيان", "النسبة"])
        row += 1
        start = row
        for lbl, val in zip(surveys["labels"], surveys["values"]):
            ws.write_row(row, 0, [_truncate_label(lbl, 60), val])
            row += 1
        chart = workbook.add_chart({"type": "column"})
        chart.add_series(
            {
                "categories": [sheet_name, start, 0, row - 1, 0],
                "values": [sheet_name, start, 1, row - 1, 1],
            }
        )
        chart.set_title({"name": "نتائج الاستبيانات"})
        ws.insert_chart(start, 3, chart, {"x_scale": 1.2, "y_scale": 1.2})
