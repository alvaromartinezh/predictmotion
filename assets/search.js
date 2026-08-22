/* Buscar (CP-R4) — búsqueda cliente sobre competiciones (PM_LEAGUES) y equipos
 * (índice construido de los snapshots /data/<slug>/latest.json). Enlaza a los
 * dashboards (/slug) y a /equipo. Se monta en el shell (PMShell), pestaña 'search'. */
(function () {
  'use strict';
  var L = window.PM_LEAGUES || {}, ORDER = window.PM_LEAGUES_ORDER || Object.keys(L), D = window.PMData;

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function norm(s) { return (s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }
  function initials(n) { var p = (n || '').trim().split(/\s+/).filter(Boolean); return ((p[0] || '?')[0] + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase(); }
  window.PMSearchCrestFallback = function (img) { var d = document.createElement('div'); d.className = 'crest-ph'; d.textContent = img.getAttribute('data-ab') || '?'; img.parentNode.replaceChild(d, img); };
  function crest(logo, name, id) {
    var ab = initials(name), sid = String(id || ''), src = (window.PM_TEAM_LOGOS && window.PM_TEAM_LOGOS[sid])
      || logo || (id ? 'https://a.espncdn.com/i/teamlogos/soccer/500/' + sid + '.png' : '');
    if (!src) return '<div class="crest-ph">' + ab + '</div>';
    return '<img class="crest" loading="lazy" alt="" src="' + esc(src) + '" data-ab="' + ab + '" onerror="PMSearchCrestFallback(this)">';
  }
  var ICSEARCH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.2-3.2"/></svg>';
  var ARROW = '<span class="pm-item__end"><span class="pm-item__arrow">›</span></span>';

  var COMPS = ORDER.filter(function (s) { return L[s]; }).map(function (s) { return { slug: s, name: L[s].name, logo: L[s].logo, country: L[s].country, norm: norm(L[s].name + ' ' + s) }; });
  var TEAMS = [], teamsReady = false;
  var PLAYERS = [], playersReady = false;

  function loadTeams() {
    if (!D) return Promise.resolve([]);
    return Promise.all(ORDER.map(function (s) { return D.snapshot(s); })).then(function (snaps) {
      // Dedup por IDENTIDAD de equipo (id ESPN), NO por (liga, id): un mismo club
      // (p. ej. Real Madrid, id 86) aparece en su liga doméstica Y en su competición
      // UEFA; debe salir UNA sola vez. ORDER pone las ligas domésticas antes que las
      // UEFA, así que el primero que se ve (y se conserva) es el doméstico → /equipo
      // abre con el contexto de liga correcto.
      var seen = {};
      snaps.forEach(function (snap, i) {
        if (!snap || !snap.teams) return;
        var slug = ORDER[i];
        snap.teams.forEach(function (t) {
          var key = String(t.id); if (seen[key]) return; seen[key] = 1;
          TEAMS.push({ id: t.id, name: t.name, logo: t.logo, slug: slug, norm: norm(t.name) });
        });
      });
      teamsReady = true; return TEAMS;
    });
  }

  function loadPlayers() {
    return fetch('/data/players/index.json', { cache: 'no-store' })
      .then(function(r) { if (!r.ok) return []; return r.json(); })
      .then(function(data) {
        PLAYERS = (data || []).map(function(p) {
          return { id: p.id, name: p.name, norm: norm(p.name), team: p.team, team_slug: p.team_slug, league: p.league, pos: p.pos, posLabel: p.posLabel, headshot: p.headshot };
        });
        playersReady = true; return PLAYERS;
      })
      .catch(function() { playersReady = true; return []; });
  }

  function compRow(c) {
    return '<a class="pm-item" href="/' + c.slug + '"><img class="lg-logo" src="' + esc(c.logo) + '" alt="">'
      + '<span class="pm-item__body"><span class="pm-item__title">' + esc(c.name) + '</span>'
      + (c.country ? '<span class="pm-item__sub">' + esc(c.country) + '</span>' : '') + '</span>' + ARROW + '</a>';
  }
  function teamRow(t) {
    return '<a class="pm-item pm-item--team" href="/equipo?id=' + encodeURIComponent(t.id) + '&league=' + encodeURIComponent(t.slug) + '&name=' + encodeURIComponent(t.name || '') + '">'
      + crest(t.logo, t.name, t.id) + '<span class="pm-item__body"><span class="pm-item__title">' + esc(t.name) + '</span>'
      + '<span class="pm-item__sub">' + esc((L[t.slug] || {}).name || t.slug) + '</span></span>' + ARROW + '</a>';
  }
  function playerRow(p) {
    var photo = p.headshot
      ? '<img class="crest" loading="lazy" alt="" src="' + esc(p.headshot) + '">'
      : '<div class="crest-ph">' + (p.name.charAt(0) || '?') + '</div>';
    return '<a class="pm-item pm-item--player" href="/jugador?id=' + encodeURIComponent(p.id) + '">'
      + photo + '<span class="pm-item__body"><span class="pm-item__title">' + esc(p.name) + '</span>'
      + '<span class="pm-item__sub">' + esc((p.posLabel || p.pos) + ' · ' + p.team) + '</span></span>' + ARROW + '</a>';
  }
  function section(title, rowsHTML) { return '<div class="feed-sec"><h2 class="feed-sec__title">' + title + '</h2></div><section class="pm-list">' + rowsHTML + '</section>'; }

  function results(q) {
    var out = document.getElementById('search-results'); if (!out) return;
    var nq = norm(q).trim();
    if (!nq) { out.innerHTML = section('Competiciones', COMPS.map(compRow).join('')); return; }
    var comps = COMPS.filter(function (c) { return c.norm.indexOf(nq) >= 0; });
    var teams = TEAMS.filter(function (t) { return t.norm.indexOf(nq) >= 0; }).slice(0, 30);
    var players = PLAYERS.filter(function (p) { return p.norm.indexOf(nq) >= 0; }).slice(0, 20);
    var html = '';
    if (comps.length) html += section('Competiciones', comps.map(compRow).join(''));
    if (teams.length) html += section('Equipos', teams.map(teamRow).join(''));
    if (players.length) html += section('Jugadores', players.map(playerRow).join(''));
    if (!html) html = '<p class="search-empty">' + ((teamsReady && playersReady) ? 'Sin resultados para "' + esc(q) + '".' : 'Buscando…') + '</p>';
    out.innerHTML = html;
  }

  function mainHTML() {
    return '<div class="feed"><div class="feed__col">'
      + '<div class="feed-sec" style="margin-top:var(--sp-2)"><h2 class="feed-sec__title">Buscar</h2></div>'
      + '<div class="search-box"><div class="search-field">' + ICSEARCH
      + '<input id="search-input" type="search" placeholder="Equipo, competición o jugador…" autocomplete="off" aria-label="Buscar">'
      + '<button class="search-clear" id="search-clear" type="button" aria-label="Limpiar" hidden>✕</button></div></div>'
      + '<div id="search-results"></div>'
      + '<div class="ad-wrap" data-ad-slot="box"></div>'
      + '</div><div class="feed__rail"></div></div>';
  }

  var qcur = '';
  function wire() {
    var inp = document.getElementById('search-input'), clr = document.getElementById('search-clear');
    if (!inp) return;
    inp.value = qcur;
    var t;
    inp.addEventListener('input', function () {
      qcur = inp.value; clr.hidden = !qcur;
      clearTimeout(t); t = setTimeout(function () { results(qcur); }, 120);
    });
    clr.addEventListener('click', function () { qcur = ''; inp.value = ''; clr.hidden = true; inp.focus(); results(''); });
    results(qcur);
  }

  function render() { window.PMShell.mount({ active: 'search', main: mainHTML(), onRender: wire }); }

  function start() {
    render();
    Promise.all([loadTeams(), loadPlayers()]).then(function () { if (qcur) results(qcur); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  document.addEventListener('pm-account-ready', render);
})();
