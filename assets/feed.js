/* PMFeed — feed unificado de artículos propios + noticias agregadas (/kiosco).
 *
 * Mezcla:
 *   - /data/articles/index.json  (broadsheets, crónicas, datos curiosos)
 *   - /data/news/latest.json     (noticias RSS de medios españoles)
 *
 * y los ordena cronológicamente. El filtro por defecto es "Para ti": prioriza
 * el contenido de las ligas y equipos que sigue el usuario (vía PMAccount y
 * /api/follows). Sin sesión, el filtro por defecto es "Todos".
 *
 * Filtros disponibles: Para ti / Todos / Artículos / Noticias.
 * También se pueden filtrar por liga/equipo con chips secundarios.
 */
(function () {
  "use strict";

  var DATA_ARTICLES = "/data/articles/index.json";
  var DATA_NEWS = "/data/news/latest.json";
  var LEAGUE_NAMES = { laliga: "LaLiga", hypermotion: "Hypermotion" };

  var TIPOS = {
    diario: "Broadsheet diario",
    partido: "Crónica de partido",
    dato: "Dato curioso",
    news: "Noticia",
  };

  var state = {
    items: [],
    filter: "following", // following | all | articles | news
    league: "all",
    team: null,
    follows: null,
    loggedIn: false,
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

  function isFollowed(it) {
    if (!state.follows) return false;
    var comps = state.follows.competitions || [];
    var teams = state.follows.teams || [];
    var fav = state.follows.favorite_team;

    if (it.leagues && it.leagues.some(function (l) { return comps.indexOf(l) >= 0; })) return true;

    var teamIds = teams.map(function (t) { return String(t.espn_team_id); });
    if (fav && fav.espn_team_id) teamIds.push(String(fav.espn_team_id));

    if (it.teams && it.teams.some(function (t) {
      var id = String(t.id != null ? t.id : t.espn_team_id);
      return teamIds.indexOf(id) >= 0;
    })) return true;

    return false;
  }

  function matches(it) {
    if (state.filter === "articles") return it.kind === "article";
    if (state.filter === "news") return it.kind === "news";
    if (state.filter === "following") return isFollowed(it);
    return true;
  }

  function leaguesPresent() {
    var seen = {};
    state.items.forEach(function (it) {
      (it.leagues || []).forEach(function (l) { seen[l] = true; });
    });
    return ["laliga", "hypermotion"].filter(function (l) { return seen[l]; });
  }

  function teamsPresent() {
    var seen = {};
    state.items.forEach(function (it) {
      (it.teams || []).forEach(function (t) {
        var id = String(t.id != null ? t.id : t.espn_team_id);
        seen[id] = t;
      });
    });
    return Object.values(seen).sort(function (a, b) { return (a.name || "").localeCompare(b.name || "", "es"); });
  }

  function filteredItems() {
    return state.items
      .filter(matches)
      .filter(function (it) {
        if (state.league !== "all" && (it.leagues || []).indexOf(state.league) < 0) return false;
        if (state.team) {
          var tid = String(state.team);
          return (it.teams || []).some(function (t) { return String(t.id != null ? t.id : t.espn_team_id) === tid; });
        }
        return true;
      })
      .sort(function (a, b) { return (b.ts || 0) - (a.ts || 0); });
  }

  function renderFilters() {
    if (!els.filters) return;
    var tabs = [
      { key: "following", label: "Para ti", show: state.loggedIn },
      { key: "all", label: "Todos", show: true },
      { key: "articles", label: "Artículos", show: true },
      { key: "news", label: "Noticias", show: true },
    ];

    var parts = tabs
      .filter(function (t) { return t.show; })
      .map(function (t) {
        var active = state.filter === t.key ? " is-active" : "";
        return '<button class="news-filter' + active + '" data-filter="' + t.key + '">' + esc(t.label) + "</button>";
      });

    // Filtro por liga
    var leagues = leaguesPresent();
    if (leagues.length > 1) {
      parts.push('<span class="news-filter__sep" aria-hidden="true"></span>');
      parts.push('<button class="news-filter' + (state.league === "all" ? " is-active" : "") + '" data-league="all">Todas las ligas</button>');
      leagues.forEach(function (l) {
        var active = state.league === l ? " is-active" : "";
        parts.push('<button class="news-filter' + active + '" data-league="' + l + '">' + esc(LEAGUE_NAMES[l] || l) + "</button>");
      });
    }

    els.filters.innerHTML = parts.join("");

    Array.prototype.forEach.call(els.filters.querySelectorAll("[data-filter]"), function (b) {
      b.addEventListener("click", function () {
        state.filter = b.dataset.filter;
        renderFilters();
        renderList();
      });
    });

    Array.prototype.forEach.call(els.filters.querySelectorAll("[data-league]"), function (b) {
      b.addEventListener("click", function () {
        state.league = b.dataset.league;
        state.team = null;
        renderFilters();
        renderList();
      });
    });
  }

  function teamChips(it) {
    var teams = it.teams || [];
    if (!teams.length) return "";
    var chips = teams.slice(0, 3).map(function (t) {
      return '<span class="news-chip' + (String(state.team) === String(t.id != null ? t.id : t.espn_team_id) ? " is-active" : "") + '" data-team="' + esc(String(t.id != null ? t.id : t.espn_team_id)) + '">' + esc(t.name) + "</span>";
    });
    if (teams.length > 3) chips.push('<span class="news-chip is-more">+' + (teams.length - 3) + "</span>");
    return '<div class="news-card__tags">' + chips.join("") + "</div>";
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
      + teamChips(it)
      + '  <div class="bscard__foot">'
      + '    <span class="bscard__date">' + esc(fechaLabel(it.fecha)) + '</span>'
      + '    <span class="bscard__cta">Leer →</span>'
      + '  </div>'
      + '</a>';
  }

  function newsCardHTML(it) {
    var ago = timeAgo(it.ts);
    var src = esc(it.source || "Medio");
    return ''
      + '<article class="news-card">'
      + '  <div class="news-card__meta">'
      + '    <span class="news-card__src">' + src + '</span>'
      + (ago ? '<span class="news-card__time">' + esc(ago) + '</span>' : "")
      + '    <span class="news-card__badge">Noticia</span>'
      + '  </div>'
      + '  <h2 class="news-card__title"><a href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer nofollow">' + esc(it.title) + '</a></h2>'
      + (it.summary ? '<p class="news-card__summary">' + esc(it.summary) + '</p>' : "")
      + teamChips(it)
      + '  <a class="news-card__link" href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer nofollow">Leer en ' + src + ' <span aria-hidden="true">↗</span></a>'
      + '</article>';
  }

  function cardHTML(it) {
    return it.kind === "news" ? newsCardHTML(it) : articleCardHTML(it);
  }

  function renderList() {
    var list = filteredItems();
    if (!list.length) {
      var msg = "No hay contenido para este filtro ahora mismo.";
      if (state.filter === "following") {
        msg = state.loggedIn
          ? "No hay novedades de lo que sigues. Sigue más equipos o ligas para personalizar este feed."
          : "Inicia sesión para ver primero las noticias y artículos de tus equipos y ligas.";
      }
      els.mount.innerHTML = '<p class="news-empty">' + esc(msg) + "</p>";
      return;
    }
    els.mount.innerHTML = '<div class="news-grid">' + list.map(cardHTML).join("") + '</div>';

    // chips de equipo dentro de las tarjetas
    Array.prototype.forEach.call(els.mount.querySelectorAll(".news-chip[data-team]"), function (c) {
      c.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        state.team = c.dataset.team;
        renderFilters();
        renderList();
        if (els.mount.scrollIntoView) els.mount.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  function fail(msg) {
    state.loading = false;
    if (els.mount) els.mount.innerHTML = '<p class="news-empty">' + esc(msg) + "</p>";
  }

  function setAccountState() {
    var a = window.PMAccount;
    if (!a) {
      state.loggedIn = false;
      state.follows = null;
      state.filter = "all";
      return;
    }
    state.loggedIn = !!a.isLoggedIn && a.isLoggedIn();
    state.follows = (a.follows && a.follows()) || null;
    if (!state.loggedIn) state.filter = "all";
  }

  function load() {
    setAccountState();

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

    var a = window.PMAccount;
    if (a && a.pending && a.pending()) {
      // Hay cookie hint: esperar a que /api/me resuelva para no flashear
      // estado anónimo mientras el usuario está logueado.
      document.addEventListener("pm-account-ready", function once() {
        document.removeEventListener("pm-account-ready", once);
        load();
      });
    } else {
      load();
    }

    // Si los follows cambian mientras la página está abierta, recargar.
    document.addEventListener("pm-follows-changed", function () {
      setAccountState();
      if (els.filters) renderFilters();
      renderList();
    });
  }

  window.PMFeed = { init: init };
})();
