/* Proxy ESPN mismo-origen (fix 2026-08-12).
 * ESPN/Cloudflare devuelve 403 a los User-Agents de navegador (solo pasan
 * curl/python-urllib). Como el navegador no puede cambiar su UA, todo fetch a la
 * API de ESPN se reescribe a /api/espn/<host>/<path>, que el backend live_tracker
 * sirve con el UA por defecto de urllib (sí pasa) y mismo origen (sin CORS).
 * Cargar ANTES que cualquier otro script en cada página que lea ESPN desde el
 * navegador. NO parchear la URL de vuelta nunca: la API bloqueará el navegador.
 */
(function () {
  var nativeFetch = window.fetch;
  if (!nativeFetch || !window.URL) return;
  var HOSTS = {
    'site.api.espn.com': 1,
    'sports.core.api.espn.com': 1,
  };
  // Competiciones de SELECCIONES: se les añade `lang=es` porque ESPN traduce los
  // nombres de país (France → Francia, Czechia → Chequia) y la web es en español.
  // Va AQUÍ, el único punto por el que pasan todas las llamadas a ESPN del
  // navegador, para que clasificación, calendario y /partidos digan lo mismo.
  // Los CLUBES no se traducen a propósito: el cron SEO guarda sus snapshots con el
  // nombre por defecto de ESPN (y de ahí salen rows.html, artículos y tuits), así
  // que traducirlos solo en cliente los descuadraría. Espejo del `_SPANISH_LEAGUES`
  // de live_tracker/providers/espn.py, que sirve /partido.
  var ES_LANG = /\/soccer\/(uefa\.nations|concacaf\.nations\.league|caf\.nations_qual|fifa\.friendly)(\/|$)/;
  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : input && input.url;
    if (url) {
      try {
        var u = new URL(url, window.location.href);
        if (HOSTS[u.host]) {
          var search = u.search;
          if (ES_LANG.test(u.pathname) && search.indexOf('lang=') < 0) {
            search += (search ? '&' : '?') + 'lang=es';
          }
          input = '/api/espn/' + u.host + u.pathname + search;
        }
      } catch (e) {}
    }
    return nativeFetch.call(this, input, init);
  };
})();
