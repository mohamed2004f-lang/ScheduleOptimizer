/**
 * مساعد الجودة العائم — يظهر في صفحات /academic_quality/*
 * يعيد استخدام API المساعد مع سياق الصفحة الحالية.
 */
(function () {
  try {
    var path = (window.location && window.location.pathname) || '';
    if (path.indexOf('/academic_quality/') !== 0) return;
    if (path.indexOf('/academic_quality/assistant') === 0) return; // الصفحة الكاملة تغني عنه
    if (window.__QA_FAB_LOADED) return;
    window.__QA_FAB_LOADED = true;

    var css = document.createElement('style');
    css.textContent = [
      '#qaFabBtn{position:fixed;bottom:1.25rem;left:1.25rem;z-index:1080;border-radius:999px;',
      'width:3.25rem;height:3.25rem;border:0;background:#0d6efd;color:#fff;box-shadow:0 8px 24px rgba(13,110,253,.35);',
      'font-size:1.15rem;cursor:pointer}',
      '#qaFabPanel{position:fixed;bottom:5rem;left:1.25rem;z-index:1080;width:min(24rem,92vw);max-height:70vh;',
      'background:#fff;border:1px solid #dee2e6;border-radius:.75rem;box-shadow:0 12px 32px rgba(15,23,42,.18);',
      'display:none;flex-direction:column;overflow:hidden;font-size:.9rem}',
      '#qaFabPanel.open{display:flex}',
      '#qaFabHead{padding:.65rem .8rem;background:#f8f9fa;border-bottom:1px solid #eee;display:flex;justify-content:space-between;gap:.5rem;align-items:center}',
      '#qaFabBody{padding:.75rem;overflow:auto;min-height:10rem;white-space:pre-wrap;background:#fbfcfe}',
      '#qaFabFoot{padding:.6rem;border-top:1px solid #eee;display:grid;gap:.4rem}',
      '#qaFabFoot textarea{width:100%;min-height:3.2rem;resize:vertical}',
      '#qaFabLinks{padding:0 .6rem .6rem;display:flex;flex-wrap:wrap;gap:.3rem}'
    ].join('');
    document.head.appendChild(css);

    var btn = document.createElement('button');
    btn.id = 'qaFabBtn';
    btn.type = 'button';
    btn.title = 'المساعد الذكي للجودة';
    btn.setAttribute('aria-label', 'فتح المساعد الذكي');
    btn.innerHTML = '✦';
    document.body.appendChild(btn);

    var panel = document.createElement('div');
    panel.id = 'qaFabPanel';
    panel.innerHTML = [
      '<div id="qaFabHead"><strong>مساعد الجودة</strong>',
      '<div><a class="btn btn-sm btn-outline-secondary" href="/academic_quality/assistant">صفحة كاملة</a> ',
      '<button type="button" class="btn btn-sm btn-outline-secondary" id="qaFabClose">إغلاق</button></div></div>',
      '<div id="qaFabBody">اسأل عن هذه الصفحة أو عن الجودة/الأرشيف/الاستخدام…</div>',
      '<div id="qaFabLinks"></div>',
      '<div id="qaFabFoot">',
      '<select id="qaFabChannel" class="form-select form-select-sm">',
      '<option value="discuss">دردشة جودة</option>',
      '<option value="system_help">مساعدة المنظومة</option>',
      '<option value="proofread">مدقق صياغة</option>',
      '<option value="proactive_alerts">تنبيهات الفصل</option>',
      '</select>',
      '<textarea id="qaFabNotes" class="form-control form-control-sm" placeholder="اكتب سؤالك…"></textarea>',
      '<button type="button" class="btn btn-primary btn-sm" id="qaFabSend">إرسال</button>',
      '</div>'
    ].join('');
    document.body.appendChild(panel);

    function setOpen(v) {
      panel.classList.toggle('open', !!v);
    }
    btn.addEventListener('click', function () { setOpen(!panel.classList.contains('open')); });
    panel.querySelector('#qaFabClose').addEventListener('click', function () { setOpen(false); });

    var history = [];
    async function send() {
      var notes = (panel.querySelector('#qaFabNotes').value || '').trim();
      var intent = panel.querySelector('#qaFabChannel').value || 'discuss';
      if (!notes && intent !== 'proactive_alerts') {
        panel.querySelector('#qaFabBody').textContent = 'اكتب سؤالاً أولاً.';
        return;
      }
      panel.querySelector('#qaFabBody').textContent = 'جاري التحليل…';
      panel.querySelector('#qaFabLinks').innerHTML = '';
      try {
        var r = await fetch('/academic_quality/api/assistant/run', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
          body: JSON.stringify({
            intent: intent,
            notes: notes,
            history: history.slice(-5),
            channel: 'fab',
            page_path: path
          })
        });
        var j = await r.json();
        if (!r.ok) {
          panel.querySelector('#qaFabBody').textContent = j.message || 'تعذّر الرد';
          return;
        }
        var lines = [];
        if (j.message_ar) lines.push(j.message_ar);
        if (j.knowledge_tag) lines.push('[' + j.knowledge_tag + ']');
        (j.bullets || []).forEach(function (b) { lines.push(String(b)); });
        if (j.llm_enrichment_ar) {
          lines.push('');
          lines.push('LLM اختياري:');
          lines.push(j.llm_enrichment_ar);
        }
        panel.querySelector('#qaFabBody').textContent = lines.join('\n');
        var box = panel.querySelector('#qaFabLinks');
        (j.links || []).forEach(function (l) {
          var a = document.createElement('a');
          a.className = 'btn btn-outline-secondary btn-sm';
          a.href = l.href;
          a.textContent = l.label_ar || l.href;
          box.appendChild(a);
        });
        if (notes) history.push({ role: 'user', text: notes });
        history.push({ role: 'assistant', text: lines.join('\n').slice(0, 1800) });
        panel.querySelector('#qaFabNotes').value = '';
      } catch (e) {
        panel.querySelector('#qaFabBody').textContent = 'خطأ اتصال';
      }
    }
    panel.querySelector('#qaFabSend').addEventListener('click', send);
    panel.querySelector('#qaFabNotes').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    });
  } catch (e) {
    /* لا تعطل الصفحة */
  }
})();
