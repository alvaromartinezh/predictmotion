/* ──────────────────────────────────────────────────────────────────────────
   PMAds — componente reutilizable para los banners Adsterra.

   El snippet nativo define una global `atOptions` que se SOBRESCRIBE entre
   banners: por eso varios snippets directos en la misma página se pisan y solo
   carga el último. Aquí cada banner se monta DENTRO DE SU PROPIO IFRAME, con su
   `atOptions` y su invoke.js aislados, de modo que cada uno tiene su contexto
   global independiente y no interfieren entre sí.

   Uso en la página:
     <div class="ad-wrap"><span class="ad-label">Publicidad</span>
       <div class="ad-slot" data-ad-slot="top|mid"></div></div>
     <script src="/assets/ads-config.js"></script>
     <script src="/assets/ads.js"></script>
     <script>PMAds.init()</script>
   ────────────────────────────────────────────────────────────────────────── */
(function (w, d) {
  'use strict';

  // Monta un banner concreto (leaderboard/rectangle/mobile) aislado en su iframe.
  function mountAdSlot(container, format) {
    var cfg = w.PM_ADS && w.PM_ADS.FORMATS[format];
    if (!cfg) return;

    var iframe = d.createElement('iframe');
    iframe.width = cfg.width;
    iframe.height = cfg.height;
    iframe.scrolling = 'no';
    iframe.setAttribute('frameborder', '0');
    iframe.setAttribute('aria-hidden', 'true');
    iframe.title = 'Publicidad';
    iframe.style.cssText = 'border:0;display:block;margin:0 auto;overflow:hidden;max-width:100%';
    container.appendChild(iframe);

    // Documento propio del iframe: atOptions + invoke.js, ambos locales a este
    // contexto. Así la global no colisiona con la de los demás banners.
    var atOptions = { key: cfg.key, format: 'iframe', height: cfg.height, width: cfg.width, params: {} };
    var html =
      '<!doctype html><html><head><meta charset="utf-8">' +
      '<style>html,body{margin:0;padding:0;overflow:hidden;background:transparent}</style></head><body>' +
      '<script type="text/javascript">atOptions=' + JSON.stringify(atOptions) + ';<\/script>' +
      '<script type="text/javascript" src="//www.highperformanceformat.com/' + cfg.key + '/invoke.js"><\/script>' +
      '</body></html>';
    try {
      var doc = iframe.contentWindow.document;
      doc.open();
      doc.write(html);
      doc.close();
    } catch (e) {
      collapse(container);
      return;
    }

    // Degradación elegante: si el banner no carga (adblocker / sin relleno),
    // colapsar el contenedor para no dejar una caja vacía.
    w.setTimeout(function () {
      try {
        var body = iframe.contentDocument && iframe.contentDocument.body;
        if (!body || body.scrollHeight < 10) collapse(container);
      } catch (e) { /* cross-origin inesperado: dejar el hueco reservado */ }
    }, 3500);
  }

  // Oculta limpiamente el slot (y su etiqueta) sin dejar hueco roto.
  function collapse(container) {
    var wrap = container.closest ? container.closest('.ad-wrap') : null;
    (wrap || container).classList.add('is-empty');
  }

  // Elige y monta el banner adecuado para el slot según el viewport actual.
  function load(slot) {
    if (slot.dataset.adLoaded) return;
    slot.dataset.adLoaded = '1';
    var map = w.PM_ADS.SLOTS[slot.dataset.adSlot];
    if (!map) return;
    var isMobile = w.matchMedia('(max-width:' + w.PM_ADS.MOBILE_BREAKPOINT + 'px)').matches;
    mountAdSlot(slot, isMobile ? map.mobile : map.desktop);
  }

  // Punto de entrada: respeta ENABLED y hace lazy-load de los slots bajo el fold.
  function init() {
    if (!w.PM_ADS || !w.PM_ADS.ENABLED) return;
    var slots = d.querySelectorAll('[data-ad-slot]');
    if (!slots.length) return;

    if (!('IntersectionObserver' in w)) {
      Array.prototype.forEach.call(slots, load); // sin IO: carga directa
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { io.unobserve(entry.target); load(entry.target); }
      });
    }, { rootMargin: '300px' });
    Array.prototype.forEach.call(slots, function (slot) { io.observe(slot); });
  }

  w.PMAds = { init: init, mountAdSlot: mountAdSlot };
})(window, document);
