/* Partidos (CP-R5) — todos los partidos del día por competición, con datos REALES
 * de ESPN (scoreboard vía PMData). Selector de día, filtro por competición y sección
 * "En vivo". SIN 1X2 por partido (D3): solo marcador/estado. Shell, pestaña 'matches'. */
(function () {
  'use strict';
  var L = window.PM_LEAGUES || {}, ORDER = window.PM_LEAGUES_ORDER || Object.keys(L), D = window.PMData;
  var DEFAULT = ['laliga', 'hypermotion', 'premier', 'seriea', 'bundesliga', 'ligue1'].filter(function (s) { return L[s]; });
  var DW = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function initials(n) { var p = (n || '').trim().split(/\s+/).filter(Boolean); return ((p[0] || '?')[0] + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase(); }
  window.PMPartCrestFallback = function (img) { var d = document.createElement('div'); d.className = 'crest-ph'; d.textContent = img.getAttribute('data-ab') || '?'; img.parentNode.replaceChild(d, img); };
  function crest(logo, name, id) {
    var ab = initials(name), src = logo || (id ? 'https://a.espncdn.com/i/teamlogos/soccer/500/' + id + '.png' : '');
    if (!src) return '<div class="crest-ph">' + ab + '</div>';
    return '<img class="crest" loading="lazy" alt="" src="' + esc(src) + '" data-ab="' + ab + '" onerror="PMPartCrestFallback(this)">';
  }
  function ymd(d) { return d.getFullYear() + ('0' + (d.getMonth() + 1)).slice(-2) + ('0' + d.getDate()).slice(-2); }
  function kick(iso) { try { return new Date(iso).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }); } catch (e) { return ''; } }
  function lname(s) { return (L[s] || {}).name || s; }
  function llogo(s) { return (L[s] || {}).logo || ''; }
  // Ranura Adsterra real (PMAds; mid = rectángulo 300×250).
  var AD = '<div class="ad-wrap"><span class="ad-label">Publicidad</span><div class="ad-slot" data-ad-slot="mid"></div></div>';

  // ── días (hoy-1 … hoy+6). ?date=YYYYMMDD fija el día inicial (deep-link) ──
  var today = new Date(); today.setHours(12, 0, 0, 0);
  var DAYS = [];
  for (var i = -1; i <= 6; i++) { var d = new Date(today); d.setDate(today.getDate() + i); DAYS.push({ ymd: ymd(d), dw: (i === 0 ? 'Hoy' : DW[d.getDay()]), dn: d.getDate() }); }
  var initial = (location.search.match(/[?&]date=(\d{8})/) || [])[1] || ymd(today);

  var state = { ymd: initial, filter: 'all' };
  var byLeague = {};   // slug -> [matches] del día cargado

  // ── qué ligas mostrar ──
  function leagues() {
    var a = window.PMAccount;
    if (a && a.isEnabled && a.isEnabled() && a.isLoggedIn && a.isLoggedIn()) {
      var f = (a.follows && a.follows()) || {}; var set = {};
      (f.competitions || []).forEach(function (s) { if (L[s]) set[s] = 1; });
      (f.teams || []).forEach(function (t) { if (L[t.league_slug]) set[t.league_slug] = 1; });
      var ls = ORDER.filter(function (s) { return set[s]; });
      if (ls.length) return ls;
    }
    return DEFAULT;
  }

  // ── componentes ──
  function daystrip() {
    return '<div class="daystrip">' + DAYS.map(function (d) {
      return '<button class="day ' + (d.ymd === state.ymd ? 'is-on' : '') + '" type="button" data-ymd="' + d.ymd + '">'
        + '<span class="dw">' + d.dw + '</span><span class="dn">' + d.dn + '</span></button>';
    }).join('') + '</div>';
  }
  function matchRow(m) {
    var status;
    if (m.state === 'in') status = '<span class="pm-time live"><i></i>' + esc(m.clock || m.detail || '') + '</span>';
    else if (m.state === 'post') status = '<span class="pm-time ft">Final</span>';
    else status = '<span class="pm-time">' + esc(kick(m.date)) + '</span>';
    function line(t, win) {
      return '<div class="pm-line ' + (m.state !== 'pre' && !win ? 'lose' : '') + '">' + crest(t.logo, t.name, t.id)
        + '<span class="name">' + esc(t.name) + '</span>' + (m.state === 'pre' ? '' : '<span class="sc">' + (t.score == null ? '-' : t.score) + '</span>') + '</div>';
    }
    return '<div class="pm-row">' + status + '<div class="pm-body">' + line(m.home, m.home.winner) + line(m.away, m.away.winner) + '</div></div>';
  }
  function leagueGroup(slug, ms) {
    return '<div class="feed-sec"><h2 class="feed-sec__title"><img class="lg-logo" src="' + esc(llogo(slug)) + '" alt="" style="width:20px;height:20px"> ' + esc(lname(slug))
      + '</h2><a class="feed-sec__more" href="/' + slug + '">Clasificación</a></div>'
      + '<section class="matchlist">' + ms.map(matchRow).join('') + '</section>';
  }

  function liveRail(live) {
    var rows = live.length ? live.map(function (m) {
      return '<div class="trend"><span class="rank" style="color:var(--live)">●</span>' + crest(m.home.logo, m.home.name, m.home.id)
        + '<span class="name">' + esc(initials(m.home.name)) + ' ' + (m.home.score == null ? 0 : m.home.score) + '-' + (m.away.score == null ? 0 : m.away.score) + ' ' + esc(initials(m.away.name)) + '</span>'
        + '<span class="val" style="color:var(--live)">' + esc(m.clock || '') + '</span></div>';
    }).join('') : '<p class="time">Sin partidos en vivo</p>';
    return '<div class="rail-card"><h4>En directo ahora</h4>' + rows + '</div>' + AD;
  }

  function renderMain() {
    var ls = leagues();
    var present = ls.filter(function (s) { return (byLeague[s] || []).length; });
    var live = [];
    present.forEach(function (s) { (byLeague[s] || []).forEach(function (m) { if (m.state === 'in') live.push(m); }); });

    var chips = '';
    if (present.length) {
      chips = '<button class="league-chip ' + (state.filter === 'all' ? 'is-on' : '') + '" type="button" data-f="all">Todas</button>'
        + present.map(function (s) { return '<button class="league-chip ' + (state.filter === s ? 'is-on' : '') + '" type="button" data-f="' + s + '"><img src="' + esc(llogo(s)) + '" alt="">' + esc(lname(s)) + '</button>'; }).join('');
      chips = '<div class="league-chips" id="pm-filter">' + chips + '</div>';
    }

    var shown = present.filter(function (s) { return state.filter === 'all' || state.filter === s; });
    var groups;
    if (!present.length) {
      var dl = DAYS.filter(function (d) { return d.ymd === state.ymd; })[0];
      groups = '<article class="card"><div style="padding:var(--sp-7) var(--sp-5);text-align:center;color:var(--text-2)">No hay partidos ' + (dl ? (dl.dw === 'Hoy' ? 'hoy' : 'el ' + dl.dn) : 'este día') + '. Prueba con otra fecha.</div></article>';
    } else {
      var liveSec = live.length ? ('<div class="feed-sec"><h2 class="feed-sec__title">En vivo <span class="tag tag--live">' + live.length + '</span></h2></div><section class="matchlist">' + live.map(matchRow).join('') + '</section>') : '';
      groups = liveSec + shown.map(function (s) { return leagueGroup(s, byLeague[s]); }).join('');
    }

    var col = '<div class="feed-sec" style="margin-top:var(--sp-2)"><h2 class="feed-sec__title">Partidos</h2></div>'
      + daystrip() + chips + groups + AD;
    window.PMShell.mount({ active: 'matches', main: '<div class="feed"><div class="feed__col">' + col + '</div><div class="feed__rail">' + liveRail(live) + '</div></div>', onRender: wire });
  }

  var loadTok = 0;
  function loadDay() {
    var my = ++loadTok, ls = leagues();
    // esqueleto inmediato del día (sin datos) para que el cambio de día responda ya
    byLeague = {}; renderMain();
    Promise.all(ls.map(function (s) {
      return D.scoreboard(s, state.ymd).then(function (evs) { return { s: s, ms: (evs || []).map(function (e) { return D.parseEvent(e, s); }).filter(Boolean) }; });
    })).then(function (res) {
      if (my !== loadTok) return;
      byLeague = {}; res.forEach(function (r) { byLeague[r.s] = r.ms; });
      renderMain();
    });
  }

  function wire() {
    var strip = document.querySelector('.daystrip');
    if (strip) strip.addEventListener('click', function (e) {
      var b = e.target.closest('.day'); if (!b) return;
      state.ymd = b.getAttribute('data-ymd'); state.filter = 'all'; loadDay();
    });
    var bar = document.getElementById('pm-filter');
    if (bar) bar.addEventListener('click', function (e) {
      var b = e.target.closest('.league-chip'); if (!b) return;
      state.filter = b.getAttribute('data-f'); renderMain();
    });
    if (window.PMAds) window.PMAds.init();   // re-inicia banners tras cada render
  }

  function start() { loadDay(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  document.addEventListener('pm-account-ready', loadDay);
  document.addEventListener('pm-follows-changed', loadDay);
})();
