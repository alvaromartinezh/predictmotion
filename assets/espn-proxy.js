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
  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : input && input.url;
    if (url) {
      try {
        var u = new URL(url, window.location.href);
        if (HOSTS[u.host]) {
          input = '/api/espn/' + u.host + u.pathname + u.search;
        }
      } catch (e) {}
    }
    return nativeFetch.call(this, input, init);
  };
})();
