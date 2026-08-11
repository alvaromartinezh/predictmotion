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

  // Hook para UI inyectada por JS después de DOMContentLoaded (p. ej. el shell del
  // rediseño): tras montar, llamar PMTheme.wire() para cablear su botón
  // [data-theme-toggle]. Sigue habiendo UN solo sistema de tema (este). wire() es
  // idempotente (guard data-bound), así que re-llamarlo no duplica handlers.
  window.PMTheme = { wire: wire, toggle: toggle, current: current };

  // ── Color de fondo del patrón (balón/banderín/copa/dado), independiente de
  // claro/oscuro. Mismo patrón que arriba: aplica lo guardado ANTES de pintar
  // (evita parpadeo), localStorage por defecto; ajustes.html + account.js pueden
  // reconciliar con el valor de cuenta (cross-device) una vez cargue la sesión.
  var BG_KEY = 'pm-bg-theme';
  var BG_THEMES = ['purple', 'green', 'blue', 'orange', 'teal', 'rose'];

  function currentBg() {
    var v = root.getAttribute('data-bg-theme');
    return BG_THEMES.indexOf(v) >= 0 ? v : 'purple';
  }

  try {
    var savedBg = localStorage.getItem(BG_KEY);
    root.setAttribute('data-bg-theme', BG_THEMES.indexOf(savedBg) >= 0 ? savedBg : 'purple');
  } catch (e) { root.setAttribute('data-bg-theme', 'purple'); }

  function setBg(t, opts) {
    opts = opts || {};
    if (BG_THEMES.indexOf(t) < 0) return;
    root.setAttribute('data-bg-theme', t);
    if (opts.persistLocal !== false) { try { localStorage.setItem(BG_KEY, t); } catch (e) {} }
  }

  window.PMBgTheme = { current: currentBg, set: setBg, THEMES: BG_THEMES.slice() };
})();
