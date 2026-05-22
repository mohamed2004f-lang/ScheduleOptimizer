/**
 * خريطة امتثال الاعتماد — تبويبات، فلترة، AJAX، إصدار كتالوج
 */
(function () {
  'use strict';

  const cfg = window.ACCRED_PAGE || {};
  const SEM = cfg.semester || '';
  let catalogVersion = cfg.catalogVersion || '';
  const domainLabels = cfg.domainLabels || {};
  const statusLabels = cfg.statusLabels || {};

  function hdr() {
    const c = document.querySelector('meta[name=csrf-token]')?.content || '';
    const h = { 'Content-Type': 'application/json' };
    if (c) h['X-CSRFToken'] = c;
    return h;
  }

  function mapQuery() {
    const qs = new URLSearchParams({ semester: SEM });
    if (catalogVersion) qs.set('catalog_version', catalogVersion);
    return qs.toString();
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
    return (
      '<tr class="indicator-row" data-status="' + escapeHtml(st) + '" data-search="' + escapeHtml(search.toLowerCase()) + '">' +
      '<td><code>' + escapeHtml(ind.code) + '</code> ' + escapeHtml(ind.title_ar) +
      (ind.is_auto_computable ? ' <span class="badge bg-primary ms-1">آلي</span>' : '') + '</td>' +
      '<td>' + escapeHtml(ind.source_type_label) + '</td>' +
      '<td class="text-muted">' + escapeHtml(ind.target_hint_ar) + '</td>' +
      '<td><span class="badge rounded-pill ' + statusBadgeClass(st) + '">' +
      escapeHtml(asm.compliance_status_label || st) + '</span></td>' +
      '<td>' + (score != null ? score + '%' : '—') + '</td>' +
      '<td>' + (ind.evidence_count ? '<span class="badge bg-success">' + ind.evidence_count + '</span>' : '<span class="text-muted">0</span>') +
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
        html += '<div class="d-flex flex-wrap justify-content-between gap-1 mb-2"><div><code class="small">' + escapeHtml(st.code) + '</code> <strong class="ms-1">' + escapeHtml(st.title_ar) + '</strong>';
        if (st.weight_percent) html += ' <span class="badge bg-secondary ms-1">' + st.weight_percent + '%</span>';
        html += '</div><span class="small text-muted">متحقق ' + (st.counts?.met || 0) + ' · جزئي ' + (st.counts?.partial || 0) + ' · لم يبدأ ' + (st.counts?.not_started || 0) + '</span></div>';
        if (st.description) html += '<p class="small text-muted mb-2">' + escapeHtml(st.description) + '</p>';
        html += '<div class="table-responsive"><table class="table table-sm table-bordered mb-0 small"><thead class="table-light"><tr>';
        html += '<th>المؤشر</th><th>المصدر</th><th>الهدف</th><th>الحالة</th><th>الدرجة</th><th>أدلة</th><th></th></tr></thead><tbody>';
        (st.indicators || []).forEach((ind) => { html += buildIndicatorRow(ind); });
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

  function applyComplianceFilters() {
    const domain = (document.getElementById('filterDomain')?.value || '').trim();
    const status = (document.getElementById('filterStatus')?.value || '').trim();
    const q = (document.getElementById('filterSearch')?.value || '').trim().toLowerCase();
    let visibleRows = 0;
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
    if (hint) hint.textContent = visibleRows ? 'يظهر ' + visibleRows + ' مؤشر' : 'لا توجد نتائج للفلتر';
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
    const sel = document.getElementById('catalogVersionSelect');
    if (sel && data.catalog_version) sel.value = data.catalog_version;
    const verLbl = document.getElementById('headerCatalogVersion');
    if (verLbl) verLbl.textContent = data.catalog_version;
    host.innerHTML = buildComplianceHtml(data);
    updateSummary(data.summary);
    bindComplianceActions();
    applyComplianceFilters();
    updateExportLinks();
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

  let evidenceModal;
  function openEvidenceModal({ indicatorId, checklistKey, title }) {
    document.getElementById('evidenceIndicatorId').value = indicatorId || '';
    document.getElementById('evidenceChecklistKey').value = checklistKey || '';
    document.getElementById('evidenceHdr').textContent = title || '';
    document.getElementById('evidenceFile').value = '';
    document.getElementById('evidenceTitle').value = '';
    document.getElementById('evidenceUrl').value = '';
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
        loadEvidenceList();
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

  function init() {
    if (typeof window.cleanupUiBlockers === 'function') window.cleanupUiBlockers();
    if (typeof window.initNavDropdowns === 'function') window.initNavDropdowns();

    updateExportLinks();

    document.getElementById('catalogVersionSelect')?.addEventListener('change', (e) => {
      catalogVersion = e.target.value || '';
      reloadComplianceMap();
    });

    ['filterDomain', 'filterStatus'].forEach((id) => {
      document.getElementById(id)?.addEventListener('change', applyComplianceFilters);
    });
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
      if (r.ok) { loadEvidenceList(); document.getElementById('evidenceFile').value = ''; }
      else alert(j.message || 'فشل الرفع');
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
      if (r.ok) { loadEvidenceList(); document.getElementById('evidenceUrl').value = ''; }
      else alert(j.message || 'فشل إضافة الرابط');
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
          sel.innerHTML = vj.versions.map((v) =>
            '<option value="' + escapeHtml(v) + '"' + (v === j.catalog_version ? ' selected' : '') + '>' + escapeHtml(v) + '</option>'
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
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
