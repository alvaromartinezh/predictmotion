/* PMArticles — listado de todos los artículos generados (/articulos):
 * broadsheets diarios, crónicas de partido y datos curiosos (ver CLAUDE.md
 * "Broadsheet diario de artículos" / "Crónica de partido" / STAT_KINDS).
 *
 * Lee /data/articles/index.json (lo escribe articles/generate.py cada vez
 * que publica algo) y pinta tarjetas .bscard (mismo componente que la del
 * broadsheet destacado en /noticias, ver assets/shell.css), reusando
 * .news-filters/.news-filter/.news-grid de assets/news.css (genéricos, sin
 * nada específico de noticias). Filtro por tipo. Degrada limpio si el JSON
 * no está o está vacío.
 */
(function () {
  "use strict";

  var DATA_URL = "/data/articles/index.json";
  var TIPOS = {
    diario: "Broadsheet diario",
    previa: "Previa del día",
    partido: "Crónica de partido",
    dato: "Dato curioso",
  };

  var state = { items: [], tipo: "all" };
  var els = {};

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fechaLabel(fecha) {
    try {
      var p = String(fecha || "").split("-");
      return new Date(+p[0], +p[1] - 1, +p[2]).toLocaleDateString("es-ES", {
        weekday: "long", day: "numeric", month: "long",
      });
    } catch (e) { return fecha || ""; }
  }

  function tiposPresent() {
    var seen = {};
    state.items.forEach(function (it) { seen[it.tipo] = true; });
    return ["diario", "previa", "partido", "dato"].filter(function (t) { return seen[t]; });
  }

  function renderFilters() {
    var parts = ['<button class="news-filter" data-tipo="all">Todos</button>'];
    tiposPresent().forEach(function (t) {
      parts.push('<button class="news-filter" data-tipo="' + t + '">' + esc(TIPOS[t] || t) + "</button>");
    });
    els.filters.innerHTML = parts.join("");
    Array.prototype.forEach.call(els.filters.querySelectorAll(".news-filter"), function (b) {
      b.classList.toggle("is-active", b.dataset.tipo === state.tipo);
      b.addEventListener("click", function () {
        state.tipo = b.dataset.tipo;
        renderFilters();
        renderList();
      });
    });
  }

  function cardHTML(it) {
    var league = (window.PM_LEAGUES && window.PM_LEAGUES[it.liga]) || {};
    return ''
      + '<a class="card card--link bscard" href="' + esc(it.url) + '">'
      + '  <div class="bscard__top">'
      + '    <span class="bscard__kicker">' + esc(TIPOS[it.tipo] || it.tipo) + '</span>'
      + '    <span class="bscard__league">' + esc(league.name || it.liga) + '</span>'
      + '  </div>'
      + '  <h3 class="bscard__title">' + esc((it.title || "").replace(" | PredictMotion", "")) + '</h3>'
      + '  <div class="bscard__foot">'
      + '    <span class="bscard__date">' + esc(fechaLabel(it.fecha)) + '</span>'
      + '    <span class="bscard__cta">Leer →</span>'
      + '  </div>'
      + '</a>';
  }

  function renderList() {
    var list = state.tipo === "all" ? state.items : state.items.filter(function (it) { return it.tipo === state.tipo; });
    if (!list.length) {
      els.mount.innerHTML = '<p class="news-empty">No hay artículos para este filtro ahora mismo.</p>';
      return;
    }
    els.mount.innerHTML = '<div class="news-grid">' + list.map(cardHTML).join("") + '</div>';
  }

  function fail(msg) {
    els.mount.innerHTML = '<p class="news-empty">' + esc(msg) + "</p>";
  }

  function init(opts) {
    opts = opts || {};
    els.mount = document.querySelector(opts.mount || "#articles-mount");
    els.filters = document.querySelector(opts.filters || "#articles-filters");
    if (!els.mount) return;

    fetch(DATA_URL, { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (items) {
        if (!Array.isArray(items) || !items.length) {
          if (els.filters) els.filters.innerHTML = "";
          return fail("Todavía no hay artículos publicados. Vuelve en un rato.");
        }
        state.items = items;
        if (els.filters) renderFilters();
        renderList();
      })
      .catch(function () {
        if (els.filters) els.filters.innerHTML = "";
        fail("No se han podido cargar los artículos.");
      });
  }

  window.PMArticles = { init: init };
})();
