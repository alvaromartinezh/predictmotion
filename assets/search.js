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
    var ab = initials(name), src = logo || (id ? 'https://a.espncdn.com/i/teamlogos/soccer/500/' + id + '.png' : '');
    if (!src) return '<div class="crest-ph">' + ab + '</div>';
    return '<img class="crest" loading="lazy" alt="" src="' + esc(src) + '" data-ab="' + ab + '" onerror="PMSearchCrestFallback(this)">';
  }
  var ICSEARCH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.2-3.2"/></svg>';
  var ARROW = '<span class="r-arrow">›</span>';

  var COMPS = ORDER.filter(function (s) { return L[s]; }).map(function (s) { return { slug: s, name: L[s].name, logo: L[s].logo, norm: norm(L[s].name + ' ' + s) }; });
  var TEAMS = [], teamsReady = false;

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

  function compRow(c) {
    return '<a class="search-row" href="/' + c.slug + '"><img class="lg-logo" src="' + esc(c.logo) + '" alt=""><span class="r-name">' + esc(c.name) + '</span>' + ARROW + '</a>';
  }
  function teamRow(t) {
    return '<a class="search-row" href="/equipo?id=' + encodeURIComponent(t.id) + '&league=' + encodeURIComponent(t.slug) + '&name=' + encodeURIComponent(t.name || '') + '">'
      + crest(t.logo, t.name, t.id) + '<span class="r-name">' + esc(t.name) + '</span><span class="r-tag">' + esc((L[t.slug] || {}).name || t.slug) + '</span>' + ARROW + '</a>';
  }
  function section(title, rowsHTML) { return '<div class="feed-sec"><h2 class="feed-sec__title">' + title + '</h2></div><section class="card">' + rowsHTML + '</section>'; }

  function results(q) {
    var out = document.getElementById('search-results'); if (!out) return;
    var nq = norm(q).trim();
    if (!nq) { out.innerHTML = section('Competiciones', COMPS.map(compRow).join('')); return; }
    var comps = COMPS.filter(function (c) { return c.norm.indexOf(nq) >= 0; });
    var teams = TEAMS.filter(function (t) { return t.norm.indexOf(nq) >= 0; }).slice(0, 30);
    var html = '';
    if (comps.length) html += section('Competiciones', comps.map(compRow).join(''));
    if (teams.length) html += section('Equipos', teams.map(teamRow).join(''));
    if (!html) html = '<p class="search-empty">' + (teamsReady ? 'Sin resultados para “' + esc(q) + '”.' : 'Buscando…') + '</p>';
    out.innerHTML = html;
  }

  function mainHTML() {
    return '<div class="feed"><div class="feed__col">'
      + '<div class="feed-sec" style="margin-top:var(--sp-2)"><h2 class="feed-sec__title">Buscar</h2></div>'
      + '<div class="search-box"><div class="search-field">' + ICSEARCH
      + '<input id="search-input" type="search" placeholder="Equipo o competición…" autocomplete="off" aria-label="Buscar">'
      + '<button class="search-clear" id="search-clear" type="button" aria-label="Limpiar" hidden>✕</button></div></div>'
      + '<div id="search-results"></div>'
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
    loadTeams().then(function () { if (qcur) results(qcur); });   // reevalúa si ya hay query
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  document.addEventListener('pm-account-ready', render);
})();
