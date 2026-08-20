  // دالة تسجيل الخروج — تنقل كامل إلى GET /logout (يمسح الجلسة + cookies)
  function handleLogout() {
    const btn = document.getElementById('logoutBtn');
    if (btn) btn.disabled = true;
    window.location.assign('/logout');
  }
  window.handleLogout = handleLogout;
  (function bindLogoutButton() {
    function attach() {
      const logoutBtn = document.getElementById('logoutBtn');
      if (!logoutBtn || logoutBtn.dataset.logoutBound === '1') return;
      logoutBtn.dataset.logoutBound = '1';
      logoutBtn.addEventListener('click', function (ev) {
        ev.preventDefault();
        handleLogout();
      });
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', attach);
    } else {
      attach();
    }
  })();

  // التحقق من حالة تسجيل الدخول وتطبيق الشريط — DOMContentLoaded (وليس load) لتجنب وميض القائمة
  async function runNavAuthCheck() {
    const INSTRUCTOR_FLAT_WRAP_IDS = [
      'navInsLibraryWrap', 'navInsQualityHubWrap', 'navInsIloCatalogWrap', 'navInstructorRowBreak',
      'navInsMyScheduleWrap', 'navInsMyExamsWrap', 'navInsMyAttendanceWrap',
      'navInsScheduleWrap', 'navInsCalendarWrap', 'navInsMidtermsWrap', 'navInsFinalsWrap',
      'navInsAttendanceWrap', 'navInsSupervisorWrap', 'navInsQualityAssistantWrap', 'navInsStudentLoWrap',
    ];

    function hideInstructorFlatNav() {
      INSTRUCTOR_FLAT_WRAP_IDS.forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.style.display = 'none'; el.classList.add('d-none'); }
      });
      const more = document.getElementById('navInstructorMoreWrap');
      if (more) { more.style.display = 'none'; more.classList.add('d-none'); }
    }

    function hideStudentNavShell() {
      ['navStudentPortalWrap', 'navStudentRegistrationsWrap', 'navStudentMoreWrap'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.style.display = 'none'; el.classList.add('d-none'); }
      });
    }

    function enforceStudentNavShell() {
      const hideIds = [
        'navDashboardWrap', 'navStudentAffairsWrap', 'navAcademicRecordsMenuWrap',
        'navPlanningMenuWrap', 'navCatalogWrap', 'navFacultySupervisionWrap',
        'navAdminSettingsWrap', 'navQualityAccreditationWrap', 'navArchivesMenuWrap', 'navStaffCompactMoreWrap',
        'navDensityToggleWrap', 'navMyCoursesWrap', 'navInstructorMoreWrap', 'navInstructorGradeDraftsWrap',
      ].concat(INSTRUCTOR_FLAT_WRAP_IDS);
      hideIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.style.display = 'none'; el.classList.add('d-none'); }
      });
      ['navStudentPortalWrap', 'navStudentRegistrationsWrap', 'navStudentMoreWrap'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.style.display = ''; el.classList.remove('d-none'); }
      });
      const navBar = document.querySelector('.app-navbar');
      if (navBar) {
        navBar.classList.add('nav-shell-student');
        navBar.classList.remove('nav-shell-instructor', 'nav-staff-compact', 'nav-staff-expanded');
      }
    }

    function enforceInstructorNavShell() {
      hideStudentNavShell();
      const hideIds = [
        'navDashboardWrap', 'navStudentAffairsWrap', 'navAcademicRecordsMenuWrap',
        'navPlanningMenuWrap', 'navCatalogWrap', 'navFacultySupervisionWrap',
        'navAdminSettingsWrap', 'navQualityAccreditationWrap', 'navStaffCompactMoreWrap',
        'navDensityToggleWrap', 'navSupervisorPortalWrap', 'navSupervisorSurveysWrap', 'navSupervisorMoreWrap',
        'navHodCourseDeliveryWrap', 'navInstructorMoreWrap',
      ];
      hideIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.style.display = 'none'; el.classList.add('d-none'); }
      });
      const showIds = [
        'navMyCoursesWrap', 'navInstructorGradeDraftsWrap',
        'navInsLibraryWrap', 'navInsQualityHubWrap', 'navInsIloCatalogWrap', 'navInstructorRowBreak',
        'navInsMyScheduleWrap', 'navInsMyExamsWrap', 'navInsMyAttendanceWrap',
        'navInsScheduleWrap', 'navInsCalendarWrap', 'navInsMidtermsWrap', 'navInsFinalsWrap',
        'navInsAttendanceWrap', 'navArchivesMenuWrap',
      ];
      showIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.style.display = ''; el.classList.remove('d-none'); }
      });
      const navBar = document.querySelector('.app-navbar');
      if (navBar) {
        navBar.classList.add('nav-shell-instructor');
        navBar.classList.remove('nav-shell-student', 'nav-shell-supervisor', 'nav-staff-compact', 'nav-staff-expanded');
      }
    }

    function enforceSupervisorNavShell() {
      hideStudentNavShell();
      hideInstructorFlatNav();
      const hideIds = [
        'navDashboardWrap', 'navStudentAffairsWrap', 'navAcademicRecordsMenuWrap',
        'navPlanningMenuWrap', 'navCatalogWrap', 'navFacultySupervisionWrap',
        'navAdminSettingsWrap', 'navQualityAccreditationWrap', 'navArchivesMenuWrap', 'navStaffCompactMoreWrap',
        'navDensityToggleWrap', 'navMyCoursesWrap', 'navInstructorMoreWrap', 'navInstructorGradeDraftsWrap',
        'navHodCourseDeliveryWrap',
      ];
      hideIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.style.display = 'none'; el.classList.add('d-none'); }
      });
      ['navSupervisorPortalWrap', 'navSupervisorSurveysWrap', 'navSupervisorMoreWrap'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.style.display = ''; el.classList.remove('d-none'); }
      });
      const navBar = document.querySelector('.app-navbar');
      if (navBar) {
        navBar.classList.add('nav-shell-supervisor');
        navBar.classList.remove('nav-shell-student', 'nav-shell-instructor', 'nav-staff-compact', 'nav-staff-expanded');
      }
    }

    try {
      const response = await fetch('/auth/check', {
        credentials: 'include',
        cache: 'no-store',
        headers: { 'Accept': 'application/json' }
      });
      const data = await response.json();
      
      if (!data.authenticated) {
        // المستخدم غير مسجل دخول، توجيهه لصفحة تسجيل الدخول
        if (window.location.pathname !== '/login') {
          window.location.href = '/login';
        }
        return;
      }
      const role = String(data.role || '').trim();
      const caps = data.capabilities;
      const isDeanNav = role === 'college_dean';
      const isViceDeanNav = role === 'academic_vice_dean';
      const isCollegeLeadNav = isDeanNav || isViceDeanNav;
      const ACAD_STAFF_ROLES = ['admin', 'admin_main', 'system_admin', 'college_dean', 'academic_vice_dean', 'head_of_department'];
      function isLeadershipOpsMode() {
        if (isDeanNav) return activeModeNav === 'dean' || activeModeNav === '';
        if (isViceDeanNav) return activeModeNav === 'vice_dean' || activeModeNav === 'dean' || activeModeNav === '';
        return false;
      }
      function isInstructorPortalMode() {
        return activeModeNav === 'instructor' && (
          role === 'instructor' || role === 'head_of_department' || isCollegeLeadNav
        );
      }
      function isSupervisorPortalModeNav() {
        return activeModeNav === 'supervisor' && (
          role === 'supervisor' || role === 'instructor' || role === 'head_of_department' || isCollegeLeadNav
        );
      }
      function defaultActiveModeForRole() {
        if (role === 'head_of_department') return 'head';
        if (isDeanNav) return 'dean';
        if (isViceDeanNav) return 'vice_dean';
        return 'instructor';
      }
      window.SO_AUTH = data;
      window.SO_CAPS = caps || null;

      fetch('/notifications/?unread=1', { credentials: 'include', cache: 'no-store' })
        .then(r => r.json().catch(() => ({})))
        .then(j => {
          const n = Array.isArray(j.notifications) ? j.notifications.length : 0;
          const badge = document.getElementById('navNotificationsBadge');
          if (!badge) return;
          if (n > 0) {
            badge.textContent = String(n > 99 ? '99+' : n);
            badge.classList.remove('d-none');
          } else {
            badge.classList.add('d-none');
          }
        })
        .catch(() => {});

      // إخفاء بعض الروابط — يُفضّل capabilities من الخادم؛ احتياطياً منطق الأدوار القديم
      let navUsers = false, navSup = false, navRules = false, navCollegeCatalog = false, navCollegeSharedCatalog = false;
      let showCourseReg = false, showScheduleVersions = false, showExamArch = false, showGradeDrafts = false;
      let showClosureReports = false, showFacultyScorecards = false, showFacultyDossier = false, showQualityDash = false, showSurveyAdmin = false, showIloCatalog = false, showDeptLoDash = false, showCollegeProfile = false, showProgramsPortal = false, showSupQuality = false, showStudentEvals = false, showStudentLo = false, showStudentRegs = false, showSurveysHub = false, showSurveysResults = false, showTermClosure = false, showTermOps = false;
      let canDeptScope = false;
      const dualInstructorSupervisor = role === 'instructor' && Number(data.is_supervisor || 0) === 1;
      const activeModeNav = (data.active_mode != null && data.active_mode !== '')
        ? String(data.active_mode).toLowerCase()
        : defaultActiveModeForRole();
      // بوابة المشرف: دور المشرف أو أي دور قيادي/أستاذ في وضع المشرف
      const inSupervisorPortal = role === 'supervisor'
        || (activeModeNav === 'supervisor' && (
          dualInstructorSupervisor
          || role === 'instructor'
          || role === 'head_of_department'
          || isCollegeLeadNav
        ));
      const inInstructorPortal = !dualInstructorSupervisor || activeModeNav !== 'supervisor';
      let isSupervisor = inSupervisorPortal;
      const alumniMode = !!(caps && caps.alumni_mode);
      const isStudentUi = (caps && caps.v >= 1) ? !!caps.is_student : (role === 'student');
      if (caps && caps.v >= 1) {
        navUsers = !!caps.nav_users_admin;
        navCollegeCatalog = !!caps.nav_college_catalog;
        navCollegeSharedCatalog = !!caps.nav_college_shared_catalog;
        navSup = !!caps.nav_supervision;
        navRules = !!caps.nav_academic_rules;
        showCourseReg = !!caps.nav_course_registration_report;
        showScheduleVersions = !!caps.nav_schedule_versions;
        showExamArch = !!caps.nav_exam_schedule_versions;
        showGradeDrafts = !!caps.nav_grade_drafts;
        showClosureReports = !!caps.nav_course_closure_reports;
        showFacultyScorecards = !!caps.nav_faculty_scorecards;
        showFacultyDossier = !!caps.nav_faculty_final_dossier;
        showQualityDash = !!caps.nav_academic_quality_dashboard;
        showSurveyAdmin = !!caps.nav_evaluation_survey_admin;
        showIloCatalog = !!caps.nav_ilo_catalog;
        showDeptLoDash = !!caps.nav_department_lo_dashboard;
        showCollegeProfile = !!caps.nav_college_profile;
        showProgramsPortal = !!caps.nav_programs_portal;
        showSupQuality = !!caps.nav_supervisor_quality_report;
        // صمام أمان: الطالب يجب أن يرى مدخل الاستبيانات حتى لو وصلت capabilities قديمة
        showStudentEvals = !!caps.nav_student_course_evaluations || role === 'student';
        showStudentLo = !!caps.nav_student_learning_outcomes;
        showStudentRegs = !!caps.nav_student_registrations;
        // صمام أمان مماثل لرابط /academic_quality/surveys
        showSurveysHub = !!caps.nav_surveys_hub || role === 'student';
        showSurveysResults = !!caps.nav_surveys_results;
        showTermClosure = !!caps.nav_term_closure;
        showTermOps = !!caps.nav_term_ops;
        isSupervisor = inSupervisorPortal || !!(caps && caps.is_supervisor_effective);
        canDeptScope = !!caps.can_switch_department_scope;
      } else {
        navUsers = (role === 'admin' || role === 'admin_main' || role === 'system_admin' || role === 'college_dean');
        navCollegeCatalog = navUsers;
        navCollegeSharedCatalog = (
          role === 'admin' || role === 'admin_main' || role === 'system_admin' ||
          role === 'college_dean' || role === 'academic_vice_dean' || role === 'head_of_department'
        );
        navSup = navUsers || role === 'head_of_department';
        navRules = navUsers;
        showCourseReg = ACAD_STAFF_ROLES.includes(role || '');
        showScheduleVersions = showCourseReg;
        showExamArch = showCourseReg;
        showGradeDrafts = ACAD_STAFF_ROLES.includes(role || '');
        showClosureReports = showCourseReg;
        showFacultyScorecards = showCourseReg || role === 'instructor';
        showFacultyDossier = showCourseReg;
        showQualityDash = showCourseReg;
        showSurveyAdmin = showCourseReg;
        showIloCatalog = showCourseReg;
        showDeptLoDash = showCourseReg;
        showCollegeProfile = true;
        showProgramsPortal = true;
        showSupQuality = isSupervisor;
        showStudentEvals = role === 'student';
        showStudentLo = role === 'student';
        showStudentRegs = role === 'student';
        showSurveysHub = ['student', 'instructor', 'supervisor', 'staff', 'head_of_department', 'college_dean', 'academic_vice_dean'].includes(role || '');
        showSurveysResults = ACAD_STAFF_ROLES.includes(role || '');
        showTermClosure = showSurveysResults;
        showTermOps = showSurveysResults;
        canDeptScope = (role === 'admin' || role === 'admin_main' || role === 'system_admin' || isLeadershipOpsMode());
      }
      const showMyCourses = (caps && caps.v >= 1)
        ? !!caps.nav_my_assigned_courses
        : (role === 'instructor' && inInstructorPortal);
      const showSupervisorPortal = (caps && caps.v >= 1)
        ? !!caps.nav_supervisor_dashboard
        : inSupervisorPortal;
      const showSupervisorPortalMenu = (caps && caps.v >= 1)
        ? !!caps.nav_supervisor_portal_menu
        : inSupervisorPortal;
      const instructorSlimNav = !!showMyCourses && inInstructorPortal && (
        role === 'instructor' ||
        (role === 'head_of_department' && activeModeNav === 'instructor') ||
        (isCollegeLeadNav && activeModeNav === 'instructor')
      );
      const showInstructorPortalMenu = (caps && caps.v >= 1)
        ? !!caps.nav_instructor_portal_menu
        : instructorSlimNav;
      // أولوية وضع الأستاذ النشط حتى لو أعاد بروفايل الصلاحيات تفعيل شريط الإدارة
      const useInstructorMore = isInstructorPortalMode()
        || (showInstructorPortalMenu && instructorSlimNav);
      const inTeachingPortalNav = (caps && caps.v >= 1)
        ? (!!caps.is_instructor_or_supervisor_nav
          || (role === 'staff' && !caps.nav_staff_operations_menu))
        : (useInstructorMore
          || isInstructorPortalMode()
          || isSupervisorPortalModeNav()
          || role === 'supervisor'
          || (role === 'instructor' && !isCollegeLeadNav && role !== 'head_of_department')
          || (role === 'staff'));
      let showStudentAffairsMenu = role !== 'student';
      if (caps && caps.v >= 1) showStudentAffairsMenu = !!caps.nav_student_affairs_menu;
      if (useInstructorMore) showStudentAffairsMenu = false;
      const wrapMy = document.getElementById('navMyCoursesWrap');
      if (wrapMy) wrapMy.style.display = showMyCourses ? '' : 'none';
      const wrapSupPortal = document.getElementById('navSupervisorPortalWrap');
      if (wrapSupPortal) wrapSupPortal.style.display = showSupervisorPortal ? '' : 'none';
      const wrapSupSurveys = document.getElementById('navSupervisorSurveysWrap');
      const wrapSupMore = document.getElementById('navSupervisorMoreWrap');
      if (wrapSupSurveys) wrapSupSurveys.style.display = showSupervisorPortalMenu ? '' : 'none';
      if (wrapSupMore) wrapSupMore.style.display = showSupervisorPortalMenu ? '' : 'none';
      const wrapStudentAffairs = document.getElementById('navStudentAffairsWrap');
      if (wrapStudentAffairs) wrapStudentAffairs.style.display = showStudentAffairsMenu ? '' : 'none';
      let showStudentPortal = false, showStudentHubMore = false;
      if (caps && caps.v >= 1) {
        showStudentPortal = !!caps.nav_student_portal || isStudentUi;
        showStudentHubMore = !!caps.nav_student_hub_more || isStudentUi;
        showStudentRegs = !!caps.nav_student_registrations || isStudentUi;
      } else {
        showStudentPortal = isStudentUi;
        showStudentHubMore = isStudentUi;
        showStudentRegs = isStudentUi;
      }
      if (useInstructorMore || showInstructorPortalMenu) {
        showStudentPortal = false;
        showStudentHubMore = false;
        showStudentRegs = false;
      }
      if (alumniMode) {
        showStudentRegs = false;
        showStudentEvals = false;
      }
      const wrapStudentPortal = document.getElementById('navStudentPortalWrap');
      if (wrapStudentPortal) wrapStudentPortal.style.display = showStudentPortal ? '' : 'none';
      const wrapStudentMore = document.getElementById('navStudentMoreWrap');
      if (wrapStudentMore) {
        wrapStudentMore.style.display = showStudentHubMore ? '' : 'none';
        if (!showStudentHubMore) wrapStudentMore.classList.add('d-none');
      }
      const wrapEvals = document.getElementById('navStudentEvaluationsWrap');
      if (wrapEvals) wrapEvals.style.display = 'none';
      const wrapStudentLo = document.getElementById('navStudentLearningOutcomesWrap');
      if (wrapStudentLo) wrapStudentLo.style.display = 'none';
      const wrapStudentRegs = document.getElementById('navStudentRegistrationsWrap');
      if (wrapStudentRegs) wrapStudentRegs.style.display = showStudentRegs ? '' : 'none';
      if (alumniMode) {
        [
          'navStudentSchedule', 'navStudentExams', 'navStudentAnnouncements',
          'navStudentCoursePages', 'navStudentRequests', 'navStudentEvaluations',
        ].forEach((id) => {
          const el = document.getElementById(id);
          if (el) {
            const li = el.closest('li');
            if (li) li.style.display = 'none';
            else el.style.display = 'none';
          }
        });
      }

      if (!navUsers) {
        const elUsers = document.getElementById('navUsersAdmin');
        if (elUsers) elUsers.style.display = 'none';
      }
      {
        const elHeadPolicy = document.getElementById('navDepartmentPolicyHead');
        if (elHeadPolicy) elHeadPolicy.style.display = (role === 'head_of_department') ? '' : 'none';
        const elMainPolicy = document.getElementById('navDepartmentPolicyApprovals');
        if (elMainPolicy) elMainPolicy.style.display = (role === 'admin_main' || role === 'college_dean' || role === 'system_admin') ? '' : 'none';
      }
      {
        const hodHeadModeSettings = role === 'head_of_department'
          && (activeModeNav === 'head' || activeModeNav === 'hod' || activeModeNav === 'department_head' || activeModeNav === '');
        const deanLeadSettings = role === 'college_dean' && isLeadershipOpsMode();
        const adminMainSettings = role === 'admin_main' || role === 'admin' || role === 'system_admin';
        // رئيس القسم: إعدادات قسم فقط — عميد: قيادة كلية — أدمن: إدارة كاملة
        const adminSettingsSubItems = adminMainSettings
          ? (navUsers || navRules || navCollegeCatalog || navCollegeSharedCatalog || navSup)
          : (deanLeadSettings
            ? (navUsers || navRules || true)
            : (hodHeadModeSettings && (role === 'head_of_department')));
        const showAdminSettingsMenu = !inTeachingPortalNav && (
          (caps && caps.v >= 1)
            ? (!!caps.nav_admin_settings && !!adminSettingsSubItems)
            : (!!adminSettingsSubItems && (adminMainSettings || deanLeadSettings || hodHeadModeSettings))
        );
        const wrapAdminSettings = document.getElementById('navAdminSettingsWrap');
        const labelFull = document.getElementById('adminSettingsMenuLabelFull');
        const labelShort = document.getElementById('adminSettingsMenuLabelShort');
        if (labelFull && labelShort) {
          if (hodHeadModeSettings) {
            labelFull.textContent = 'إعدادات القسم';
            labelShort.textContent = 'إعدادات';
          } else if (deanLeadSettings) {
            labelFull.textContent = 'قيادة الكلية';
            labelShort.textContent = 'القيادة';
          } else {
            labelFull.textContent = 'الإدارة والإعدادات';
            labelShort.textContent = 'إدارة';
          }
        }
        // إخفاء عناصر غير مناسبة حسب الدور (مع الإبقاء على نفس الـ ids)
        const elUsers = document.getElementById('navUsersAdmin');
        const elRules = document.getElementById('navAcademicRules');
        const elProjectStatus = document.getElementById('navProjectStatus');
        const elAdminBackup = document.getElementById('navAdminBackup');
        const elCc = document.getElementById('navCollegeCatalog');
        const elShared = document.getElementById('navCollegeSharedCatalog');
        const elHeadPolicy2 = document.getElementById('navDepartmentPolicyHead');
        const elMainPolicy2 = document.getElementById('navDepartmentPolicyApprovals');
        if (hodHeadModeSettings) {
          if (elUsers) elUsers.style.display = 'none';
          if (elRules) elRules.style.display = 'none';
          if (elProjectStatus) elProjectStatus.style.display = 'none';
          if (elAdminBackup) elAdminBackup.style.display = 'none';
          if (elCc) elCc.style.display = 'none';
          if (elMainPolicy2) elMainPolicy2.style.display = 'none';
          if (elHeadPolicy2) elHeadPolicy2.style.display = '';
          if (elShared) elShared.style.display = '';
        } else if (deanLeadSettings) {
          if (elUsers) elUsers.style.display = navUsers ? '' : 'none';
          if (elRules) elRules.style.display = navRules ? '' : 'none';
          if (elProjectStatus) elProjectStatus.style.display = '';
          if (elAdminBackup) elAdminBackup.style.display = 'none';
          if (elCc) elCc.style.display = 'none';
          if (elShared) elShared.style.display = 'none';
          if (elHeadPolicy2) elHeadPolicy2.style.display = 'none';
          if (elMainPolicy2) elMainPolicy2.style.display = '';
        } else if (adminMainSettings) {
          if (elUsers) elUsers.style.display = navUsers ? '' : 'none';
          if (elRules) elRules.style.display = navRules ? '' : 'none';
          if (elProjectStatus) elProjectStatus.style.display = '';
          if (elAdminBackup) elAdminBackup.style.display = (role === 'admin_main' || role === 'system_admin') ? '' : 'none';
          if (elCc) elCc.style.display = (navCollegeCatalog || role === 'head_of_department') ? '' : 'none';
          if (elShared) elShared.style.display = (navCollegeSharedCatalog || role === 'head_of_department') ? '' : 'none';
        }
        if (wrapAdminSettings) {
          if (!showAdminSettingsMenu) {
            wrapAdminSettings.style.display = 'none';
          } else if (!useInstructorMore && !isStudentUi && !inTeachingPortalNav) {
            wrapAdminSettings.style.removeProperty('display');
            wrapAdminSettings.classList.remove('d-none');
          }
        }
      }
      if (!navSup) {
        const elSup = document.getElementById('navSupervision');
        if (elSup) elSup.style.display = 'none';
      }
      if (!navRules) {
        const elRules = document.getElementById('navAcademicRules');
        // لا تُخفِ لائحة الإنذارات إذا كان العميد في وضع القيادة (يظهر في قيادة الكلية)
        if (elRules && !(role === 'college_dean' && isLeadershipOpsMode())) {
          elRules.style.display = 'none';
        }
      }
      {
        const elCc = document.getElementById('navCollegeCatalog');
        const elCcCourses = document.getElementById('navCollegeCatalogCourses');
        const elCcShared = document.getElementById('navCollegeSharedCatalog');
        const elCcSharedCourses = document.getElementById('navCollegeSharedCatalogCourses');
        const elCcDiv = document.getElementById('navCollegeCatalogCoursesDivider');
        const showCcCatalogMenu = !!navCollegeCatalog || role === 'head_of_department';
        const showSharedCatalogMenu = !!navCollegeSharedCatalog || role === 'head_of_department';
        const hodHeadModeCc = role === 'head_of_department'
          && (activeModeNav === 'head' || activeModeNav === 'hod' || activeModeNav === 'department_head' || activeModeNav === '');
        const deanLeadCc = role === 'college_dean' && isLeadershipOpsMode();
        // في قائمة الإدارة: رئيس القسم = مشترك فقط؛ العميد = لا كتالوج هنا؛ الأدمن = كامل
        if (elCc) {
          if (hodHeadModeCc || deanLeadCc) elCc.style.display = 'none';
          else elCc.style.display = showCcCatalogMenu ? '' : 'none';
        }
        if (elCcShared) {
          if (deanLeadCc) elCcShared.style.display = 'none';
          else if (hodHeadModeCc) elCcShared.style.display = '';
          else elCcShared.style.display = showSharedCatalogMenu ? '' : 'none';
        }
        if (elCcCourses) elCcCourses.style.display = showCcCatalogMenu ? '' : 'none';
        if (elCcSharedCourses) elCcSharedCourses.style.display = showSharedCatalogMenu ? '' : 'none';
        if (elCcDiv) elCcDiv.style.display = (showCcCatalogMenu || showSharedCatalogMenu) ? '' : 'none';
      }
      const elCourseRegReport = document.getElementById('navCourseRegistrationReport');
      if (elCourseRegReport) elCourseRegReport.style.display = showCourseReg ? '' : 'none';
      const staffReportsFallback = ACAD_STAFF_ROLES.includes(role || '') && !inSupervisorPortal && !useInstructorMore;
      const showPerfReport = (caps && caps.v >= 1) ? !!caps.nav_performance_report : staffReportsFallback;
      const showElectivesReport = (caps && caps.v >= 1) ? !!caps.nav_electives_report : staffReportsFallback;
      const showRegChangesReport = (caps && caps.v >= 1) ? !!caps.nav_registration_changes_report : staffReportsFallback;
      const showFailedReport = (caps && caps.v >= 1) ? !!caps.nav_failed_courses_report : staffReportsFallback;
      const showNotRegReport = (caps && caps.v >= 1) ? !!caps.nav_not_registered_courses_report : staffReportsFallback;
      const showUncompletedReport = (caps && caps.v >= 1) ? !!caps.nav_uncompleted_courses_report : staffReportsFallback;
      const showGradeAuditReport = (caps && caps.v >= 1) ? !!caps.nav_grade_course_mapping_audit : staffReportsFallback;
      const showAnalyticsReport = (caps && caps.v >= 1) ? !!caps.nav_analytics_report : staffReportsFallback;
      const showDeptReportsSection = (caps && caps.v >= 1)
        ? !!caps.nav_academic_reports_section
        : staffReportsFallback;
      function applyAcademicReportNavVisibility() {
        const reportMap = [
          ['navPerformance', showPerfReport],
          ['navElectivesReport', showElectivesReport],
          ['navRegistrationChangesReport', showRegChangesReport],
          ['navFailedCoursesReport', showFailedReport],
          ['navNotRegisteredCoursesReport', showNotRegReport],
          ['navUncompletedCoursesReport', showUncompletedReport],
          ['navGradeCourseAudit', showGradeAuditReport],
          ['navCourseRegistrationReport', showCourseReg],
          ['navAnalytics', showAnalyticsReport],
        ];
        reportMap.forEach(function ([id, show]) {
          const el = document.getElementById(id);
          if (el) el.style.display = show ? '' : 'none';
        });
        const anyReport = reportMap.some(function (pair) { return pair[1]; });
        const header = document.getElementById('navDeptReportsHeader');
        const gradesDivider = document.getElementById('navAcademicRecordsGradesDivider');
        if (header) header.style.display = (showDeptReportsSection && anyReport) ? '' : 'none';
        if (gradesDivider) gradesDivider.style.display = anyReport ? '' : 'none';
      }
      applyAcademicReportNavVisibility();
      const elScheduleVersions = document.getElementById('navScheduleVersions');
      if (elScheduleVersions) elScheduleVersions.style.display = showScheduleVersions ? '' : 'none';
      const elExamScheduleVersions = document.getElementById('navExamScheduleVersions');
      if (elExamScheduleVersions) elExamScheduleVersions.style.display = showExamArch ? '' : 'none';
      const elArchiveScheduleVersions = document.getElementById('navArchiveScheduleVersions');
      if (elArchiveScheduleVersions) elArchiveScheduleVersions.style.display = showScheduleVersions ? '' : 'none';
      const elArchiveExamScheduleVersions = document.getElementById('navArchiveExamScheduleVersions');
      if (elArchiveExamScheduleVersions) elArchiveExamScheduleVersions.style.display = showExamArch ? '' : 'none';
      const elArchivesOpsDivider = document.getElementById('navArchivesOpsDivider');
      const elArchivesOpsHeader = document.getElementById('navArchivesOpsHeader');
      const showArchivesOps = !!(showScheduleVersions || showExamArch);
      if (elArchivesOpsDivider) elArchivesOpsDivider.style.display = showArchivesOps ? '' : 'none';
      if (elArchivesOpsHeader) elArchivesOpsHeader.style.display = showArchivesOps ? '' : 'none';
      const elGradeDrafts = document.getElementById('navGradeDrafts');
      if (elGradeDrafts) elGradeDrafts.style.display = showGradeDrafts ? '' : 'none';
      const hodHeadModeNav = role === 'head_of_department'
        && (activeModeNav === 'head' || activeModeNav === 'hod' || activeModeNav === 'department_head' || activeModeNav === '');
      const showHodCourseDelivery = hodHeadModeNav;
      const elHodCourseDelivery = document.getElementById('navHodCourseDelivery');
      if (elHodCourseDelivery) elHodCourseDelivery.style.display = showHodCourseDelivery ? '' : 'none';
      const elHodCoursePages = document.getElementById('navHodCoursePages');
      if (elHodCoursePages) elHodCoursePages.style.display = showHodCourseDelivery ? '' : 'none';
      const elHodCourseDeliveryFaculty = document.getElementById('navHodCourseDeliveryFaculty');
      if (elHodCourseDeliveryFaculty) elHodCourseDeliveryFaculty.style.display = showHodCourseDelivery ? '' : 'none';
      const elHodCoursePagesFaculty = document.getElementById('navHodCoursePagesFaculty');
      if (elHodCoursePagesFaculty) elHodCoursePagesFaculty.style.display = showHodCourseDelivery ? '' : 'none';
      const elHodFinalBatch = document.getElementById('navHodFinalBatch');
      if (elHodFinalBatch) elHodFinalBatch.style.display = showHodCourseDelivery ? '' : 'none';
      const showDeanFinalBatches = role === 'college_dean' || role === 'academic_vice_dean' || role === 'admin_main' || role === 'admin' || role === 'system_admin';
      const elDeanFinalBatches = document.getElementById('navDeanFinalBatches');
      if (elDeanFinalBatches) elDeanFinalBatches.style.display = showDeanFinalBatches ? '' : 'none';
      const wrapHodCourseDelivery = document.getElementById('navHodCourseDeliveryWrap');
      if (wrapHodCourseDelivery) wrapHodCourseDelivery.style.display = showHodCourseDelivery ? '' : 'none';
      if (showHodCourseDelivery) {
        fetch('/course_delivery/hod/pending', { credentials: 'include' })
          .then(r => r.json().catch(() => ({})))
          .then(j => {
            const n = Number((j.summary && j.summary.total_pending) != null ? j.summary.total_pending :
              ((j.pending_baselines || []).length + (j.pending_gate_reports || []).length + (j.pending_grade_drafts || []).length));
            const badge = document.getElementById('navHodCourseDeliveryBadge');
            if (!badge) return;
            if (n > 0) {
              badge.textContent = String(n);
              badge.classList.remove('d-none');
            } else {
              badge.classList.add('d-none');
            }
          })
          .catch(() => {});
      }
      const anyFacultyQuality = showClosureReports || showFacultyScorecards || showFacultyDossier || showSupQuality || showHodCourseDelivery;
      const elFacultyQualityDivider = document.getElementById('navFacultyQualityDivider');
      if (elFacultyQualityDivider) elFacultyQualityDivider.style.display = anyFacultyQuality ? '' : 'none';
      const elClosure = document.getElementById('navCourseClosureReports');
      if (elClosure) elClosure.style.display = showClosureReports ? '' : 'none';
      const elScorecards = document.getElementById('navFacultyScorecards');
      if (elScorecards) elScorecards.style.display = showFacultyScorecards ? '' : 'none';
      const elDossier = document.getElementById('navFacultyFinalDossier');
      if (elDossier) elDossier.style.display = showFacultyDossier ? '' : 'none';
      const elQuality = document.getElementById('navAcademicQuality');
      if (elQuality) elQuality.style.display = showQualityDash ? '' : 'none';
      const elAccredMap = document.getElementById('navAccreditationMap');
      if (elAccredMap) elAccredMap.style.display = showQualityDash ? '' : 'none';
      const elAccredMapProg = document.getElementById('navAccreditationMapProg');
      if (elAccredMapProg) elAccredMapProg.style.display = showQualityDash ? '' : 'none';
      const elDeptArchive = document.getElementById('navDeptArchive');
      if (elDeptArchive) elDeptArchive.style.display = (showQualityDash && !useInstructorMore) ? '' : 'none';
      const showCollegeArchive = (caps && caps.v >= 1)
        ? !!caps.nav_college_archive
        : (role === 'college_dean' || role === 'academic_vice_dean' || role === 'admin_main' || role === 'system_admin' || role === 'admin' || !!auth?.is_college_quality_lead);
      const elCollegeArchive = document.getElementById('navCollegeArchive');
      if (elCollegeArchive) elCollegeArchive.style.display = (showCollegeArchive && !useInstructorMore && !(showSupervisorPortalMenu && inSupervisorPortal)) ? '' : 'none';
      const showArchiveShared = showQualityDash || showCollegeArchive || role === 'instructor' || useInstructorMore;
      const elArchiveShared = document.getElementById('navArchiveShared');
      if (elArchiveShared) elArchiveShared.style.display = showArchiveShared ? '' : 'none';
      const elDeptArchiveGuide = document.getElementById('navDeptArchiveGuide');
      if (elDeptArchiveGuide) elDeptArchiveGuide.style.display = (showQualityDash && !useInstructorMore) ? '' : 'none';
      const showQualityAssistant = (caps && caps.v >= 1)
        ? !!caps.nav_quality_assistant
        : (showQualityDash || !!caps?.nav_instructor_quality_hub);
      const elQualityAssistant = document.getElementById('navQualityAssistant');
      if (elQualityAssistant) elQualityAssistant.style.display = showQualityAssistant && showQualityDash ? '' : 'none';
      const elQualityKnowledge = document.getElementById('navQualityKnowledge');
      if (elQualityKnowledge) elQualityKnowledge.style.display = showQualityAssistant && showQualityDash ? '' : 'none';
      const elInsQualityAssistant = document.getElementById('navInsQualityAssistant');
      const wrapInsQualityAssistant = document.getElementById('navInsQualityAssistantWrap');
      const showInsQA = (caps && caps.v >= 1)
        ? (!!caps.nav_quality_assistant && !!caps.nav_instructor_quality_hub)
        : false;
      if (elInsQualityAssistant) elInsQualityAssistant.style.display = showInsQA ? '' : 'none';
      if (wrapInsQualityAssistant && !useInstructorMore) {
        wrapInsQualityAssistant.style.display = 'none';
        wrapInsQualityAssistant.classList.add('d-none');
      }
      const elSurveysHub = document.getElementById('navSurveysHub');
      if (elSurveysHub) elSurveysHub.style.display = showSurveysHub ? '' : 'none';
      const elSurveyAdmin = document.getElementById('navEvaluationSurveyAdmin');
      if (elSurveyAdmin) elSurveyAdmin.style.display = showSurveyAdmin ? '' : 'none';
      const elSurveysResults = document.getElementById('navSurveysResults');
      if (elSurveysResults) elSurveysResults.style.display = showSurveysResults ? '' : 'none';
      const showCourseQualityCollege = role === 'college_dean' || role === 'academic_vice_dean' || role === 'admin_main' || role === 'admin' || role === 'system_admin' || role === 'head_of_department';
      const elCourseQualityCollege = document.getElementById('navCourseQualityCollege');
      if (elCourseQualityCollege) elCourseQualityCollege.style.display = showCourseQualityCollege ? '' : 'none';
      const elTermClosure = document.getElementById('navTermClosure');
      if (elTermClosure) elTermClosure.style.display = showTermClosure ? '' : 'none';
      const elTermOps = document.getElementById('navTermOps');
      if (elTermOps) elTermOps.style.display = showTermOps ? '' : 'none';
      const elTermOpsAffairs = document.getElementById('navTermOpsAffairs');
      if (elTermOpsAffairs) elTermOpsAffairs.style.display = showTermOps ? '' : 'none';
      const elTermOfferings = document.getElementById('navTermOfferings');
      if (elTermOfferings) elTermOfferings.style.display = showTermOps ? '' : 'none';
      const elSurveysCompletion = document.getElementById('navSurveysCompletion');
      if (elSurveysCompletion) elSurveysCompletion.style.display = showSurveysResults ? '' : 'none';
      const elSurveysTrends = document.getElementById('navSurveysTrends');
      if (elSurveysTrends) elSurveysTrends.style.display = showSurveysResults ? '' : 'none';
      const elSurveysInvites = document.getElementById('navSurveysInvites');
      const showSurveysInvites = (caps && caps.v >= 1)
        ? !!(caps.nav_surveys_invites || caps.can_manage_survey_invites)
        : (role === 'admin_main' || role === 'system_admin' || role === 'college_dean');
      if (elSurveysInvites) elSurveysInvites.style.display = showSurveysInvites ? '' : 'none';
      const elCollegeProf = document.getElementById('navCollegeProfile');
      if (elCollegeProf) elCollegeProf.style.display = showCollegeProfile ? '' : 'none';
      const elProgramsPortal = document.getElementById('navProgramsPortal');
      if (elProgramsPortal) elProgramsPortal.style.display = showProgramsPortal ? '' : 'none';
      const elIlo = document.getElementById('navIloCatalog');
      if (elIlo) elIlo.style.display = showIloCatalog ? '' : 'none';
      const elDeptLo = document.getElementById('navDepartmentLoDashboard');
      if (elDeptLo) elDeptLo.style.display = showDeptLoDash ? '' : 'none';
      const elSupQ = document.getElementById('navSupervisorQualityReport');
      if (elSupQ) elSupQ.style.display = showSupQuality ? '' : 'none';
      if (!isSupervisor) {
        const elSD = document.getElementById('navSupervisorDashboard');
        if (elSD) elSD.style.display = 'none';
      }
      const isInstructorOrSupervisor = (caps && caps.v >= 1)
        ? !!caps.is_instructor_or_supervisor_nav
        : ((role === 'instructor') || (role === 'supervisor') || isSupervisor);
      if (isInstructorOrSupervisor) {
        // phase-2 RBAC UI: إخفاء الصفحات غير المسموحة وإبقاء العرض فقط
        const hideIds = [
          'navDashboard',
          'navAnalytics',
          'navInstructors',
          'navSupervision',
          'navPrereqs',
          'navPrereqsFlowchart',
          'navElectivesReport',
          'navRegistrationChangesReport',
          'navFailedCoursesReport',
          'navNotRegisteredCoursesReport',
          'navUncompletedCoursesReport',
          'navGradeCourseAudit',
          'navCourseRegistrationReport',
          'navScheduleVersions',
          'navExamScheduleVersions',
          'navWithdrawnFiles',
          'navUsersAdmin',
          'navAcademicRules',
          'navCollegeCatalog',
          'navCollegeCatalogCourses',
          'navCollegeSharedCatalog',
          'navCollegeSharedCatalogCourses',
          'navCatalogWrap',
          'navQualityAccreditationWrap',
          'navAdminSettingsWrap',
        ];
        if (useInstructorMore) {
          hideIds.push(
            'navStudentAffairsWrap', 'navPlanningMenuWrap', 'navAcademicRecordsMenuWrap',
            'navStudentPortalWrap', 'navStudentRegistrationsWrap', 'navStudentMoreWrap',
          );
        }
        if (!showSupervisorPortal) {
          hideIds.push('navFacultySupervisionWrap');
        }
        hideIds.forEach(id => {
          const el = document.getElementById(id);
          if (el) el.style.display = 'none';
        });
        if (showSupervisorPortal && !dualInstructorSupervisor) {
          const wrapFs = document.getElementById('navFacultySupervisionWrap');
          if (wrapFs) wrapFs.style.removeProperty('display');
          ['navInstructors', 'navSupervision'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
          });
          const elSD = document.getElementById('navSupervisorDashboard');
          if (elSD) elSD.style.display = '';
        }
      }

      const supervisorSlimNav = inSupervisorPortal && (
        !!showSupervisorPortal || !!showSupervisorPortalMenu
        || isSupervisorPortalModeNav() || role === 'supervisor'
      ) && (
        dualInstructorSupervisor || role === 'supervisor' || role === 'instructor'
        || role === 'head_of_department' || isCollegeLeadNav
      );
      // وضع المشرف لا يشارك شريط الإدارة حتى لو أعاد البروفايل تفعيل nav_staff_operations_menu
      const isStaffOpsNav = !inSupervisorPortal && !supervisorSlimNav && !isSupervisorPortalModeNav() && ((caps && caps.v >= 1)
        ? !!caps.nav_staff_operations_menu
        : (['admin', 'admin_main', 'system_admin'].includes(role || '')
          || (role === 'head_of_department' && (activeModeNav === 'head' || activeModeNav === 'hod' || activeModeNav === 'department_head' || activeModeNav === ''))
          || isLeadershipOpsMode()));
      let showTranscriptNav = true;
      let saAttendanceOnly = false;
      if (caps && caps.v >= 1) {
        showTranscriptNav = !!caps.nav_transcript_nav;
        saAttendanceOnly = !!caps.nav_student_affairs_attendance_only;
      } else {
        showTranscriptNav = ACAD_STAFF_ROLES.includes(role || '')
          || role === 'student' || inSupervisorPortal;
        saAttendanceOnly = (role === 'instructor' && inInstructorPortal && dualInstructorSupervisor);
      }
      const wrapInsGd = document.getElementById('navInstructorGradeDraftsWrap');
      const wrapInsMore = document.getElementById('navInstructorMoreWrap');
      if (wrapInsGd) wrapInsGd.style.display = useInstructorMore ? '' : 'none';
      if (wrapInsMore) { wrapInsMore.style.display = 'none'; wrapInsMore.classList.add('d-none'); }
      const instructorAlwaysFlat = [
        'navInsLibraryWrap', 'navInsQualityHubWrap', 'navInsIloCatalogWrap', 'navInstructorRowBreak',
        'navInsMyScheduleWrap', 'navInsMyExamsWrap', 'navInsMyAttendanceWrap',
        'navInsScheduleWrap', 'navInsCalendarWrap', 'navInsMidtermsWrap', 'navInsFinalsWrap',
        'navInsAttendanceWrap',
      ];
      instructorAlwaysFlat.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        if (useInstructorMore) {
          el.style.display = '';
          el.classList.remove('d-none');
        } else {
          el.style.display = 'none';
          el.classList.add('d-none');
        }
      });
      // إشراف / مساعد ذكي / مخرجات تعليمية — شرطي داخل شريط الأستاذ
      const showInsSupervisorLink = useInstructorMore && dualInstructorSupervisor && inInstructorPortal;
      const showInsStudentLo = useInstructorMore && !!showStudentLo && role !== 'student';
      function applyInstructorConditionalExtras() {
        if (!useInstructorMore) return;
        const wrapInsSup = document.getElementById('navInsSupervisorWrap');
        const elInsSup = document.getElementById('navInsSupervisor');
        if (elInsSup) elInsSup.style.display = showInsSupervisorLink ? '' : 'none';
        if (wrapInsSup) {
          if (showInsSupervisorLink) { wrapInsSup.style.display = ''; wrapInsSup.classList.remove('d-none'); }
          else { wrapInsSup.style.display = 'none'; wrapInsSup.classList.add('d-none'); }
        }
        const wrapInsQA = document.getElementById('navInsQualityAssistantWrap');
        if (wrapInsQA) {
          if (showInsQA) { wrapInsQA.style.display = ''; wrapInsQA.classList.remove('d-none'); }
          else { wrapInsQA.style.display = 'none'; wrapInsQA.classList.add('d-none'); }
        }
        const wrapInsStudentLo = document.getElementById('navInsStudentLoWrap');
        const elInsStudentLo = document.getElementById('navInsStudentLo');
        if (elInsStudentLo) elInsStudentLo.style.display = showInsStudentLo ? '' : 'none';
        if (wrapInsStudentLo) {
          if (showInsStudentLo) { wrapInsStudentLo.style.display = ''; wrapInsStudentLo.classList.remove('d-none'); }
          else { wrapInsStudentLo.style.display = 'none'; wrapInsStudentLo.classList.add('d-none'); }
        }
      }
      applyInstructorConditionalExtras();
      if (useInstructorMore) {
        ['navPlanningMenuWrap', 'navAcademicRecordsMenuWrap', 'navStudentAffairsWrap'].forEach(id => {
          const el = document.getElementById(id);
          if (el) el.style.display = 'none';
        });
        const elInsIlo = document.getElementById('navInsIloCatalog');
        const wrapIlo = document.getElementById('navInsIloCatalogWrap');
        const showIlo = (showIloCatalog || role === 'instructor');
        if (elInsIlo) elInsIlo.style.display = showIlo ? '' : 'none';
        if (wrapIlo) {
          if (showIlo) { wrapIlo.style.display = ''; wrapIlo.classList.remove('d-none'); }
          else { wrapIlo.style.display = 'none'; wrapIlo.classList.add('d-none'); }
        }
        enforceInstructorNavShell();
        applyInstructorConditionalExtras();
      } else if (!isStudentUi) {
        hideStudentNavShell();
      }
      if (supervisorSlimNav) {
        [
          'navMyCoursesWrap', 'navInstructorGradeDraftsWrap', 'navInstructorMoreWrap',
          'navPlanningMenuWrap', 'navStudentAffairsWrap', 'navCatalogWrap',
          'navFacultySupervisionWrap', 'navAdminSettingsWrap', 'navDashboardWrap',
          'navHodCourseDeliveryWrap', 'navQualityAccreditationWrap',
        ].forEach(id => {
          const el = document.getElementById(id);
          if (el) el.style.display = 'none';
        });
        hideInstructorFlatNav();
        const wrapQuality = document.getElementById('navQualityAccreditationWrap');
        if (wrapQuality) {
          wrapQuality.classList.add('d-none');
          wrapQuality.style.display = 'none';
        }
        if (showSupervisorPortalMenu || supervisorSlimNav) {
          ['navSupervisorPortalWrap', 'navSupervisorSurveysWrap', 'navSupervisorMoreWrap'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.style.removeProperty('display'); el.classList.remove('d-none'); }
          });
          enforceSupervisorNavShell();
          if (showSupervisorPortalMenu || showSupervisorPortal) {
            fetch('/supervisors/quality_context', { credentials: 'include', cache: 'no-store' })
              .then(r => r.json().catch(() => ({})))
              .then(j => {
                const pc = Number((j.surveys && j.surveys.pending_count) || 0);
                const badge = document.getElementById('navSupervisorSurveysBadge');
                if (!badge) return;
                if (pc > 0) {
                  badge.textContent = String(pc);
                  badge.classList.remove('d-none');
                } else {
                  badge.classList.add('d-none');
                }
              })
              .catch(() => {});
          }
        }
        const wrapAR = document.getElementById('navAcademicRecordsMenuWrap');
        if (wrapAR) {
          wrapAR.style.display = 'none';
          wrapAR.classList.add('d-none');
        }
        [
          'navGradeDrafts', 'navHodCourseDelivery', 'navElectivesReport',
          'navRegistrationChangesReport', 'navFailedCoursesReport',
          'navNotRegisteredCoursesReport', 'navUncompletedCoursesReport',
          'navGradeCourseAudit', 'navCourseRegistrationReport', 'navAnalytics',
        ].forEach(id => {
          const el = document.getElementById(id);
          if (el) el.style.display = 'none';
        });
        const elTranscriptSup = document.getElementById('navTranscript');
        if (elTranscriptSup) elTranscriptSup.style.display = showTranscriptNav ? '' : 'none';
        const elPerfSup = document.getElementById('navPerformance');
        if (elPerfSup) elPerfSup.style.display = '';
      }
      if (isStaffOpsNav && !useInstructorMore && !supervisorSlimNav && !inSupervisorPortal) {
        [
          'navMyCoursesWrap', 'navSupervisorPortalWrap',
          'navInstructorGradeDraftsWrap', 'navInstructorMoreWrap',
        ].forEach(id => {
          const el = document.getElementById(id);
          if (el) el.style.display = 'none';
        });
        hideInstructorFlatNav();
        [
          'navInsMySchedule', 'navInsMyExams', 'navInsMyAttendance',
          'navInsSupervisor', 'navInsQualityHub', 'navInsQualityAssistant', 'navInsIloCatalog', 'navInsStudentLo',
          'navInsLibrary', 'navInsSchedule', 'navInsCalendar', 'navInsMidterms', 'navInsFinals', 'navInsAttendance',
        ].forEach(id => {
          const el = document.getElementById(id);
          if (el) el.style.display = 'none';
        });
        if (!showSupervisorPortal) {
          const elSD = document.getElementById('navSupervisorDashboard');
          if (elSD) elSD.style.display = 'none';
        }
        if (!showSupQuality) {
          const elSupQFac = document.getElementById('navSupervisorQualityReport');
          if (elSupQFac) elSupQFac.style.display = 'none';
        }
        const showDashboardNav = (caps && caps.v >= 1)
          ? !!caps.nav_dashboard
          : (role !== 'student' && !inSupervisorPortal && !useInstructorMore);
        const wrapDashboard = document.getElementById('navDashboardWrap');
        if (wrapDashboard && !supervisorSlimNav) {
          wrapDashboard.style.display = showDashboardNav ? '' : 'none';
        }
      }
      const elTranscript = document.getElementById('navTranscript');
      if (elTranscript && !supervisorSlimNav) elTranscript.style.display = showTranscriptNav ? '' : 'none';
      if (saAttendanceOnly) {
        ['navStudents', 'navGraduates', 'navEnrollmentPlans', 'navRegistrations', 'navWithdrawnFiles', 'navRegistrationRequests'].forEach(id => {
          const el = document.getElementById(id);
          if (el) el.style.display = 'none';
        });
        const elAttendance = document.getElementById('navAttendance');
        if (elAttendance) elAttendance.style.display = '';
        const elPerf = document.getElementById('navPerformance');
        if (elPerf) elPerf.style.display = 'none';
        const elExamConflicts = document.getElementById('navExamsConflicts');
        if (elExamConflicts) elExamConflicts.style.display = 'none';
      }
      if (isSupervisor) {
        const elAttendance = document.getElementById('navAttendance');
        if (elAttendance) elAttendance.style.display = 'none';
      }

      const modeBanner = document.getElementById('activeModeBanner');
      /* إظهار الشريط: لا تعتمد فقط على caps.v (قد تفشل جلسات قديمة أو استجابة ناقصة) */
      const canSwitchMode =
        !!(caps && caps.can_switch_active_mode)
        || dualInstructorSupervisor
        || role === 'head_of_department'
        || isCollegeLeadNav;
      const switchProfile = (caps && caps.v >= 1)
        ? (caps.active_mode_switch_profile || '')
        : (role === 'head_of_department' ? 'triple'
          : (isDeanNav ? 'dean_triple'
            : (isViceDeanNav ? 'vice_dean_triple' : (dualInstructorSupervisor ? 'dual' : ''))));
      if (modeBanner) {
        if (canSwitchMode) {
          modeBanner.classList.remove('d-none');
          const am = (data.active_mode != null && data.active_mode !== '')
            ? data.active_mode.toString().toLowerCase()
            : defaultActiveModeForRole();
          const labelEl = document.getElementById('activeModeBannerLabel');
          if (labelEl) {
            const useDeanTriple = switchProfile === 'dean_triple' || switchProfile === 'dean_dual' || isDeanNav;
            const useViceDeanTriple = switchProfile === 'vice_dean_triple' || switchProfile === 'vice_dean_dual' || isViceDeanNav;
            if (switchProfile === 'triple' || role === 'head_of_department') {
              if (am === 'head' || am === 'hod' || am === 'department_head' || am === '')
                labelEl.textContent = 'الوضع الحالي: رئيس القسم (صلاحيات القسم والإدارة التشغيلية)';
              else if (am === 'supervisor')
                labelEl.textContent = 'الوضع الحالي: مشرف أكاديمي';
              else
                labelEl.textContent = 'الوضع الحالي: أستاذ (مقرراتي وتدريس)';
            } else if (useViceDeanTriple) {
              if (am === 'vice_dean' || am === 'dean' || am === '')
                labelEl.textContent = 'الوضع الحالي: وكيل الكلية للشؤون العلمية (صلاحيات القيادة الأكاديمية)';
              else if (am === 'supervisor')
                labelEl.textContent = 'الوضع الحالي: مشرف أكاديمي';
              else
                labelEl.textContent = 'الوضع الحالي: أستاذ (مقرراتي وتدريس)';
            } else if (useDeanTriple) {
              if (am === 'dean' || am === '')
                labelEl.textContent = 'الوضع الحالي: عميد الكلية (صلاحيات القيادة على مستوى الكلية)';
              else if (am === 'supervisor')
                labelEl.textContent = 'الوضع الحالي: مشرف أكاديمي';
              else
                labelEl.textContent = 'الوضع الحالي: أستاذ (مقرراتي وتدريس)';
            } else {
              labelEl.textContent = am === 'supervisor'
                ? 'الوضع الحالي: مشرف أكاديمي'
                : 'الوضع الحالي: أستاذ (مقرراتي وتدريس)';
            }
          }
          const dualG = document.getElementById('activeModeDualGroup');
          const tripleG = document.getElementById('activeModeTripleGroup');
          const useTriple = switchProfile === 'triple' || switchProfile === 'dean_triple' || switchProfile === 'dean_dual'
            || switchProfile === 'vice_dean_triple' || switchProfile === 'vice_dean_dual'
            || role === 'head_of_department' || isCollegeLeadNav;
          if (dualG) dualG.style.display = useTriple ? 'none' : '';
          if (tripleG) tripleG.style.display = useTriple ? '' : 'none';
          /** بعد تبديل الوضع: صفحة افتراضية مناسبة للدور الجديد (تجنّب بقاء صفحة رئيس القسم معلّقة مثل /dashboard) */
          function redirectAfterActiveModeSwitch(userRole, profile, newMode) {
            var m = String(newMode || '').toLowerCase().trim();
            if (userRole === 'head_of_department' || profile === 'triple') {
              if (m === 'head' || m === 'hod' || m === 'department_head') return '/dashboard';
              if (m === 'supervisor') return '/supervisor_dashboard';
              if (m === 'instructor') return '/my_courses';
              return '/';
            }
            if (userRole === 'college_dean' || profile === 'dean_triple' || profile === 'dean_dual') {
              if (m === 'dean' || m === '') return '/dashboard';
              if (m === 'supervisor') return '/supervisor_dashboard';
              if (m === 'instructor') return '/my_courses';
              return '/';
            }
            if (userRole === 'academic_vice_dean' || profile === 'vice_dean_triple' || profile === 'vice_dean_dual') {
              if (m === 'vice_dean' || m === 'dean' || m === '') return '/dashboard';
              if (m === 'supervisor') return '/supervisor_dashboard';
              if (m === 'instructor') return '/my_courses';
              return '/';
            }
            if (m === 'supervisor') return '/supervisor_dashboard';
            if (m === 'instructor') return '/my_courses';
            return '/';
          }
          const switchMode = function(mode) {
            const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
            const headers = {
              'Content-Type': 'application/json',
              'Accept': 'application/json',
              'X-Requested-With': 'XMLHttpRequest'
            };
            if (csrf) headers['X-CSRFToken'] = csrf;
            fetch('/auth/active_mode', {
              method: 'POST',
              credentials: 'include',
              cache: 'no-store',
              headers: headers,
              body: JSON.stringify({ mode: mode })
            }).then(function(r) {
              if (r.ok) {
                var next = redirectAfterActiveModeSwitch(role, switchProfile, mode);
                window.location.assign(next);
                return;
              }
              return r.json().catch(function() { return null; }).then(function(j) {
                var msg = (j && j.message) ? j.message : ('HTTP ' + r.status);
                console.error('active_mode failed', r.status, j);
                alert('تعذّر تبديل الوضع: ' + msg);
              });
            }).catch(function(err) {
              console.error('active_mode fetch', err);
              alert('تعذّر تبديل الوضع: ' + (err && err.message ? err.message : String(err)));
            });
          };
          if (useTriple) {
            const bHead = document.getElementById('btnActiveModeHead');
            const bHodIns = document.getElementById('btnHodInstructor');
            const bHodSup = document.getElementById('btnHodSupervisor');
            const headActive = am === 'head' || am === 'hod' || am === 'department_head' || am === '';
            const deanActive = am === 'dean' || am === '';
            const viceDeanActive = am === 'vice_dean' || am === 'dean' || am === '';
            if (bHead) {
              if (role === 'college_dean') {
                bHead.textContent = 'عميد الكلية';
                bHead.classList.toggle('active', deanActive);
                bHead.onclick = function() { switchMode('dean'); };
              } else if (role === 'academic_vice_dean') {
                bHead.textContent = 'وكيل الشؤون العلمية';
                bHead.classList.toggle('active', viceDeanActive);
                bHead.onclick = function() { switchMode('vice_dean'); };
              } else {
                bHead.textContent = 'رئيس القسم';
                bHead.classList.toggle('active', headActive);
                bHead.onclick = function() { switchMode('head'); };
              }
            }
            if (bHodIns) {
              bHodIns.classList.toggle('active', am === 'instructor');
              bHodIns.onclick = function() { switchMode('instructor'); };
            }
            if (bHodSup) {
              bHodSup.classList.toggle('active', am === 'supervisor');
              bHodSup.onclick = function() { switchMode('supervisor'); };
            }
          } else {
            const bIns = document.getElementById('btnActiveModeInstructor');
            const bSup = document.getElementById('btnActiveModeSupervisor');
            if (bIns) {
              bIns.classList.toggle('active', am === 'instructor');
              bIns.onclick = function() { switchMode('instructor'); };
            }
            if (bSup) {
              bSup.classList.toggle('active', am === 'supervisor');
              bSup.onclick = function() { switchMode('supervisor'); };
            }
          }
        } else {
          modeBanner.classList.add('d-none');
        }
      }

      const deptBanner = document.getElementById('adminDeptScopeBanner');
      const deptSel = document.getElementById('adminDeptScopeSelect');
      const showDevHints = document.querySelector('meta[name="show-dev-hints"]')?.getAttribute('content') === '1';
      const deptDevHint = document.getElementById('adminDeptScopeDevHint');
      const deptHelpBtn = document.getElementById('adminDeptScopeHelpBtn');
      const deptEmptyWarn = document.getElementById('adminDeptScopeEmptyWarn');
      const deptScopeLabel = document.getElementById('adminDeptScopeLabelText');

      function updateAdminDeptScopeLabel(scopeObj, selectEl) {
        if (!deptScopeLabel) return;
        if (scopeObj && scopeObj.id != null) {
          const code = (scopeObj.code || '').trim();
          const name = (scopeObj.name_ar || '').trim() || 'قسم';
          deptScopeLabel.textContent = 'نطاق العرض: ' + (code ? (code + ' — ') : '') + name;
        } else if (selectEl && selectEl.selectedIndex >= 0 && !selectEl.value) {
          deptScopeLabel.textContent = 'نطاق العرض: كل الأقسام';
        } else {
          deptScopeLabel.textContent = 'نطاق العرض: كل الأقسام';
        }
      }

      async function refreshAdminDeptScopeEmptyWarn() {
        if (!deptEmptyWarn || !deptSel || !deptSel.value) {
          if (deptEmptyWarn) deptEmptyWarn.classList.add('d-none');
          return;
        }
        try {
          const stResp = await fetch('/auth/admin_department_scope/status', {
            credentials: 'include',
            cache: 'no-store',
            headers: { 'Accept': 'application/json' }
          });
          const stJson = await stResp.json().catch(function () { return null; });
          if (stResp.ok && stJson && stJson.scoped && stJson.is_empty) {
            deptEmptyWarn.classList.remove('d-none');
          } else {
            deptEmptyWarn.classList.add('d-none');
          }
        } catch (_e) {
          deptEmptyWarn.classList.add('d-none');
        }
      }

      if (showDevHints) {
        if (deptDevHint) deptDevHint.classList.remove('d-none');
        if (deptHelpBtn) {
          deptHelpBtn.classList.remove('d-none');
          const popHtml = (
            'يُعرض الطلاب عند تطابق <strong>قسم الطالب</strong> أو '
            + '<strong>برنامجه الحالي/الالتحاق</strong> ضمن القسم.<br>'
            + 'إن بقي النطاق فارغاً: شغّل <code>scripts/phase0_apply.py</code> '
            + 'أو راجع <code>department_id</code> و <code>current_program_id</code>.'
          );
          deptHelpBtn.setAttribute('data-bs-content', popHtml);
          if (window.bootstrap && typeof window.bootstrap.Popover !== 'undefined') {
            try { bootstrap.Popover.getOrCreateInstance(deptHelpBtn); } catch (_e) { /* ignore */ }
          }
        }
      }

      if (deptBanner && deptSel && canDeptScope && !isStudentUi && !isInstructorPortalMode() && !isSupervisorPortalModeNav()) {
        deptBanner.classList.remove('d-none');
        try {
          const dResp = await fetch('/college/catalog/departments', {
            credentials: 'include',
            cache: 'no-store',
            headers: { 'Accept': 'application/json' }
          });
          const dJson = await dResp.json().catch(function () { return null; });
          const items = (dJson && dJson.items) ? dJson.items : [];
          deptSel.innerHTML = '';
          const optAll = document.createElement('option');
          optAll.value = '';
          optAll.textContent = 'كل الكلية (بدون تصفية قسم)';
          deptSel.appendChild(optAll);
          items.forEach(function (d) {
            const o = document.createElement('option');
            o.value = String(d.id);
            o.textContent = (d.code ? (d.code + ' — ') : '') + (d.name_ar || '');
            deptSel.appendChild(o);
          });
          const curScope = data.admin_department_scope;
          deptSel.value = (curScope && curScope.id != null) ? String(curScope.id) : '';
          updateAdminDeptScopeLabel(curScope, deptSel);
          await refreshAdminDeptScopeEmptyWarn();
          let lastDeptSelect = deptSel.value;
          deptSel.addEventListener('change', async function () {
            const v = deptSel.value;
            const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
            const headers = {
              'Content-Type': 'application/json',
              'Accept': 'application/json',
              'X-Requested-With': 'XMLHttpRequest'
            };
            if (csrf) headers['X-CSRFToken'] = csrf;
            const body = v
              ? JSON.stringify({ department_id: parseInt(v, 10) })
              : JSON.stringify({ department_id: null });
            const pr = await fetch('/auth/admin_department_scope', {
              method: 'POST',
              credentials: 'include',
              cache: 'no-store',
              headers: headers,
              body: body
            });
            if (!pr.ok) {
              const j = await pr.json().catch(function () { return null; });
              alert((j && j.message) ? j.message : ('HTTP ' + pr.status));
              deptSel.value = lastDeptSelect;
              return;
            }
            lastDeptSelect = v;
            window.location.reload();
          });
        } catch (e) {
          console.error(e);
          deptSel.innerHTML = '<option value=\"\">تعذّر تحميل الأقسام</option>';
        }
      }

      if (isStudentUi) {
        // واجهة الطالب: بوابتي + تسجيلاتي + المزيد فقط (بدون قوائم الإدارة)
        enforceStudentNavShell();
      }

      // ضمان الجودة والاعتماد (بعد فلاتر الأدوار — لا يُخفى بـ d-none فقط)
      let showQualityMenu = showQualityDash || showSurveyAdmin || showIloCatalog || showDeptLoDash || showCollegeProfile || showProgramsPortal || showSurveysHub || showSurveysResults || showTermClosure;
      if (isStudentUi) showQualityMenu = false;
      if (useInstructorMore) showQualityMenu = false;
      if (showSupervisorPortalMenu && inSupervisorPortal) showQualityMenu = false;
      if (isSupervisorPortalModeNav() || role === 'supervisor') showQualityMenu = false;
      // trends + invites تستخدم نفس صلاحية نتائج الاستبيانات
      if (!showQualityMenu && !useInstructorMore && !inSupervisorPortal && role !== 'supervisor' && !isSupervisorPortalModeNav()) {
        const amQ = (data.active_mode || '').trim().toLowerCase();
        const hodHeadMode = role === 'head_of_department'
          && (amQ === '' || amQ === 'head' || amQ === 'hod' || amQ === 'department_head');
        const deanLeadMode = isDeanNav && (amQ === '' || amQ === 'dean');
        const viceDeanLeadMode = isViceDeanNav && (amQ === '' || amQ === 'vice_dean' || amQ === 'dean');
        showQualityMenu = (role === 'admin' || role === 'admin_main' || role === 'system_admin' || isLeadershipOpsMode()) || hodHeadMode || deanLeadMode || viceDeanLeadMode;
      }
      const wrapQuality = document.getElementById('navQualityAccreditationWrap');
      if (wrapQuality) {
        if (showQualityMenu) {
          wrapQuality.classList.remove('d-none');
          wrapQuality.style.removeProperty('display');
        } else {
          wrapQuality.classList.add('d-none');
          wrapQuality.style.display = 'none';
        }
      }
      // قائمة الأرشيف في الشريط الرئيسي
      (function applyArchivesMenuVisibility() {
        const wrapArchives = document.getElementById('navArchivesMenuWrap');
        if (!wrapArchives) return;
        if (isStudentUi || (showSupervisorPortalMenu && inSupervisorPortal) || role === 'supervisor' || isSupervisorPortalModeNav()) {
          wrapArchives.classList.add('d-none');
          wrapArchives.style.display = 'none';
          return;
        }
        const ids = [
          'navDeptArchive', 'navCollegeArchive', 'navArchiveShared', 'navDeptArchiveGuide',
          'navArchiveScheduleVersions', 'navArchiveExamScheduleVersions',
        ];
        let any = false;
        ids.forEach(function (id) {
          const el = document.getElementById(id);
          if (el && el.style.display !== 'none') any = true;
        });
        if (any) {
          wrapArchives.classList.remove('d-none');
          wrapArchives.style.removeProperty('display');
        } else {
          wrapArchives.classList.add('d-none');
          wrapArchives.style.display = 'none';
        }
      })();
      // إخفاء عناوين المجموعات الفارغة في قائمة الجودة
      (function hideEmptyQaNavGroups() {
        const groups = ['overview', 'surveys', 'closure', 'accred', 'college'];
        groups.forEach(function(g) {
          const markers = document.querySelectorAll('[data-qa-group="' + g + '"]');
          let anyItem = false;
          markers.forEach(function(el) {
            if (el.classList.contains('dropdown-item') && el.style.display !== 'none') anyItem = true;
          });
          markers.forEach(function(el) {
            if (el.classList.contains('dropdown-item')) return;
            const li = el.closest('li') || el.parentElement;
            if (!li) return;
            li.style.display = anyItem ? '' : 'none';
          });
        });
      })();

      // إخفاء قائمة Dropdown بالكامل إذا صارت كل عناصرها مخفية
      const skipAutoShow = new Set([
        'navQualityAccreditationWrap',
        'navArchivesMenuWrap',
        'navInstructorMoreWrap',
        'navAdminSettingsWrap',
        'navStaffCompactMoreWrap',
        'navStudentPortalWrap',
        'navStudentRegistrationsWrap',
        'navStudentMoreWrap',
      ]);
      if (isStudentUi) {
        skipAutoShow.add('navStudentAffairsWrap');
        skipAutoShow.add('navCatalogWrap');
        skipAutoShow.add('navFacultySupervisionWrap');
        skipAutoShow.add('navAdminSettingsWrap');
        skipAutoShow.add('navStudentMoreWrap');
        skipAutoShow.add('navAcademicRecordsMenuWrap');
        skipAutoShow.add('navPlanningMenuWrap');
        skipAutoShow.add('navQualityAccreditationWrap');
        skipAutoShow.add('navArchivesMenuWrap');
      }
      if (useInstructorMore) {
        skipAutoShow.add('navStudentAffairsWrap');
        skipAutoShow.add('navAcademicRecordsMenuWrap');
        skipAutoShow.add('navPlanningMenuWrap');
        skipAutoShow.add('navCatalogWrap');
        skipAutoShow.add('navFacultySupervisionWrap');
        skipAutoShow.add('navAdminSettingsWrap');
        skipAutoShow.add('navQualityAccreditationWrap');
        skipAutoShow.add('navStudentMoreWrap');
        skipAutoShow.add('navStudentPortalWrap');
        skipAutoShow.add('navStudentRegistrationsWrap');
      }
      if (supervisorSlimNav || inSupervisorPortal) {
        skipAutoShow.add('navStudentAffairsWrap');
        skipAutoShow.add('navAcademicRecordsMenuWrap');
        skipAutoShow.add('navPlanningMenuWrap');
        skipAutoShow.add('navCatalogWrap');
        skipAutoShow.add('navFacultySupervisionWrap');
        skipAutoShow.add('navAdminSettingsWrap');
        skipAutoShow.add('navQualityAccreditationWrap');
        skipAutoShow.add('navArchivesMenuWrap');
        skipAutoShow.add('navHodCourseDeliveryWrap');
        skipAutoShow.add('navDashboardWrap');
        skipAutoShow.add('navStaffCompactMoreWrap');
        skipAutoShow.add('navDensityToggleWrap');
      }
      document.querySelectorAll('.nav-item.dropdown').forEach(dd => {
        if (skipAutoShow.has(dd.id)) return;
        const items = dd.querySelectorAll('.dropdown-item');
        if (!items.length) return;
        const hasVisible = Array.from(items).some(it => it.style.display !== 'none');
        if (!hasVisible) {
          dd.style.display = 'none';
        } else if (!skipAutoShow.has(dd.id) && !isStudentUi && !useInstructorMore && !supervisorSlimNav && !inSupervisorPortal) {
          dd.style.removeProperty('display');
          dd.classList.remove('d-none');
        }
      });

      if (isStudentUi) enforceStudentNavShell();
      else if (useInstructorMore) {
        enforceInstructorNavShell();
        applyInstructorConditionalExtras();
      }
      else if (supervisorSlimNav || (showSupervisorPortalMenu && inSupervisorPortal)) enforceSupervisorNavShell();

      // منع إعادة إظهار قوائم الأستاذ بعد الحلقة أعلاه (خلل سابق)
      if (!useInstructorMore) {
        ['navInstructorMoreWrap', 'navInstructorGradeDraftsWrap'].forEach(id => {
          const el = document.getElementById(id);
          if (el) el.style.display = 'none';
        });
        hideInstructorFlatNav();
      }
      // لا تخفِ بوابة المشرف عند شريط الإدارة — وضعان متنافيان
      if (isStaffOpsNav && !useInstructorMore && !supervisorSlimNav && !inSupervisorPortal) {
        ['navMyCoursesWrap', 'navSupervisorPortalWrap', 'navInstructorMoreWrap', 'navInstructorGradeDraftsWrap'].forEach(id => {
          const el = document.getElementById(id);
          if (el) el.style.display = 'none';
        });
        hideInstructorFlatNav();
      }

      // وضع الشريط المدمج / الموسع (إدارة ورئيس قسم / عميد / وكيلة)
      const STAFF_NAV_SECONDARY_BY_ROLE = {
        admin_main: [
          { wrapId: 'navAcademicRecordsMenuWrap', header: 'السجل الأكاديمي' },
          { wrapId: 'navCatalogWrap', header: 'المقررات' },
          { wrapId: 'navFacultySupervisionWrap', header: 'الأساتذة والإشراف' },
          { wrapId: 'navAdminSettingsWrap', header: 'الإدارة والإعدادات' },
        ],
        head_of_department: [
          { wrapId: 'navAcademicRecordsMenuWrap', header: 'السجل الأكاديمي' },
          { wrapId: 'navCatalogWrap', header: 'المقررات' },
          { wrapId: 'navFacultySupervisionWrap', header: 'الأساتذة والإشراف' },
          { wrapId: 'navAdminSettingsWrap', header: 'إعدادات القسم' },
        ],
        college_dean: [
          { wrapId: 'navAcademicRecordsMenuWrap', header: 'السجل الأكاديمي' },
          { wrapId: 'navCatalogWrap', header: 'المقررات' },
          { wrapId: 'navFacultySupervisionWrap', header: 'الأساتذة والإشراف' },
          { wrapId: 'navAdminSettingsWrap', header: 'قيادة الكلية' },
        ],
        academic_vice_dean: [
          { wrapId: 'navAcademicRecordsMenuWrap', header: 'السجل الأكاديمي' },
          { wrapId: 'navCatalogWrap', header: 'المقررات' },
        ],
      };
      const STAFF_NAV_SECONDARY_DEFAULT = [
        { wrapId: 'navAcademicRecordsMenuWrap', header: 'السجل الأكاديمي' },
        { wrapId: 'navCatalogWrap', header: 'المقررات' },
        { wrapId: 'navFacultySupervisionWrap', header: 'الأساتذة والإشراف' },
        { wrapId: 'navQualityAccreditationWrap', header: 'ضمان الجودة والاعتماد' },
        { wrapId: 'navArchivesMenuWrap', header: 'الأرشيف' },
        { wrapId: 'navAdminSettingsWrap', header: 'الإدارة والإعدادات' },
      ];
      const EXPANDED_NAV_ORDER = {
        admin_main: [
          'navDashboardWrap', 'navStudentAffairsWrap', 'navPlanningMenuWrap',
          'navAcademicRecordsMenuWrap', 'navCatalogWrap', 'navFacultySupervisionWrap',
          'navQualityAccreditationWrap', 'navArchivesMenuWrap', 'navAdminSettingsWrap',
        ],
        head_of_department: [
          'navDashboardWrap', 'navHodCourseDeliveryWrap', 'navStudentAffairsWrap',
          'navPlanningMenuWrap', 'navAcademicRecordsMenuWrap', 'navCatalogWrap',
          'navQualityAccreditationWrap', 'navArchivesMenuWrap', 'navFacultySupervisionWrap', 'navAdminSettingsWrap',
        ],
        college_dean: [
          'navDashboardWrap', 'navStudentAffairsWrap', 'navPlanningMenuWrap',
          'navAcademicRecordsMenuWrap', 'navCatalogWrap', 'navFacultySupervisionWrap',
          'navQualityAccreditationWrap', 'navArchivesMenuWrap', 'navAdminSettingsWrap',
        ],
        academic_vice_dean: [
          'navDashboardWrap', 'navStudentAffairsWrap', 'navPlanningMenuWrap',
          'navAcademicRecordsMenuWrap', 'navCatalogWrap', 'navQualityAccreditationWrap', 'navArchivesMenuWrap',
        ],
      };
      const QUALITY_PRIMARY_ROLES = new Set([
        'admin_main', 'college_dean', 'academic_vice_dean', 'head_of_department',
      ]);
      // ترتيب الشريط المدمج (primary فقط) — الجودة والأرشيف ظاهران؛ اعتماد القسم لرئيس القسم فقط
      const COMPACT_PRIMARY_ORDER = {
        admin_main: [
          'navDashboardWrap', 'navStudentAffairsWrap', 'navPlanningMenuWrap',
          'navQualityAccreditationWrap', 'navArchivesMenuWrap', 'navStaffCompactMoreWrap',
        ],
        college_dean: [
          'navDashboardWrap', 'navStudentAffairsWrap', 'navPlanningMenuWrap',
          'navQualityAccreditationWrap', 'navArchivesMenuWrap', 'navStaffCompactMoreWrap',
        ],
        academic_vice_dean: [
          'navDashboardWrap', 'navStudentAffairsWrap', 'navPlanningMenuWrap',
          'navQualityAccreditationWrap', 'navArchivesMenuWrap', 'navStaffCompactMoreWrap',
        ],
        head_of_department: [
          'navDashboardWrap', 'navHodCourseDeliveryWrap', 'navStudentAffairsWrap',
          'navPlanningMenuWrap', 'navQualityAccreditationWrap', 'navArchivesMenuWrap', 'navStaffCompactMoreWrap',
        ],
      };
      const STAFF_NAV_ORDER_RESET_IDS = [
        'navDashboardWrap', 'navHodCourseDeliveryWrap', 'navStudentAffairsWrap',
        'navPlanningMenuWrap', 'navAcademicRecordsMenuWrap', 'navCatalogWrap',
        'navFacultySupervisionWrap', 'navQualityAccreditationWrap', 'navArchivesMenuWrap',
        'navAdminSettingsWrap', 'navStaffCompactMoreWrap',
      ];
      const STAFF_NAV_ALL_OPS_WRAP_IDS = [
        'navDashboardWrap', 'navHodCourseDeliveryWrap', 'navStudentAffairsWrap',
        'navPlanningMenuWrap', 'navAcademicRecordsMenuWrap', 'navCatalogWrap',
        'navFacultySupervisionWrap', 'navQualityAccreditationWrap', 'navArchivesMenuWrap',
        'navAdminSettingsWrap', 'navStaffCompactMoreWrap',
      ];
      function getExpandedNavRoleKey() {
        if (role === 'head_of_department') {
          const am = activeModeNav;
          if (am === 'head' || am === 'hod' || am === 'department_head' || am === '')
            return 'head_of_department';
          return '';
        }
        if (role === 'college_dean' && isLeadershipOpsMode()) return 'college_dean';
        if (role === 'academic_vice_dean' && isLeadershipOpsMode()) return 'academic_vice_dean';
        if (role === 'admin_main' || role === 'system_admin' || role === 'admin') return 'admin_main';
        return '';
      }
      function getStaffNavSecondary() {
        const key = getExpandedNavRoleKey();
        return (key && STAFF_NAV_SECONDARY_BY_ROLE[key])
          ? STAFF_NAV_SECONDARY_BY_ROLE[key]
          : STAFF_NAV_SECONDARY_DEFAULT;
      }
      function applyQualityNavTier(roleKey) {
        const wrapQuality = document.getElementById('navQualityAccreditationWrap');
        if (!wrapQuality) return;
        if (QUALITY_PRIMARY_ROLES.has(roleKey)) {
          wrapQuality.setAttribute('data-nav-tier', 'primary');
        } else {
          wrapQuality.setAttribute('data-nav-tier', 'secondary');
        }
      }
      function resetExpandedNavOrder() {
        STAFF_NAV_ORDER_RESET_IDS.forEach(id => {
          const el = document.getElementById(id);
          if (el) el.style.removeProperty('order');
        });
      }
      function applyExpandedNavOrder(roleKey) {
        resetExpandedNavOrder();
        if (!roleKey) return;
        const order = EXPANDED_NAV_ORDER[roleKey];
        if (!order) return;
        order.forEach((wrapId, idx) => {
          const el = document.getElementById(wrapId);
          if (el) el.style.order = String(idx + 1);
        });
        // أخفِ أي قائمة تشغيل ليست ضمن ترتيب الدور (مثل الأساتذة للوكيلة)
        const allowed = new Set(order.concat(['navStaffCompactMoreWrap']));
        STAFF_NAV_ALL_OPS_WRAP_IDS.forEach(id => {
          if (allowed.has(id)) return;
          if (id === 'navHodCourseDeliveryWrap' && roleKey !== 'head_of_department') return;
          const el = document.getElementById(id);
          if (!el) return;
          // لا تُخفِ قوائم مخفية أصلاً بسبب الصلاحية؛ فقط غير المسموح في ترتيب الدور
          if (id === 'navFacultySupervisionWrap' && roleKey === 'academic_vice_dean') {
            el.style.display = 'none';
          }
          if (id === 'navAdminSettingsWrap' && roleKey === 'academic_vice_dean') {
            el.style.display = 'none';
          }
        });
      }
      function applyCompactNavOrder(roleKey) {
        resetExpandedNavOrder();
        if (!roleKey) return;
        const order = COMPACT_PRIMARY_ORDER[roleKey];
        if (!order) return;
        order.forEach((wrapId, idx) => {
          const el = document.getElementById(wrapId);
          if (el) el.style.order = String(idx + 1);
        });
      }
      function reorderMenuByIds(menuId, orderedIds) {
        const menu = document.getElementById(menuId);
        if (!menu || !orderedIds || !orderedIds.length) return;
        const orderedLis = [];
        orderedIds.forEach(id => {
          const node = document.getElementById(id);
          if (!node) return;
          const li = node.closest('li') || (node.tagName === 'LI' ? node : null);
          if (!li || li.parentElement !== menu) return;
          orderedLis.push(li);
        });
        orderedLis.forEach(li => menu.appendChild(li));
        Array.from(menu.children).forEach(li => {
          if (orderedLis.indexOf(li) === -1) menu.appendChild(li);
        });
      }
      function applyRoleDropdownOrders(roleKey) {
        // السجل: درجات التشغيل أولاً (الـ HTML أصلاً مرتّب؛ إعادة ضمان حسب الدور)
        if (roleKey === 'head_of_department') {
          reorderMenuByIds('academicRecordsMenuList', [
            'navHodFinalBatch', 'navGradeDrafts', 'navHodCourseDelivery', 'navTranscript',
            'navAcademicRecordsGradesDivider', 'navDeptReportsHeader',
            'navPerformance', 'navElectivesReport', 'navRegistrationChangesReport',
            'navFailedCoursesReport', 'navNotRegisteredCoursesReport', 'navUncompletedCoursesReport',
            'navGradeCourseAudit', 'navCourseRegistrationReport',
            'navAcademicRecordsReportsDivider', 'navAnalytics',
          ]);
        } else if (roleKey === 'college_dean' || roleKey === 'academic_vice_dean' || roleKey === 'admin_main') {
          reorderMenuByIds('academicRecordsMenuList', [
            'navDeanFinalBatches', 'navGradeDrafts', 'navTranscript',
            'navAcademicRecordsGradesDivider', 'navDeptReportsHeader',
            'navPerformance', 'navElectivesReport', 'navRegistrationChangesReport',
            'navFailedCoursesReport', 'navNotRegisteredCoursesReport', 'navUncompletedCoursesReport',
            'navGradeCourseAudit', 'navCourseRegistrationReport',
            'navAcademicRecordsReportsDivider', 'navAnalytics',
          ]);
        }
        reorderMenuByIds('studentAffairsMenuList', [
          'navStudents', 'navRegistrations', 'navEnrollmentPlans', 'navRegistrationRequests',
          'navAttendance', 'navGraduates', 'navWithdrawnFiles',
        ]);
        if (roleKey === 'admin_main') {
          reorderMenuByIds('adminSettingsMenuList', [
            'navUsersAdmin', 'navAdminBackup', 'navDepartmentPolicyApprovals',
            'navProjectStatus', 'navAcademicRules', 'navCollegeCatalog', 'navCollegeSharedCatalog',
          ]);
        } else if (roleKey === 'college_dean') {
          reorderMenuByIds('adminSettingsMenuList', [
            'navUsersAdmin', 'navDepartmentPolicyApprovals', 'navAcademicRules', 'navProjectStatus',
          ]);
        } else if (roleKey === 'head_of_department') {
          reorderMenuByIds('adminSettingsMenuList', [
            'navDepartmentPolicyHead', 'navCollegeSharedCatalog',
          ]);
        }
      }
      function staffWrapHasVisibleItems(wrapId) {
        const wrap = document.getElementById(wrapId);
        if (!wrap) return false;
        return Array.from(wrap.querySelectorAll('.dropdown-item')).some(it => it.style.display !== 'none');
      }
      function revealStaffSecondaryWrap(wrapId) {
        if (!staffWrapHasVisibleItems(wrapId)) return;
        const wrap = document.getElementById(wrapId);
        if (!wrap || useInstructorMore || isStudentUi) return;
        wrap.style.removeProperty('display');
        wrap.classList.remove('d-none');
      }
      function revealStaffNavSecondaryList(secondaryList) {
        (secondaryList || []).forEach(({ wrapId }) => revealStaffSecondaryWrap(wrapId));
      }
      function navItemVisible(el) {
        if (!el) return false;
        if (el.classList.contains('d-none')) return false;
        if (el.style.display === 'none') return false;
        const cs = window.getComputedStyle(el);
        return cs.display !== 'none' && cs.visibility !== 'hidden';
      }
      function buildStaffCompactMoreMenu(secondaryList) {
        const menu = document.getElementById('navStaffCompactMoreMenu');
        if (!menu) return false;
        menu.innerHTML = '';
        let sections = 0;
        (secondaryList || getStaffNavSecondary()).forEach(({ wrapId, header }) => {
          const wrap = document.getElementById(wrapId);
          if (!wrap) return;
          const items = Array.from(wrap.querySelectorAll('.dropdown-item')).filter(it => {
            // لا تعتمد على computed للأب المخفي؛ استخدم style مباشرة
            if (it.classList.contains('d-none')) return false;
            if (it.style.display === 'none') return false;
            return true;
          });
          if (!items.length) return;
          if (sections > 0) {
            const hr = document.createElement('li');
            hr.innerHTML = '<hr class="dropdown-divider">';
            menu.appendChild(hr);
          }
          const hdr = document.createElement('li');
          hdr.innerHTML = '<h6 class="dropdown-header">' + header + '</h6>';
          menu.appendChild(hdr);
          items.forEach(src => {
            const li = document.createElement('li');
            const a = document.createElement('a');
            a.className = 'dropdown-item';
            a.href = src.getAttribute('href') || '#';
            a.innerHTML = src.innerHTML;
            if (src.target) a.target = src.target;
            li.appendChild(a);
            menu.appendChild(li);
          });
          sections += 1;
        });
        return sections > 0;
      }
      function staffNavDensityStorageKey() {
        const u = (data.user || 'default').toString().trim() || 'default';
        return 'so_staff_nav_density_' + u;
      }
      function updateNavDensityToggleUi(mode) {
        const compactBtn = document.getElementById('navDensityCompactBtn');
        const expandedBtn = document.getElementById('navDensityExpandedBtn');
        if (compactBtn) compactBtn.classList.toggle('active', mode === 'compact');
        if (expandedBtn) expandedBtn.classList.toggle('active', mode === 'expanded');
      }
      /** يمنع تكرار التسمية: واحدة فقط ظاهرة (كاملة أو قصيرة) */
      function applyNavLabelVisibility(useShort) {
        document.querySelectorAll('.app-navbar .nav-label-short').forEach(el => {
          el.hidden = !useShort;
          el.style.setProperty('display', useShort ? 'inline' : 'none', 'important');
        });
        document.querySelectorAll('.app-navbar .nav-label-full').forEach(el => {
          el.hidden = !!useShort;
          el.style.setProperty('display', useShort ? 'none' : 'inline', 'important');
        });
      }
      function applyStaffNavDensity(mode, persist) {
        const navBar = document.querySelector('.app-navbar');
        const moreWrap = document.getElementById('navStaffCompactMoreWrap');
        if (!navBar || !moreWrap) return;
        const roleKey = getExpandedNavRoleKey();
        const secondaryList = getStaffNavSecondary();
        applyQualityNavTier(roleKey);
        applyRoleDropdownOrders(roleKey);
        const compact = mode === 'compact';
        navBar.classList.remove('nav-staff-expanded');
        resetExpandedNavOrder();
        if (compact) {
          revealStaffNavSecondaryList(secondaryList);
          // الجودة primary للقيادات + رئيس القسم: ظاهرة خارج «المزيد»
          if (QUALITY_PRIMARY_ROLES.has(roleKey)) {
            revealStaffSecondaryWrap('navQualityAccreditationWrap');
          }
          const hasItems = buildStaffCompactMoreMenu(secondaryList);
          if (hasItems) {
            navBar.classList.add('nav-staff-compact');
            moreWrap.classList.remove('d-none');
            moreWrap.style.removeProperty('display');
            applyCompactNavOrder(roleKey);
          } else {
            navBar.classList.remove('nav-staff-compact');
            moreWrap.classList.add('d-none');
            moreWrap.style.display = 'none';
            revealStaffNavSecondaryList(secondaryList);
            if (QUALITY_PRIMARY_ROLES.has(roleKey)) {
              revealStaffSecondaryWrap('navQualityAccreditationWrap');
            }
            if (isStaffOpsNav && !useInstructorMore && !isStudentUi) {
              navBar.classList.add('nav-staff-expanded');
              applyExpandedNavOrder(roleKey);
            }
            updateNavDensityToggleUi('expanded');
          }
        } else {
          navBar.classList.remove('nav-staff-compact');
          moreWrap.classList.add('d-none');
          moreWrap.style.display = 'none';
          revealStaffNavSecondaryList(secondaryList);
          if (QUALITY_PRIMARY_ROLES.has(roleKey)) {
            revealStaffSecondaryWrap('navQualityAccreditationWrap');
          }
          if (isStaffOpsNav && !useInstructorMore && !isStudentUi) {
            navBar.classList.add('nav-staff-expanded');
            applyExpandedNavOrder(roleKey);
          }
        }
        const effectiveMode = (compact && navBar.classList.contains('nav-staff-compact')) ? 'compact' : 'expanded';
        applyNavLabelVisibility(effectiveMode === 'expanded');
        updateNavDensityToggleUi(effectiveMode);
        if (persist) {
          try { localStorage.setItem(staffNavDensityStorageKey(), mode); } catch (_e) { /* ignore */ }
        }
        if (typeof window.initNavDropdowns === 'function') window.initNavDropdowns();
      }
      // كشف أولي للقوائم الثانوية قبل تفعيل الكثافة
      if (isStaffOpsNav && !useInstructorMore && !isStudentUi) {
        revealStaffNavSecondaryList(getStaffNavSecondary());
        const rk0 = getExpandedNavRoleKey();
        applyQualityNavTier(rk0);
        if (QUALITY_PRIMARY_ROLES.has(rk0)) {
          revealStaffSecondaryWrap('navQualityAccreditationWrap');
        }
      }
      if (isStaffOpsNav) {
        const toggleWrap = document.getElementById('navDensityToggleWrap');
        if (toggleWrap) toggleWrap.classList.remove('d-none');
        let densityMode = 'compact';
        try {
          const saved = localStorage.getItem(staffNavDensityStorageKey());
          if (saved === 'compact' || saved === 'expanded') densityMode = saved;
        } catch (_e) { /* ignore */ }
        applyStaffNavDensity(densityMode, false);
        const compactBtn = document.getElementById('navDensityCompactBtn');
        const expandedBtn = document.getElementById('navDensityExpandedBtn');
        if (compactBtn) {
          compactBtn.addEventListener('click', function () {
            applyStaffNavDensity('compact', true);
          });
        }
        if (expandedBtn) {
          expandedBtn.addEventListener('click', function () {
            applyStaffNavDensity('expanded', true);
          });
        }
      }
      if (isStudentUi) enforceStudentNavShell();
      else if (useInstructorMore) {
        enforceInstructorNavShell();
        applyInstructorConditionalExtras();
      }
      else if (supervisorSlimNav || (showSupervisorPortalMenu && inSupervisorPortal)) enforceSupervisorNavShell();
      else hideStudentNavShell();

      // تفعيل الرابط الحالي (Active state) حسب المسار
      const path = (window.location.pathname || '/').toLowerCase();
      const map = [
        ['/my_courses','navMyCourses'],
        ['/supervisor_dashboard','navSupervisorPortal'],
        ['/academic_quality/supervisor/quality-hub','navSupervisorSurveys'],
        ['/academic_quality/surveys','navSupervisorSurveys'],
        ['/supervisor_quality_report_page','navSupQualityReport'],
        ['/supervisors/summary.pdf','navSupSummaryPdf'],
        ['/my_schedule','navInsMySchedule'],
        ['/my_exams','navInsMyExams'],
        ['/my_attendance','navInsMyAttendance'],
        ['/instructor_library','navInsLibrary'],
        ['/schedule_form','navInsSchedule'],
        ['/academic_calendar_page','navInsCalendar'],
        ['/exams/midterms','navInsMidterms'],
        ['/exams/finals','navInsFinals'],
        ['/attendance_export','navInsAttendance'],
        ['/supervisor_dashboard','navInsSupervisor'],
        ['/grade_drafts','navInstructorGradeDrafts'],
        ['/grade_drafts','navGradeDrafts'],
        ['/course_delivery_hod_page','navHodCourseDeliveryTop'],
        ['/course_delivery_hod_page','navHodCourseDelivery'],
        ['/course_delivery_hod_page','navHodCourseDeliveryFaculty'],
        ['/dashboard','navDashboard'],
        ['/analytics','navAnalytics'],
        ['/academic_calendar_page','navAcademicCalendar'],
        ['/students_form','navStudents'],
        ['/graduates_page','navGraduates'],
        ['/courses_form','navCourses'],
        ['/instructors_form','navInstructors'],
        ['/supervision_form','navSupervision'],
        ['/prereqs_form','navPrereqs'],
        ['/prereqs_flowchart','navPrereqsFlowchart'],
        ['/registrations_form','navRegistrations'],
        ['/withdrawn_file_list','navWithdrawnFiles'],
        ['/enrollment_plans','navEnrollmentPlans'],
        ['/schedule_form','navScheduleForm'],
        ['/attendance_export','navAttendance'],
        ['/my_attendance','navInsMyAttendance'],
        ['/exams/midterms','navExamsMidterms'],
        ['/exams/finals','navExamsFinals'],
        ['/exams/conflicts','navExamsConflicts'],
        ['/transcript_page','navTranscript'],
        ['/grade_drafts','navGradeDrafts'],
        ['/not_registered_courses_report_page','navNotRegisteredCoursesReport'],
        ['/grade_course_mapping_audit_page','navGradeCourseAudit'],
        ['/course_registration_report_page','navCourseRegistrationReport'],
        ['/schedule_versions_page','navScheduleVersions'],
        ['/exam_schedule_versions_page','navExamScheduleVersions'],
        ['/performance_report','navPerformance'],
        ['/supervisor_dashboard','navSupervisorDashboard'],
        ['/course_closure_reports_page','navCourseClosureReports'],
        ['/faculty_scorecards_page','navFacultyScorecards'],
        ['/faculty_final_dossier_page','navFacultyFinalDossier'],
        ['/academic_quality/dashboard','navAcademicQuality'],
        ['/academic_quality/accreditation/map','navAccreditationMap'],
        ['/academic_quality/accreditation/map?scope=prog','navAccreditationMapProg'],
        ['/academic_quality/archive','navDeptArchive'],
        ['/academic_quality/college-archive','navCollegeArchive'],
        ['/academic_quality/archive/shared','navArchiveShared'],
        ['/academic_quality/archive/guide','navDeptArchiveGuide'],
        ['/academic_quality/assistant','navQualityAssistant'],
        ['/academic_quality/assistant/knowledge','navQualityKnowledge'],
        ['/academic_quality/survey_admin','navEvaluationSurveyAdmin'],
        ['/academic_quality/surveys','navSurveysHub'],
        ['/academic_quality/instructor/quality-hub','navInsQualityHub'],
        ['/academic_quality/assistant?mode=instructor','navInsQualityAssistant'],
        ['/academic_quality/surveys/fill','navInsQualityHub'],
        ['/academic_quality/ilo/outcomes-map','navInsIloCatalog'],
        ['/academic_quality/ilo/catalog','navInsIloCatalog'],
        ['/academic_quality/ilo/student/learning-outcomes','navInsStudentLo'],
        ['/academic_quality/surveys/results','navSurveysResults'],
        ['/academic_quality/course_reports','navCourseQualityCollege'],
        ['/course_quality_college_page','navCourseQualityCollege'],
        ['/academic_quality/term_closure','navTermClosure'],
        ['/term_ops','navTermOps'],
        ['/term_offerings','navTermOfferings'],
        ['/academic_quality/surveys/completion','navSurveysCompletion'],
        ['/academic_quality/surveys/trends','navSurveysTrends'],
        ['/academic_quality/surveys/invites','navSurveysInvites'],
        ['/my_portal','navStudentPortal'],
        ['/my_schedule','navStudentSchedule'],
        ['/my_exams','navStudentExams'],
        ['/my_transcript','navStudentTranscript'],
        ['/my_announcements','navStudentAnnouncements'],
        ['/my_requests','navStudentRequests'],
        ['/academic_quality/student/identity','navStudentIdentity'],
        ['/students/evaluations','navStudentEvaluations'],
        ['/academic_quality/surveys','navStudentSurveys'],
        ['/academic_quality/ilo/student/learning-outcomes','navStudentLearningOutcomes'],
        ['/academic_quality/student/progress','navStudentProgress'],
        ['/academic_quality/glossary','navStudentGlossary'],
        ['/my_registrations','navStudentRegistrations'],
        ['/academic_quality/college','navCollegeProfile'],
        ['/academic_quality/programs','navProgramsPortal'],
        ['/ilo_catalog_page','navIloCatalog'],
        ['/academic_quality/ilo/catalog','navIloCatalog'],
        ['/supervisor_quality_report_page','navSupervisorQualityReport'],
        ['/results','navResults'],
        ['/notifications_center','navNotificationsTop'],
        ['/users_admin','navUsersAdmin'],
        ['/department_policy_head_page','navDepartmentPolicyHead'],
        ['/department_policy_approvals_page','navDepartmentPolicyApprovals'],
        ['/admin/project_status','navProjectStatus'],
        ['/admin/backup_page','navAdminBackup'],
        ['/academic_rules_page','navAcademicRules'],
        ['/college_catalog_page','navCollegeCatalog'],
        ['/college_catalog_page','navCollegeCatalogCourses'],
        ['/college_shared_catalog_page','navCollegeSharedCatalog'],
        ['/college_shared_catalog_page','navCollegeSharedCatalogCourses'],
      ];
      const urlScope = new URL(window.location.href).searchParams.get('scope') || '';
      const accredProgActive = path.startsWith('/academic_quality/accreditation/map') && urlScope === 'prog';
      map.forEach(([prefix, id])=>{
        if (prefix === '/academic_quality/accreditation/map?scope=prog') {
          if (!accredProgActive) return;
        } else if (prefix === '/academic_quality/accreditation/map') {
          if (accredProgActive) return;
        }
        if (path === prefix || (prefix !== '/' && path.startsWith(prefix.split('?')[0]))) {
          const el = document.getElementById(id);
          if (el) {
            el.classList.add('active');
            const qWrap = document.getElementById('navQualityAccreditationWrap');
            if (qWrap && qWrap.contains(el)) {
              const qToggle = qWrap.querySelector('.dropdown-toggle');
              if (qToggle) qToggle.classList.add('active');
            }
            const parentWrap = el.closest('.nav-item.dropdown');
            if (parentWrap) {
              const parentToggle = parentWrap.querySelector('.dropdown-toggle');
              if (parentToggle) parentToggle.classList.add('active');
            }
          }
        }
      });

      // تمييز الرابط النشط داخل «المزيد — إدارة» (وضع مدمج)
      if (document.querySelector('.app-navbar.nav-staff-compact')) {
        document.querySelectorAll('#navStaffCompactMoreMenu .dropdown-item[href]').forEach(a => {
          const raw = (a.getAttribute('href') || '').toLowerCase();
          if (!raw || raw === '#') return;
          if (raw.includes('scope=prog') && !accredProgActive) return;
          if (raw.startsWith('/academic_quality/accreditation/map') && !raw.includes('scope=prog') && accredProgActive) return;
          const hp = raw.split('?')[0];
          const match = path === hp || (hp !== '/' && path.startsWith(hp));
          if (match) {
            a.classList.add('active');
            const moreToggle = document.querySelector('#navStaffCompactMoreWrap .dropdown-toggle');
            if (moreToggle) moreToggle.classList.add('active');
          }
        });
      }

      // تنبيه تغيير الجدول — غير حرج؛ يُحمَّل بعد اكتمال الشريط
      setTimeout(async () => {
      try {
        const metaResp = await fetch('/schedule/meta', { credentials: 'include' });
        const meta = await metaResp.json().catch(()=>null);
        const banner = document.getElementById('scheduleChangeBanner');
        const updatedEl = document.getElementById('scheduleUpdatedAt');
        if (banner && meta && meta.published && meta.changed_since_publish) {
          if (updatedEl) updatedEl.textContent = meta.updated_at || '—';
          banner.classList.remove('d-none');
        } else if (banner) {
          banner.classList.add('d-none');
        }
      } catch(e) {
        // تجاهل أي خطأ في عرض التنبيه
      }
      }, 0);
      window.showLoading = function() {
        var el = document.getElementById('loadingOverlay');
        if (el) { el.classList.add('active'); el.setAttribute('aria-hidden', 'false'); }
      };
      window.hideLoading = function() {
        var el = document.getElementById('loadingOverlay');
        if (el) { el.classList.remove('active'); el.setAttribute('aria-hidden', 'true'); }
      };
      if (typeof window.cleanupUiBlockers === 'function') window.cleanupUiBlockers();
      if (typeof window.initNavDropdowns === 'function') window.initNavDropdowns();
      document.documentElement.classList.remove('nav-shell-student-pending', 'nav-shell-instructor-pending', 'nav-shell-supervisor-pending');

      // Fallback: قوائم منسدلة يدوياً فقط إذا Bootstrap غير متاح
      try {
        if (!(window.bootstrap && typeof window.bootstrap.Dropdown !== 'undefined')) {
          const toggles = document.querySelectorAll('.navbar .dropdown-toggle');
          const closeAll = () => {
            document.querySelectorAll('.navbar .dropdown-menu.show').forEach(m => m.classList.remove('show'));
            document.querySelectorAll('.navbar .dropdown-toggle[aria-expanded="true"]').forEach(t => t.setAttribute('aria-expanded', 'false'));
          };
          toggles.forEach(toggle => {
            toggle.addEventListener('click', function(ev){
              ev.preventDefault();
              ev.stopPropagation();
              const menu = this.parentElement ? this.parentElement.querySelector('.dropdown-menu') : null;
              if(!menu) return;
              const isOpen = menu.classList.contains('show');
              closeAll();
              if(!isOpen){
                menu.classList.add('show');
                this.setAttribute('aria-expanded', 'true');
              }
            });
          });
          document.addEventListener('click', function(){ closeAll(); });
        }
      } catch(e) {
        // ignore dropdown fallback errors
      }
    } catch (error) {
      console.error('Auth check error:', error);
      // في حالة الخطأ، توجيه المستخدم لصفحة تسجيل الدخول
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runNavAuthCheck);
  } else {
    runNavAuthCheck();
  }
