/**
 * راسمات الجدول الجديدة:
 * - أسبوع شخصي: يوم | وقت | مقرر | أستاذ | قاعة (ما لديه فقط)
 * - مصفوفة مراحل: يوم | وقت | 3 كتل × (مقرر|أستاذ|قاعة)
 */
(function (global) {
  'use strict';

  const BUCKETS = [
    { id: 'general_or_y1', label: 'اتجاه عام + السنة الأولى بالقسم' },
    { id: 'y3', label: 'المرحلة الثالثة' },
    { id: 'y4y5', label: 'الرابعة + الخامسة' },
  ];

  function esc(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escAttr(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;');
  }

  function daysList() {
    return global.SCHEDULE_DAYS || ['السبت', 'الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس'];
  }

  function parseStartMinutes(timeStr) {
    const m = String(timeStr || '').trim().match(/(\d{1,2}):(\d{2})/);
    if (!m) return 0;
    return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
  }

  function sortTimes(times) {
    return Array.from(times).filter(Boolean).sort((a, b) => parseStartMinutes(a) - parseStartMinutes(b));
  }

  function canonicalDay(day) {
    if (typeof global.canonicalScheduleDayForGrid === 'function') {
      return global.canonicalScheduleDayForGrid(day);
    }
    return String(day || '').trim();
  }

  function rowBucket(row) {
    const b = String(row && row.stage_bucket || '').trim();
    if (b === 'y3' || b === 'y4y5' || b === 'general_or_y1') return b;
    return 'general_or_y1';
  }

  /**
   * أوقات لكل يوم: من byDay إن وُجدت، وإلا من الصفوف فقط (لا تفرض كل أوقات الأسبوع).
   * @param {Array} rows
   * @param {Record<string, string[]>} byDay
   */
  function timesByDayFromRows(rows, byDay) {
    const map = {};
    daysList().forEach((d) => { map[d] = new Set(); });
    const bd = byDay && typeof byDay === 'object' ? byDay : {};
    Object.keys(bd).forEach((d) => {
      const cd = canonicalDay(d);
      if (!map[cd]) map[cd] = new Set();
      (bd[d] || []).forEach((t) => { if (t) map[cd].add(String(t).trim()); });
    });
    (rows || []).forEach((r) => {
      const d = canonicalDay(r && r.day);
      const t = String((r && r.time) || '').trim();
      if (!d || !t) return;
      if (!map[d]) map[d] = new Set();
      map[d].add(t);
    });
    const out = {};
    Object.keys(map).forEach((d) => {
      out[d] = sortTimes(map[d]);
    });
    return out;
  }

  function courseLabel(row) {
    const code = String((row && row.course_code) || '').trim();
    const nameOnly = courseDisplayName(row);
    if (code && nameOnly && nameOnly !== code) return `${code} — ${nameOnly}`;
    return nameOnly || code || '—';
  }

  /**
   * نص الخلية: اسم المقرر فقط.
   * كثير من صفوف الجدول تخزّن الاسم بصيغة «ME 204 — الاسم» فيزيل البادئة هنا.
   */
  function courseDisplayName(row) {
    let name = String((row && row.course_name) || '').trim();
    const code = String((row && row.course_code) || '').trim();
    if (code && name.toLowerCase().startsWith(code.toLowerCase())) {
      name = name.slice(code.length).replace(/^[\s\-—–:/|]+/u, '').trim();
    }
    // نمط شائع حتى بدون course_code: ME 204 — … أو GS201: …
    name = name.replace(/^[A-Za-z]{1,6}\s*-?\s*\d{2,4}[A-Za-z]?\s*[\-—–:/|]+\s*/u, '').trim();
    if (code && name.toLowerCase() === code.toLowerCase()) {
      name = '';
    }
    return name || '—';
  }

  function renderCourseTriple(row, opts) {
    opts = opts || {};
    const showManage = !!opts.showSlotManage;
    const color = typeof opts.getCourseColor === 'function'
      ? opts.getCourseColor(row.course_name)
      : '#64748b';
    const titleTip = escAttr(
      [courseLabel(row), row.room && ('قاعة: ' + row.room), row.instructor && ('أستاذ: ' + row.instructor)]
        .filter(Boolean)
        .join(' — ')
    );
    // شارات المرحلة مخفية بصرياً (الأعمدة تكفي) وتبقى في DOM لكشف تعارض عام+قسم2
    const badge = String(row.stage_badge || '').trim();
    const badgeHtml = badge
      ? `<span class="stage-badge stage-badge--${escAttr(badge === 'عام' ? 'general' : badge === 'قسم 2' ? 'y2' : 'other')}" aria-hidden="true"></span>`
      : '';
    const display = esc(courseDisplayName(row));
    let courseCell;
    if (showManage && row.section_id && !row.is_college_general) {
      courseCell = `<button type="button" class="course-btn course-btn--col" style="background:${color};" data-section-id="${escAttr(row.section_id)}" title="${titleTip}">${display}</button>${badgeHtml}`;
    } else if (showManage && row.is_college_general) {
      courseCell = `<span class="course-label-readonly" style="background:${color};" title="${titleTip}">${display}</span>${badgeHtml}<span class="stage-readonly-hint" title="مقرر اتجاه عام — للتنسيق مع رئيس الاتجاه العام">🔒</span>`;
    } else {
      // عرض قراءة: نفس شكل زر المقرر مع نص أبيض على لون المقرر
      courseCell = `<span class="course-pub-label course-pub-label--filled" style="background:${color};" title="${titleTip}">${display}</span>${badgeHtml}`;
    }
    const room = String(row.room || '').trim();
    const inst = String(row.instructor || '').trim();
    return (
      `<div class="slot-course-record">` +
      `<div class="slot-cell slot-cell--course">${courseCell}</div>` +
      `<div class="slot-cell slot-cell--inst"><span class="slot-text${inst ? '' : ' slot-text--empty'}">${esc(inst || '—')}</span></div>` +
      `<div class="slot-cell slot-cell--room"><span class="slot-text${room ? '' : ' slot-text--empty'}">${esc(room || '—')}</span></div>` +
      `</div>`
    );
  }

  function emptyTriple(opts) {
    opts = opts || {};
    // في وضع القراءة: خلية فارغة هادئة بدون شرطات مزعجة
    if (!opts.showSlotManage) {
      return `<div class="slot-course-record slot-course-record--empty slot-course-record--blank" aria-hidden="true"></div>`;
    }
    return (
      `<div class="slot-course-record slot-course-record--empty">` +
      `<div class="slot-cell slot-cell--course"><span class="slot-placeholder">—</span></div>` +
      `<div class="slot-cell slot-cell--inst"><span class="slot-placeholder">—</span></div>` +
      `<div class="slot-cell slot-cell--room"><span class="slot-placeholder">—</span></div>` +
      `</div>`
    );
  }

  function timeCellHtml(day, time, opts) {
    opts = opts || {};
    let html = `<td class="time-slot-time" data-slot-day="${escAttr(day)}" data-slot-time="${escAttr(time)}">`;
    html += `<div class="time-slot-time-stack">`;
    html += `<div class="time-slot-time-label">${esc(time)}</div>`;
    html += `<div class="slot-conflict-actions slot-conflict-actions--inline" data-conflict-day="${escAttr(day)}" data-conflict-time="${escAttr(time)}"></div>`;
    if (opts.showSlotManage) {
      html += `<button type="button" class="manage-courses-btn manage-courses-btn--time" data-manage-day="${escAttr(day)}" data-manage-time="${escAttr(time)}" title="إدارة مقررات هذا التوقيت">إدارة</button>`;
    }
    html += `</div></td>`;
    return html;
  }

  /**
   * خلية اليوم لكل صف (بدون rowspan) لتفادي تداخل sticky مع عمود الوقت.
   * @param {'start'|'cont'} role
   */
  function dayHeaderCellHtml(day, opts, role) {
    opts = opts || {};
    const r = role === 'cont' ? 'cont' : 'start';
    if (r === 'cont') {
      return `<th class="day-header day-header--cont" data-day="${escAttr(day)}"><span class="visually-hidden">${esc(day)}</span></th>`;
    }
    let inner = `<div class="day-header-name">${esc(day)}</div>`;
    if (opts.showDayPeriodEdit) {
      inner += `<button type="button" class="btn btn-outline-primary btn-sm btn-edit-day-periods" data-day="${escAttr(day)}" title="تعديل فترات هذا اليوم">فترات</button>`;
    }
    return `<th class="day-header day-header--start" data-day="${escAttr(day)}"><div class="day-header-inner">${inner}</div></th>`;
  }

  function buildPersonalWeeklyTimetableHtml(scheduleRows, opts) {
    opts = opts || {};
    const cleanClass = opts.showSlotManage ? '' : ' timetable--clean';
    const compactClass = opts.compact ? ' is-compact' : '';
    const rows = (scheduleRows || []).filter(
      (r) => r && String(r.day || '').trim() && String(r.time || '').trim()
    );
    const byDayTimes = timesByDayFromRows(rows, opts.byDay || {});
    const unionFallback = sortTimes(opts.unionSlots || []);
    if (opts.fillEmptyDays) {
      daysList().forEach((d) => {
        if (!(byDayTimes[d] || []).length && unionFallback.length) {
          byDayTimes[d] = unionFallback.slice();
        }
      });
    }
    const hasAnyTime = daysList().some((d) => (byDayTimes[d] || []).length);
    if (!rows.length && !hasAnyTime) {
      return '<div class="alert alert-info p-2 mb-0">لا توجد حصص في الجدول لهذا العرض.</div>';
    }
    const slotsMap = {};
    rows.forEach((row) => {
      const d = canonicalDay(row.day);
      const t = String(row.time || '').trim();
      const key = `${d}|${t}`;
      if (!slotsMap[key]) slotsMap[key] = [];
      slotsMap[key].push(row);
    });

    let html =
      `<table class="timetable timetable--personal${compactClass}${cleanClass}"><thead><tr>` +
      `<th class="day-header">اليوم</th><th class="time-header">الوقت</th>` +
      `<th class="sub-time-header">المقرر</th><th class="sub-time-header">الأستاذ</th><th class="sub-time-header">القاعة</th>` +
      `</tr></thead><tbody>`;

    daysList().forEach((day) => {
      const times = byDayTimes[day] || [];
      if (!times.length) return;
      times.forEach((time, idx) => {
        const courses = slotsMap[`${day}|${time}`] || [];
        html += `<tr class="personal-time-row${idx === 0 ? ' is-day-start' : ''}">`;
        html += dayHeaderCellHtml(day, opts, idx === 0 ? 'start' : 'cont');
        html += timeCellHtml(day, time, opts);
        html += `<td colspan="3" class="time-slot-cell slot-slot-block" data-slot-day="${escAttr(day)}" data-slot-time="${escAttr(time)}">`;
        html += '<div class="slot-aligned-rows">';
        if (!courses.length) {
          html += emptyTriple(opts);
        } else {
          courses.forEach((c, cidx) => {
            if (cidx > 0) html += '<div class="slot-record-fullsep"></div>';
            html += renderCourseTriple(c, opts);
          });
        }
        html += '</div></td></tr>';
      });
    });
    html += '</tbody></table>';
    return html;
  }

  /**
   * مصفوفة مراحل للأقسام التخصصية.
   * صف واحد لكل (يوم، وقت) — بلا rowspan وبلا صفوف إجراءات منفصلة (تفادي تداخل اليوم/الوقت).
   */
  function buildStageMatrixTimetableHtml(scheduleRows, opts) {
    opts = opts || {};
    const cleanClass = opts.showSlotManage ? '' : ' timetable--clean';
    const compactClass = opts.compact ? ' is-compact' : '';
    const rows = Array.isArray(scheduleRows) ? scheduleRows : [];
    const byDayTimes = timesByDayFromRows(rows, opts.byDay || {});
    const unionFallback = sortTimes(opts.unionSlots || []);
    const slotsMap = {};
    rows.forEach((row) => {
      const d = canonicalDay(row.day);
      const t = String(row.time || '').trim();
      if (!d || !t) return;
      const key = `${d}|${t}|${rowBucket(row)}`;
      if (!slotsMap[key]) slotsMap[key] = [];
      slotsMap[key].push(row);
    });

    let html =
      `<table class="timetable timetable--stages${compactClass}${cleanClass}"><thead>` +
      `<tr><th rowspan="2" class="day-header">اليوم</th><th rowspan="2" class="time-header">الوقت</th>`;
    BUCKETS.forEach((b) => {
      html += `<th colspan="3" class="stage-block-header" data-stage-bucket="${escAttr(b.id)}">${esc(b.label)}</th>`;
    });
    html += '</tr><tr>';
    BUCKETS.forEach(() => {
      html +=
        '<th class="sub-time-header">المقرر</th><th class="sub-time-header">الأستاذ</th><th class="sub-time-header">القاعة</th>';
    });
    html += '</tr></thead><tbody>';

    function appendStageTimeRow(day, time, idx) {
      html += `<tr class="stage-time-row${idx === 0 ? ' is-day-start' : ''}">`;
      html += dayHeaderCellHtml(day, opts, idx === 0 ? 'start' : 'cont');
      html += timeCellHtml(day, time, opts);
      BUCKETS.forEach((b) => {
        const courses = slotsMap[`${day}|${time}|${b.id}`] || [];
        html += `<td colspan="3" class="time-slot-cell slot-slot-block stage-bucket-cell" data-slot-day="${escAttr(day)}" data-slot-time="${escAttr(time)}" data-stage-bucket="${escAttr(b.id)}">`;
        html += '<div class="slot-aligned-rows">';
        if (!courses.length) {
          html += emptyTriple(opts);
        } else {
          courses.forEach((c, cidx) => {
            if (cidx > 0) html += '<div class="slot-record-fullsep"></div>';
            html += renderCourseTriple(c, opts);
          });
        }
        html += '</div></td>';
      });
      html += '</tr>';
    }

    let anyRow = false;
    daysList().forEach((day) => {
      let times = byDayTimes[day] || [];
      if (!times.length && unionFallback.length && opts.fillEmptyDays) {
        times = unionFallback.slice();
      }
      if (!times.length) return;
      anyRow = true;
      times.forEach((time, idx) => appendStageTimeRow(day, time, idx));
    });

    if (!anyRow) {
      const defTimes = unionFallback.length
        ? unionFallback
        : ['09:00-11:00', '11:00-12:00', '12:00-13:00'];
      const day0 = daysList()[0];
      defTimes.forEach((time, idx) => appendStageTimeRow(day0, time, idx));
    }

    html += '</tbody></table>';
    return html;
  }

  /**
   * ملء أزرار التعارض على الصف من بيانات الطلبة/الأستاذ.
   * يرسم الشارات دائماً؛ الإظهار/الإخفاء يتم عبر CSS (hide-student-conflicts).
   */
  function paintConflictActions(rootEl, studentConflicts, instructorConflicts) {
    const root = rootEl || document;
    const studentList = Array.isArray(studentConflicts) ? studentConflicts : [];
    const instList = Array.isArray(instructorConflicts) ? instructorConflicts : [];

    function parseRange(v) {
      const s = String(v || '').trim();
      if (!s) return null;
      const parts = s.split(/[-–—/]/).map((x) => x.trim()).filter(Boolean);
      const toMin = (t) => {
        const m = String(t || '').match(/^(\d{1,2}):(\d{2})/);
        if (!m) return null;
        return Number(m[1]) * 60 + Number(m[2]);
      };
      if (parts.length >= 2) {
        let a = toMin(parts[0]);
        let b = toMin(parts[1]);
        if (a == null || b == null) return null;
        if (b < a) {
          const tmp = a;
          a = b;
          b = tmp;
        }
        return { start: a, end: b };
      }
      const a = toMin(s);
      return a == null ? null : { start: a, end: a };
    }

    function overlapRange(aStart, aEnd, cellTime) {
      const cell = parseRange(cellTime);
      const other =
        parseRange(`${aStart || ''}-${aEnd || ''}`) ||
        parseRange(aStart) ||
        parseRange(aEnd);
      if (!cell || !other) return false;
      return Math.max(cell.start, other.start) < Math.min(cell.end, other.end)
        || (cell.start === other.start && cell.end === other.end);
    }

    function slotMatchesCell(slot, day, time) {
      if (String(slot.day || '').trim() !== day) return false;
      const start = String(slot.start_time || '').trim();
      const end = String(slot.end_time || '').trim();
      const raw =
        String(slot.time || '').trim() ||
        (start && end ? `${start}-${end}` : start || end);
      if (raw && raw === time) return true;
      if (start || end) {
        if (overlapRange(start, end, time)) return true;
      }
      if (raw && overlapRange(raw, '', time)) return true;
      return false;
    }

    root.querySelectorAll('.slot-conflict-actions').forEach((box) => {
      const day = (box.getAttribute('data-conflict-day') || '').trim();
      const time = (box.getAttribute('data-conflict-time') || '').trim();
      let studentCount = 0;
      studentList.forEach((slot) => {
        if (!slotMatchesCell(slot, day, time)) return;
        const n = Array.isArray(slot.entries) ? slot.entries.length : 0;
        studentCount += n || 1;
      });

      let instHit = false;
      instList.forEach((c) => {
        if (String(c.day || '').trim() !== day) return;
        const start = c.start_time || '';
        const end = c.end_time || '';
        const raw = String(c.time || '').trim();
        if (overlapRange(start, end, time) || (raw && (raw === time || overlapRange(raw, '', time)))) {
          instHit = true;
        }
      });

      // مؤشر عام+قسم2 في نفس اللحظة (عبر data إن وُجدت الشارات المخفية)
      let mixedGeneralDept = false;
      try {
        const cells = root.querySelectorAll(
          `.stage-bucket-cell[data-slot-day="${CSS.escape(day)}"][data-slot-time="${CSS.escape(time)}"][data-stage-bucket="general_or_y1"] .stage-badge--general, ` +
            `.time-slot-cell[data-slot-day="${CSS.escape(day)}"][data-slot-time="${CSS.escape(time)}"] .stage-badge--general`
        );
        const y2 = root.querySelectorAll(
          `.stage-bucket-cell[data-slot-day="${CSS.escape(day)}"][data-slot-time="${CSS.escape(time)}"][data-stage-bucket="general_or_y1"] .stage-badge--y2, ` +
            `.time-slot-cell[data-slot-day="${CSS.escape(day)}"][data-slot-time="${CSS.escape(time)}"] .stage-badge--y2`
        );
        if (cells.length && y2.length) mixedGeneralDept = true;
      } catch (_e) {}

      const studentBadgeCount = studentCount > 0 || mixedGeneralDept
        ? (studentCount || (mixedGeneralDept ? 1 : 0))
        : 0;
      let html = '';
      if (studentBadgeCount > 0) {
        html += `<button type="button" class="btn btn-sm btn-danger conflict-row-btn" data-conflict-kind="students" data-day="${escAttr(day)}" data-time="${escAttr(time)}">طلبة ${studentBadgeCount}</button>`;
      }
      if (instHit) {
        html += `<button type="button" class="btn btn-sm btn-warning conflict-row-btn" data-conflict-kind="instructor" data-day="${escAttr(day)}" data-time="${escAttr(time)}">أستاذ</button>`;
      }
      box.innerHTML = html;
      box.dataset.studentPayload = studentBadgeCount ? '1' : '';
      box.dataset.studentCount = String(studentBadgeCount || 0);
      const empty = !html;
      box.hidden = empty;
      if (empty) box.style.setProperty('display', 'none', 'important');
      else box.style.removeProperty('display');
    });
  }

  /** إظهار/إخفاء حاويات التعارض حسب الشارات المرئية */
  function collapseScheduleActionRows(rootEl, hideStudentConflicts) {
    const root = rootEl || document;
    const hideStudents = !!hideStudentConflicts;
    root.querySelectorAll('.conflict-row-btn[data-conflict-kind="students"]').forEach((btn) => {
      btn.hidden = hideStudents;
      if (hideStudents) {
        btn.setAttribute('aria-hidden', 'true');
        btn.style.setProperty('display', 'none', 'important');
      } else {
        btn.removeAttribute('aria-hidden');
        btn.style.removeProperty('display');
      }
    });
    root.querySelectorAll('.slot-conflict-actions').forEach((box) => {
      const hasStudent = Number(box.dataset.studentCount || 0) > 0;
      const hasInstructor = !!box.querySelector('.conflict-row-btn[data-conflict-kind="instructor"]');
      const showBox = hasInstructor || (hasStudent && !hideStudents);
      box.hidden = !showBox;
      if (!showBox) box.style.setProperty('display', 'none', 'important');
      else box.style.removeProperty('display');
    });
  }

  function fixStageDayHeaderRowspans() {
    /* لم يعد هناك rowspan على عمود اليوم */
  }

  global.SCHEDULE_STAGE_BUCKETS = BUCKETS;
  global.buildPersonalWeeklyTimetableHtml = buildPersonalWeeklyTimetableHtml;
  global.buildStageMatrixTimetableHtml = buildStageMatrixTimetableHtml;
  global.scheduleTimesByDayFromRows = timesByDayFromRows;
  global.paintScheduleConflictActions = paintConflictActions;
  global.collapseScheduleActionRows = collapseScheduleActionRows;
  global.fixStageDayHeaderRowspans = fixStageDayHeaderRowspans;
})(typeof window !== 'undefined' ? window : globalThis);
