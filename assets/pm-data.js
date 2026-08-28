/* PMData — capa de acceso a datos REALES del home del rediseño (CP-R2).
 * Fuentes de producción existentes:
 *   - follows: PMAccount (/api/follows)
 *   - clasificación/probabilidades: /data/<slug>/latest.json (snapshot del cron)
 *   - resultado/último/en vivo: ESPN (schedule/scoreboard) — mismo patrón que fixtures.js
 *   - noticias: /data/news/latest.json (agregador RSS; sin imagen por diseño legal)
 * Todo defensivo: si una fuente falla, devuelve null/[] y el home degrada.
 */
(function () {
  'use strict';
  var ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer/';
  var ESPN_V2 = 'https://site.api.espn.com/apis/v2/sports/soccer/';   // clasificación
  var L = window.PM_LEAGUES || {};
  var cache = {};

  function getJSON(url, opts) {
    return fetch(url, opts || { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }
  function memo(key, fn) {
    if (cache[key] !== undefined) return Promise.resolve(cache[key]);
    return fn().then(function (v) { cache[key] = v; return v; });
  }
  function codeOf(slug) { return (L[slug] || {}).code; }
  // Base del backend live_tracker (mismo criterio que assets/live.js: local con
  // frontend en otro puerto → :8770 directo; producción → mismo origen vía Caddy).
  function liveApiBase() {
    if (window.PM_LIVE_API) return window.PM_LIVE_API;
    var h = location.hostname, p = location.port;
    if ((h === 'localhost' || h === '127.0.0.1') && p !== '8770') return 'http://127.0.0.1:8770/api/live';
    return '/api/live';
  }
  // ── live_tracker: detalle de un partido (probabilidad 1X2 + colores de equipo) ──
  function liveMatch(slug, eventId) {
    if (!slug || !eventId) return Promise.resolve(null);
    return getJSON(liveApiBase() + '/' + encodeURIComponent(slug) + '/match/' + encodeURIComponent(eventId))
      .then(function (r) { return (r && r.ok && r.match) ? r.match : null; });
  }

  // ── snapshot (clasificación + probabilidades por equipo) ──
  function snapshot(slug) {
    return memo('snap:' + slug, function () { return getJSON('/data/' + slug + '/latest.json'); });
  }

  // ── noticias (todas; con tags teams[]/leagues[]) ──
  function news() {
    return memo('news', function () {
      return getJSON('/data/news/latest.json').then(function (j) { return (j && j.items) || (Array.isArray(j) ? j : []) || []; });
    });
  }

  // ── broadsheet diario (pointer al último artículo publicado) ──
  function articles() {
    return memo('articles', function () {
      return getJSON('/data/articles/latest.json');
    });
  }

  // ── índice de artículos (todos los tipos: diario/previa/dato/partido) ──
  function articlesIndex() {
    return memo('articlesIndex', function () {
      return getJSON('/data/articles/index.json').then(function (j) { return j || []; });
    });
  }
  // ── previa diaria más reciente de una liga (tipo "previa" en el índice) ──
  function previaArticle(slug) {
    if (!slug) return Promise.resolve(null);
    return articlesIndex().then(function (items) {
      return (items || []).filter(function (it) { return it.tipo === 'previa' && it.liga === slug; })[0] || null;
    });
  }

  function ymd(iso) { var d = new Date(iso); return d.getFullYear() + ('0' + (d.getMonth() + 1)).slice(-2) + ('0' + d.getDate()).slice(-2); }
  // ── ESPN: TODOS los partidos de la temporada de una liga (rango del `calendar`
  // del scoreboard) — mismo patrón que assets/fixtures.js. Sirve de fallback cuando
  // el endpoint por equipo viene vacío (ver más abajo).
  function seasonEvents(slug) {
    var code = codeOf(slug); if (!code) return Promise.resolve([]);
    return memo('season:' + code, function () {
      return getJSON(ESPN + code + '/scoreboard').then(function (sb) {
        var cal = (((sb && sb.leagues) || [])[0] || {}).calendar || [];
        cal = cal.filter(function (x) { return typeof x === 'string'; });
        if (!cal.length) return (sb && sb.events) || [];
        return getJSON(ESPN + code + '/scoreboard?dates=' + ymd(cal[0]) + '-' + ymd(cal[cal.length - 1]) + '&limit=700')
          .then(function (d) { return (d && d.events) || []; });
      });
    });
  }
  // ── ESPN: calendario de un equipo (para su último/próximo/en vivo) ──
  // El endpoint por equipo puede venir sin ningún partido pendiente (visto en
  // vivo el 2026-08-28: solo devuelve los 2 últimos jugados, todos `post`, sin
  // el próximo) aunque la liga siga en juego — ESPN no lo repuebla siempre a
  // tiempo. No basta con mirar si el array está vacío: hay que comprobar que
  // trae algo pendiente/en vivo. Si no, se filtra del calendario completo de
  // la liga (si tiene próximo partido, ahí sí sale).
  function schedule(slug, teamId) {
    var code = codeOf(slug); if (!code || !teamId) return Promise.resolve([]);
    return memo('sch:' + code + ':' + teamId, function () {
      return getJSON(ESPN + code + '/teams/' + teamId + '/schedule').then(function (j) {
        var evs = (j && j.events) || [];
        var hasUpcoming = evs.some(function (e) {
          var st = ((e.status || ((e.competitions || [])[0] || {}).status || {}).type || {}).state;
          return st === 'pre' || st === 'in';
        });
        if (hasUpcoming) return evs;
        return seasonEvents(slug).then(function (all) {
          return all.filter(function (e) {
            var cs = (((e.competitions || [])[0] || {}).competitors) || [];
            return cs.some(function (c) { return String((c.team || {}).id) === String(teamId); });
          });
        });
      });
    });
  }
  // ── ESPN: marcador del día de una liga ──
  function scoreboard(slug, yyyymmdd) {
    var code = codeOf(slug); if (!code) return Promise.resolve([]);
    var u = ESPN + code + '/scoreboard' + (yyyymmdd ? '?dates=' + yyyymmdd : '');
    return memo('sb:' + u, function () { return getJSON(u).then(function (j) { return (j && j.events) || []; }); });
  }

  // ── ESPN: clasificación REAL de una liga, con los partidos en juego aplicados ──
  // El snapshot del cron se queda congelado durante un partido (y hasta 3 h después
  // de acabar), así que las tablas del home enseñaban posiciones viejas mientras la
  // página de liga ya mostraba las provisionales. Mismo cálculo que los dashboards:
  // clasificación de ESPN + puntos provisionales de los partidos `in` + reordenar.
  // Devuelve null si ESPN falla → quien llama se queda con el snapshot.
  function liveTable(slug) {
    var code = codeOf(slug); if (!code) return Promise.resolve(null);
    // Scoreboard SIN fecha: el "hoy" lo decide ESPN, como en los dashboards. Con la
    // fecha del reloj del visitante, quien va por delante del huso de la jornada (o
    // mira pasada su medianoche) pedía el día equivocado y no veía ningún directo.
    // Sin memo: la home no hace polling, pero así un re-render (cambio de follows)
    // trae el marcador de ese momento y no el de la carga.
    return Promise.all([
      getJSON(ESPN_V2 + code + '/standings'),
      scoreboard(slug),
    ]).then(function (r) {
      var entries = r[0] && r[0].children && r[0].children[0]
        && r[0].children[0].standings && r[0].children[0].standings.entries;
      if (!entries || !entries.length) return null;
      var rows = entries.map(function (e, i) {
        function stat(n) { return ((e.stats || []).filter(function (s) { return s.name === n; })[0] || {}).value || 0; }
        var t = e.team || {}, tId = String(t.id || '');
        return {
          rank: i + 1, id: tId, name: t.displayName || t.shortDisplayName || '',
          logo: (window.PM_TEAM_LOGOS && window.PM_TEAM_LOGOS[tId])
            || (t.logos && t.logos[0] && t.logos[0].href) || t.logo || '',
          gp: stat('gamesPlayed'), pts: stat('points'),
          gf: stat('pointsFor'), gc: stat('pointsAgainst'), live: null,
        };
      });
      var byId = {}; rows.forEach(function (t) { byId[t.id] = t; });
      var any = false;
      (r[1] || []).forEach(function (ev) {
        var m = parseEvent(ev, slug);
        if (!m || m.state !== 'in' || m.home.score == null || m.away.score == null) return;
        var h = byId[m.home.id], a = byId[m.away.id]; if (!h || !a) return;
        var hp = m.home.score > m.away.score ? 3 : m.home.score === m.away.score ? 1 : 0;
        var ap = m.away.score > m.home.score ? 3 : (hp === 1 ? 1 : 0);
        h.pts += hp; h.gp += 1; h.gf += m.home.score; h.gc += m.away.score;
        a.pts += ap; a.gp += 1; a.gf += m.away.score; a.gc += m.home.score;
        h.live = { eventId: m.id, res: hp === 3 ? 'win' : hp === 1 ? 'draw' : 'loss' };
        a.live = { eventId: m.id, res: ap === 3 ? 'win' : ap === 1 ? 'draw' : 'loss' };
        any = true;
      });
      if (any) {
        rows.sort(function (x, y) {
          return y.pts !== x.pts ? y.pts - x.pts
            : (y.gf - y.gc) !== (x.gf - x.gc) ? (y.gf - y.gc) - (x.gf - x.gc) : y.gf - x.gf;
        });
        rows.forEach(function (t, i) { t.rank = i + 1; });
      }
      return rows;
    });
  }

  // Normaliza un event de ESPN (schedule o scoreboard) a nuestro modelo mínimo.
  function parseEvent(ev, slug) {
    var comp = (ev.competitions || [])[0]; if (!comp) return null;
    var cs = comp.competitors || [];
    var home = cs.filter(function (c) { return c.homeAway === 'home'; })[0] || cs[0];
    var away = cs.filter(function (c) { return c.homeAway === 'away'; })[0] || cs[1];
    if (!home || !away) return null;
    // score: scoreboard lo da como string; schedule como objeto {value,displayValue,winner}.
    function scoreVal(c) {
      var s = c.score; if (s == null) return null;
      if (typeof s === 'object') return s.value != null ? Math.round(s.value) : (s.displayValue != null ? parseInt(s.displayValue, 10) : null);
      var n = parseInt(s, 10); return isNaN(n) ? null : n;
    }
    function winnerOf(c) { return c.winner === true || !!(c.score && typeof c.score === 'object' && c.score.winner === true); }
    function side(c) {
      var t = c.team || {};
      var tId = String(t.id || '');
      return {
        id: tId, name: t.displayName || t.shortDisplayName || '',
        logo: (window.PM_TEAM_LOGOS && window.PM_TEAM_LOGOS[tId])
          || (t.logos && t.logos[0] && t.logos[0].href) || t.logo || '',
        score: scoreVal(c), winner: winnerOf(c)
      };
    }
    var st = (ev.status || comp.status || {}).type || {};
    return {
      id: String(ev.id || comp.id || ''),
      slug: slug,
      date: ev.date || comp.date,
      state: st.state || 'pre',                 // 'pre' | 'in' | 'post'
      clock: (ev.status || comp.status || {}).displayClock || '',
      detail: st.shortDetail || '',
      home: side(home), away: side(away)
    };
  }

  // Elige el partido relevante de un equipo: en vivo > el más cercano en el tiempo
  // entre el último jugado y el próximo (el que quede más cerca de "ahora").
  function pickTeamMatch(events, slug) {
    var parsed = (events || []).map(function (e) { return parseEvent(e, slug); }).filter(Boolean);
    var live = parsed.filter(function (p) { return p.state === 'in'; });
    if (live.length) return live[0];
    var now = Date.now();
    var past = parsed.filter(function (p) { return p.state === 'post'; })
      .sort(function (a, b) { return new Date(b.date) - new Date(a.date); })[0];
    var future = parsed.filter(function (p) { return p.state === 'pre'; })
      .sort(function (a, b) { return new Date(a.date) - new Date(b.date); })[0];
    if (!past) return future || parsed[0] || null;
    if (!future) return past;
    var dPast = now - new Date(past.date), dFuture = new Date(future.date) - now;
    return dFuture < dPast ? future : past;
  }

  window.PMData = {
    L: L, codeOf: codeOf,
    snapshot: snapshot, news: news, articles: articles, articlesIndex: articlesIndex, previaArticle: previaArticle,
    schedule: schedule, scoreboard: scoreboard,
    liveTable: liveTable, liveMatch: liveMatch,
    parseEvent: parseEvent, pickTeamMatch: pickTeamMatch
  };
})();
