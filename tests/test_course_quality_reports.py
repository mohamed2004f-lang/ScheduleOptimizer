"""تقارير جودة المقررات: سياق المعاينة + فهرس + شاهد المساعد."""

from backend.core.accreditation_evidence_types import DEFAULT_EVIDENCE_TYPES
from backend.core.quality_assistant_catalog import match_system_usage_topic
from backend.services import course_delivery as cd
from backend.services.course_delivery import ensure_course_delivery_schema
from backend.services.utilities import get_connection


def test_evidence_type_course_delivery_quality_report():
    codes = {t[0] for t in DEFAULT_EVIDENCE_TYPES}
    assert "course_delivery_quality_report" in codes
    row = next(t for t in DEFAULT_EVIDENCE_TYPES if t[0] == "course_delivery_quality_report")
    assert row[3] == "report"
    assert row[4] == "course_delivery"
    assert row[5] == "quality_report"


def test_assistant_catalog_matches_course_report_keywords():
    topic = match_system_usage_topic("تقرير مقرر ونسب إنجاز المفردات")
    assert topic is not None
    assert topic.get("code") == "course_quality_reports"
    hrefs = {lnk.get("href") for lnk in (topic.get("links") or [])}
    assert "/academic_quality/course_reports" in hrefs


def test_operational_recommendations_and_executive_summary():
    policy = {"partial_min_pct": 70.0, "final_min_pct": 80.0}
    partial = {
        "status": "draft",
        "overall_pct": 40.0,
        "incomplete_topics": [
            {"topic_title": "مفرد أ", "completion_pct": 30},
            {"topic_title": "مفرد ب", "completion_pct": 20},
        ],
        "book_reference_count": 0,
        "assessment_methods": [],
        "instructor_recommendations": "",
    }
    recs = cd.build_operational_recommendations(
        partial=partial, final=None, policy=policy, baseline_ok=True
    )
    assert any("فجوات" in r for r in recs)
    assert any("كتاب" in r for r in recs)
    assert any("الجزئي" in r and "إرسال" in r for r in recs)
    assert any("النهائي" in r for r in recs)

    lines = cd.build_executive_summary_lines(
        primary=partial,
        primary_phase="partial",
        partial=partial,
        final=None,
        policy=policy,
        baseline_ok=True,
    )
    assert any("40" in x for x in lines)
    assert any("فجوات" in x for x in lines)


def test_build_course_report_view_and_index(app):
    with app.app_context():
        with get_connection() as conn:
            ensure_course_delivery_schema(conn)
            cur = conn.cursor()
            course = "مقرر تقرير جودة اختبار"
            now = cd._now_iso()
            cur.execute(
                """
                INSERT INTO course_syllabus_baselines
                    (course_name, version, status, created_by, created_at, updated_at)
                VALUES (?, 1, ?, 'inst-test', ?, ?)
                """,
                (course, cd.BASELINE_APPROVED, now, now),
            )
            conn.commit()
            bid = int(
                cur.execute(
                    "SELECT id FROM course_syllabus_baselines WHERE course_name=? ORDER BY id DESC LIMIT 1",
                    (course,),
                ).fetchone()[0]
            )
            cur.execute(
                "INSERT INTO course_syllabus_topics (baseline_id, sort_order, topic_title, is_active) VALUES (?, 0, ?, 1)",
                (bid, "مفرد جودة 1"),
            )
            cur.execute(
                "INSERT INTO course_syllabus_topics (baseline_id, sort_order, topic_title, is_active) VALUES (?, 1, ?, 1)",
                (bid, "مفرد جودة 2"),
            )
            conn.commit()
            topics = (
                cur.execute(
                    "SELECT id FROM course_syllabus_topics WHERE baseline_id=? ORDER BY sort_order",
                    (bid,),
                ).fetchall()
            )
            tid1 = int(topics[0][0] if not hasattr(topics[0], "keys") else topics[0]["id"])
            tid2 = int(topics[1][0] if not hasattr(topics[1], "keys") else topics[1]["id"])

            tgid = 99101
            sem = "ربيع 25-26"
            cur.execute(
                """
                INSERT INTO course_delivery_reports (
                    teaching_group_id, semester, course_name, instructor_id,
                    baseline_id, phase, overall_pct, status,
                    instructor_comments, instructor_recommendations,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 9, ?, 'partial', 40, 'draft', ?, ?, ?, ?)
                """,
                (tgid, sem, course, bid, "ملاحظة اختبار", "توصية اختبار", now, now),
            )
            conn.commit()
            rid = int(
                cur.execute(
                    "SELECT id FROM course_delivery_reports WHERE teaching_group_id=? AND phase='partial'",
                    (tgid,),
                ).fetchone()[0]
            )
            cur.execute(
                """
                INSERT INTO course_delivery_report_items (report_id, topic_id, completion_pct, incomplete_reason)
                VALUES (?, ?, 30, 'وقت'), (?, ?, 50, '')
                """,
                (rid, tid1, rid, tid2),
            )
            conn.commit()

            from backend.database.database import table_exists

            if table_exists(conn, "teaching_groups"):
                try:
                    cur.execute(
                        """
                        INSERT INTO teaching_groups (
                            id, course_name, semester, department_id, instructor_id, group_code, is_active
                        ) VALUES (?, ?, ?, 2, 9, 'T', 1)
                        """,
                        (tgid, course, sem),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()

            rep = cd.get_delivery_report(conn, tgid, sem, "partial")
            assert rep is not None
            assert rep.get("instructor_recommendations") == "توصية اختبار"
            assert rep.get("instructor_comments") == "ملاحظة اختبار"

            view = cd.build_course_report_view(conn, teaching_group_id=tgid, semester=sem)
            if view is None:
                bl = cd.get_active_baseline(conn, course)
                assert bl and len(bl["topics"]) == 2
                assert float(rep.get("overall_pct") or 0) == 40.0
                assert len(rep.get("incomplete_topics") or []) == 1
            else:
                assert view["course_name"] == course
                assert view["evidence_type_code"] == "course_delivery_quality_report"
                assert view["partial"] is not None
                assert view["partial"].get("instructor_recommendations") == "توصية اختبار"
                assert len(view["partial"].get("incomplete_topics") or []) == 1
                assert view.get("executive_summary")
                assert view.get("operational_recommendations")
                assert any("فجوات" in b or "جزئي" in b for b in (view.get("analysis_bits") or []))
                assert "assistant_url" in view and "/academic_quality/assistant" in view["assistant_url"]

            idx = cd.build_course_reports_index(conn, semester=sem, department_id=2)
            assert "summary" in idx
            assert "package_pdf_url" in idx
