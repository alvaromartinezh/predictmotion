/* PredictMotion — conmutador de tema claro/oscuro
   Aplica el tema guardado en <html data-theme> lo antes posible y
   cablea cualquier botón con [data-theme-toggle]. Persiste en localStorage. */
(function () {
  var KEY = 'pm-theme';
  var root = document.documentElement;

  function current() { return root.getAttribute('data-theme') === 'light' ? 'light' : 'dark'; }

  // Aplica el tema guardado de inmediato (evita parpadeo)
  try {
    var saved = localStorage.getItem(KEY);
    root.setAttribute('data-theme', saved === 'light' ? 'light' : 'dark');
  } catch (e) { root.setAttribute('data-theme', 'dark'); }

  function sync() {
    var light = current() === 'light';
    document.querySelectorAll('[data-theme-toggle]').forEach(function (b) {
      b.setAttribute('aria-pressed', light ? 'true' : 'false');
      b.setAttribute('aria-label', light ? 'Cambiar a modo oscuro' : 'Cambiar a modo claro');
    });
    if (window.__pmThemeChange) try { window.__pmThemeChange(current()); } catch (e) {}
  }

  function toggle() {
    var next = current() === 'light' ? 'dark' : 'light';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem(KEY, next); } catch (e) {}
    sync();
  }

  function wire() {
    document.querySelectorAll('[data-theme-toggle]').forEach(function (b) {
      if (b.dataset.bound) return;
      b.dataset.bound = '1';
      b.addEventListener('click', toggle);
    });
    sync();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire);
  else wire();
})();
