/* PMFeed — feed unificado de artículos propios + noticias agregadas (/kiosco).
 *
 * Lee:
 *   - /data/articles/index.json  (previas, resúmenes diarios, crónicas, datos curiosos)
 *   - /data/news/latest.json     (noticias RSS de medios españoles)
 *
 * Todo lo que se ve es de UN solo día (`state.day`, selector arriba —
 * `.daystrip`/`.day-pick`, reusando el mismo componente de /partidos): así se
 * puede ir día a día viendo qué datos curiosos, crónicas o resúmenes se
 * generaron cada jornada, en vez de mezclar piezas de días distintos.
 * "De PredictMotion" agrupa los artículos propios de ese día por tipo
 * (GROUP_ORDER); "Prensa deportiva" lista las noticias agregadas de ese
 * mismo día en orden cronológico.
 *
 * Único filtro además del día: liga (chips, solo si hay más de una presente).
 */
(function () {
  "use strict";

  var DATA_ARTICLES = "/data/articles/index.json";
  var DATA_NEWS = "/data/news/latest.json";
  var LEAGUE_NAMES = { laliga: "LaLiga", hypermotion: "Hypermotion" };
  var MAX_PER_GROUP = 12;
  var MAX_PRESS_ROWS = 40;
  var DAY_RANGE = 6; // días hacia atrás que muestra la tira rápida (hoy incluido = 7)
  var DW = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];

  function ymd(d) { return d.getFullYear() + ("0" + (d.getMonth() + 1)).slice(-2) + ("0" + d.getDate()).slice(-2); }
  function ymdToInput(y) { return y.slice(0, 4) + "-" + y.slice(4, 6) + "-" + y.slice(6, 8); } // YYYYMMDD -> YYYY-MM-DD

  var today = new Date(); today.setHours(12, 0, 0, 0);
  var DAYS = [];
  for (var _i = -DAY_RANGE; _i <= 0; _i++) {
    var _d = new Date(today); _d.setDate(today.getDate() + _i);
    DAYS.push({ ymd: ymd(_d), dw: (_i === 0 ? "Hoy" : DW[_d.getDay()]), dn: _d.getDate() });
  }
  var initialDay = (location.search.match(/[?&]date=(\d{8})/) || [])[1] || ymd(today);

  var TIPOS = {
    previa: "Previa del día",
    diario: "Resumen de jornada",
    partido: "Crónica de partido",
    dato: "Dato de la hora",
    news: "Noticia",
  };

  // Orden de aparición de "De PredictMotion" + su copy descriptivo (fijo,
  // no dato de negocio — los artículos de cada grupo sí son reales).
  var GROUP_ORDER = ["previa", "partido", "diario", "dato"];
  var GROUP_META = {
    previa: {
      title: "Qué esperar hoy",
      desc: "Antes de que arranque la jornada, un resumen de lo que se puede esperar de los partidos del día.",
      cadence: "08:00 · días de partido",
    },
    dato: {
      title: "Un equipo, un dato",
      desc: "Cada hora del día, una pieza corta sobre un dato de un equipo dentro de su liga.",
      cadence: "cada hora · 10:00–22:00",
    },
    partido: {
      title: "Nada más terminar",
      desc: "En cuanto acaba cada partido, una crónica con lo ocurrido y la lectura del modelo.",
      cadence: "al terminar cada partido",
    },
    diario: {
      title: "Cómo se ha movido",
      desc: "Cuando se han jugado los partidos del día, un cierre con lo ocurrido y cómo se han movido los pronósticos.",
      cadence: "23:00 · cierre del día",
    },
  };

  var state = {
    items: [],
    league: "all",
    day: initialDay, // YYYYMMDD
    loading: true,
  };

  var els = {};

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
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

  function fechaLabel(fecha) {
    try {
      var p = String(fecha || "").split("-");
      return new Date(+p[0], +p[1] - 1, +p[2]).toLocaleDateString("es-ES", {
        weekday: "long",
        day: "numeric",
        month: "long",
      });
    } catch (e) {
      return fecha || "";
    }
  }

  function fechaToTs(fecha) {
    try {
      var p = String(fecha || "").split("-");
      // mediodía para no desfasar por zona horaria
      return Math.floor(new Date(+p[0], +p[1] - 1, +p[2], 12, 0, 0).getTime() / 1000);
    } catch (e) {
      return 0;
    }
  }

  function tsToFecha(ts) {
    try {
      var d = new Date(ts * 1000);
      return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
    } catch (e) {
      return "";
    }
  }

  function normalizeArticles(items) {
    return (items || []).map(function (it) {
      var league = (window.PM_LEAGUES && window.PM_LEAGUES[it.liga]) || {};
      return {
        kind: "article",
        tipo: it.tipo,
        title: (it.title || "").replace(" | PredictMotion", ""),
        url: it.url,
        fecha: it.fecha,
        ts: fechaToTs(it.fecha),
        liga: it.liga,
        leagues: it.liga ? [it.liga] : [],
        teams: it.teams || [],
        source: "PredictMotion",
        leagueName: league.name || it.liga,
      };
    });
  }

  function normalizeNews(d) {
    return ((d && d.items) || []).map(function (it) {
      var liga = (it.leagues || [])[0];
      var league = (window.PM_LEAGUES && window.PM_LEAGUES[liga]) || {};
      return {
        kind: "news",
        tipo: "news",
        title: it.title,
        url: it.link,
        summary: it.summary,
        fecha: tsToFecha(it.ts),
        ts: it.ts || fechaToTs(tsToFecha(it.ts)),
        liga: liga,
        leagues: it.leagues || [],
        teams: it.teams || [],
        source: it.source,
        image: it.image,
        leagueName: league.name || liga,
      };
    });
  }

  function leaguesPresent() {
    var seen = {};
    state.items.forEach(function (it) {
      (it.leagues || []).forEach(function (l) { seen[l] = true; });
    });
    return ["laliga", "hypermotion"].filter(function (l) { return seen[l]; });
  }

  function filteredItems() {
    var dayDashed = ymdToInput(state.day);
    return state.items
      .filter(function (it) { return it.fecha === dayDashed; })
      .filter(function (it) {
        return state.league === "all" || (it.leagues || []).indexOf(state.league) >= 0;
      })
      .sort(function (a, b) { return (b.ts || 0) - (a.ts || 0); });
  }

  function daystripHTML() {
    var buttons = DAYS.map(function (d) {
      return '<button class="day' + (d.ymd === state.day ? " is-on" : "") + '" type="button" data-ymd="' + d.ymd + '">'
        + '<span class="dw">' + esc(d.dw) + '</span><span class="dn">' + d.dn + '</span></button>';
    }).join('');
    var inStrip = DAYS.some(function (d) { return d.ymd === state.day; });
    var far = inStrip ? '' : '<button class="day is-on" type="button" data-ymd="' + state.day + '"><span class="dw">Fecha</span><span class="dn">' + (+state.day.slice(6, 8)) + '</span></button>';
    var picker = '<label class="day-pick" title="Ir a otra fecha">'
      + '<svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>'
      + '<input type="date" id="pm-feed-datepick" aria-label="Elegir fecha" max="' + ymdToInput(ymd(today)) + '" value="' + ymdToInput(state.day) + '"></label>';
    return '<div class="daystrip-row"><div class="daystrip">' + buttons + far + '</div>' + picker + '</div>';
  }

  function renderFilters() {
    if (!els.filters) return;
    var parts = [];
    var leagues = leaguesPresent();
    if (leagues.length > 1) {
      parts.push('<button class="news-filter' + (state.league === "all" ? " is-active" : "") + '" data-league="all">Todas las ligas</button>');
      leagues.forEach(function (l) {
        var active = state.league === l ? " is-active" : "";
        parts.push('<button class="news-filter' + active + '" data-league="' + l + '">' + esc(LEAGUE_NAMES[l] || l) + "</button>");
      });
    }

    els.filters.innerHTML = daystripHTML() + (parts.length ? '<div class="news-filters">' + parts.join("") + '</div>' : '');

    Array.prototype.forEach.call(els.filters.querySelectorAll("[data-league]"), function (b) {
      b.addEventListener("click", function () {
        state.league = b.dataset.league;
        renderFilters();
        renderList();
      });
    });

    var strip = els.filters.querySelector(".daystrip");
    if (strip) strip.addEventListener("click", function (e) {
      var b = e.target.closest(".day");
      if (!b) return;
      state.day = b.getAttribute("data-ymd");
      renderFilters();
      renderList();
    });

    var dp = document.getElementById("pm-feed-datepick");
    if (dp) {
      dp.addEventListener("click", function () { try { dp.showPicker(); } catch (e) {} });
      dp.addEventListener("change", function () {
        if (!dp.value) return;
        state.day = dp.value.replace(/-/g, "");
        renderFilters();
        renderList();
      });
    }
  }

  function articleCardHTML(it) {
    var leagueName = esc(it.leagueName || it.liga);
    var tipoLabel = esc(TIPOS[it.tipo] || it.tipo);
    return ''
      + '<a class="card card--link bscard" href="' + esc(it.url) + '">'
      + '  <div class="bscard__top">'
      + '    <span class="bscard__kicker">' + tipoLabel + '</span>'
      + '    <span class="bscard__league">' + leagueName + '</span>'
      + '  </div>'
      + '  <h3 class="bscard__title">' + esc(it.title) + '</h3>'
      + '  <div class="bscard__foot">'
      + '    <span class="bscard__date">' + esc(fechaLabel(it.fecha)) + '</span>'
      + '    <span class="bscard__cta">Leer →</span>'
      + '  </div>'
      + '</a>';
  }

  function pressRowHTML(it) {
    var ago = timeAgo(it.ts);
    var src = esc(it.source || "Medio");
    return ''
      + '<a class="press-row" href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer nofollow">'
      + '  <span class="press-row__time">' + esc(ago) + '</span>'
      + '  <span class="press-row__title">' + esc(it.title) + '</span>'
      + '  <span class="press-row__source">' + src + '</span>'
      + '</a>';
  }

  function renderArticleSection(articles) {
    var byTipo = {};
    articles.forEach(function (it) { (byTipo[it.tipo] = byTipo[it.tipo] || []).push(it); });
    var present = GROUP_ORDER.filter(function (t) { return byTipo[t] && byTipo[t].length; });
    if (!present.length) return "";

    var groups = present.map(function (t) {
      var meta = GROUP_META[t];
      var items = byTipo[t].slice(0, MAX_PER_GROUP);
      return ''
        + '<div class="feed-group">'
        + '  <div class="feed-group__side">'
        + '    <span class="feed-group__chip">' + esc(TIPOS[t] || t) + '</span>'
        + '    <h3 class="feed-group__title">' + esc(meta.title) + '</h3>'
        + '    <p class="feed-group__desc">' + esc(meta.desc) + '</p>'
        + '    <div class="feed-group__cadence">' + esc(meta.cadence) + '</div>'
        + '  </div>'
        + '  <div class="feed-group__cards news-grid">' + items.map(articleCardHTML).join('') + '</div>'
        + '</div>';
    }).join('');

    return ''
      + '<section class="feed-section">'
      + '  <div class="feed-section__head">'
      + '    <div class="feed-section__title-row"><span class="feed-section__dot"></span><h2>De PredictMotion</h2></div>'
      + '    <span class="feed-section__meta">' + present.length + ' formatos · generado por el modelo</span>'
      + '  </div>'
      + '  <div class="feed-groups">' + groups + '</div>'
      + '</section>';
  }

  function renderPressSection(news) {
    var rows = news.slice(0, MAX_PRESS_ROWS).map(pressRowHTML).join('');
    return ''
      + '<section class="feed-section feed-section--press">'
      + '  <div class="feed-section__head">'
      + '    <div class="feed-section__title-row"><span class="feed-section__dot feed-section__dot--outline"></span><h2>Prensa deportiva</h2></div>'
      + '    <span class="feed-section__meta">Medios externos · sin editar</span>'
      + '  </div>'
      + '  <div class="press-list">' + rows + '</div>'
      + '</section>';
  }

  function renderList() {
    var list = filteredItems();
    var articles = list.filter(function (it) { return it.kind === "article"; });
    var news = list.filter(function (it) { return it.kind === "news"; });
    var html = renderArticleSection(articles) + renderPressSection(news);

    if (!html) {
      var when = state.day === ymd(today) ? "hoy" : "el " + fechaLabel(ymdToInput(state.day));
      var msg = "No hay contenido " + when + (state.league !== "all" ? " para " + esc(LEAGUE_NAMES[state.league] || state.league) : "") + ". Prueba con otro día.";
      els.mount.innerHTML = '<p class="news-empty">' + msg + "</p>";
      return;
    }
    els.mount.innerHTML = html;
  }

  function fail(msg) {
    state.loading = false;
    if (els.mount) els.mount.innerHTML = '<p class="news-empty">' + esc(msg) + "</p>";
  }

  function load() {
    Promise.all([
      fetch(DATA_ARTICLES, { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : []; }).catch(function () { return []; }),
      fetch(DATA_NEWS, { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
    ]).then(function (r) {
      var articles = normalizeArticles(r[0]);
      var news = normalizeNews(r[1] || {});
      state.items = articles.concat(news);
      state.loading = false;
      if (!state.items.length) {
        if (els.filters) els.filters.innerHTML = "";
        return fail("Todavía no hay contenido disponible. Vuelve en un rato.");
      }
      if (els.filters) renderFilters();
      renderList();
    }).catch(function () {
      fail("No se ha podido cargar el feed. Inténtalo más tarde.");
    });
  }

  function init(opts) {
    opts = opts || {};
    els.mount = document.querySelector(opts.mount || "#feed-mount");
    els.filters = document.querySelector(opts.filters || "#feed-filters");
    if (!els.mount) return;
    load();
  }

  window.PMFeed = { init: init };
})();
