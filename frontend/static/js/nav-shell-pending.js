(function applyNavShellPending() {
  var el = document.currentScript;
  var kind = el && el.getAttribute("data-nav-shell");
  if (!kind) return;
  document.documentElement.classList.add("nav-shell-" + kind + "-pending");
})();
