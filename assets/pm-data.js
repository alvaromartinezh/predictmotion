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

  // ── ESPN: calendario de un equipo (para su último/próximo/en vivo) ──
  function schedule(slug, teamId) {
    var code = codeOf(slug); if (!code || !teamId) return Promise.resolve([]);
    return memo('sch:' + code + ':' + teamId, function () {
      return getJSON(ESPN + code + '/teams/' + teamId + '/schedule').then(function (j) { return (j && j.events) || []; });
    });
  }
  // ── ESPN: marcador del día de una liga ──
  function scoreboard(slug, yyyymmdd) {
    var code = codeOf(slug); if (!code) return Promise.resolve([]);
    var u = ESPN + code + '/scoreboard' + (yyyymmdd ? '?dates=' + yyyymmdd : '');
    return memo('sb:' + u, function () { return getJSON(u).then(function (j) { return (j && j.events) || []; }); });
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

  // Elige el partido relevante de un equipo: en vivo > último jugado > próximo.
  function pickTeamMatch(events, slug) {
    var parsed = (events || []).map(function (e) { return parseEvent(e, slug); }).filter(Boolean);
    var live = parsed.filter(function (p) { return p.state === 'in'; });
    if (live.length) return live[0];
    var now = Date.now();
    var past = parsed.filter(function (p) { return p.state === 'post'; })
      .sort(function (a, b) { return new Date(b.date) - new Date(a.date); });
    if (past.length) return past[0];
    var future = parsed.filter(function (p) { return p.state === 'pre' && new Date(p.date) >= now - 6 * 3600e3; })
      .sort(function (a, b) { return new Date(a.date) - new Date(b.date); });
    return future[0] || parsed[0] || null;
  }

  window.PMData = {
    L: L, codeOf: codeOf,
    snapshot: snapshot, news: news, schedule: schedule, scoreboard: scoreboard,
    parseEvent: parseEvent, pickTeamMatch: pickTeamMatch
  };
})();
