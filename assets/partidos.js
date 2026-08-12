/* Partidos (CP-R5) — todos los partidos del día por competición, con datos REALES
 * de ESPN (scoreboard vía PMData). Selector de día, filtro por competición y sección
 * "En vivo". SIN 1X2 por partido (D3): solo marcador/estado. Shell, pestaña 'matches'. */
(function () {
  'use strict';
  var L = window.PM_LEAGUES || {}, ORDER = window.PM_LEAGUES_ORDER || Object.keys(L), D = window.PMData;
  var DEFAULT = ['laliga', 'hypermotion', 'premier', 'seriea', 'bundesliga', 'ligue1'].filter(function (s) { return L[s]; });
  var DW = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];
  // Ligas con página de partido en vivo propia (/partido lo sirve el live_tracker,
  // que SOLO cubre estas): solo en ellas la fila entera es enlace. El resto de
  // ligas queda sin enlace (la fila es un <div>).
  var MATCH_LEAGUES = { hypermotion: 1, laliga: 1 };

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function initials(n) { var p = (n || '').trim().split(/\s+/).filter(Boolean); return ((p[0] || '?')[0] + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase(); }
  window.PMPartCrestFallback = function (img) { var d = document.createElement('div'); d.className = 'crest-ph'; d.textContent = img.getAttribute('data-ab') || '?'; img.parentNode.replaceChild(d, img); };
  function crest(logo, name, id) {
    var ab = initials(name), src = logo || (id ? 'https://a.espncdn.com/i/teamlogos/soccer/500/' + id + '.png' : '');
    if (!src) return '<div class="crest-ph">' + ab + '</div>';
    return '<img class="crest" loading="lazy" alt="" src="' + esc(src) + '" data-ab="' + ab + '" onerror="PMPartCrestFallback(this)">';
  }
  function ymd(d) { return d.getFullYear() + ('0' + (d.getMonth() + 1)).slice(-2) + ('0' + d.getDate()).slice(-2); }
  function ymdToInput(y) { return y.slice(0, 4) + '-' + y.slice(4, 6) + '-' + y.slice(6, 8); }   // YYYYMMDD → YYYY-MM-DD (input date)
  function humanDate(y) { try { return new Date(+y.slice(0, 4), +y.slice(4, 6) - 1, +y.slice(6, 8)).toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' }); } catch (e) { return 'este día'; } }
  function kick(iso) { try { return new Date(iso).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }); } catch (e) { return ''; } }
  function lname(s) { return (L[s] || {}).name || s; }
  function llogo(s) { return (L[s] || {}).logo || ''; }

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
    var buttons = DAYS.map(function (d) {
      return '<button class="day ' + (d.ymd === state.ymd ? 'is-on' : '') + '" type="button" data-ymd="' + d.ymd + '">'
        + '<span class="dw">' + d.dw + '</span><span class="dn">' + d.dn + '</span></button>';
    }).join('');
    // Fuera de la franja rápida (hoy-1…hoy+6): pastilla con la fecha elegida.
    var inStrip = DAYS.some(function (d) { return d.ymd === state.ymd; });
    var far = inStrip ? '' : '<button class="day is-on" type="button" data-ymd="' + state.ymd + '"><span class="dw">Fecha</span><span class="dn">' + (+state.ymd.slice(6, 8)) + '</span></button>';
    // Selector de fecha (nativo, oculto tras un icono) para saltar más allá de la franja.
    var picker = '<label class="day-pick" title="Ir a otra fecha">'
      + '<svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>'
      + '<input type="date" id="pm-datepick" aria-label="Elegir fecha" value="' + ymdToInput(state.ymd) + '"></label>';
    return '<div class="daystrip-row"><div class="daystrip">' + buttons + far + '</div>' + picker + '</div>';
  }
  function matchRow(m) {
    var inner;
    if (m.state === 'in') inner = '<span class="pm-time live"><i></i>' + esc(m.clock || m.detail || '') + '</span>';
    else if (m.state === 'post') inner = '<span class="pm-time ft">Final</span>';
    else inner = '<span class="pm-time">' + esc(kick(m.date)) + '</span>';
    // Los nombres de equipo NO enlazan (sin página de equipo desde aquí): la fila
    // entera es el botón que abre el partido en vivo (solo ligas con /partido
    // propio; el resto de ligas se queda sin enlace).
    function line(t, win) {
      return '<div class="pm-line ' + (m.state !== 'pre' && !win ? 'lose' : '') + '">' + crest(t.logo, t.name, t.id)
        + '<span class="name">' + esc(t.name) + '</span>' + (m.state === 'pre' ? '' : '<span class="sc">' + (t.score == null ? '-' : t.score) + '</span>') + '</div>';
    }
    var body = '<div class="pm-body">' + line(m.home, m.home.winner) + line(m.away, m.away.winner) + '</div>';
    var href = (MATCH_LEAGUES[m.slug] && m.id)
      ? '/partido?league=' + encodeURIComponent(m.slug) + '&id=' + encodeURIComponent(m.id) : '';
    return href
      ? '<a class="pm-row pm-row--link" href="' + href + '" title="Ver partido">' + inner + body + '</a>'
      : '<div class="pm-row">' + inner + body + '</div>';
  }
  function leagueGroup(slug, ms) {
    // El nombre de la liga es el botón que lleva a la clasificación de la liga.
    return '<div class="feed-sec"><h2 class="feed-sec__title"><a class="btn-league" href="/' + slug + '" title="Ver clasificación de ' + esc(lname(slug)) + '">'
      + '<img class="lg-logo" src="' + esc(llogo(slug)) + '" alt="" style="width:20px;height:20px"> ' + esc(lname(slug))
      + '<span class="btn-league__cta">Ver clasificación →</span>'
      + '</a></h2></div>'
      + '<section class="matchlist">' + ms.map(matchRow).join('') + '</section>';
  }

  function liveRail(live) {
    var rows = live.length ? live.map(function (m) {
      return '<div class="trend"><span class="rank" style="color:var(--live)">●</span>' + crest(m.home.logo, m.home.name, m.home.id)
        + '<span class="name">' + esc(initials(m.home.name)) + ' ' + (m.home.score == null ? 0 : m.home.score) + '-' + (m.away.score == null ? 0 : m.away.score) + ' ' + esc(initials(m.away.name)) + '</span>'
        + '<span class="val" style="color:var(--live)">' + esc(m.clock || '') + '</span></div>';
    }).join('') : '<p class="time">Sin partidos en vivo</p>';
    return '<div class="rail-card"><h4>En directo ahora</h4>' + rows + '</div>';
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
      var when = state.ymd === ymd(today) ? 'hoy' : 'el ' + humanDate(state.ymd);
      groups = '<article class="card"><div style="padding:var(--sp-7) var(--sp-5);text-align:center;color:var(--text-2)">No hay partidos ' + when + '. Prueba con otra fecha.</div></article>';
    } else {
      var liveSec = live.length ? ('<div class="feed-sec"><h2 class="feed-sec__title">En vivo <span class="tag tag--live">' + live.length + '</span></h2></div><section class="matchlist">' + live.map(matchRow).join('') + '</section>') : '';
      groups = liveSec + shown.map(function (s) { return leagueGroup(s, byLeague[s]); }).join('');
    }

    var col = '<div class="feed-sec" style="margin-top:var(--sp-2)"><h2 class="feed-sec__title">Partidos</h2></div>'
      + daystrip() + chips + groups;
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
    // Selector de fecha: salta a cualquier día fuera de la franja rápida.
    var dp = document.getElementById('pm-datepick');
    if (dp) {
      dp.addEventListener('click', function () { try { dp.showPicker(); } catch (e) {} });
      dp.addEventListener('change', function () {
        if (!dp.value) return;
        state.ymd = dp.value.replace(/-/g, ''); state.filter = 'all'; loadDay();
      });
    }
    var bar = document.getElementById('pm-filter');
    if (bar) bar.addEventListener('click', function (e) {
      var b = e.target.closest('.league-chip'); if (!b) return;
      state.filter = b.getAttribute('data-f'); renderMain();
    });
  }
  function start() { loadDay(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  document.addEventListener('pm-account-ready', loadDay);
  document.addEventListener('pm-follows-changed', loadDay);
})();
