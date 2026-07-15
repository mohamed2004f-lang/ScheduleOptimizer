/**
 * Universal Page Guide System
 * Automatically shows an interactive guide overlay on first visit to any page.
 * Adapts content based on user role.
 */
(function () {
  'use strict';

  const PAGE_ROUTES = {
    '/my_courses': 'my_courses',
    '/dashboard': 'dashboard',
    '/schedule_form': 'schedule_form',
    '/grade_drafts': 'grade_drafts',
    '/courses_form': 'courses_form',
    '/attendance_export': 'attendance_export',
    '/users_admin': 'users_admin',
    '/college_catalog_page': 'college_catalog',
    '/college_shared_catalog_page': 'college_shared_catalog',
    '/academic_rules_page': 'academic_rules',
    '/ilo_catalog_page': 'ilo_catalog',
    '/course_closure_reports_page': 'course_closure_reports',
    '/supervisor_dashboard': 'supervisor_dashboard',
    '/instructors_form': 'instructors_form',
    '/student_view': 'student_view',
    '/my_portal': 'student_portal',
    '/my_registrations': 'student_registrations',
    '/my_transcript': 'transcript',
    '/my_schedule': 'student_schedule',
    '/my_exams': 'student_exams',
    '/transcript_page': 'transcript',
    '/enrollment_plans': 'enrollment_plans',
    '/registrations_form': 'registrations_form',
    '/graduates_page': 'graduates',
    '/notifications_center': 'notifications_center',
    '/results': 'results',
    '/academic_calendar_page': 'academic_calendar',
    '/analytics': 'analytics_dashboard',
    '/exams/midterms': 'exams_midterms',
    '/exams/finals': 'exams_finals',
    '/performance_report': 'performance_report',
    '/faculty_scorecards_page': 'faculty_scorecards',
    '/faculty_final_dossier_page': 'faculty_final_dossier',
    '/schedule_versions_page': 'schedule_versions',
    '/exam_schedule_versions_page': 'exam_versions',
    '/course_equivalences_page': 'course_equivalences',
    '/prereqs_form': 'prereqs_form',
    '/prereqs_flowchart': 'prereqs_flowchart',
    '/department_policy_head_page': 'department_policy_head',
    '/department_policy_approvals_page': 'department_policy_approvals',
    '/course_registration_report_page': 'course_registration_report',
    '/grade_course_mapping_audit_page': 'grade_mapping_audit',
    '/registration_requests_page': 'registration_requests',
    '/electives_report_page': 'electives_report',
    '/failed_courses_report_page': 'failed_courses_report',
    '/uncompleted_courses_report_page': 'uncompleted_courses_report',
    '/not_registered_courses_report_page': 'not_registered_report',
    '/registration_changes_report_page': 'registration_changes_report',
  };

  const BLUEPRINT_ROUTES = {
    '/academic_quality/': 'academic_quality_dashboard',
    '/academic_quality/college': 'college_profile',
    '/academic_quality/programs': 'programs_portal',
    '/academic_quality/survey_admin': 'survey_admin',
    '/academic_quality/surveys': 'survey_hub',
    '/academic_quality/ilo/catalog': 'ilo_catalog',
    '/academic_quality/ilo/department/dashboard': 'department_lo_dashboard',
    '/academic_quality/ilo/student/learning-outcomes': 'student_learning_outcomes',
    '/academic_quality/accreditation/map': 'accreditation_map',
    '/academic_quality/archive': 'department_archive',
    '/academic_quality/archive/guide': 'department_archive',
    '/academic_quality/glossary': 'quality_glossary',
    '/academic_quality/assistant': 'quality_assistant',
    '/academic_quality/assistant/knowledge': 'quality_knowledge',
    '/students/evaluations/form': 'student_evaluations',
  };

  let _role = '';
  let _pageKey = '';

  function detectPageKey() {
    const path = window.location.pathname;
    if (PAGE_ROUTES[path]) return PAGE_ROUTES[path];
    for (const [prefix, key] of Object.entries(BLUEPRINT_ROUTES)) {
      if (path === prefix || path.startsWith(prefix)) return key;
    }
    const segments = path.replace(/^\//, '').replace(/\/\d+/g, '').replace(/\//g, '_');
    return segments || 'index';
  }

  function detectRole(callback) {
    try {
      var cached = sessionStorage.getItem('pg_user_role');
      if (cached && cached !== '') { callback(cached); return; }
    } catch (e) {}

    fetch('/auth/check', { credentials: 'include' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var role = (d && d.role) || '';
        if (role) { try { sessionStorage.setItem('pg_user_role', role); } catch (e) {} }
        callback(role);
      })
      .catch(function () { callback(''); });
  }

  function getGuideData(pageKey, role, skipRoleCheck) {
    var catalog = window.PAGE_GUIDE_CATALOG;
    if (!catalog || !catalog[pageKey]) return null;
    var entry = catalog[pageKey];
    if (!skipRoleCheck && entry.roles && entry.roles.length && role && !entry.roles.includes(role)) return null;
    var steps = (entry.steps || []).filter(function (s) {
      if (!s.forRoles || !s.forRoles.length) return true;
      if (!role) return true;
      return s.forRoles.includes(role);
    });
    if (!steps.length) steps = entry.steps || [];
    if (!steps.length) return null;
    return { title: entry.title || '', steps: steps };
  }

  function storageKey(pageKey) { return 'pg_seen_' + pageKey; }

  function hasSeen(pageKey) {
    try { return localStorage.getItem(storageKey(pageKey)) === '1'; } catch (e) { return false; }
  }

  function markSeen(pageKey) {
    try { localStorage.setItem(storageKey(pageKey), '1'); } catch (e) {}
  }

  function buildDOM(data) {
    const overlay = document.createElement('div');
    overlay.className = 'pg-overlay';
    overlay.innerHTML =
      '<div class="pg-card">' +
      '<button class="pg-close" title="\u0625\u063a\u0644\u0627\u0642">&times;</button>' +
      '<div class="pg-steps-container"></div>' +
      '<div class="pg-dots"></div>' +
      '<div class="pg-nav">' +
      '<button class="pg-prev" disabled>\u0627\u0644\u0633\u0627\u0628\u0642</button>' +
      '<button class="pg-next">\u0627\u0644\u062a\u0627\u0644\u064a</button>' +
      '</div></div>';

    const container = overlay.querySelector('.pg-steps-container');
    const dotsEl = overlay.querySelector('.pg-dots');

    data.steps.forEach(function (step, i) {
      const div = document.createElement('div');
      div.className = 'pg-step' + (i === 0 ? ' active' : '');
      div.innerHTML = '<h3>' + step.title + '</h3>' + step.body;
      container.appendChild(div);

      const dot = document.createElement('span');
      dot.className = 'dot' + (i === 0 ? ' active' : '');
      dot.setAttribute('data-idx', i);
      dotsEl.appendChild(dot);
    });

    document.body.appendChild(overlay);
    return overlay;
  }

  function buildHelpButton() {
    const btn = document.createElement('button');
    btn.className = 'pg-help-btn';
    btn.title = '\u062f\u0644\u064a\u0644 \u0627\u0633\u062a\u062e\u062f\u0627\u0645 \u0627\u0644\u0635\u0641\u062d\u0629';
    btn.textContent = '?';
    document.body.appendChild(btn);
    return btn;
  }

  var _openFn = null;

  function initGuide(pageKey, role) {
    _pageKey = pageKey;
    _role = role;
    var data = getGuideData(pageKey, role);
    if (!data) {
      data = getGuideData(pageKey, role, true);
      if (!data) return;
    }

    var helpBtn = buildHelpButton();
    var overlay = null;
    var current = 0;

    function open() {
      if (!overlay) overlay = buildDOM(data);
      current = 0;
      showStep(0);
      overlay.classList.add('active');
      markSeen(pageKey);
    }

    function close() {
      if (overlay) overlay.classList.remove('active');
    }

    function showStep(idx) {
      var steps = overlay.querySelectorAll('.pg-step');
      var dots = overlay.querySelectorAll('.pg-dots .dot');
      steps.forEach(function (s) { s.classList.remove('active'); });
      dots.forEach(function (d) { d.classList.remove('active'); });
      if (steps[idx]) steps[idx].classList.add('active');
      if (dots[idx]) dots[idx].classList.add('active');
      current = idx;
      var prevBtn = overlay.querySelector('.pg-prev');
      if (prevBtn) prevBtn.disabled = idx === 0;
      var nextBtn = overlay.querySelector('.pg-next');
      if (nextBtn) nextBtn.textContent = idx === steps.length - 1 ? '\u0625\u0646\u0647\u0627\u0621' : '\u0627\u0644\u062a\u0627\u0644\u064a';
    }

    _openFn = open;
    helpBtn.addEventListener('click', open);

    if (!hasSeen(pageKey)) {
      setTimeout(open, 600);
    }

    document.addEventListener('click', function (e) {
      if (!overlay) return;
      if (e.target.classList.contains('pg-close') || e.target === overlay) close();
      if (e.target.classList.contains('pg-next')) {
        if (current < data.steps.length - 1) showStep(current + 1);
        else close();
      }
      if (e.target.classList.contains('pg-prev')) {
        if (current > 0) showStep(current - 1);
      }
      if (e.target.classList.contains('dot') && e.target.hasAttribute('data-idx')) {
        showStep(parseInt(e.target.getAttribute('data-idx'), 10));
      }
    });
  }

  // Auto-init on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  function boot() {
    _pageKey = detectPageKey();
    if (!window.PAGE_GUIDE_CATALOG) return;
    detectRole(function (role) {
      initGuide(_pageKey, role);
    });
  }

  // Expose global API
  window.PageGuide = {
    open: function () {
      if (_openFn) { _openFn(); return; }
      if (!_pageKey) _pageKey = detectPageKey();
      var data = getGuideData(_pageKey, _role, true);
      if (!data) return;
      initGuide(_pageKey, _role);
      if (_openFn) _openFn();
    },
    reset: function (pageKey) {
      try { localStorage.removeItem(storageKey(pageKey || _pageKey)); } catch (e) {}
    },
    resetAll: function () {
      try {
        Object.keys(localStorage).forEach(function (k) {
          if (k.startsWith('pg_seen_')) localStorage.removeItem(k);
        });
      } catch (e) {}
    }
  };
})();
