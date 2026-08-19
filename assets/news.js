/* PMNews — tarjetas de noticias (consumidas por /kiosco y /equipo).
 *
 * Lee /data/news/latest.json (lo genera el cron `python -m news.aggregate`) y
 * pinta tarjetas con título, resumen corto, fuente (atribución) y etiquetas por
 * liga/equipo. Filtro por liga y por equipo (clic en chip). Degrada limpio si el
 * JSON no está o está vacío.
 *
 * Legal: solo se muestra lo que trae el JSON (título + resumen corto + enlace al
 * original + fuente). El enlace abre el artículo del medio en pestaña nueva.
 */
(function () {
  "use strict";

  var DATA_URL = "/data/news/latest.json";
  var LEAGUE_NAMES = { laliga: "LaLiga", hypermotion: "Hypermotion" };
  var MAX_TEAM_CHIPS = 3; // por tarjeta; el resto colapsa en "+N"

  var state = { items: [], league: "all", team: null };
  var els = {};

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function timeAgo(ts) {
    if (!ts) return "";
    var diff = Math.floor(Date.now() / 1000) - ts;
    if (diff < 60) return "ahora";
    if (diff < 3600) return "hace " + Math.floor(diff / 60) + " min";
    if (diff < 86400) return "hace " + Math.floor(diff / 3600) + " h";
    var d = Math.floor(diff / 86400);
    return "hace " + d + (d === 1 ? " día" : " días");
  }

  function leaguesPresent() {
    var seen = {};
    state.items.forEach(function (it) {
      (it.leagues || []).forEach(function (l) { seen[l] = true; });
    });
    // Orden estable conocido; solo las presentes.
    return ["laliga", "hypermotion"].filter(function (l) { return seen[l]; });
  }

  function matches(it) {
    if (state.league !== "all" && (it.leagues || []).indexOf(state.league) < 0)
      return false;
    if (state.team && !(it.teams || []).some(function (t) { return t.id === state.team; }))
      return false;
    return true;
  }

  function renderFilters() {
    var parts = ['<button class="news-filter" data-league="all">Todas</button>'];
    leaguesPresent().forEach(function (l) {
      parts.push('<button class="news-filter" data-league="' + l + '">'
        + esc(LEAGUE_NAMES[l] || l) + "</button>");
    });
    els.filters.innerHTML = parts.join("");
    Array.prototype.forEach.call(els.filters.querySelectorAll(".news-filter"), function (b) {
      b.classList.toggle("is-active", b.dataset.league === state.league);
      b.addEventListener("click", function () {
        state.league = b.dataset.league;
        state.team = null; // cambiar de liga limpia el filtro de equipo
        renderFilters();
        renderList();
      });
    });
  }

  function teamChips(it) {
    var teams = it.teams || [];
    if (!teams.length) return "";
    var shown = teams.slice(0, MAX_TEAM_CHIPS);
    var chips = shown.map(function (t) {
      return '<button class="news-chip" data-team="' + esc(t.id) + '">'
        + esc(t.name) + "</button>";
    });
    if (teams.length > shown.length)
      chips.push('<span class="news-chip is-more">+' + (teams.length - shown.length) + "</span>");
    return '<div class="news-card__tags">' + chips.join("") + "</div>";
  }

  function cardHTML(it) {
    var ago = timeAgo(it.ts);
    return ''
      + '<article class="news-card">'
      + '  <div class="news-card__meta"><span class="news-card__src">' + esc(it.source)
      + '</span>' + (ago ? '<span class="news-card__time">' + esc(ago) + "</span>" : "")
      + "  </div>"
      + '  <h2 class="news-card__title"><a href="' + esc(it.link)
      + '" target="_blank" rel="noopener noreferrer nofollow">' + esc(it.title) + "</a></h2>"
      + (it.summary ? '  <p class="news-card__summary">' + esc(it.summary) + "</p>" : "")
      + teamChips(it)
      + '  <a class="news-card__link" href="' + esc(it.link)
      + '" target="_blank" rel="noopener noreferrer nofollow">Leer en ' + esc(it.source)
      + ' <span aria-hidden="true">↗</span></a>'
      + "</article>";
  }

  function renderList() {
    var list = state.items.filter(matches);
    if (!list.length) {
      els.mount.innerHTML = '<p class="news-empty">No hay noticias para este filtro ahora mismo.</p>';
      return;
    }
    els.mount.innerHTML = list.map(cardHTML).join("");
    Array.prototype.forEach.call(els.mount.querySelectorAll(".news-chip[data-team]"), function (c) {
      c.addEventListener("click", function () {
        state.team = c.dataset.team;
        renderList();
        if (els.mount.scrollIntoView) els.mount.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  function fail(msg) {
    els.mount.innerHTML = '<p class="news-empty">' + esc(msg) + "</p>";
  }

  function init(opts) {
    opts = opts || {};
    els.mount = document.querySelector(opts.mount || "#news-mount");
    els.filters = document.querySelector(opts.filters || "#news-filters");
    if (!els.mount) return;

    fetch(DATA_URL, { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !Array.isArray(d.items) || !d.items.length) {
          if (els.filters) els.filters.innerHTML = "";
          return fail("Todavía no hay noticias disponibles. Vuelve en un rato.");
        }
        state.items = d.items;
        if (els.filters) renderFilters();
        renderList();
      })
      .catch(function () {
        if (els.filters) els.filters.innerHTML = "";
        fail("No se han podido cargar las noticias. Inténtalo más tarde.");
      });
  }

  window.PMNews = { init: init };
})();
