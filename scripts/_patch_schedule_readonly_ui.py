from pathlib import Path

p = Path("frontend/templates/schedule_form.html")
t = p.read_text(encoding="utf-8")

# 1) subtitle id
t = t.replace(
    '<p class="page-subtitle">إدارة جلسات المقررات ثم اعتماد/نشر الجدول ليظهر للطلبة والمشرفين</p>',
    '<p class="page-subtitle" id="schedulePageSubtitle">إدارة جلسات المقررات ثم اعتماد/نشر الجدول ليظهر للطلبة والمشرفين</p>',
    1,
)

# 2) wrap admin panel
marker = '    <motion id="sd_msg"'
if marker not in t:
    marker = '    <div id="sd_msg"'
insert_before = """    <div id="schedulePublishBanner" class="alert alert-warning py-2 small d-none mb-2" role="status"></motion>
"""
insert_before = insert_before.replace("motion", "motion")
insert_before = """    <motion id="schedulePublishBanner" class="alert alert-warning py-2 small d-none mb-2" role="status"></motion>
"""
# use div only
insert_before = '    <div id="schedulePublishBanner" class="alert alert-warning py-2 small d-none mb-2" role="status"></div>\n'

readonly_toolbar = """
      <div class="card mb-3 filter-section d-none" id="scheduleReadonlyToolbar">
        <motion class="card-body d-flex flex-wrap align-items-center gap-2">
          <a class="btn btn-outline-success btn-sm" href="/schedule/export/excel" target="_blank">تصدير Excel</a>
          <a class="btn btn-outline-danger btn-sm" href="/schedule/export/pdf" target="_blank">تصدير PDF</a>
          <button type="button" class="btn btn-outline-secondary btn-sm" id="btnSchedulePreviewRo">عرض</button>
          <button type="button" class="btn btn-outline-dark btn-sm" id="btnSchedulePrintRo">طباعة</button>
        </motion>
      </motion>
""".replace("motion", "div")

if "scheduleReadonlyToolbar" not in t:
    t = t.replace(
        '    <div id="sd_msg" class="mb-2" aria-live="polite"></motion>',
        insert_before + '    <div id="sd_msg" class="mb-2" aria-live="polite"></div>',
    )
    if "scheduleReadonlyToolbar" not in t:
        t = t.replace(
            '    <motion id="sd_msg" class="mb-2" aria-live="polite"></motion>',
            insert_before + '    <div id="sd_msg" class="mb-2" aria-live="polite"></div>',
        )
    t = t.replace(
        '      <div class="instruction-text">',
        readonly_toolbar + '\n      <div id="scheduleAdminPanel">\n      <div class="instruction-text">',
        1,
    )
    # close admin panel before chart container
    t = t.replace(
        '      <div class="card mb-3 chart-container">',
        '      </div>\n\n      <div class="card mb-3 chart-container">',
        1,
    )

# 3) wrap chart admin buttons
old_btns = """            <div class="d-flex flex-wrap gap-1">
              <button id="btnScheduleViewTable" class="btn btn-outline-secondary btn-sm active" type="button">جدول</button>
              <button id="btnScheduleViewCards" class="btn btn-outline-secondary btn-sm" type="button">بطاقات (موبايل)</button>
              <button id="btnToggleCompact" class="btn btn-outline-primary btn-sm" type="button">عرض مضغوط</button>
              <button id="btnToggleScheduleSlotManage" class="btn btn-outline-info btn-sm" type="button" title="إظهار أو إخفاء أزرار التعديل في خلايا الجدول">إظهار أزرار إدارة المقررات</button>
              <button id="btnRun" class="btn btn-success btn-sm" type="button">انتاج الجداول وعرض التعارضات</button>
              <a href="/results" class="btn btn-outline-secondary btn-sm">عرض النتائج</a>
            </div>"""
new_btns = """            <div class="d-flex flex-wrap gap-1 align-items-center">
              <button id="btnScheduleViewTable" class="btn btn-outline-secondary btn-sm active" type="button">جدول</button>
              <button id="btnScheduleViewCards" class="btn btn-outline-secondary btn-sm" type="button">بطاقات (موبايل)</button>
              <span id="scheduleChartAdminBtns" class="d-inline-flex flex-wrap gap-1">
              <button id="btnToggleCompact" class="btn btn-outline-primary btn-sm" type="button">عرض مضغوط</button>
              <button id="btnToggleScheduleSlotManage" class="btn btn-outline-info btn-sm" type="button" title="إظهار أو إخفاء أزرار التعديل في خلايا الجدول">إظهار أزرار إدارة المقررات</button>
              <button id="btnRun" class="btn btn-success btn-sm" type="button">انتاج الجداول وعرض التعارضات</button>
              <a href="/results" class="btn btn-outline-secondary btn-sm">عرض النتائج</a>
              </span>
            </div>"""
if "scheduleChartAdminBtns" not in t:
    t = t.replace(old_btns, new_btns, 1)

# 4) JS applyScheduleRoleUi
js_anchor = "  // Determine role once and apply view-only rules"
if "function applyScheduleRoleUi" not in t:
    fn = """
  function applyScheduleRoleUi(auth) {
    const role = auth?.role || '';
    const caps = auth?.capabilities;
    const isSupervisor = (caps && caps.v >= 1)
      ? !!caps.is_supervisor_effective
      : ((role === 'supervisor') || (role === 'instructor' && Number(auth?.is_supervisor || 0) === 1));
    const isStudent = (role === 'student') || !!(caps && caps.is_student);
    IS_VIEW_ONLY_ROLE = (role === 'instructor') || isSupervisor || isStudent;
    IS_ADMIN = (caps && caps.v >= 1)
      ? !!caps.can_manage_schedule_edit
      : ['admin', 'admin_main', 'head_of_department'].includes(role);

    const adminPanel = document.getElementById('scheduleAdminPanel');
    const readonlyToolbar = document.getElementById('scheduleReadonlyToolbar');
    const chartAdminBtns = document.getElementById('scheduleChartAdminBtns');
    const insights = document.getElementById('scheduleRegistrationInsights');
    const subtitle = document.getElementById('schedulePageSubtitle');

    if (IS_VIEW_ONLY_ROLE) {
      if (adminPanel) adminPanel.style.display = 'none';
      if (readonlyToolbar) readonlyToolbar.classList.remove('d-none');
      if (chartAdminBtns) chartAdminBtns.style.display = 'none';
      if (insights) insights.style.display = 'none';
      if (subtitle) subtitle.textContent = 'عرض الجدول الدراسي للفصل الحالي (قراءة فقط)';
    } else {
      if (adminPanel) adminPanel.style.display = '';
      if (readonlyToolbar) readonlyToolbar.classList.add('d-none');
      if (chartAdminBtns) chartAdminBtns.style.display = '';
      if (insights) insights.style.display = '';
    }

    const btnSaveSlots = document.getElementById('btnSaveTimeSlots');
    const btnNormalize = document.getElementById('btnNormalizeTimes');
    const btnClear = document.getElementById('btnClearSchedule');
    if (btnSaveSlots) btnSaveSlots.disabled = !IS_ADMIN;
    if (btnNormalize) btnNormalize.disabled = !IS_ADMIN;
    if (btnClear) btnClear.disabled = !IS_ADMIN;

    const btnPreviewRo = document.getElementById('btnSchedulePreviewRo');
  const btnPrintRo = document.getElementById('btnSchedulePrintRo');
    if (btnPreviewRo) btnPreviewRo.addEventListener('click', () => document.getElementById('btnSchedulePreview')?.click());
    if (btnPrintRo) btnPrintRo.addEventListener('click', () => document.getElementById('btnSchedulePrintStudentStyle')?.click());
  }

"""
    t = t.replace(js_anchor, fn + js_anchor, 1)

# simplify fetch handler
old_block_start = "  fetch('/auth/check').then(r=>r.json()).then(auth=>{\n    const role = auth?.role || '';"
if old_block_start in t and "applyScheduleRoleUi(auth)" not in t:
    # find and replace the big block - use simpler patch after applyScheduleRoleUi added
    pass

p.write_text(t, encoding="utf-8")
print("html patched")
