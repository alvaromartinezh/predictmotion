/* PMAds — banners Adsterra no intrusivos (solo display/nativo).
 *
 * Cada hueco es <div class="ad-wrap" data-ad-slot="box|leader"></div>.
 * El código de ads-config.js se inyecta en un <iframe> aislado y se ejecuta
 * ahí (los códigos de Adsterra usan document.write: dentro del iframe sigue
 * funcionando tras la carga, sin tocar nuestro DOM).
 *
 * Los huecos pueden existir ya en el HTML estático O aparecer después
 * (feeds renderizados por JS): un MutationObserver los detecta igual.
 * Sin código configurado el hueco se marca .is-empty y no ocupa espacio.
 */
(function () {
  "use strict";

  /* Marcadores típicos de un código aún no sustituido. */
  var UNFILLED_RE = /PON_TU_|XXXXXXXXX|ADSTERRA_KEY/i;

  function render(el) {
    if (!el || el.__pmAd) return;
    el.__pmAd = true;

    var name = el.getAttribute("data-ad-slot");
    var conf = window.PM_ADS || {};
    var slot = conf.slots && conf.slots[name];

    if (conf.enabled === false || !slot || !slot.html || UNFILLED_RE.test(slot.html)) {
      el.classList.add("is-empty");
      return;
    }

    el.classList.add("has-ad");
    el.innerHTML = '<span class="ad-label">Publicidad</span>';

    var f = document.createElement("iframe");
    f.className = "ad-frame";
    f.title = "Publicidad";
    f.setAttribute("scrolling", "no");
    f.setAttribute("loading", "lazy");
    // Sin esto, un creativo agresivo puede hacer top.location = ... o window.open()
    // y secuestrar toda la pestaña ("anuncio a pantalla completa" pese a que el
    // panel de Adsterra solo tiene banner/nativo activado — algún sub-afiliado se
    // lo salta). El navegador bloquea la navegación/popup a nivel estructural,
    // no dependen de que el script del anuncio "respete" nada.
    f.setAttribute("sandbox", "allow-scripts allow-same-origin");
    if (slot.w) f.style.maxWidth = slot.w + "px";
    f.style.height = (slot.h || 250) + "px";
    el.appendChild(f);

    try {
      var doc = f.contentWindow.document;
      doc.open();
      doc.write(slot.html);
      doc.close();
      if (slot.autoHeight) autoResize(f);
    } catch (e) {
      /* Red rara / bloqueador agresivo: el iframe queda vacío, sin romper nada. */
      if (window.console && console.warn) console.warn("[PMAds] no se pudo pintar", name, e);
    }
  }

  /* El widget nativo carga async: ajusta la altura del iframe a su contenido
   * durante los primeros segundos (mismo origen, podemos medirlo). */
  function autoResize(f) {
    var tries = 0;
    var t = setInterval(function () {
      tries++;
      try {
        var h = f.contentWindow.document.body.scrollHeight;
        if (h > 40 && Math.abs(h - parseFloat(f.style.height)) > 4) f.style.height = h + "px";
        if (tries >= 20) clearInterval(t);
      } catch (e) {
        clearInterval(t);
      }
    }, 400);
  }

  function scan(root) {
    var nodes = (root || document).querySelectorAll(".ad-wrap[data-ad-slot]");
    for (var i = 0; i < nodes.length; i++) render(nodes[i]);
  }

  /* Rescan con debounce cuando el DOM cambia (home/partidos/kiosco pintan tarde).
   * Es idempotente (__pmAd), así que re-observar nuestros propios iframes no cicla. */
  var t = null;
  function queue() {
    if (t) clearTimeout(t);
    t = setTimeout(function () {
      t = null;
      scan();
    }, 120);
  }

  function boot() {
    scan();
    if ("MutationObserver" in window) {
      new MutationObserver(queue).observe(document.documentElement, { childList: true, subtree: true });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  window.PMAds = { scan: scan };
})();
