"""اختبارات حقن حصص الاتجاه العام + التعيين الفردي (بدون نقل جماعي)."""

from __future__ import annotations

import uuid

import pytest

from backend.services import schedule_general_overlay as sgo
from backend.services import teaching_groups as tg
from backend.services.schedule import (
    _get_time_slots_setting,
    _setting_key_time_slots,
    _save_app_setting_json,
)


def _ensure_general(db_conn) -> int:
    cur = db_conn.cursor()
    row = cur.execute(
        "SELECT id FROM departments WHERE UPPER(COALESCE(code,'')) IN ('GENERAL','GEN','GS') LIMIT 1"
    ).fetchone()
    if row:
        return int(row[0])
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES ('GENERAL', 'اتجاه عام', 'General', 1)"
    )
    db_conn.commit()
    return int(cur.execute("SELECT id FROM departments WHERE code='GENERAL' LIMIT 1").fetchone()[0])


def _seed_overlay_world(db_conn):
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    gen_id = _ensure_general(db_conn)
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"ME{uid}".upper()[:12], f"ميكانيكا {uid}", "Mech"),
    )
    mech_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (f"ME{uid}".upper()[:12],)).fetchone()[0])
    sem = f"خريف 14{uid[:2]}"
    course = f"رياضيات عامة {uid}"
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"GS{uid}"[:8], gen_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. عام {uid}", gen_id),
    )
    iid = int(cur.lastrowid)
    # مجموعتان A/B مع حصص
    for code, day, time in (("A", "السبت", "09:00-11:00"), ("B", "الأحد", "11:00-13:00")):
        cur.execute(
            """
            INSERT INTO teaching_groups
                (course_name, semester, department_id, group_code, group_kind, instructor_id, capacity_max, is_active)
            VALUES (?, ?, ?, ?, 'split', ?, ?, 1)
            """,
            (course, sem, gen_id, code, iid, 2 if code == "A" else 50),
        )
        gid = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO schedule
                (course_name, day, time, room, instructor, instructor_id, semester, department_id, teaching_group_id)
            VALUES (?, ?, ?, 'G1', ?, ?, ?, ?, ?)
            """,
            (course, day, time, f"د. عام {uid}", iid, sem, gen_id, gid),
        )
        try:
            cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
        except Exception:
            pass

    groups = {
        g["group_code"]: int(g["id"])
        for g in tg.list_teaching_groups(db_conn, semester=sem, department_id=gen_id, course_name=course)
    }
    # طالبان في الميكانيكا على مجموعة A
    for i in range(2):
        sid = f"S{uid}{i}"
        cur.execute(
            """
            INSERT INTO students (student_id, student_name, department_id, enrollment_status)
            VALUES (?, ?, ?, 'active')
            """,
            (sid, f"طالب {i}", mech_id),
        )
        cur.execute(
            """
            INSERT INTO registrations (student_id, course_name, semester, teaching_group_id)
            VALUES (?, ?, ?, ?)
            """,
            (sid, course, sem, groups["A"]),
        )
    db_conn.commit()
    return {
        "uid": uid,
        "gen_id": gen_id,
        "mech_id": mech_id,
        "sem": sem,
        "course": course,
        "groups": groups,
        "inst_id": iid,
    }


def test_overlay_absent_without_regs(db_conn):
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    gen_id = _ensure_general(db_conn)
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"CV{uid}".upper()[:12], f"مدني {uid}", "Civil"),
    )
    civil = int(cur.execute("SELECT id FROM departments WHERE code=?", (f"CV{uid}".upper()[:12],)).fetchone()[0])
    db_conn.commit()
    items = sgo.fetch_overlay_schedule_items(db_conn, consumer_department_id=civil, semester="خريف 9999")
    assert items == []


def test_overlay_shows_bound_group_slots(db_conn):
    world = _seed_overlay_world(db_conn)
    items = sgo.fetch_overlay_schedule_items(
        db_conn, consumer_department_id=world["mech_id"], semester=world["sem"]
    )
    assert len(items) >= 1
    assert all(x.get("is_overlay_general") for x in items)
    assert all(int(x.get("teaching_group_id") or 0) == world["groups"]["A"] for x in items)
    assert items[0]["student_count"] == 2
    # عمود المرحلة الأولى
    from backend.core.schedule_stage_layout import enrich_schedule_row_stage_fields

    enrich_schedule_row_stage_fields(db_conn, items[0])
    assert items[0].get("stage_bucket") == "general_or_y1"
    assert items[0].get("stage_badge") == "عام"


def test_select_no_longer_mass_moves_and_clears_binding(db_conn):
    """النقل الجماعي متوقف — لا تُحدَّث تسجيلات القسم ويُمسح الربط القديم."""
    world = _seed_overlay_world(db_conn)
    cur = db_conn.cursor()
    # ربط قديم (أسلوب القسم الموحّد)
    sgo.ensure_bindings_schema(db_conn)
    cur.execute(
        """
        INSERT INTO department_general_group_bindings
            (semester, consumer_department_id, course_name, teaching_group_id, updated_by)
        VALUES (?, ?, ?, ?, 'legacy')
        """,
        (world["sem"], world["mech_id"], world["course"], world["groups"]["A"]),
    )
    db_conn.commit()

    result = sgo.select_general_group_for_department(
        db_conn,
        course_name=world["course"],
        semester=world["sem"],
        teaching_group_id=world["groups"]["B"],
        consumer_department_id=world["mech_id"],
        actor="test",
        force_admin=True,
    )
    db_conn.commit()
    assert result["code"] == "PER_STUDENT_ONLY"
    assert result["moved_count"] == 0
    assert result["mode"] == "per_student"
    assert result.get("binding_cleared") is True

    # تسجيلات الميكانيكا بقيت على A
    rows = cur.execute(
        """
        SELECT teaching_group_id FROM registrations
        WHERE course_name = ? AND student_id LIKE ?
        """,
        (world["course"], f"S{world['uid']}%"),
    ).fetchall()
    assert len(rows) == 2
    assert all(int(r[0]) == world["groups"]["A"] for r in rows)

    bindings = sgo.list_bindings(
        db_conn, semester=world["sem"], consumer_department_id=world["mech_id"]
    )
    assert world["course"].lower() not in bindings


def test_registration_options_include_general(db_conn):
    world = _seed_overlay_world(db_conn)
    sid = f"S{world['uid']}0"
    opts = tg.list_registration_group_options(
        db_conn,
        course_name=world["course"],
        semester=world["sem"],
        student_id=sid,
    )
    gids = {int(o.get("teaching_group_id") or 0) for o in opts}
    assert world["groups"]["A"] in gids
    assert world["groups"]["B"] in gids


def test_time_slots_dept_key_migrates_legacy(db_conn):
    world = _seed_overlay_world(db_conn)
    # محاكاة مفتاح كلّي قديم
    legacy = _setting_key_time_slots(db_conn, None)
    _save_app_setting_json(
        db_conn, legacy, {"slots": ["08:00-10:00", "10:00-12:00"]}, "test"
    )
    db_conn.commit()
    out = _get_time_slots_setting(db_conn, department_id=world["mech_id"])
    assert "08:00-10:00" in (out.get("slots") or [])
    assert f"dept:{world['mech_id']}" in (out.get("key") or "")


def test_split_warning_when_multiple_groups(db_conn):
    world = _seed_overlay_world(db_conn)
    cur = db_conn.cursor()
    # انقل أحد الطالبين إلى B يدوياً بدون ربط
    cur.execute(
        "UPDATE registrations SET teaching_group_id = ? WHERE student_id = ?",
        (world["groups"]["B"], f"S{world['uid']}1"),
    )
    db_conn.commit()
    resolved = sgo.resolve_effective_general_groups(
        db_conn, consumer_department_id=world["mech_id"], semester=world["sem"]
    )
    assert resolved["split_warnings"]
    assert any(
        str(w.get("course_name") or "").lower() == world["course"].lower()
        for w in resolved["split_warnings"]
    )


def test_early_discovery_lists_registered_general_courses(db_conn):
    world = _seed_overlay_world(db_conn)
    disc = sgo.discover_general_courses_for_department(
        db_conn, consumer_department_id=world["mech_id"], semester=world["sem"]
    )
    assert disc["applicable"] is True
    assert disc["courses"]
    names = {str(c["course_name"]).lower() for c in disc["courses"]}
    assert world["course"].lower() in names
    row = next(c for c in disc["courses"] if c["course_name"].lower() == world["course"].lower())
    assert row["dept_registered_count"] == 2
    assert row["groups_count"] >= 2
    assert row["slots_preview"]


def test_times_changed_alert_after_general_slot_edit(db_conn):
    world = _seed_overlay_world(db_conn)
    # اطّلاع أولي
    sgo.acknowledge_general_course_times(
        db_conn,
        course_name=world["course"],
        semester=world["sem"],
        consumer_department_id=world["mech_id"],
        actor="hod",
    )
    db_conn.commit()
    disc1 = sgo.discover_general_courses_for_department(
        db_conn, consumer_department_id=world["mech_id"], semester=world["sem"]
    )
    assert disc1["times_changed_count"] == 0

    # رئيس GENERAL يغيّر الوقت
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE schedule SET time = ? WHERE teaching_group_id = ?",
        ("14:00-16:00", world["groups"]["A"]),
    )
    db_conn.commit()
    disc2 = sgo.discover_general_courses_for_department(
        db_conn, consumer_department_id=world["mech_id"], semester=world["sem"]
    )
    assert disc2["times_changed_count"] >= 1
    row = next(c for c in disc2["courses"] if c["course_name"].lower() == world["course"].lower())
    assert row["times_changed"] is True


def test_overlay_fallback_by_general_dept_course_name(db_conn):
    """شعبة واحدة بلا teaching_group تظهر؛ متعدد الشعب لا يُحقَن تلقائياً."""
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    gen_id = _ensure_general(db_conn)
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"CV{uid}".upper()[:12], f"مدني {uid}", "Civil"),
    )
    civil = int(cur.execute("SELECT id FROM departments WHERE code=?", (f"CV{uid}".upper()[:12],)).fetchone()[0])
    sem = f"خريف 14{uid[:2]}"
    course = f"ميكانيكا هندسية {uid}"
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"EM{uid}"[:8], gen_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. م {uid}", gen_id),
    )
    iid = int(cur.lastrowid)
    cur.execute(
        """
        INSERT INTO schedule
            (course_name, day, time, room, instructor, instructor_id, semester, department_id)
        VALUES (?, 'الإثنين', '09:00-12:00', 'R1', ?, ?, ?, ?)
        """,
        (course, f"د. م {uid}", iid, sem, gen_id),
    )
    try:
        cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
    except Exception:
        pass
    sid = f"CVS{uid}"
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id, enrollment_status) VALUES (?, 'ط', ?, 'active')",
        (sid, civil),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, ?)",
        (sid, course, sem),
    )
    db_conn.commit()
    items = sgo.fetch_overlay_schedule_items(db_conn, consumer_department_id=civil, semester=sem)
    assert len(items) >= 1
    assert items[0]["course_name"] == course
    assert items[0].get("is_overlay_general") is True

    # شعبتان مختلفتان → لا حقن في الشبكة بدون اختيار
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. ن {uid}", gen_id),
    )
    iid2 = int(cur.lastrowid)
    cur.execute(
        """
        INSERT INTO schedule
            (course_name, day, time, room, instructor, instructor_id, semester, department_id)
        VALUES (?, 'الثلاثاء', '09:00-12:00', 'R2', ?, ?, ?, ?)
        """,
        (course, f"د. ن {uid}", iid2, sem, gen_id),
    )
    db_conn.commit()
    items2 = sgo.fetch_overlay_schedule_items(db_conn, consumer_department_id=civil, semester=sem)
    assert items2 == []


def test_full_general_timetable_returns_rows(db_conn):
    world = _seed_overlay_world(db_conn)
    full = sgo.fetch_full_general_timetable(db_conn, semester=world["sem"])
    assert full["count"] >= 1
    assert any(r["course_name"] == world["course"] for r in full["rows"])
    assert full.get("use_display_tracks") is True
    assert isinstance(full.get("display_tracks"), list) and len(full["display_tracks"]) >= 2
    assert all("display_column" in r for r in full["rows"])


def test_auto_single_group_overlay_without_binding(db_conn):
    """مجموعة GENERAL واحدة + مسجّلون → تظهر في overlay حتى بلا ربط صريح."""
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    gen_id = _ensure_general(db_conn)
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"PW{uid}".upper()[:12], f"طاقات {uid}", "Power"),
    )
    dept = int(cur.execute("SELECT id FROM departments WHERE code=?", (f"PW{uid}".upper()[:12],)).fetchone()[0])
    sem = f"ربيع 14{uid[:2]}"
    course = f"فيزياء عامة {uid}"
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"PH{uid}"[:8], gen_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. ف {uid}", gen_id),
    )
    iid = int(cur.lastrowid)
    cur.execute(
        """
        INSERT INTO teaching_groups
            (course_name, semester, department_id, group_code, group_kind, instructor_id, is_active)
        VALUES (?, ?, ?, '—', 'single', ?, 1)
        """,
        (course, sem, gen_id, iid),
    )
    gid = int(cur.lastrowid)
    cur.execute(
        """
        INSERT INTO schedule
            (course_name, day, time, room, instructor, instructor_id, semester, department_id, teaching_group_id)
        VALUES (?, 'الثلاثاء', '09:00-11:00', 'P1', ?, ?, ?, ?, ?)
        """,
        (course, f"د. ف {uid}", iid, sem, gen_id, gid),
    )
    try:
        cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
    except Exception:
        pass
    sid = f"SP{uid}"
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id, enrollment_status) VALUES (?, 'ط', ?, 'active')",
        (sid, dept),
    )
    # تسجيل بلا teaching_group_id
    cur.execute(
        "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, ?)",
        (sid, course, sem),
    )
    db_conn.commit()
    items = sgo.fetch_overlay_schedule_items(db_conn, consumer_department_id=dept, semester=sem)
    assert len(items) >= 1
    assert int(items[0]["teaching_group_id"]) == gid


def test_shared_catalog_courses_excluded_from_general_discovery(db_conn):
    """مقرر مشترك مملوك لـ GENERAL لا يظهر في لوحة اختيار شعبة الاتجاه العام."""
    from backend.core.college_shared_catalog import save_catalog_entry

    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    gen_id = _ensure_general(db_conn)
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"ME{uid}".upper()[:12], f"ميكانيكا {uid}", "Mech"),
    )
    mech_id = int(
        cur.execute("SELECT id FROM departments WHERE code=?", (f"ME{uid}".upper()[:12],)).fetchone()[0]
    )
    sem = f"خريف 14{uid[:2]}"
    shared_course = f"تحليلات عددية {uid}"
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (shared_course, f"SH{uid}"[:8], gen_id),
    )
    save_catalog_entry(
        db_conn,
        {
            "catalog_key": f"sh_{uid}",
            "share_type": "unified",
            "canonical_course_name": shared_course,
            "canonical_course_code": f"SH{uid}"[:8],
            "units": 3,
            "requirement_scope": "pre_track",
        },
    )
    sid = f"SHS{uid}"
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id, enrollment_status) VALUES (?, 'ط', ?, 'active')",
        (sid, mech_id),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, ?)",
        (sid, shared_course, sem),
    )
    db_conn.commit()

    assert sgo._is_overlay_candidate_course(db_conn, shared_course) is False
    disc = sgo.discover_general_courses_for_department(
        db_conn, consumer_department_id=mech_id, semester=sem
    )
    names = {str(c.get("course_name") or "").lower() for c in (disc.get("courses") or [])}
    assert shared_course.lower() not in names


def test_options_dept_on_group_differs_from_course_total_when_unlinked(db_conn):
    """عمود «على هذه المجموعة» يجب ألا يكرّر إجمالي مسجّلي المقرر قبل الربط."""
    world = _seed_overlay_world(db_conn)
    cur = db_conn.cursor()
    # أزل ربط طلبة الميكانيكا بالمجموعة A
    cur.execute(
        """
        UPDATE registrations SET teaching_group_id = NULL
        WHERE course_name = ? AND student_id LIKE ?
        """,
        (world["course"], f"S{world['uid']}%"),
    )
    db_conn.commit()

    opts = sgo.list_general_group_options(
        db_conn,
        course_name=world["course"],
        semester=world["sem"],
        consumer_department_id=world["mech_id"],
    )
    options = opts.get("options") or []
    assert len(options) >= 2
    totals = {int(o.get("dept_enrolled_count") or 0) for o in options}
    assert totals == {2}
    for o in options:
        assert int(o.get("dept_on_group_count") or 0) == 0
        assert int(o.get("dept_on_group_count") or 0) != int(o.get("dept_enrolled_count") or 0)


def test_select_does_not_assign_unlinked_registrations(db_conn):
    """select لا يربط التسجيلات بلا مجموعة — التعيين فردي فقط."""
    world = _seed_overlay_world(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        """
        UPDATE registrations SET teaching_group_id = NULL
        WHERE course_name = ? AND student_id LIKE ?
        """,
        (world["course"], f"S{world['uid']}%"),
    )
    db_conn.commit()

    result = sgo.select_general_group_for_department(
        db_conn,
        course_name=world["course"],
        semester=world["sem"],
        teaching_group_id=world["groups"]["B"],
        consumer_department_id=world["mech_id"],
        actor="test",
        force_admin=True,
    )
    db_conn.commit()
    assert result["code"] == "PER_STUDENT_ONLY"
    assert result["moved_count"] == 0
    assert int(result.get("distribution", {}).get("unlinked") or 0) == 2

    rows = cur.execute(
        """
        SELECT teaching_group_id FROM registrations
        WHERE course_name = ? AND student_id LIKE ?
        """,
        (world["course"], f"S{world['uid']}%"),
    ).fetchall()
    assert len(rows) == 2
    assert all(r[0] in (None, 0) for r in rows)

    disc = sgo.discover_general_courses_for_department(
        db_conn, consumer_department_id=world["mech_id"], semester=world["sem"]
    )
    row = next(c for c in disc["courses"] if c["course_name"].lower() == world["course"].lower())
    assert row["needs_choice"] is True
    assert int(row.get("dept_unlinked_count") or 0) == 2


def test_overlay_includes_both_groups_when_students_split(db_conn):
    """عند توزيع فردي على A و B تُحقَن شعبنا المجموعتين في شبكة القسم."""
    world = _seed_overlay_world(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE registrations SET teaching_group_id = ? WHERE student_id = ?",
        (world["groups"]["B"], f"S{world['uid']}1"),
    )
    db_conn.commit()
    items = sgo.fetch_overlay_schedule_items(
        db_conn, consumer_department_id=world["mech_id"], semester=world["sem"]
    )
    gids = {int(x.get("teaching_group_id") or 0) for x in items}
    assert world["groups"]["A"] in gids
    assert world["groups"]["B"] in gids
    resolved = sgo.resolve_effective_general_groups(
        db_conn, consumer_department_id=world["mech_id"], semester=world["sem"]
    )
    meta = resolved["by_course"][world["course"].lower()]
    assert meta.get("multi_group") is True
    assert set(meta.get("teaching_group_ids") or []) == {
        world["groups"]["A"],
        world["groups"]["B"],
    }
