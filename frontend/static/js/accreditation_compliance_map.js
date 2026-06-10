/**
 * خريطة امتثال الاعتماد — تبويبات، فلترة، AJAX، إصدار كتالوج
 */
(function () {
  'use strict';

  const cfg = window.ACCRED_PAGE || {};
  const SEM = cfg.semester || '';
  let catalogVersion = cfg.catalogVersion || '';
  let activeScopeKey = cfg.activeScopeKey || 'inst';
  const mapScopes = cfg.mapScopes || [];
  const domainLabels = cfg.domainLabels || {};
  const statusLabels = cfg.statusLabels || {};
  const qaaAxisOptions = cfg.qaaAxisOptions || [];

  function isQaaCatalog() {
    return String(catalogVersion || '').startsWith('QAA-');
  }

  function hdr() {
    const c = document.querySelector('meta[name=csrf-token]')?.content || '';
    const h = { 'Content-Type': 'application/json' };
    if (c) h['X-CSRFToken'] = c;
    return h;
  }

  function mapQuery() {
    const qs = new URLSearchParams({ semester: SEM });
    if (activeScopeKey) qs.set('scope', activeScopeKey);
    if (catalogVersion) qs.set('catalog_version', catalogVersion);
    return qs.toString();
  }

  function syncScopeTabs() {
    document.querySelectorAll('#catalogScopeTabs [data-scope]').forEach((btn) => {
      const on = (btn.dataset.scope || '') === activeScopeKey;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    const meta = mapScopes.find((s) => s.key === activeScopeKey);
    const titleEl = document.getElementById('pageTitle');
    if (titleEl && meta?.page_title_ar) {
      titleEl.innerHTML = '<i class="fa-solid fa-map text-primary"></i> ' + escapeHtml(meta.page_title_ar);
    }
    if (meta?.page_title_ar) document.title = meta.page_title_ar;
  }

  function updateScopeInUrl() {
    try {
      const u = new URL(window.location.href);
      if (activeScopeKey) u.searchParams.set('scope', activeScopeKey);
      else u.searchParams.delete('scope');
      if (catalogVersion) u.searchParams.set('catalog_version', catalogVersion);
      window.history.replaceState({}, '', u.pathname + u.search);
    } catch (_e) { /* ignore */ }
  }

  function statusBadgeClass(st) {
    const m = {
      met: 'bg-success',
      gap: 'bg-danger',
      partial: 'bg-warning text-dark',
      in_progress: 'bg-info text-dark',
    };
    return m[st] || 'bg-secondary';
  }

  function coverageBadgeClass(st) {
    const m = { ok: 'bg-success', partial: 'bg-warning text-dark', missing: 'bg-secondary' };
    return m[st] || 'bg-secondary';
  }

  function renderEvidenceCoverageCell(ind) {
    const cov = ind.evidence_coverage;
    if (cov && cov.label_ar) {
      return '<span class="badge bg-success" title="' +
        escapeHtml(cov.detail_ar || '') + '">' + escapeHtml(cov.label_ar || '') + '</span>';
    }
    if (ind.evidence_count) {
      return '<span class="badge bg-success" title="شواهد مرفوعة">' + ind.evidence_count + ' شاهد</span>';
    }
    return '<span class="text-muted small">—</span>';
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function updateSummary(summary) {
    if (!summary) return;
    const pct = summary.documented_progress_percent ?? 0;
    const bar = document.querySelector('#summaryProgressBar');
    const pctEl = document.querySelector('#summaryProgressPct');
    if (bar) bar.style.width = pct + '%';
    if (pctEl) pctEl.textContent = pct + '%';
    const map = {
      indicators_total: summary.indicators_total,
      not_started: summary.not_started,
      in_progress: summary.in_progress,
      partial: summary.partial,
      met: summary.met,
      gap: summary.gap,
    };
    Object.keys(map).forEach((k) => {
      const el = document.querySelector('[data-summary="' + k + '"]');
      if (el) el.textContent = map[k] ?? 0;
    });
  }

  function buildIndicatorRow(ind) {
    const asm = ind.assessment || {};
    const st = asm.compliance_status || 'not_started';
    const score = asm.score_percent;
    const search = (ind.code || '') + ' ' + (ind.title_ar || '');
    const targetCol = isQaaCatalog()
      ? ''
      : '<td class="text-muted">' + escapeHtml(ind.target_hint_ar) + '</td>';
    return (
      '<tr class="indicator-row" data-status="' + escapeHtml(st) + '" data-search="' + escapeHtml(search.toLowerCase()) + '">' +
      '<td><div><span class="fw-semibold text-secondary">' + escapeHtml(ind.seq || '') + '.</span> ' +
      escapeHtml(ind.title_ar) + '</div>' +
      '<code class="small text-muted">' + escapeHtml(ind.code) + '</code>' +
      (ind.is_auto_computable ? ' <span class="badge bg-primary ms-1">آلي</span>' : '') + '</td>' +
      '<td>' + escapeHtml(ind.source_type_label) + '</td>' +
      targetCol +
      '<td><span class="badge rounded-pill ' + statusBadgeClass(st) + '">' +
      escapeHtml(asm.compliance_status_label || st) + '</span></td>' +
      '<td>' + (score != null ? score + '%' : '—') + '</td>' +
      '<td>' + renderEvidenceCoverageCell(ind) +
      ' <button type="button" class="btn btn-link btn-sm p-0 btn-evidence" data-indicator-id="' + ind.id + '" data-indicator-code="' + escapeHtml(ind.code) + '" data-indicator-title="' + escapeHtml(ind.title_ar) + '">إدارة</button></td>' +
      '<td><button type="button" class="btn btn-link btn-sm p-0 btn-assess" data-indicator-id="' + ind.id + '" data-indicator-code="' + escapeHtml(ind.code) + '" data-indicator-title="' + escapeHtml(ind.title_ar) + '" data-status="' + escapeHtml(st) + '" data-score="' + (score != null ? score : '') + '" data-notes="' + escapeHtml(asm.notes || '') + '">تقييم</button></td>' +
      '</tr>'
    );
  }

  function buildComplianceHtml(mapData) {
    if (!mapData || mapData.status !== 'ok') {
      return '<p class="text-danger p-3">تعذر تحميل الخريطة.</p>';
    }
    let html = '';
    (mapData.domains || []).forEach((dom) => {
      html += '<div class="card mb-3 domain-card" data-domain="' + escapeHtml(dom.code) + '">';
      html += '<div class="card-header bg-light"><strong>' + escapeHtml(dom.label) + '</strong>';
      html += ' <span class="text-muted small">(' + (dom.standards || []).length + ' معيار)</span></div><div class="card-body p-0">';
      (dom.standards || []).forEach((st) => {
        html += '<div class="border-bottom p-3 standard-block">';
        const indCount = st.indicator_count || (st.indicators || []).length;
        html += '<div class="d-flex flex-wrap justify-content-between gap-1 mb-2"><div><code class="small">' + escapeHtml(st.code) + '</code> <strong class="ms-1">' + escapeHtml(st.title_ar) + '</strong>';
        html += ' <span class="text-muted small">(' + indCount + ' مؤشر)</span>';
        if (st.weight_percent) html += ' <span class="badge bg-secondary ms-1">' + st.weight_percent + '%</span>';
        html += '</div><span class="small text-muted">متحقق ' + (st.counts?.met || 0) + ' · جزئي ' + (st.counts?.partial || 0) + ' · لم يبدأ ' + (st.counts?.not_started || 0) + '</span></div>';
        if (st.description) html += '<p class="small text-muted mb-2">' + escapeHtml(st.description) + '</p>';
        html += '<div class="table-responsive"><table class="table table-sm table-bordered mb-0 small"><thead class="table-light"><tr>';
        html += '<th>المؤشر</th><th>المصدر</th>';
        if (!isQaaCatalog()) html += '<th>الهدف</th>';
        html += '<th>الحالة</th><th>الدرجة</th><th>أدلة</th><th></th></tr></thead><tbody>';
        (st.indicators || []).forEach((ind, idx) => {
          if (ind.seq == null) ind.seq = idx + 1;
          html += buildIndicatorRow(ind);
        });
        html += '</tbody></table></div></div>';
      });
      html += '</div></div>';
    });
    return html || '<p class="text-muted p-3">لا توجد مؤشرات لهذا الإصدار.</p>';
  }

  function bindComplianceActions() {
    document.querySelectorAll('.btn-assess').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.getElementById('assessIndicatorId').value = btn.dataset.indicatorId;
        document.getElementById('assessHdr').textContent =
          (btn.dataset.indicatorCode || '') + ' — ' + (btn.dataset.indicatorTitle || '');
        document.getElementById('assessStatus').value = btn.dataset.status || 'not_started';
        document.getElementById('assessScore').value = btn.dataset.score || '';
        document.getElementById('assessNotes').value = btn.dataset.notes || '';
        bootstrap.Modal.getOrCreateInstance(document.getElementById('assessModal')).show();
      });
    });
    document.querySelectorAll('.btn-evidence').forEach((btn) => {
      btn.addEventListener('click', () => openEvidenceModal({
        indicatorId: btn.dataset.indicatorId,
        title: (btn.dataset.indicatorCode || '') + ' — ' + (btn.dataset.indicatorTitle || ''),
      }));
    });
  }

  function syncDomainFilterOptions(domains) {
    const sel = document.getElementById('filterDomain');
    if (!sel) return;
    const prev = sel.value || '';
    const labels = domainLabels || {};
    let html = '<option value="">الكل</option>';
    const valid = new Set();
    if (qaaAxisOptions.length) {
      qaaAxisOptions.forEach((o) => {
        if (catalogVersion && o.catalog_version && o.catalog_version !== catalogVersion) return;
        valid.add(o.domain_code);
        html += '<option value="' + escapeHtml(o.domain_code) + '" data-catalog-version="' +
          escapeHtml(o.catalog_version) + '">' + escapeHtml(o.label || labels[o.domain_code] || o.domain_code) + '</option>';
      });
    } else {
      (domains || []).forEach((d) => {
        valid.add(d.code);
        html += '<option value="' + escapeHtml(d.code) + '">' + escapeHtml(d.label || labels[d.code] || d.code) + '</option>';
      });
    }
    sel.innerHTML = html;
    if (prev && valid.has(prev)) sel.value = prev;
    else sel.value = '';
  }

  async function onDomainFilterChange() {
    const sel = document.getElementById('filterDomain');
    if (!sel) return;
    const opt = sel.selectedOptions[0];
    const cat = opt?.dataset?.catalogVersion;
    const dom = sel.value || '';
    if (cat && cat !== catalogVersion) {
      catalogVersion = cat;
      const verSel = document.getElementById('catalogVersionSelect');
      if (verSel) verSel.value = cat;
      await reloadComplianceMap();
      const sel2 = document.getElementById('filterDomain');
      if (sel2 && dom) sel2.value = dom;
      applyComplianceFilters();
      return;
    }
    applyComplianceFilters();
  }

  function applyComplianceFilters() {
    const domain = (document.getElementById('filterDomain')?.value || '').trim();
    const status = (document.getElementById('filterStatus')?.value || '').trim();
    const q = (document.getElementById('filterSearch')?.value || '').trim().toLowerCase();
    let visibleRows = 0;
    const totalCards = document.querySelectorAll('.domain-card').length;
    document.querySelectorAll('.domain-card').forEach((card) => {
      const domCode = card.dataset.domain || '';
      if (domain && domCode !== domain) {
        card.classList.add('d-none');
        return;
      }
      let cardHasVisible = false;
      card.querySelectorAll('.standard-block').forEach((block) => {
        let blockVisible = false;
        block.querySelectorAll('.indicator-row').forEach((row) => {
          const st = row.dataset.status || '';
          const search = row.dataset.search || '';
          const ok = (!status || st === status) && (!q || search.includes(q));
          row.classList.toggle('d-none', !ok);
          if (ok) {
            visibleRows += 1;
            blockVisible = true;
            cardHasVisible = true;
          }
        });
        block.classList.toggle('d-none', !blockVisible);
      });
      card.classList.toggle('d-none', !cardHasVisible);
    });
    const hint = document.getElementById('filterResultHint');
    if (hint) {
      if (visibleRows) {
        hint.textContent = 'يظهر ' + visibleRows + ' مؤشر';
      } else if (domain && totalCards) {
        hint.textContent = 'لا توجد نتائج — المحور المختار لا يطابق إصدار الكتالوج الحالي. اختر «الكل» أو غيّر إصدار المعايير أعلاه.';
      } else if (totalCards) {
        hint.textContent = 'لا توجد نتائج للفلتر — جرّب مسح الفلاتر.';
      } else {
        hint.textContent = 'لا توجد مؤشرات لهذا الإصدار — اختر «معايير المركز» من قائمة إصدار المعايير.';
      }
    }
  }

  async function reloadComplianceMap() {
    const host = document.getElementById('complianceDomains');
    if (!host) return null;
    host.innerHTML = '<p class="text-muted p-3">جاري التحميل…</p>';
    const r = await fetch('/academic_quality/api/accreditation/compliance_map?' + mapQuery(), {
      credentials: 'include',
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.status !== 'ok') {
      host.innerHTML = '<p class="text-danger p-3">' + escapeHtml(data.message || 'فشل التحميل') + '</p>';
      return null;
    }
    catalogVersion = data.catalog_version || catalogVersion;
    const scopeMatch = mapScopes.find((s) => s.catalog_version === catalogVersion);
    if (scopeMatch) activeScopeKey = scopeMatch.key;
    syncScopeTabs();
    updateScopeInUrl();
    const sel = document.getElementById('catalogVersionSelect');
    if (sel && data.catalog_version) sel.value = data.catalog_version;
    const verLbl = document.getElementById('headerCatalogVersion');
    if (verLbl) verLbl.textContent = data.catalog_version;
    host.innerHTML = buildComplianceHtml(data);
    syncDomainFilterOptions(data.domains || []);
    updateSummary(data.summary);
    bindComplianceActions();
    applyComplianceFilters();
    updateExportLinks();
    if (document.getElementById('tabEvidence')?.classList.contains('active')) {
      loadEvidenceMatrix();
    }
    return data;
  }

  function updateExportLinks() {
    const qs = '?' + mapQuery();
    document.getElementById('btnExportXlsx')?.setAttribute('href', '/academic_quality/api/accreditation/export/xlsx' + qs);
    document.getElementById('btnExportPdf')?.setAttribute('href', '/academic_quality/api/accreditation/export/pdf' + qs);
  }

  function renderPlansTable(items) {
    const tbody = document.getElementById('plansTableBody');
    if (!tbody) return;
    const labels = cfg.planStatusLabels || {};
    const pri = cfg.planPriorityLabels || {};
    if (!items || !items.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-muted text-center">لا توجد خطط بعد.</td></tr>';
      return;
    }
    tbody.innerHTML = items.map((p) =>
      '<tr><td>' + escapeHtml(p.title_ar) + '</td><td><code>' + escapeHtml(p.indicator_code || '—') + '</code></td>' +
      '<td>' + escapeHtml(p.status_label || labels[p.status] || p.status) + '</td>' +
      '<td>' + escapeHtml(p.priority_label || pri[p.priority] || p.priority) + '</td>' +
      '<td>' + escapeHtml(p.target_date || '—') + '</td><td>' +
      '<button type="button" class="btn btn-link btn-sm p-0 btn-edit-plan" data-id="' + p.id + '" data-title="' + escapeHtml(p.title_ar) + '" data-action="' + escapeHtml(p.action_ar || '') + '" data-indicator-id="' + (p.indicator_id || '') + '" data-status="' + escapeHtml(p.status) + '" data-priority="' + escapeHtml(p.priority) + '" data-target-date="' + escapeHtml(p.target_date || '') + '" data-owner="' + escapeHtml(p.owner_ar || '') + '" data-notes="' + escapeHtml(p.notes || '') + '">تعديل</button> ' +
      '<button type="button" class="btn btn-link btn-sm p-0 text-danger btn-del-plan" data-id="' + p.id + '">حذف</button></td></tr>'
    ).join('');
    bindPlanButtons();
  }

  function fillManualSections(sections) {
    (sections || []).forEach((sec) => {
      (sec.fields || []).forEach((f) => {
        const el = document.querySelector('.manual-field[data-key="' + f.key + '"]');
        if (!el) return;
        const v = (sec.values || {})[f.key];
        el.value = v == null ? '' : v;
      });
    });
  }

  function showToast(msg, ok) {
    if (typeof window.showToast === 'function') {
      window.showToast(msg, ok ? 'success' : 'danger');
      return;
    }
    alert(msg);
  }

  let evidenceMatrixRows = [];

  function linkModeBadgeClass(m) {
    const map = { auto: 'bg-primary', hybrid: 'bg-info text-dark', manual: 'bg-dark', evidence: 'bg-secondary' };
    return map[m] || 'bg-secondary';
  }

  function fulfillmentBadgeClass(st) {
    const map = { met: 'bg-success', partial: 'bg-warning text-dark', missing: 'bg-danger', not_applicable: 'bg-light text-dark border' };
    return map[st] || 'bg-secondary';
  }

  function renderEvidenceMatrixSummary(summary) {
    const el = document.getElementById('evMatrixSummary');
    if (!el || !summary) return;
    const cov = summary.required_coverage_percent ?? 0;
    el.innerHTML =
      '<span class="badge bg-secondary">قواعد: ' + (summary.total || 0) + '</span>' +
      '<span class="badge bg-success">مكتمل: ' + (summary.met || 0) + '</span>' +
      '<span class="badge bg-warning text-dark">جزئي: ' + (summary.partial || 0) + '</span>' +
      '<span class="badge bg-danger">ناقص: ' + (summary.missing || 0) + '</span>' +
      '<span class="badge bg-primary">تغطية إلزامي: ' + cov + '%</span>';
  }

  function applyEvidenceMatrixFilters() {
    const mode = (document.getElementById('evMatrixFilterMode')?.value || '').trim();
    const st = (document.getElementById('evMatrixFilterStatus')?.value || '').trim();
    const q = (document.getElementById('evMatrixSearch')?.value || '').trim().toLowerCase();
    const rows = evidenceMatrixRows.filter((r) => {
      if (mode && r.link_mode !== mode) return false;
      const fst = (r.fulfillment || {}).status || '';
      if (st && fst !== st) return false;
      if (q) {
        const hay = ((r.indicator_code || '') + ' ' + (r.indicator_title_ar || '') + ' ' +
          (r.evidence_type_title_ar || '') + ' ' + (r.standard_code || '')).toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    const host = document.getElementById('evMatrixHost');
    if (!host) return;
    if (!rows.length) {
      host.innerHTML = '<p class="text-muted mb-0">لا توجد صفوف مطابقة للفلتر.</p>';
      return;
    }
    let html = '<div class="table-responsive"><table class="table table-sm table-bordered mb-0 small"><thead class="table-light"><tr>' +
      '<th>المؤشر</th><th>نوع الدليل</th><th>الربط</th><th>الحالة</th><th>التفاصيل</th><th></th></tr></thead><tbody>';
    rows.forEach((r) => {
      const f = r.fulfillment || {};
      html += '<tr data-ev-matrix-row="1">' +
        '<td><code class="small">' + escapeHtml(r.indicator_code) + '</code><div class="text-muted">' +
        escapeHtml((r.standard_title_ar || '').slice(0, 80)) + '</div></td>' +
        '<td>' + escapeHtml(r.evidence_type_title_ar) +
        (r.is_required ? ' <span class="badge bg-danger">إلزامي</span>' : '') + '</td>' +
        '<td><span class="badge ' + linkModeBadgeClass(r.link_mode) + '">' + escapeHtml(r.link_mode_label || r.link_mode) + '</span></td>' +
        '<td><span class="badge ' + fulfillmentBadgeClass(f.status) + '">' + escapeHtml(f.status_label || f.status) + '</span></td>' +
        '<td class="text-muted">' + escapeHtml(f.detail_ar || '') + '</td>' +
        '<td class="text-nowrap">' +
        '<button type="button" class="btn btn-link btn-sm p-0 btn-ev-matrix-ev" data-indicator-id="' + r.indicator_id + '" data-title="' +
        escapeHtml(r.indicator_code + ' — ' + (r.evidence_type_title_ar || '')) + '">شاهد</button> ' +
        '<button type="button" class="btn btn-link btn-sm p-0 btn-ev-matrix-assess" data-indicator-id="' + r.indicator_id + '" data-code="' +
        escapeHtml(r.indicator_code) + '" data-title="' + escapeHtml(r.indicator_title_ar) + '">تقييم</button></td></tr>';
    });
    html += '</tbody></table></div>';
    host.innerHTML = html;
    host.querySelectorAll('.btn-ev-matrix-ev').forEach((btn) => {
      btn.addEventListener('click', () => openEvidenceModal({
        indicatorId: btn.dataset.indicatorId,
        title: btn.dataset.title,
      }));
    });
    host.querySelectorAll('.btn-ev-matrix-assess').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.getElementById('assessIndicatorId').value = btn.dataset.indicatorId;
        document.getElementById('assessHdr').textContent =
          (btn.dataset.code || '') + ' — ' + (btn.dataset.title || '');
        bootstrap.Modal.getOrCreateInstance(document.getElementById('assessModal')).show();
      });
    });
  }

  async function loadEvidenceMatrix() {
    const host = document.getElementById('evMatrixHost');
    if (!host) return;
    host.innerHTML = '<p class="text-muted mb-0">جاري التحميل…</p>';
    const qs = new URLSearchParams({ semester: SEM });
    if (catalogVersion) qs.set('catalog_version', catalogVersion);
    const r = await fetch('/academic_quality/api/accreditation/evidence/matrix?' + qs, { credentials: 'include' });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.status !== 'ok') {
      host.innerHTML = '<p class="text-danger mb-0">' + escapeHtml(data.message || 'تعذر تحميل المصفوفة') + '</p>';
      return;
    }
    evidenceMatrixRows = data.rows || [];
    const catLbl = document.getElementById('evMatrixCatalog');
    if (catLbl) catLbl.textContent = data.catalog_version || catalogVersion;
    renderEvidenceMatrixSummary(data.summary);
    applyEvidenceMatrixFilters();
  }

  let evidenceModal;
  let bindableSourcesCache = null;
  let evidencePermsLoaded = false;

  async function ensureEvidencePermissions() {
    if (evidencePermsLoaded) return;
    try {
      const r = await fetch('/academic_quality/api/accreditation/evidence/permissions', { credentials: 'include' });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        cfg.canBindSources = !!j.can_bind_sources;
        if (j.can_edit_catalog !== undefined) cfg.canEditAccreditationCatalog = !!j.can_edit_catalog;
      }
    } catch (_) { /* ignore */ }
    evidencePermsLoaded = true;
  }

  function bindingOptionValue(item) {
    return (item.binding_kind || '') + '|' + (item.source_ref || '');
  }

  function buildBindingSelectOptions(sources, currentBinding) {
    const curVal = currentBinding ? bindingOptionValue(currentBinding) : '';
    let html = '<option value="">— اختر المصدر —</option>';

    function optionRow(item) {
      const val = bindingOptionValue(item);
      const selected = val === curVal ? ' selected' : '';
      let extra = (item.detail_ar || '').trim();
      if (item.binding_kind === 'survey') {
        const parts = [];
        if (item.response_count > 0) parts.push(item.response_count + ' رد');
        if (item.overall_score_percent != null && item.overall_score_percent !== '') {
          parts.push(item.overall_score_percent + '%');
        }
        if (parts.length) extra = parts.join(' · ');
      } else if (item.count > 0 && !extra) {
        extra = item.count + '';
      }
      const rec = item.is_recommended ? ' ★' : '';
      const label = (item.label_ar || item.source_ref || '') + (extra ? ' — ' + extra : '') + rec;
      const disabled = item.available === false ? ' disabled' : '';
      return '<option value="' + escapeHtml(val) + '"' + selected + disabled + '>' + escapeHtml(label) + '</option>';
    }

    const surveys = sources.surveys || [];
    if (surveys.length) {
      html += '<optgroup label="استبيانات المنظومة">';
      surveys.forEach((s) => { html += optionRow(s); });
      html += '</optgroup>';
    }
    const reports = (sources.reports || []).filter((x) => x.available !== false);
    const reportsUnavailable = (sources.reports || []).filter((x) => x.available === false);
    if (reports.length) {
      html += '<optgroup label="تقارير ومصادر النظام">';
      reports.forEach((s) => { html += optionRow(s); });
      html += '</optgroup>';
    }
    if (reportsUnavailable.length) {
      html += '<optgroup label="تقارير غير متوفرة بعد">';
      reportsUnavailable.forEach((s) => { html += optionRow(s); });
      html += '</optgroup>';
    }
    const witnesses = sources.witnesses || [];
    if (witnesses.length) {
      html += '<optgroup label="شواهد مرفوعة">';
      witnesses.forEach((s) => { html += optionRow(s); });
      html += '</optgroup>';
    }
    const manual = sources.manual || [];
    if (manual.length) {
      html += '<optgroup label="يدوي / تقييم">';
      manual.forEach((s) => { html += optionRow(s); });
      html += '</optgroup>';
    }
    return html;
  }

  function renderCurrentBindingHtml(cur) {
    if (!cur) return '<span class="text-muted">—</span>';
    return '<span class="badge bg-success-subtle text-success border">' +
      escapeHtml(cur.label_ar || cur.source_ref) + '</span> ' +
      '<span class="text-muted small">(' + escapeHtml(cur.binding_kind_label || cur.binding_kind) + ')</span>';
  }

  function renderEvidenceBindingsPanel(data) {
    const host = document.getElementById('evidenceBindingsHost');
    const catLbl = document.getElementById('evidenceBindingsCatalog');
    if (!host) return;
    const expected = data.expected_evidence || [];
    const bindings = data.bindings || [];
    const sources = data.sources || {};
    const freeform = data.freeform_mode !== false;
    const canBind = cfg.canBindSources !== false;
    if (catLbl) catLbl.textContent = data.catalog_version || catalogVersion || '';

    if (freeform) {
      let html = '';
      if (bindings.length) {
        html += '<div class="table-responsive mb-3"><table class="table table-sm table-bordered align-middle mb-0">' +
          '<thead class="table-light"><tr><th>المصدر المربوط</th><th>النوع</th>';
        if (canBind) html += '<th></th>';
        html += '</tr></thead><tbody>';
        bindings.forEach((b) => {
          html += '<tr><td><strong>' + escapeHtml(b.label_ar || b.source_ref) + '</strong>' +
            '<div class="text-muted small"><code>' + escapeHtml(b.source_ref || '') + '</code></div></td>' +
            '<td><span class="badge bg-light text-dark border">' +
            escapeHtml(b.binding_kind_label || b.binding_kind) + '</span></td>';
          if (canBind) {
            html += '<td><button type="button" class="btn btn-outline-danger btn-sm btn-clear-binding" data-id="' +
              escapeHtml(b.id) + '">إلغاء</button></td>';
          }
          html += '</tr>';
        });
        html += '</tbody></table></div>';
      } else {
        html += '<p class="text-muted small mb-2">لا توجد مصادر مربوطة بعد.</p>';
      }
      if (canBind) {
        html += '<div class="border rounded p-2 bg-light">' +
          '<label class="form-label small mb-1">إضافة ربط جديد</label>' +
          '<select class="form-select form-select-sm mb-2" id="evFreeformBindSel">' +
          buildBindingSelectOptions(sources, null) + '</select>' +
          '<button type="button" class="btn btn-primary btn-sm" id="btnFreeformSaveBinding">حفظ الربط</button></div>';
      }
      host.innerHTML = html;
      if (!canBind) return;
      host.querySelectorAll('.btn-clear-binding').forEach((btn) => {
        btn.addEventListener('click', () => clearEvidenceBinding(btn.dataset.id));
      });
      const saveBtn = document.getElementById('btnFreeformSaveBinding');
      if (saveBtn) {
        saveBtn.addEventListener('click', () => {
          const sel = document.getElementById('evFreeformBindSel');
          if (sel) saveFreeformBinding(sel);
        });
      }
      return;
    }

    if (!expected.length) {
      host.innerHTML = '<p class="text-muted mb-0">لا توجد قواعد أدلة في المصفوفة لهذا المؤشر. يمكنك رفع شواهد يدوياً أدناه.</p>';
      return;
    }

    let html = '<div class="table-responsive"><table class="table table-sm table-bordered align-middle mb-0">' +
      '<thead class="table-light"><tr><th>نوع الدليل</th><th>وضع الربط</th><th>المصدر الحالي</th>';
    if (canBind) html += '<th style="min-width:220px">اختيار المصدر</th>';
    html += '</tr></thead><tbody>';

    expected.forEach((row) => {
      const cur = row.current_binding;
      const selId = 'evBindSel_' + row.evidence_type_id;
      html += '<tr><td><strong>' + escapeHtml(row.evidence_type_title_ar) + '</strong>' +
        '<div class="text-muted small"><code>' + escapeHtml(row.evidence_type_code) + '</code></div></td>' +
        '<td><span class="badge ' + linkModeBadgeClass(row.link_mode) + '">' +
        escapeHtml(row.link_mode_label || row.link_mode) + '</span></td>' +
        '<td>' + renderCurrentBindingHtml(cur) + '</td>';
      if (canBind) {
        html += '<td><select class="form-select form-select-sm ev-bind-select mb-1" id="' + selId + '" ' +
          'data-rule="' + escapeHtml(row.rule_id) + '" data-et="' + escapeHtml(row.evidence_type_id) + '">' +
          buildBindingSelectOptions(sources, cur) + '</select>' +
          '<div class="d-flex flex-wrap gap-1">' +
          '<button type="button" class="btn btn-primary btn-sm btn-save-binding" data-rule="' + escapeHtml(row.rule_id) + '" ' +
          'data-et="' + escapeHtml(row.evidence_type_id) + '" data-sel="' + selId + '">حفظ الربط</button>';
        if (cur && cur.id) {
          html += '<button type="button" class="btn btn-outline-danger btn-sm btn-clear-binding" data-id="' +
            escapeHtml(cur.id) + '">إلغاء الربط</button>';
        }
        html += '</div></td>';
      }
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    host.innerHTML = html;

    if (!canBind) return;

    host.querySelectorAll('.btn-save-binding').forEach((btn) => {
      btn.addEventListener('click', () => {
        const sel = document.getElementById(btn.dataset.sel);
        if (sel) saveEvidenceBinding(btn.dataset.rule, btn.dataset.et, sel);
      });
    });
    host.querySelectorAll('.btn-clear-binding').forEach((btn) => {
      btn.addEventListener('click', () => clearEvidenceBinding(btn.dataset.id));
    });
  }

  async function loadBindableSources(indicatorId) {
    const panel = document.getElementById('evidenceBindingsPanel');
    const host = document.getElementById('evidenceBindingsHost');
    if (!panel || !host || !indicatorId) {
      panel?.classList.add('d-none');
      return;
    }
    panel.classList.remove('d-none');
    host.innerHTML = '<span class="text-muted">جاري التحميل…</span>';
    await ensureEvidencePermissions();
    const qs = new URLSearchParams({ semester: SEM, indicator_id: String(indicatorId) });
    if (catalogVersion) qs.set('catalog_version', catalogVersion);
    const r = await fetch('/academic_quality/api/accreditation/evidence/bindable-sources?' + qs, { credentials: 'include' });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      host.innerHTML = '<p class="text-danger mb-0">' + escapeHtml(j.message || 'تعذّر تحميل مصادر الربط') + '</p>';
      bindableSourcesCache = null;
      return;
    }
    bindableSourcesCache = j;
    renderEvidenceBindingsPanel(j);
  }

  async function saveFreeformBinding(selectEl) {
    const raw = selectEl.value;
    if (!raw) { alert('اختر مصدراً من القائمة'); return; }
    const pipe = raw.indexOf('|');
    if (pipe < 1) { alert('اختيار غير صالح'); return; }
    const bindingKind = raw.slice(0, pipe);
    const sourceRef = raw.slice(pipe + 1);
    const iid = +document.getElementById('evidenceIndicatorId').value;
    const opt = selectEl.options[selectEl.selectedIndex];
    const body = {
      semester: SEM,
      indicator_id: iid,
      binding_kind: bindingKind,
      source_ref: sourceRef,
      label_ar: (opt.textContent || '').replace(/\s*★\s*$/, '').trim(),
    };
    const r = await fetch('/academic_quality/api/accreditation/evidence/bindings', {
      method: 'POST', credentials: 'include', headers: hdr(), body: JSON.stringify(body),
    });
    const j = await r.json().catch(() => ({}));
    if (r.ok) {
      showToast('تم حفظ ربط المصدر', true);
      await loadBindableSources(iid);
      await reloadComplianceMap();
    } else {
      showToast(j.message || 'فشل حفظ الربط', false);
    }
  }

  async function saveEvidenceBinding(ruleId, evidenceTypeId, selectEl) {
    const raw = selectEl.value;
    if (!raw) { alert('اختر مصدراً من القائمة'); return; }
    const pipe = raw.indexOf('|');
    if (pipe < 1) { alert('اختيار غير صالح'); return; }
    const bindingKind = raw.slice(0, pipe);
    const sourceRef = raw.slice(pipe + 1);
    const iid = +document.getElementById('evidenceIndicatorId').value;
    const opt = selectEl.options[selectEl.selectedIndex];
    const body = {
      semester: SEM,
      indicator_id: iid,
      evidence_type_id: +evidenceTypeId,
      rule_id: ruleId ? +ruleId : null,
      binding_kind: bindingKind,
      source_ref: sourceRef,
      label_ar: (opt.textContent || '').replace(/\s*★\s*$/, '').trim(),
    };
    const cur = (bindableSourcesCache?.expected_evidence || []).find(
      (e) => +e.evidence_type_id === +evidenceTypeId
    )?.current_binding;
    if (cur?.id) body.id = cur.id;
    const r = await fetch('/academic_quality/api/accreditation/evidence/bindings', {
      method: 'POST', credentials: 'include', headers: hdr(), body: JSON.stringify(body),
    });
    const j = await r.json().catch(() => ({}));
    if (r.ok) {
      showToast('تم حفظ ربط المصدر', true);
      await loadBindableSources(iid);
      await reloadComplianceMap();
    } else {
      showToast(j.message || 'فشل حفظ الربط', false);
    }
  }

  async function clearEvidenceBinding(bindingId) {
    if (!bindingId || !confirm('إلغاء ربط هذا المصدر؟')) return;
    const r = await fetch('/academic_quality/api/accreditation/evidence/bindings/' + bindingId, {
      method: 'DELETE', credentials: 'include', headers: hdr(),
    });
    const j = await r.json().catch(() => ({}));
    const iid = document.getElementById('evidenceIndicatorId').value;
    if (r.ok) {
      showToast('تم إلغاء الربط', true);
      if (iid) {
        await loadBindableSources(iid);
        await reloadComplianceMap();
      }
    } else {
      showToast(j.message || 'فشل الإلغاء', false);
    }
  }

  function openEvidenceModal({ indicatorId, checklistKey, title }) {
    document.getElementById('evidenceIndicatorId').value = indicatorId || '';
    document.getElementById('evidenceChecklistKey').value = checklistKey || '';
    document.getElementById('evidenceHdr').textContent = title || '';
    document.getElementById('evidenceFile').value = '';
    document.getElementById('evidenceTitle').value = '';
    document.getElementById('evidenceUrl').value = '';
    const panel = document.getElementById('evidenceBindingsPanel');
    const witnessTitle = document.getElementById('evidenceWitnessTitle');
    if (indicatorId && !checklistKey) {
      if (witnessTitle) witnessTitle.textContent = 'شواهد مرفوعة (ملفات وروابط)';
      loadBindableSources(indicatorId);
    } else {
      panel?.classList.add('d-none');
      bindableSourcesCache = null;
      if (witnessTitle) witnessTitle.textContent = 'شواهد مرفوعة';
    }
    evidenceModal = bootstrap.Modal.getOrCreateInstance(document.getElementById('evidenceModal'));
    evidenceModal.show();
    loadEvidenceList();
  }

  async function loadEvidenceList() {
    const iid = document.getElementById('evidenceIndicatorId').value;
    const ck = document.getElementById('evidenceChecklistKey').value;
    const qs = new URLSearchParams({ semester: SEM });
    if (iid) qs.set('indicator_id', iid);
    if (ck) qs.set('checklist_key', ck);
    const r = await fetch('/academic_quality/api/accreditation/evidence/list?' + qs, { credentials: 'include' });
    const j = await r.json().catch(() => ({}));
    const ul = document.getElementById('evidenceList');
    ul.innerHTML = '';
    (j.items || []).forEach((it) => {
      const li = document.createElement('li');
      li.className = 'list-group-item d-flex justify-content-between align-items-start gap-2';
      let link = '';
      if (it.download_url) link = '<a href="' + it.download_url + '" target="_blank" rel="noopener">تنزيل</a>';
      else if (it.external_url) link = '<a href="' + it.external_url + '" target="_blank" rel="noopener">فتح</a>';
      li.innerHTML = '<div><strong>' + escapeHtml(it.title_ar) + '</strong><div class="text-muted">' +
        escapeHtml(it.evidence_type) + ' · ' + escapeHtml(it.uploaded_at) + '</div></div><div class="d-flex gap-2">' + link +
        '<button type="button" class="btn btn-link btn-sm text-danger p-0" data-del="' + it.id + '">حذف</button></div>';
      ul.appendChild(li);
    });
    if (!ul.children.length) ul.innerHTML = '<li class="list-group-item text-muted">لا توجد أدلة بعد.</li>';
    ul.querySelectorAll('[data-del]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!confirm('حذف هذا الدليل؟')) return;
        await fetch('/academic_quality/api/accreditation/evidence/' + btn.dataset.del, {
          method: 'DELETE', credentials: 'include', headers: hdr(),
        });
        await loadEvidenceList();
        if (iid) await loadBindableSources(iid);
      });
    });
  }

  const planModal = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('planModal'));

  function bindPlanButtons() {
    document.querySelectorAll('.btn-edit-plan').forEach((btn) => {
      btn.onclick = () => {
        document.getElementById('planId').value = btn.dataset.id || '';
        document.getElementById('planTitle').value = btn.dataset.title || '';
        document.getElementById('planAction').value = btn.dataset.action || '';
        document.getElementById('planIndicatorId').value = btn.dataset.indicatorId || '';
        document.getElementById('planStatus').value = btn.dataset.status || 'planned';
        document.getElementById('planPriority').value = btn.dataset.priority || 'medium';
        document.getElementById('planTargetDate').value = btn.dataset.targetDate || '';
        document.getElementById('planOwner').value = btn.dataset.owner || '';
        document.getElementById('planNotes').value = btn.dataset.notes || '';
        planModal().show();
      };
    });
    document.querySelectorAll('.btn-del-plan').forEach((btn) => {
      btn.onclick = async () => {
        if (!confirm('حذف الخطة؟')) return;
        await fetch('/academic_quality/api/accreditation/improvement_plans/' + btn.dataset.id, {
          method: 'DELETE', credentials: 'include', headers: hdr(),
        });
        const lst = await fetch('/academic_quality/api/accreditation/improvement_plans?semester=' + encodeURIComponent(SEM), { credentials: 'include' });
        const j = await lst.json().catch(() => ({}));
        renderPlansTable(j.items || []);
      };
    });
  }

  let catalogTypesCache = [];
  let catalogRulesCache = [];
  let catalogIndicatorsCache = [];

  function evidenceTypeModal() {
    return bootstrap.Modal.getOrCreateInstance(document.getElementById('evidenceTypeModal'));
  }

  function evidenceRuleModal() {
    return bootstrap.Modal.getOrCreateInstance(document.getElementById('evidenceRuleModal'));
  }

  function renderCatalogTypesTable() {
    const host = document.getElementById('catalogTypesHost');
    if (!host) return;
    if (!catalogTypesCache.length) {
      host.innerHTML = '<p class="text-muted mb-0">لا توجد أنواع أدلة.</p>';
      return;
    }
    let html = '<div class="table-responsive"><table class="table table-sm table-bordered mb-0"><thead class="table-light"><tr>' +
      '<th>الرمز</th><th>العنوان</th><th>التصنيف</th><th>مصدر</th><th></th></tr></thead><tbody>';
    const catLbl = cfg.evidenceCategoryLabels || {};
    catalogTypesCache.forEach((t) => {
      const sys = t.is_system ? ' <span class="badge bg-secondary">نظامي</span>' : '';
      const src = (t.source_module || '') + (t.source_ref ? ':' + t.source_ref : '');
      html += '<tr><td><code>' + escapeHtml(t.code) + '</code>' + sys + '</td>' +
        '<td>' + escapeHtml(t.title_ar) + '</td>' +
        '<td>' + escapeHtml(catLbl[t.category] || t.category) + '</td>' +
        '<td class="text-muted">' + escapeHtml(src || '—') + '</td><td class="text-nowrap">' +
        '<button type="button" class="btn btn-link btn-sm p-0 btn-edit-ev-type" data-id="' + t.id + '">تعديل</button>';
      if (!t.is_system) {
        html += ' <button type="button" class="btn btn-link btn-sm p-0 text-danger btn-del-ev-type" data-id="' + t.id + '">حذف</button>';
      }
      html += '</td></tr>';
    });
    html += '</tbody></table></div>';
    host.innerHTML = html;
    host.querySelectorAll('.btn-edit-ev-type').forEach((btn) => {
      btn.addEventListener('click', () => {
        const t = catalogTypesCache.find((x) => String(x.id) === btn.dataset.id);
        if (!t) return;
        document.getElementById('evTypeId').value = t.id;
        document.getElementById('evTypeCode').value = t.code || '';
        document.getElementById('evTypeCode').readOnly = !!t.is_system;
        document.getElementById('evTypeTitle').value = t.title_ar || '';
        document.getElementById('evTypeDesc').value = t.description_ar || '';
        document.getElementById('evTypeCategory').value = t.category || 'file';
        document.getElementById('evTypeSort').value = t.sort_order || 0;
        document.getElementById('evTypeModule').value = t.source_module || '';
        document.getElementById('evTypeRef').value = t.source_ref || '';
        evidenceTypeModal().show();
      });
    });
    host.querySelectorAll('.btn-del-ev-type').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!confirm('حذف نوع الدليل؟')) return;
        const r = await fetch('/academic_quality/api/accreditation/evidence/types/' + btn.dataset.id, {
          method: 'DELETE', credentials: 'include', headers: hdr(),
        });
        const j = await r.json().catch(() => ({}));
        if (r.ok) { showToast('تم الحذف', true); loadCatalogTypes(); }
        else showToast(j.message || 'فشل الحذف', false);
      });
    });
  }

  function renderCatalogRulesTable() {
    const host = document.getElementById('catalogRulesHost');
    if (!host) return;
    const q = (document.getElementById('catalogRulesSearch')?.value || '').trim().toLowerCase();
    const rows = catalogRulesCache.filter((r) => {
      if (!q) return true;
      const hay = ((r.indicator_code || '') + ' ' + (r.indicator_title_ar || '') + ' ' +
        (r.evidence_type_title_ar || '') + ' ' + (r.standard_code || '')).toLowerCase();
      return hay.includes(q);
    });
    if (!rows.length) {
      host.innerHTML = '<p class="text-muted mb-0">لا توجد قواعد مطابقة.</p>';
      return;
    }
    let html = '<div class="table-responsive"><table class="table table-sm table-bordered mb-0"><thead class="table-light"><tr>' +
      '<th>المؤشر</th><th>نوع الدليل</th><th>الربط</th><th>إلزامي</th><th></th></tr></thead><tbody>';
    rows.forEach((r) => {
      html += '<tr><td><code class="small">' + escapeHtml(r.indicator_code) + '</code><div class="text-muted">' +
        escapeHtml((r.indicator_title_ar || '').slice(0, 60)) + '</div></td>' +
        '<td>' + escapeHtml(r.evidence_type_title_ar) + '</td>' +
        '<td><span class="badge ' + linkModeBadgeClass(r.link_mode) + '">' + escapeHtml(r.link_mode_label || r.link_mode) + '</span></td>' +
        '<td>' + (r.is_required ? 'نعم' : 'لا') + '</td><td class="text-nowrap">' +
        '<button type="button" class="btn btn-link btn-sm p-0 btn-edit-ev-rule" data-id="' + r.id + '">تعديل</button> ' +
        '<button type="button" class="btn btn-link btn-sm p-0 text-danger btn-del-ev-rule" data-id="' + r.id + '">حذف</button></td></tr>';
    });
    html += '</tbody></table></div>';
    host.innerHTML = html;
    host.querySelectorAll('.btn-edit-ev-rule').forEach((btn) => {
      btn.addEventListener('click', () => openEvidenceRuleEditor(btn.dataset.id));
    });
    host.querySelectorAll('.btn-del-ev-rule').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!confirm('حذف قاعدة الربط؟')) return;
        const r = await fetch('/academic_quality/api/accreditation/evidence/rules/' + btn.dataset.id, {
          method: 'DELETE', credentials: 'include', headers: hdr(),
        });
        const j = await r.json().catch(() => ({}));
        if (r.ok) { showToast('تم الحذف', true); loadCatalogRules(); loadEvidenceMatrix(); }
        else showToast(j.message || 'فشل الحذف', false);
      });
    });
  }

  async function loadCatalogTypes() {
    const r = await fetch('/academic_quality/api/accreditation/evidence/types', { credentials: 'include' });
    const j = await r.json().catch(() => ({}));
    catalogTypesCache = j.items || [];
    renderCatalogTypesTable();
    return catalogTypesCache;
  }

  async function loadCatalogRules() {
    const qs = new URLSearchParams();
    if (catalogVersion) qs.set('catalog_version', catalogVersion);
    const r = await fetch('/academic_quality/api/accreditation/evidence/rules?' + qs, { credentials: 'include' });
    const j = await r.json().catch(() => ({}));
    catalogRulesCache = j.items || [];
    renderCatalogRulesTable();
    const verLbl = document.getElementById('catalogMatrixVer');
    if (verLbl) verLbl.textContent = catalogVersion;
    return catalogRulesCache;
  }

  async function loadCatalogIndicators() {
    const qs = new URLSearchParams();
    if (catalogVersion) qs.set('catalog_version', catalogVersion);
    const r = await fetch('/academic_quality/api/accreditation/evidence/indicators?' + qs, { credentials: 'include' });
    const j = await r.json().catch(() => ({}));
    catalogIndicatorsCache = j.items || [];
    return catalogIndicatorsCache;
  }

  function fillRuleTypeSelect() {
    const sel = document.getElementById('evRuleTypeCode');
    if (!sel) return;
    sel.innerHTML = catalogTypesCache.map((t) =>
      '<option value="' + escapeHtml(t.code) + '">' + escapeHtml(t.title_ar) + ' (' + escapeHtml(t.code) + ')</option>'
    ).join('');
  }

  async function fillRuleIndicatorSelect(selectedId) {
    await loadCatalogIndicators();
    const sel = document.getElementById('evRuleIndicator');
    if (!sel) return;
    sel.innerHTML = catalogIndicatorsCache.map((i) =>
      '<option value="' + i.id + '">' + escapeHtml(i.code) + ' — ' + escapeHtml((i.title_ar || '').slice(0, 80)) + '</option>'
    ).join('');
    if (selectedId) sel.value = String(selectedId);
  }

  async function openEvidenceRuleEditor(ruleId) {
    const rule = catalogRulesCache.find((x) => String(x.id) === String(ruleId));
    if (!rule) return;
    document.getElementById('evRuleId').value = rule.id;
    await loadCatalogTypes();
    fillRuleTypeSelect();
    await fillRuleIndicatorSelect(rule.indicator_id);
    document.getElementById('evRuleTypeCode').value = rule.evidence_type_code || '';
    document.getElementById('evRuleLinkMode').value = rule.link_mode || 'evidence';
    document.getElementById('evRuleSort').value = rule.sort_order || 0;
    document.getElementById('evRuleRequired').checked = !!rule.is_required;
    document.getElementById('evRuleNotes').value = rule.notes_ar || '';
    evidenceRuleModal().show();
  }

  function initCatalogMatrixAdmin() {
    if (!cfg.canEditAccreditationCatalog) return;

    document.querySelector('[data-bs-target="#tabAdmin"]')?.addEventListener('shown.bs.tab', () => {
      loadCatalogTypes();
    });
    document.querySelector('[data-bs-target="#catalogRulesPane"]')?.addEventListener('shown.bs.tab', () => {
      loadCatalogRules();
    });
    document.getElementById('catalogRulesSearch')?.addEventListener('input', renderCatalogRulesTable);

    document.getElementById('btnAddEvidenceType')?.addEventListener('click', () => {
      document.getElementById('evTypeId').value = '';
      document.getElementById('evTypeCode').value = '';
      document.getElementById('evTypeCode').readOnly = false;
      document.getElementById('evTypeTitle').value = '';
      document.getElementById('evTypeDesc').value = '';
      document.getElementById('evTypeCategory').value = 'file';
      document.getElementById('evTypeSort').value = '500';
      document.getElementById('evTypeModule').value = '';
      document.getElementById('evTypeRef').value = '';
      evidenceTypeModal().show();
    });

    document.getElementById('btnSaveEvidenceType')?.addEventListener('click', async () => {
      const body = {
        id: document.getElementById('evTypeId').value || null,
        code: document.getElementById('evTypeCode').value.trim(),
        title_ar: document.getElementById('evTypeTitle').value.trim(),
        description_ar: document.getElementById('evTypeDesc').value.trim(),
        category: document.getElementById('evTypeCategory').value,
        sort_order: parseInt(document.getElementById('evTypeSort').value, 10) || 0,
        source_module: document.getElementById('evTypeModule').value.trim(),
        source_ref: document.getElementById('evTypeRef').value.trim(),
      };
      const r = await fetch('/academic_quality/api/accreditation/evidence/types', {
        method: 'POST', credentials: 'include', headers: hdr(), body: JSON.stringify(body),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        evidenceTypeModal().hide();
        showToast('تم حفظ نوع الدليل', true);
        loadCatalogTypes();
      } else showToast(j.message || 'فشل الحفظ', false);
    });

    document.getElementById('btnAddEvidenceRule')?.addEventListener('click', async () => {
      document.getElementById('evRuleId').value = '';
      await loadCatalogTypes();
      fillRuleTypeSelect();
      await fillRuleIndicatorSelect();
      document.getElementById('evRuleLinkMode').value = 'evidence';
      document.getElementById('evRuleSort').value = '0';
      document.getElementById('evRuleRequired').checked = true;
      document.getElementById('evRuleNotes').value = '';
      evidenceRuleModal().show();
    });

    document.getElementById('btnSaveEvidenceRule')?.addEventListener('click', async () => {
      const body = {
        id: document.getElementById('evRuleId').value || null,
        catalog_version: catalogVersion,
        indicator_id: parseInt(document.getElementById('evRuleIndicator').value, 10),
        evidence_type_code: document.getElementById('evRuleTypeCode').value,
        link_mode: document.getElementById('evRuleLinkMode').value,
        sort_order: parseInt(document.getElementById('evRuleSort').value, 10) || 0,
        is_required: document.getElementById('evRuleRequired').checked,
        notes_ar: document.getElementById('evRuleNotes').value.trim(),
      };
      const r = await fetch('/academic_quality/api/accreditation/evidence/rules', {
        method: 'POST', credentials: 'include', headers: hdr(), body: JSON.stringify(body),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        evidenceRuleModal().hide();
        showToast('تم حفظ قاعدة الربط', true);
        loadCatalogRules();
        if (document.getElementById('tabEvidence')?.classList.contains('active')) loadEvidenceMatrix();
      } else showToast(j.message || 'فشل الحفظ', false);
    });

    loadCatalogTypes();
  }

  function init() {
    if (typeof window.cleanupUiBlockers === 'function') window.cleanupUiBlockers();
    if (typeof window.initNavDropdowns === 'function') window.initNavDropdowns();

    updateExportLinks();

    document.getElementById('catalogVersionSelect')?.addEventListener('change', (e) => {
      catalogVersion = e.target.value || '';
      const scopeMatch = mapScopes.find((s) => s.catalog_version === catalogVersion);
      if (scopeMatch) activeScopeKey = scopeMatch.key;
      syncScopeTabs();
      reloadComplianceMap();
      if (cfg.canEditAccreditationCatalog && document.getElementById('catalogRulesPane')?.classList.contains('active')) {
        loadCatalogRules();
      }
    });

    document.querySelectorAll('#catalogScopeTabs [data-scope]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const scope = btn.dataset.scope || '';
        const cat = btn.dataset.catalog || '';
        if (!scope || scope === activeScopeKey) return;
        activeScopeKey = scope;
        catalogVersion = cat || catalogVersion;
        syncScopeTabs();
        const verSel = document.getElementById('catalogVersionSelect');
        if (verSel && cat) verSel.value = cat;
        const d = document.getElementById('filterDomain');
        const s = document.getElementById('filterStatus');
        const q = document.getElementById('filterSearch');
        if (d) d.value = '';
        if (s) s.value = '';
        if (q) q.value = '';
        reloadComplianceMap();
        if (cfg.canEditAccreditationCatalog && document.getElementById('catalogRulesPane')?.classList.contains('active')) {
          loadCatalogRules();
        }
      });
    });

    document.getElementById('filterDomain')?.addEventListener('change', onDomainFilterChange);
    document.getElementById('filterStatus')?.addEventListener('change', applyComplianceFilters);
    document.getElementById('filterSearch')?.addEventListener('input', applyComplianceFilters);
    document.getElementById('btnClearFilters')?.addEventListener('click', () => {
      const d = document.getElementById('filterDomain');
      const s = document.getElementById('filterStatus');
      const q = document.getElementById('filterSearch');
      if (d) d.value = '';
      if (s) s.value = '';
      if (q) q.value = '';
      applyComplianceFilters();
    });

    document.getElementById('btnRefreshMap')?.addEventListener('click', () => reloadComplianceMap());
    if (cfg.showEvidenceMatrixTab) {
      document.getElementById('btnReloadEvidenceMatrix')?.addEventListener('click', () => loadEvidenceMatrix());
      ['evMatrixFilterMode', 'evMatrixFilterStatus'].forEach((id) => {
        document.getElementById(id)?.addEventListener('change', applyEvidenceMatrixFilters);
      });
      document.getElementById('evMatrixSearch')?.addEventListener('input', applyEvidenceMatrixFilters);
      document.querySelector('[data-bs-target="#tabEvidence"]')?.addEventListener('shown.bs.tab', () => {
        loadEvidenceMatrix();
      });
    }

    document.getElementById('btnSaveManual')?.addEventListener('click', async () => {
      const body = { semester: SEM, catalog_version: catalogVersion };
      document.querySelectorAll('.manual-field').forEach((el) => {
        const k = el.dataset.key;
        if (!k) return;
        body[k] = el.value === '' ? null : (el.tagName === 'TEXTAREA' ? el.value : parseFloat(el.value));
      });
      const r = await fetch('/academic_quality/api/accreditation/manual_inputs/save', {
        method: 'POST', credentials: 'include', headers: hdr(), body: JSON.stringify(body),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        fillManualSections(j.sections);
        const sync = j.indicator_sync || [];
        const n = sync.filter((x) => x.action === 'updated').length;
        showToast('تم الحفظ' + (n ? ' — وربط ' + n + ' مؤشراً' : ''), true);
        await reloadComplianceMap();
      } else showToast(j.message || 'فشل الحفظ', false);
    });

    document.getElementById('btnAddPlan')?.addEventListener('click', () => {
      document.getElementById('planId').value = '';
      document.getElementById('planTitle').value = '';
      document.getElementById('planAction').value = '';
      document.getElementById('planIndicatorId').value = '';
      document.getElementById('planStatus').value = 'planned';
      document.getElementById('planPriority').value = 'medium';
      document.getElementById('planTargetDate').value = '';
      document.getElementById('planOwner').value = '';
      document.getElementById('planNotes').value = '';
      planModal().show();
    });

    document.getElementById('btnSavePlan')?.addEventListener('click', async () => {
      const body = {
        semester: SEM,
        id: document.getElementById('planId').value || null,
        title_ar: document.getElementById('planTitle').value,
        action_ar: document.getElementById('planAction').value,
        indicator_id: document.getElementById('planIndicatorId').value || null,
        status: document.getElementById('planStatus').value,
        priority: document.getElementById('planPriority').value,
        target_date: document.getElementById('planTargetDate').value,
        owner_ar: document.getElementById('planOwner').value,
        notes: document.getElementById('planNotes').value,
      };
      const r = await fetch('/academic_quality/api/accreditation/improvement_plans/save', {
        method: 'POST', credentials: 'include', headers: hdr(), body: JSON.stringify(body),
      });
      if (r.ok) {
        planModal().hide();
        const lst = await fetch('/academic_quality/api/accreditation/improvement_plans?semester=' + encodeURIComponent(SEM), { credentials: 'include' });
        const j = await lst.json().catch(() => ({}));
        renderPlansTable(j.items || []);
        showToast('تم حفظ الخطة', true);
      } else {
        const j = await r.json().catch(() => ({}));
        showToast(j.message || 'فشل الحفظ', false);
      }
    });

    document.getElementById('btnSaveAssess')?.addEventListener('click', async () => {
      const body = {
        semester: SEM,
        indicator_id: +document.getElementById('assessIndicatorId').value,
        compliance_status: document.getElementById('assessStatus').value,
        score_percent: parseFloat(document.getElementById('assessScore').value) || null,
        notes: document.getElementById('assessNotes').value,
      };
      const r = await fetch('/academic_quality/api/accreditation/assessment/save', {
        method: 'POST', credentials: 'include', headers: hdr(), body: JSON.stringify(body),
      });
      if (r.ok) {
        bootstrap.Modal.getOrCreateInstance(document.getElementById('assessModal')).hide();
        showToast('تم حفظ التقييم', true);
        await reloadComplianceMap();
      } else {
        const j = await r.json().catch(() => ({}));
        showToast(j.message || 'فشل الحفظ', false);
      }
    });

    document.querySelectorAll('.btn-checklist-ev').forEach((btn) => {
      btn.addEventListener('click', () => openEvidenceModal({
        checklistKey: btn.dataset.checklistKey,
        title: 'قائمة التحقق: ' + (btn.dataset.title || ''),
      }));
    });

    document.getElementById('btnUploadEvidence')?.addEventListener('click', async () => {
      const f = document.getElementById('evidenceFile').files[0];
      if (!f) { alert('اختر ملفاً'); return; }
      const fd = new FormData();
      fd.append('semester', SEM);
      fd.append('file', f);
      const iid = document.getElementById('evidenceIndicatorId').value;
      const ck = document.getElementById('evidenceChecklistKey').value;
      if (iid) fd.append('indicator_id', iid);
      if (ck) fd.append('checklist_key', ck);
      const t = document.getElementById('evidenceTitle').value.trim();
      if (t) fd.append('title_ar', t);
      const csrf = document.querySelector('meta[name=csrf-token]')?.content || '';
      const h = {};
      if (csrf) h['X-CSRFToken'] = csrf;
      const r = await fetch('/academic_quality/api/accreditation/evidence/upload', {
        method: 'POST', credentials: 'include', headers: h, body: fd,
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        document.getElementById('evidenceFile').value = '';
        await loadEvidenceList();
        const iid = document.getElementById('evidenceIndicatorId').value;
        if (iid) await loadBindableSources(iid);
      } else alert(j.message || 'فشل الرفع');
    });

    document.getElementById('btnLinkEvidence')?.addEventListener('click', async () => {
      const url = document.getElementById('evidenceUrl').value.trim();
      if (!url) { alert('أدخل رابطاً'); return; }
      const body = { semester: SEM, external_url: url };
      const iid = document.getElementById('evidenceIndicatorId').value;
      const ck = document.getElementById('evidenceChecklistKey').value;
      if (iid) body.indicator_id = +iid;
      if (ck) body.checklist_key = ck;
      const t = document.getElementById('evidenceTitle').value.trim();
      if (t) body.title_ar = t;
      const r = await fetch('/academic_quality/api/accreditation/evidence/link', {
        method: 'POST', credentials: 'include', headers: hdr(), body: JSON.stringify(body),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        document.getElementById('evidenceUrl').value = '';
        await loadEvidenceList();
        const iid = document.getElementById('evidenceIndicatorId').value;
        if (iid) await loadBindableSources(iid);
      } else alert(j.message || 'فشل إضافة الرابط');
    });

    document.getElementById('btnComputeAuto')?.addEventListener('click', async () => {
      if (!confirm('حساب المؤشرات الآلية من بيانات النظام لهذا الفصل؟\nلن يُستبدل التقييم اليدوي السابق (غير الآلي).')) return;
      const r = await fetch('/academic_quality/api/accreditation/compute_auto', {
        method: 'POST', credentials: 'include', headers: hdr(),
        body: JSON.stringify({ semester: SEM, only_not_started: true }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        showToast('تم تحديث ' + (j.updated_count || 0) + ' مؤشراً', true);
        await reloadComplianceMap();
      } else showToast(j.message || 'فشل الحساب', false);
    });

    document.getElementById('btnEnsureCatalog')?.addEventListener('click', async () => {
      if (!confirm('إعادة بذر كتالوج المعايير الافتراضي (2026.1)؟\nلن يحذف التقييمات المحفوظة.')) return;
      const r = await fetch('/academic_quality/api/accreditation/ensure_catalog', {
        method: 'POST', credentials: 'include', headers: hdr(),
        body: JSON.stringify({}),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        showToast('تم تحديث الكتالوج', true);
        await reloadComplianceMap();
      } else showToast(j.message || 'فشل', false);
    });

    document.getElementById('btnImportCatalog')?.addEventListener('click', async () => {
      const f = document.getElementById('importCatalogFile').files[0];
      if (!f) { alert('اختر ملف Excel'); return; }
      const fd = new FormData();
      fd.append('file', f);
      if (document.getElementById('importDeactivatePrev').checked) fd.append('deactivate_previous', '1');
      const csrf = document.querySelector('meta[name=csrf-token]')?.content || '';
      const h = {};
      if (csrf) h['X-CSRFToken'] = csrf;
      const r = await fetch('/academic_quality/api/accreditation/import_catalog', {
        method: 'POST', credentials: 'include', headers: h, body: fd,
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        showToast('تم الاستيراد: ' + (j.catalog_version || ''), true);
        const vr = await fetch('/academic_quality/api/accreditation/catalog_versions', { credentials: 'include' });
        const vj = await vr.json().catch(() => ({}));
        const sel = document.getElementById('catalogVersionSelect');
        if (sel && vj.versions) {
          const labels = vj.labels || window.ACCRED_PAGE?.catalogVersionLabels || {};
          sel.innerHTML = vj.versions.map((v) =>
            '<option value="' + escapeHtml(v) + '"' + (v === j.catalog_version ? ' selected' : '') + '>' +
            escapeHtml(labels[v] || v) + '</option>'
          ).join('');
          catalogVersion = j.catalog_version || catalogVersion;
        }
        await reloadComplianceMap();
      } else showToast(j.message || 'فشل الاستيراد', false);
    });

    document.querySelectorAll('#evidenceModal, #planModal, #assessModal').forEach((el) => {
      el.addEventListener('hidden.bs.modal', () => {
        if (typeof window.cleanupUiBlockers === 'function') window.cleanupUiBlockers();
      });
    });

    bindComplianceActions();
    bindPlanButtons();
    applyComplianceFilters();
    initCatalogMatrixAdmin();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
