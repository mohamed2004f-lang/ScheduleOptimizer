/**
 * تلميحات المصطلحات — عربي أولاً، بلا عرض رموز تقنية للمستخدم.
 */
(function () {
  let glossary = null;
  let loadPromise = null;

  function loadGlossary() {
    if (glossary) return Promise.resolve(glossary);
    if (loadPromise) return loadPromise;
    loadPromise = fetch("/static/data/quality_glossary.json", { cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("glossary");
        return r.json();
      })
      .then(function (data) {
        glossary = data.terms || {};
        return glossary;
      })
      .catch(function () {
        glossary = {};
        return glossary;
      });
    return loadPromise;
  }

  function attachIcon(el, term) {
    if (!term || el.querySelector(".term-help-icon")) return;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "term-help-icon";
    btn.setAttribute("aria-label", "شرح: " + (term.title_ar || ""));
    btn.innerHTML = '<i class="fa-solid fa-circle-info"></i>';
    btn.setAttribute("data-bs-toggle", "popover");
    btn.setAttribute("data-bs-trigger", "focus hover");
    btn.setAttribute("data-bs-placement", "top");
    btn.setAttribute("data-bs-custom-class", "term-help-popover");
    btn.setAttribute(
      "data-bs-content",
      (term.definition_ar || "").replace(/"/g, "&quot;")
    );
    btn.setAttribute("data-bs-title", term.title_ar || "");
    el.appendChild(btn);
    if (window.bootstrap && bootstrap.Popover) {
      new bootstrap.Popover(btn, { html: false, sanitize: true });
    }
  }

  function initTermHelp(root) {
    var scope = root || document;
    return loadGlossary().then(function (terms) {
      scope.querySelectorAll("[data-term]").forEach(function (el) {
        var id = (el.getAttribute("data-term") || "").trim().toLowerCase();
        var term = terms[id];
        if (!term) return;
        if (!el.getAttribute("title")) {
          el.setAttribute("title", term.title_ar || "");
        }
        attachIcon(el, term);
      });
    });
  }

  window.TermHelp = {
    load: loadGlossary,
    init: initTermHelp,
    get: function (id) {
      return glossary && glossary[(id || "").toLowerCase()];
    },
  };

  document.addEventListener("DOMContentLoaded", function () {
    initTermHelp(document);
  });
})();
