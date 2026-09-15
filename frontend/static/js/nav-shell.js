(function initNavShell() {
  function cleanupUiBlockers() {
    var lo = document.getElementById('loadingOverlay');
    if (lo) {
      lo.classList.remove('active');
      lo.setAttribute('aria-hidden', 'true');
    }
    document.querySelectorAll('.modal-backdrop').forEach(function (el) { el.remove(); });
    document.body.classList.remove('modal-open');
    document.body.style.removeProperty('overflow');
    document.body.style.removeProperty('padding-right');
  }
  function initNavDropdowns() {
    if (!window.bootstrap || typeof window.bootstrap.Dropdown === 'undefined') return;
    document.querySelectorAll('.app-navbar [data-bs-toggle="dropdown"]').forEach(function (el) {
      try {
        var existing = bootstrap.Dropdown.getInstance(el);
        if (existing) existing.dispose();
        bootstrap.Dropdown.getOrCreateInstance(el);
      } catch (_e) { /* ignore */ }
    });
  }
  window.cleanupUiBlockers = cleanupUiBlockers;
  window.initNavDropdowns = initNavDropdowns;
  function onReady() {
    cleanupUiBlockers();
    initNavDropdowns();
    if (typeof window.initTheme === 'function') window.initTheme();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', onReady);
  } else {
    onReady();
  }
  // بعد اكتمال كل السكربتات (يشمل صفحات كانت تعيد تحميل Bootstrap بالخطأ)
  window.addEventListener('load', function () {
    cleanupUiBlockers();
    initNavDropdowns();
  });
  window.addEventListener('pageshow', function () {
    cleanupUiBlockers();
    initNavDropdowns();
  });
})();
