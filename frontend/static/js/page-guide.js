/**
 * Universal Page Guide System
 * يتكيّف حسب الدور + الوضع النشط + أعلام الجودة + الصلاحيات (ما هو متاح فعلياً).
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
    '/academic_quality/instructor/quality-hub': 'instructor_quality_hub',
    '/academic_quality/supervisor/quality-hub': 'supervisor_quality_slim',
    '/academic_quality/ilo/outcomes-map': 'college_identity_story',
    '/academic_quality/surveys/invites': 'survey_invites',
    '/academic_quality/surveys/results': 'survey_results',
    '/academic_quality/surveys/trends': 'survey_results',
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
  let _audience = null;
  let _openFn = null;

  function detectPageKey() {
    const path = window.location.pathname;
    if (PAGE_ROUTES[path]) return PAGE_ROUTES[path];
    // أطوال أطول أولاً لتفادي التقاط بادئة عامة
    const keys = Object.keys(BLUEPRINT_ROUTES).sort(function (a, b) { return b.length - a.length; });
    for (var i = 0; i < keys.length; i++) {
      var prefix = keys[i];
      if (path === prefix || path.startsWith(prefix)) return BLUEPRINT_ROUTES[prefix];
    }
    var segments = path.replace(/^\//, '').replace(/\/\d+/g, '').replace(/\//g, '_');
    return segments || 'index';
  }

  function audienceFromAuth(d) {
    var caps = (d && d.capabilities) || {};
    var scope = (d && d.admin_department_scope) || {};
    return {
      role: String((d && d.role) || ''),
      active_mode: String((d && d.active_mode) || ''),
      is_college_quality_lead: Number((d && d.is_college_quality_lead) || 0) === 1,
      is_dept_quality_coordinator: Number((d && d.is_dept_quality_coordinator) || 0) === 1,
      capabilities: caps,
      department_label: (scope && (scope.label_ar || scope.name_ar || scope.department_label)) || null,
      allowed_guide_keys: null,
      packs: [],
    };
  }

  function loadAudience(callback) {
    fetch('/auth/check', { credentials: 'include', cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var aud = audienceFromAuth(d);
        if (aud.role) {
          try { sessionStorage.setItem('pg_user_role', aud.role); } catch (e) {}
        }
        _role = aud.role;
        _audience = aud;
        // اثراء من API الحزم الموحّدة (إن وُجدت صلاحية جودة)
        return fetch('/academic_quality/api/guide/audience', { credentials: 'include', cache: 'no-store' })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (j) {
            if (j && j.status === 'ok') {
              aud.allowed_guide_keys = j.allowed_guide_keys || [];
              aud.packs = j.packs || [];
              aud.department_label = j.department_label || aud.department_label;
              aud.is_primary_quality_audience = !!j.is_primary_quality_audience;
              aud.active_mode = j.active_mode || aud.active_mode;
              aud.is_college_quality_lead = !!j.is_college_quality_lead;
              aud.is_dept_quality_coordinator = !!j.is_dept_quality_coordinator;
              if (j.capabilities) aud.capabilities = Object.assign({}, aud.capabilities || {}, j.capabilities);
            }
            _audience = aud;
            callback(aud);
          })
          .catch(function () { callback(aud); });
      })
      .catch(function () {
        var role = '';
        try { role = sessionStorage.getItem('pg_user_role') || ''; } catch (e) {}
        _role = role;
        _audience = { role: role, active_mode: '', capabilities: {}, packs: [] };
        callback(_audience);
      });
  }

  function stepAllowed(step, aud) {
    if (!step) return false;
    var role = (aud && aud.role) || '';
    var am = (aud && aud.active_mode) || '';
    var caps = (aud && aud.capabilities) || {};

    if (step.forRoles && step.forRoles.length) {
      if (!role || step.forRoles.indexOf(role) < 0) {
        // أعلام قد تُعامل كأدوار مساندة
        var flagOk = false;
        if (step.forFlags && step.forFlags.length) {
          if (step.forFlags.indexOf('is_college_quality_lead') >= 0 && aud.is_college_quality_lead) flagOk = true;
          if (step.forFlags.indexOf('is_dept_quality_coordinator') >= 0 && aud.is_dept_quality_coordinator) flagOk = true;
        }
        if (!flagOk) return false;
      }
    }
    if (step.forFlags && step.forFlags.length) {
      var anyFlag = false;
      if (step.forFlags.indexOf('is_college_quality_lead') >= 0 && aud.is_college_quality_lead) anyFlag = true;
      if (step.forFlags.indexOf('is_dept_quality_coordinator') >= 0 && aud.is_dept_quality_coordinator) anyFlag = true;
      // إن وُجدت forFlags وحدها بدون forRoles تطابق الصارم
      if ((!step.forRoles || !step.forRoles.length) && !anyFlag) return false;
    }
    if (step.forModes && step.forModes.length) {
      if (!am || step.forModes.indexOf(am) < 0) {
        if (!(role === 'supervisor' && step.forModes.indexOf('supervisor') >= 0)) return false;
      }
    }
    if (step.forCaps && step.forCaps.length) {
      var okCap = step.forCaps.some(function (k) { return !!caps[k]; });
      if (!okCap) {
        if (aud.is_college_quality_lead && step.forCaps.indexOf('nav_surveys_results') >= 0) return true;
        return false;
      }
    }
    if (step.denyCaps && step.denyCaps.length) {
      if (step.denyCaps.some(function (k) { return !!caps[k]; })) return false;
    }
    return true;
  }

  function getGuideData(pageKey, aud, forceShow) {
    var catalog = window.PAGE_GUIDE_CATALOG;
    if (!catalog || !catalog[pageKey]) return null;
    var entry = catalog[pageKey];
    var role = (aud && aud.role) || '';

    // صفحات الجودة: إن وُجدت قائمة مفاتيح مسموحة من الخادم فلا تعرض مفتاحاً غير مدرج
    var qualityKeys = {
      academic_quality_dashboard: 1, college_profile: 1, college_identity_story: 1,
      programs_portal: 1, survey_admin: 1, survey_hub: 1, survey_results: 1, survey_invites: 1,
      instructor_quality_hub: 1, supervisor_quality_slim: 1, accreditation_map: 1,
      department_archive: 1, quality_glossary: 1, quality_assistant: 1, quality_knowledge: 1,
      ilo_catalog: 1, department_lo_dashboard: 1,
    };
    if (qualityKeys[pageKey] && aud && Array.isArray(aud.allowed_guide_keys) && aud.allowed_guide_keys.length) {
      if (aud.allowed_guide_keys.indexOf(pageKey) < 0 && !forceShow) return null;
    }

    if (!forceShow && entry.roles && entry.roles.length && role && entry.roles.indexOf(role) < 0) {
      var flagPass = false;
      if (aud && aud.is_college_quality_lead && entry.roles.indexOf('admin_main') >= 0) flagPass = true;
      if (aud && aud.is_dept_quality_coordinator && entry.roles.indexOf('head_of_department') >= 0) flagPass = true;
      if (!flagPass) return null;
    }

    var steps = (entry.steps || []).filter(function (s) {
      return stepAllowed(s, aud || {});
    });
    if (!steps.length && forceShow) steps = entry.steps || [];
    if (!steps.length) return null;

    var title = entry.title || '';
    var footer = '';
    if (aud && aud.department_label) {
      footer = '<p class="small text-muted mb-0 mt-2">نطاقك: <strong>' + String(aud.department_label).replace(/</g, '') + '</strong></p>';
    }
    if (footer && steps.length) {
      steps = steps.map(function (s, i) {
        if (i !== steps.length - 1) return s;
        return { title: s.title, body: (s.body || '') + footer, forRoles: s.forRoles, forCaps: s.forCaps, forFlags: s.forFlags, forModes: s.forModes };
      });
    }
    return { title: title, steps: steps };
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
      '<button class="pg-close" title="إغلاق">&times;</button>' +
      '<div class="pg-steps-container"></div>' +
      '<div class="pg-dots"></div>' +
      '<div class="pg-nav">' +
      '<button class="pg-prev" disabled>السابق</button>' +
      '<button class="pg-next">التالي</button>' +
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
    btn.title = 'دليل استخدام الصفحة';
    btn.textContent = '?';
    document.body.appendChild(btn);
    return btn;
  }

  function initGuide(pageKey, aud) {
    _pageKey = pageKey;
    _role = (aud && aud.role) || '';
    _audience = aud;
    var data = getGuideData(pageKey, aud, false);
    if (!data) return;

    var helpBtn = buildHelpButton();
    var overlay = null;
    var current = 0;

    function open() {
      data = getGuideData(pageKey, _audience || aud, false) || data;
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
      if (nextBtn) nextBtn.textContent = idx === steps.length - 1 ? 'إنهاء' : 'التالي';
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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  function boot() {
    _pageKey = detectPageKey();
    if (!window.PAGE_GUIDE_CATALOG) return;
    loadAudience(function (aud) {
      initGuide(_pageKey, aud);
    });
  }

  window.PageGuide = {
    open: function (pageKey) {
      var key = pageKey || _pageKey || detectPageKey();
      function doOpen(aud) {
        _audience = aud;
        var data = getGuideData(key, aud, false);
        if (!data) {
          // لا نتجاوز صلاحيات الجودة؛ فقط صفحات عامة غير مفهرسة كجودة
          return;
        }
        _pageKey = key;
        if (_openFn && key === _pageKey) { _openFn(); return; }
        initGuide(key, aud);
        if (_openFn) _openFn();
      }
      if (_audience) doOpen(_audience);
      else loadAudience(doOpen);
    },
    openKey: function (pageKey) { window.PageGuide.open(pageKey); },
    audience: function () { return _audience; },
    reset: function (pageKey) {
      try { localStorage.removeItem(storageKey(pageKey || _pageKey)); } catch (e) {}
    },
    resetAll: function () {
      try {
        Object.keys(localStorage).forEach(function (k) {
          if (k.indexOf('pg_seen_') === 0) localStorage.removeItem(k);
        });
      } catch (e) {}
    }
  };
})();
