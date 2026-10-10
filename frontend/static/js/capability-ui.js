/**
 * واجهة موحدة لفحص صلاحيات التشغيل (fail-closed).
 * لا يُسمح بالتعديل إلا إذا كان المفتاح === true صراحة.
 */
(function (global) {
  'use strict';

  function hasCap(caps, key) {
    return !!(caps && caps[key] === true);
  }

  function isLeadershipOpsMode(role, activeMode) {
    const r = String(role || '').trim().toLowerCase();
    const am = String(activeMode || '').trim().toLowerCase();
    if (r === 'college_dean') return am === '' || am === 'dean';
    if (r === 'academic_vice_dean') return am === '' || am === 'vice_dean' || am === 'dean';
    return false;
  }

  /**
   * هل الصفحة في وضع عرض فقط لمفتاح تشغيل معيّن؟
   * - المشرف الفعّال: ليس عرض-فقط عاماً (نطاق طلبته)
   * - وإلا: لا تعديل ما لم يُمنَح المفتاح صراحة
   */
  function isOpsViewOnly(caps, key, opts) {
    const o = opts || {};
    if (o.supervisorBypass && caps && caps.is_supervisor_effective) return false;
    if (hasCap(caps, key)) return false;
    return true;
  }

  function hideEl(el) {
    if (!el) return;
    el.style.display = 'none';
    el.setAttribute('hidden', '');
  }

  function disableForm(root) {
    if (!root) return;
    root.querySelectorAll('input, button, select, textarea').forEach(function (x) {
      x.disabled = true;
    });
  }

  global.CapabilityUI = {
    has: hasCap,
    isLeadershipOpsMode: isLeadershipOpsMode,
    isOpsViewOnly: isOpsViewOnly,
    hideEl: hideEl,
    disableForm: disableForm,
  };
})(typeof window !== 'undefined' ? window : globalThis);
