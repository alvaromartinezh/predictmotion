/* PM_ADS — configuración de banners de Adsterra (formato display/nativo).
 *
 * CÓMO USARLO: pega en `html` el código EXACTO que da Adsterra para cada
 * formato ("Banner" 300x250 o 728x90 — NUNCA Popunder/Push/Social Bar/
 * Interstitial/Vignette/Multitag: son los formatos intrusivos).
 *
 * El código se ejecuta dentro de un <iframe> aislado (ver ads.js): no toca
 * el DOM de la página y document.write funciona igual que en su ejemplo.
 *
 * Mientras `html` esté vacío (o contenga marcadores sin sustituir como
 * PON_TU_KEY), el hueco NO se pinta: cero espacio reservado, cera rastro visual.
 *
 * Bloqueo de categorías (adulto/dating, etc.) se hace en el PANEL de Adsterra:
 * Websites → tu sitio → Categories / Block categories. Aquí no hay control técnico.
 */
window.PM_ADS = {
  enabled: true,

  slots: {
    /* Formato universal inline — se usa en TODAS las páginas:
     * dashboards (tras la tabla), home, /partidos, /partido, /kiosco,
     * /equipo, /acerca. */
    box: {
      w: 300,
      h: 250,
      html: "" /* pega aquí el código del banner 300x250 */,
    },

    /* Solo escritorio (≥768px) — cabecera de los dashboards de liga. */
    leader: {
      w: 728,
      h: 90,
      html: "" /* pega aquí el código del banner 728x90 */,
    },

    /* Native Banner — tarjeta de contenido recomendado en /kiosco.
     * Ancho completo del feed y altura automática (el widget crece solo).
     * Layout del panel: 4:1, fuente heredada de la página. */
    native: {
      w: null,
      h: 260,
      autoHeight: true,
      html: '<script async="async" data-cfasync="false" src="https://pl30961780.profitableratecpmnetwork.com/0d6aacefc55ecd38bd08030a173a84c6/invoke.js"><\/script>\n<div id="container-0d6aacefc55ecd38bd08030a173a84c6"></div>',
    },
  },
};
