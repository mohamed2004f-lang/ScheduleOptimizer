/**
 * مكوّن اختيار الفصل + العام الدراسي الموحّد.
 * يعتمد على /admin/settings/term_options و /admin/settings/parse_term
 */
(function (global) {
  'use strict';

  const CACHE = { options: null, promise: null };

  function requestHeaders(extra) {
    const h = Object.assign({ Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, extra || {});
    try {
      if (global.__CSRF_TOKEN__) h['X-CSRFToken'] = global.__CSRF_TOKEN__;
    } catch (_e) {}
    return h;
  }

  async function fetchTermOptions(force) {
    if (!force && CACHE.options) return CACHE.options;
    if (!force && CACHE.promise) return CACHE.promise;
    CACHE.promise = fetch('/admin/settings/term_options', {
      credentials: 'same-origin',
      headers: requestHeaders(),
    })
      .then((r) => r.json().then((j) => ({ ok: r.ok, json: j })))
      .then((r) => {
        if (!r.ok || !r.json || r.json.status === 'error') {
          throw new Error((r.json && r.json.message) || 'تعذر تحميل خيارات الفصل');
        }
        CACHE.options = r.json;
        CACHE.promise = null;
        return r.json;
      })
      .catch((err) => {
        CACHE.promise = null;
        throw err;
      });
    return CACHE.promise;
  }

  function fillYearSelect(sel, years, selected, allowEmpty) {
    if (!sel) return;
    const cur = selected || sel.value || '';
    const list = Array.isArray(years) ? years.slice() : [];
    if (cur && list.indexOf(cur) < 0) list.unshift(cur);
    const emptyLabel = allowEmpty ? '— الكل / فارغ —' : '— اختر العام —';
    sel.innerHTML = `<option value="">${emptyLabel}</option>` +
      list.map((y) => `<option value="${String(y).replace(/"/g, '&quot;')}">${y}</option>`).join('');
    if (cur) sel.value = cur;
  }

  function normalizeSeasonAr(raw) {
    const s = String(raw || '').trim();
    if (!s) return '';
    if (s === 'خريف' || s === 'ربيع') return s;
    if (/fall|خريف|autumn/i.test(s)) return 'خريف';
    if (/spring|ربيع/i.test(s)) return 'ربيع';
    return s;
  }

  /**
   * @param {object} opts
   * @param {string} [opts.rootId]
   * @param {string} [opts.seasonId]
   * @param {string} [opts.yearId]
   * @param {string} [opts.termName]
   * @param {string} [opts.termYear]
   * @param {boolean} [opts.disabled]
   * @param {boolean} [opts.useCurrent]
   */
  async function mountTermYearPicker(opts) {
    opts = opts || {};
    const root = opts.rootId ? document.getElementById(opts.rootId) : null;
    const seasonId = opts.seasonId || (root && root.getAttribute('data-season-id')) || '';
    const yearId = opts.yearId || (root && root.getAttribute('data-year-id')) || '';
    const seasonEl = document.getElementById(seasonId);
    const yearEl = document.getElementById(yearId);
    if (!seasonEl || !yearEl) {
      throw new Error('term-year-picker: season/year elements missing');
    }

    const allowEmpty = !!opts.allowEmpty;
    if (allowEmpty && !Array.from(seasonEl.options).some((o) => o.value === '')) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = '— الكل —';
      seasonEl.insertBefore(opt, seasonEl.firstChild);
    }

    const data = await fetchTermOptions(!!opts.forceReload);
    const years = data.academic_years || [];
    const cur = data.current || {};

    let wantSeason = normalizeSeasonAr(opts.termName);
    let wantYear = (opts.termYear || '').trim();
    if (opts.useCurrent || (!allowEmpty && !wantSeason && !wantYear)) {
      wantSeason = wantSeason || normalizeSeasonAr(cur.term_name);
      wantYear = wantYear || (cur.term_year || '');
    }
    if (opts.opsLabel) {
      const parts = String(opts.opsLabel).trim().split(/\s+/);
      if (parts.length >= 2) {
        wantSeason = wantSeason || normalizeSeasonAr(parts[0]);
        wantYear = wantYear || parts.slice(1).join(' ');
      }
    }

    fillYearSelect(yearEl, years, wantYear, allowEmpty);
    if (wantSeason === 'خريف' || wantSeason === 'ربيع') seasonEl.value = wantSeason;
    else if (allowEmpty) seasonEl.value = '';
    if (wantYear) yearEl.value = wantYear;

    const disabled = !!opts.disabled;
    seasonEl.disabled = disabled;
    yearEl.disabled = disabled;

    const hiddenEl = opts.hiddenId ? document.getElementById(opts.hiddenId) : null;
    const syncHidden = () => {
      if (!hiddenEl) return;
      const term_name = normalizeSeasonAr(seasonEl.value);
      const term_year = (yearEl.value || '').trim();
      hiddenEl.value = term_name && term_year ? `${term_name} ${term_year}` : '';
    };
    seasonEl.addEventListener('change', syncHidden);
    yearEl.addEventListener('change', syncHidden);
    syncHidden();

    return {
      seasonEl,
      yearEl,
      hiddenEl,
      options: data,
      getValue() {
        const term_name = normalizeSeasonAr(seasonEl.value);
        const term_year = (yearEl.value || '').trim();
        return {
          term_name,
          term_year,
          ops_label: term_name && term_year ? `${term_name} ${term_year}` : '',
        };
      },
      setValue(termName, termYear) {
        const s = normalizeSeasonAr(termName);
        const y = (termYear || '').trim();
        if (s === 'خريف' || s === 'ربيع') seasonEl.value = s;
        else if (allowEmpty) seasonEl.value = '';
        if (y) {
          fillYearSelect(yearEl, years, y, allowEmpty);
          yearEl.value = y;
        } else if (allowEmpty) {
          yearEl.value = '';
        }
        syncHidden();
      },
      setFromOpsLabel(label) {
        const parts = String(label || '').trim().split(/\s+/);
        if (parts.length >= 2) this.setValue(parts[0], parts.slice(1).join(' '));
        else if (allowEmpty) this.setValue('', '');
        else syncHidden();
      },
      setDisabled(flag) {
        seasonEl.disabled = !!flag;
        yearEl.disabled = !!flag;
      },
      syncHidden,
      async parse() {
        const v = this.getValue();
        if (!v.term_name || !v.term_year) {
          if (allowEmpty) return { term_name: '', term_year: '', ops_label: '' };
          throw new Error('اختر الفصل والعام الدراسي');
        }
        const r = await fetch('/admin/settings/parse_term', {
          method: 'POST',
          credentials: 'same-origin',
          headers: requestHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify(v),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.status === 'error') {
          throw new Error(j.message || 'فصل/عام غير صالح');
        }
        if (hiddenEl) hiddenEl.value = j.ops_label || '';
        return j;
      },
    };
  }

  /** حوار بسيط لاختيار فصل+عام (للأدمن الرئيسي عند تعديل سجل). */
  function openTermYearDialog(opts) {
    opts = opts || {};
    return new Promise(async (resolve, reject) => {
      let overlay;
      try {
        const data = await fetchTermOptions();
        if (opts.opsLabel && !opts.termName) {
          const parts = String(opts.opsLabel).trim().split(/\s+/);
          if (parts.length >= 2) {
            opts.termName = parts[0];
            opts.termYear = parts.slice(1).join(' ');
          }
        }
        overlay = document.createElement('div');
        overlay.style.cssText =
          'position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:2000;display:flex;align-items:center;justify-content:center;padding:1rem;';
        const box = document.createElement('div');
        box.className = 'card shadow';
        box.style.cssText = 'max-width:420px;width:100%;';
        const title = opts.title || 'اختيار الفصل الدراسي';
        const hint = opts.hint || 'اختر الفصل والعام الدراسي بصيغة 2025/2026';
        box.innerHTML =
          `<div class="card-header fw-semibold">${title}</div>` +
          `<div class="card-body">` +
          `<p class="small text-muted">${hint}</p>` +
          `<div class="mb-2"><label class="form-label small">الفصل</label>` +
          `<select id="typDlgSeason" class="form-select form-select-sm">` +
          `<option value="خريف">خريف</option><option value="ربيع">ربيع</option></select></div>` +
          `<div class="mb-3"><label class="form-label small">العام الدراسي</label>` +
          `<select id="typDlgYear" class="form-select form-select-sm" dir="ltr"></select></div>` +
          `<div class="d-flex gap-2 justify-content-end">` +
          `<button type="button" class="btn btn-outline-secondary btn-sm" data-act="cancel">إلغاء</button>` +
          `<button type="button" class="btn btn-primary btn-sm" data-act="ok">تأكيد</button>` +
          `</div></div>`;
        overlay.appendChild(box);
        document.body.appendChild(overlay);

        const seasonEl = box.querySelector('#typDlgSeason');
        const yearEl = box.querySelector('#typDlgYear');
        const cur = data.current || {};
        const wantSeason = normalizeSeasonAr(opts.termName || cur.term_name) || 'خريف';
        const wantYear = (opts.termYear || cur.term_year || '').trim();
        fillYearSelect(yearEl, data.academic_years || [], wantYear);
        seasonEl.value = wantSeason === 'ربيع' ? 'ربيع' : 'خريف';
        if (wantYear) yearEl.value = wantYear;

        const close = (val) => {
          try { overlay.remove(); } catch (_e) {}
          resolve(val);
        };
        box.querySelector('[data-act="cancel"]').onclick = () => close(null);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(null); });
        box.querySelector('[data-act="ok"]').onclick = async () => {
          const term_name = normalizeSeasonAr(seasonEl.value);
          const term_year = (yearEl.value || '').trim();
          if (!term_name || !term_year) {
            alert('اختر الفصل والعام الدراسي');
            return;
          }
          try {
            const r = await fetch('/admin/settings/parse_term', {
              method: 'POST',
              credentials: 'same-origin',
              headers: requestHeaders({ 'Content-Type': 'application/json' }),
              body: JSON.stringify({ term_name, term_year }),
            });
            const j = await r.json().catch(() => ({}));
            if (!r.ok || j.status === 'error') throw new Error(j.message || 'غير صالح');
            close(j);
          } catch (err) {
            alert(err.message || 'تعذر التحقق');
          }
        };
      } catch (err) {
        try { if (overlay) overlay.remove(); } catch (_e) {}
        reject(err);
      }
    });
  }

  global.TermYearPicker = {
    fetchOptions: fetchTermOptions,
    mount: mountTermYearPicker,
    openDialog: openTermYearDialog,
    normalizeSeasonAr,
  };
})(window);
