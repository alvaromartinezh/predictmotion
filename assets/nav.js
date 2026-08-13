/* PMNav — polish de navegación (multipágina estático): PRECARGA de enlaces
   internos al pasar el puntero por encima, para que el click (que siempre es un
   recargo del documento) se sienta casi instantáneo. Sin dependencias. */
(function () {
  'use strict';

  var done = {};

  function prefetch(href) {
    if (done[href]) return;
    done[href] = 1;
    var l = document.createElement('link');
    l.rel = 'prefetch';
    l.href = href;
    document.head.appendChild(l);
  }

  // Solo enlaces internos, a otra página (no anclas, no externos, no descargas,
  // no pestañas nuevas) — los únicos que provocan recargo del documento.
  function internal(a) {
    var u = a.getAttribute('href');
    if (!u) return null;
    if (/^(?:[a-z]+:)?\/\//i.test(u)) return null; /* externo: http(s), mailto, tel… */
    if (u.charAt(0) === '#') return null;          /* ancla en la misma página */
    if (a.target === '_blank' || a.hasAttribute('download')) return null;
    return u;
  }

  function onHover(ev) {
    var t = ev.target;
    var a = t && t.closest ? t.closest('a[href]') : null;
    if (!a) return;
    var u = internal(a);
    if (u) prefetch(u);
  }

  // Solo punteros finos (hover real) y conexiones sin ahorro de datos.
  if (window.matchMedia && matchMedia('(hover: hover)').matches
      && !(navigator.connection && navigator.connection.saveData)) {
    document.addEventListener('pointerover', onHover, { passive: true });
  }
})();
