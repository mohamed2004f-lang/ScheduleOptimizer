/**
 * Page Hints System
 * - Context Hints: dismissible info boxes (data-hint)
 * - Tab Tooltips: hover descriptions on tabs (data-tab-tip)
 * - Axis Explainer: popover explaining the 6 axes (data-axis-info)
 *
 * Uses localStorage to remember dismissed hints.
 * Adapts to user role via data-for-role attribute.
 */
(function () {
  'use strict';

  var STORAGE_PREFIX = 'ph_dismissed_';

  function isDismissed(key) {
    try { return localStorage.getItem(STORAGE_PREFIX + key) === '1'; } catch (e) { return false; }
  }
  function dismiss(key) {
    try { localStorage.setItem(STORAGE_PREFIX + key, '1'); } catch (e) {}
  }

  function getUserRole() {
    try {
      var cached = sessionStorage.getItem('pg_user_role');
      if (cached) return cached;
    } catch (e) {}
    return '';
  }

  // === Context Hints ===
  function initContextHints() {
    var role = getUserRole();
    var hints = document.querySelectorAll('[data-hint]');
    hints.forEach(function (el) {
      var forRole = el.getAttribute('data-for-role');
      if (forRole && role && forRole.indexOf(role) === -1) {
        el.style.display = 'none';
        return;
      }
      var hintId = el.getAttribute('data-hint-id') || el.getAttribute('data-hint').substring(0, 30);
      if (isDismissed(hintId)) { el.style.display = 'none'; return; }

      var icon = el.getAttribute('data-hint-icon') || '\uD83D\uDCA1';
      var text = el.getAttribute('data-hint');

      var card = document.createElement('div');
      card.className = 'ctx-hint';
      card.innerHTML =
        '<span class="hint-icon">' + icon + '</span>' +
        '<span class="hint-text">' + text + '</span>' +
        '<button class="hint-close" title="\u0625\u063a\u0644\u0627\u0642">&times;</button>';

      card.querySelector('.hint-close').addEventListener('click', function () {
        card.style.opacity = '0';
        card.style.transform = 'translateY(-6px)';
        setTimeout(function () { card.remove(); }, 200);
        dismiss(hintId);
      });

      el.parentNode.insertBefore(card, el);
    });
  }

  // === Tab Tooltips ===
  function initTabTooltips() {
    var tabs = document.querySelectorAll('[data-tab-tip]');
    tabs.forEach(function (tab) {
      var tip = tab.getAttribute('data-tab-tip');
      if (!tip) return;

      var wrapper = document.createElement('span');
      wrapper.className = 'tab-tip-wrapper';
      tab.parentNode.insertBefore(wrapper, tab);
      wrapper.appendChild(tab);

      var bubble = document.createElement('span');
      bubble.className = 'tab-tip-bubble';
      bubble.textContent = tip;
      wrapper.appendChild(bubble);
    });
  }

  // === Axis Explainer ===
  function initAxisExplainer() {
    var triggers = document.querySelectorAll('[data-axis-info]');
    triggers.forEach(function (container) {
      var btn = document.createElement('button');
      btn.className = 'axis-explainer-btn';
      btn.textContent = '?';
      btn.title = '\u0634\u0631\u062d \u0627\u0644\u0645\u062d\u0627\u0648\u0631';
      btn.type = 'button';

      var pop = document.createElement('div');
      pop.className = 'axis-explainer-pop';
      pop.innerHTML =
        '<h6>\u0627\u0644\u0645\u062d\u0627\u0648\u0631 \u0627\u0644\u0633\u062a</h6>' +
        '<table>' +
        '<tr><td>\uD83D\uDCCB</td><td>\u0625\u062f\u0627\u0631\u0629 \u0627\u0644\u0645\u0642\u0631\u0631 \u2014 \u062a\u0648\u0635\u064a\u0641\u060c \u0645\u0641\u0631\u062f\u0627\u062a\u060c \u062a\u062d\u0636\u064a\u0631</td></tr>' +
        '<tr><td>\uD83D\uDCDA</td><td>\u0627\u0644\u062a\u062f\u0631\u064a\u0633 \u0648\u0627\u0644\u0645\u062d\u062a\u0648\u0649 \u2014 \u062a\u0646\u0641\u064a\u0630 \u0627\u0644\u0645\u062d\u0627\u0636\u0631\u0627\u062a</td></tr>' +
        '<tr><td>\uD83D\uDCDD</td><td>\u0627\u0644\u062a\u0642\u064a\u064a\u0645 \u0648\u0627\u0644\u0627\u062e\u062a\u0628\u0627\u0631\u0627\u062a \u2014 \u0625\u0639\u062f\u0627\u062f \u0648\u062a\u0635\u062d\u064a\u062d \u0648\u0631\u0635\u062f</td></tr>' +
        '<tr><td>\uD83D\uDCAC</td><td>\u0627\u0644\u062a\u0648\u0627\u0635\u0644 \u0648\u0627\u0644\u0625\u0634\u0631\u0627\u0641 \u2014 \u0633\u0627\u0639\u0627\u062a \u0645\u0643\u062a\u0628\u064a\u0629\u060c \u0625\u0631\u0634\u0627\u062f</td></tr>' +
        '<tr><td>\uD83D\uDCC2</td><td>\u0627\u0644\u062a\u0648\u062b\u064a\u0642 \u0648\u0627\u0644\u062c\u0648\u062f\u0629 \u2014 \u0645\u0644\u0641 \u0627\u0644\u0645\u0642\u0631\u0631\u060c \u062a\u062d\u0633\u064a\u0646 \u0645\u0633\u062a\u0645\u0631</td></tr>' +
        '<tr><td>\uD83C\uDFAF</td><td>\u0627\u0644\u0623\u0646\u0634\u0637\u0629 \u0627\u0644\u0625\u0636\u0627\u0641\u064a\u0629 \u2014 \u0644\u062c\u0627\u0646\u060c \u0628\u062d\u062b\u060c \u062e\u062f\u0645\u0629 \u0645\u062c\u062a\u0645\u0639</td></tr>' +
        '</table>' +
        '<div class="badge-cycle mt-2">' +
        '<span>\u0622\u0644\u064a\u0629 \u0627\u0644\u0646\u0642\u0631:</span> ' +
        '<span style="background:#fff3cd;color:#664d03;">\u0642\u064a\u062f \u0627\u0644\u0645\u062a\u0627\u0628\u0639\u0629</span> \u2192 ' +
        '<span style="background:#d1e7dd;color:#0f5132;">\u0645\u0646\u062c\u0632</span> \u2192 ' +
        '<span style="background:#e9ecef;color:#6c757d;">\u0644\u0627 \u064a\u0646\u0637\u0628\u0642</span>' +
        '</div>';

      container.style.position = 'relative';
      container.insertBefore(btn, container.firstChild);
      container.appendChild(pop);

      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        pop.classList.toggle('show');
      });
      document.addEventListener('click', function (e) {
        if (!pop.contains(e.target) && e.target !== btn) {
          pop.classList.remove('show');
        }
      });
    });
  }

  // Boot
  function boot() {
    initContextHints();
    initTabTooltips();
    initAxisExplainer();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  // Public API
  window.PageHints = {
    resetAll: function () {
      try {
        Object.keys(localStorage).forEach(function (k) {
          if (k.startsWith(STORAGE_PREFIX)) localStorage.removeItem(k);
        });
      } catch (e) {}
    },
    reset: function (hintId) {
      try { localStorage.removeItem(STORAGE_PREFIX + hintId); } catch (e) {}
    }
  };
})();
