/* PMLive — vista de partido en vivo.
   Consume el endpoint interno propio (NUNCA ESPN directamente). Render diferido
   (skeleton → datos) y polling mientras el partido está en vivo. Mismo patrón de
   módulo que PMFixtures/PMTabs.

   La LÓGICA (fetch, normalización, polling, pestañas, anuncios) no cambia: solo
   las plantillas de render emiten el marcado del diseño de partido.html. */
(function (w, d) {
  'use strict';

  // Base del API: en producción mismo origen (Caddy proxya /api/*); en local
  // (frontend en otro puerto) apunta al servicio en :8770.
  function apiBase() {
    if (w.PM_LIVE_API) return w.PM_LIVE_API;
    var h = location.hostname, p = location.port;
    if ((h === 'localhost' || h === '127.0.0.1') && p !== '8770') return 'http://127.0.0.1:8770/api/live';
    return '/api/live';
  }
  var API = apiBase();
  var POLL_MS = 20000;
  var league = '', eventId = '', timer = null;

  var LEAGUE_NAMES = { hypermotion: 'Liga Hypermotion', laliga: 'LaLiga', mundial: 'Mundial 2026' };
  function leagueName(slug) { return LEAGUE_NAMES[slug] || ''; }

  function qs(n) { return new URLSearchParams(location.search).get(n); }
  function getJSON(u) { return fetch(u, { cache: 'no-store' }).then(function (r) { return r.json(); }); }
  function esc(s) { var x = d.createElement('div'); x.textContent = (s == null ? '' : String(s)); return x.innerHTML; }
  function el(id) { return d.getElementById(id); }
  function pname(p) { return (p && p.athlete) ? (p.athlete.shortName || p.athlete.name) : ''; }
  function num(v) { return parseFloat(String(v).replace('%', '')) || 0; }

  // ── Arranque ────────────────────────────────────────────────────────────────
  function init() {
    league = qs('league'); eventId = qs('id');
    if (league) d.body.classList.add('theme-' + league);
    var back = el('back-link');
    if (back && league) { back.href = '/' + league; back.textContent = '← Volver a ' + (leagueName(league) || 'la competición'); }
    if (!league || !eventId) { unavailable('Partido no especificado.'); return; }

    getJSON(API + '/health').then(function (h) {
      if (!h || !h.ok || !h.enabled) { unavailable('El seguimiento en vivo no está disponible ahora mismo.'); return; }
      load(true);
    }).catch(function () { unavailable('El seguimiento en vivo no está disponible ahora mismo.'); });
  }

  function load(first) {
    getJSON(API + '/' + encodeURIComponent(league) + '/match/' + encodeURIComponent(eventId))
      .then(function (res) {
        if (!res || !res.ok || !res.match) { if (first) unavailable('No hay datos de este partido.'); return; }
        render(res.match);
        scheduleNext(res.match);
      })
      .catch(function () { if (first) unavailable('No se pudo cargar el partido.'); });
  }

  function scheduleNext(m) {
    clearTimeout(timer);
    if (m.status && m.status.state === 'in') timer = setTimeout(function () { load(false); }, POLL_MS);
  }

  function unavailable(msg) {
    var u = el('live-unavailable');
    if (u) { u.textContent = msg; u.style.display = ''; }
    var hdr = el('match-header'); if (hdr) hdr.innerHTML = '';
    var c = el('live-content'); if (c) c.style.display = 'none';
  }

  function render(m) {
    el('live-unavailable').style.display = 'none';
    el('live-content').style.display = '';
    renderHeader(m);
    renderLineups(m);
    renderTimeline(m);
    renderStats(m);
  }

  // ── Cabecera: marcador, minuto y probabilidad estimada ────────────────────
  function crest(team) {
    if (team.logo) return '<span class="sl-crest"><img src="' + esc(team.logo) + '" alt="" loading="lazy"></span>';
    return '<span class="sl-crest ph">' + esc(team.abbr || '') + '</span>';
  }
  function renderHeader(m) {
    var st = m.status || {};
    var pill;
    if (st.state === 'in') pill = '<span class="live-pill"><i></i>En vivo</span>';
    else if (st.state === 'post') pill = '<span>Final</span>';
    else pill = '<span>Por jugar</span>';
    var meta = '<div class="match-hd__meta">' + pill +
      (leagueName(m.league) ? '<span class="dot"></span><span>' + esc(leagueName(m.league)) + '</span>' : '') +
      '</div>';

    var clock = '';
    if (st.state === 'in') clock = '<div class="sl-clock">' + esc(st.minute || '') + '</div>';
    else if (st.state === 'post') clock = '<div class="sl-clock">Final</div>';

    var scoreline =
      '<div class="scoreline">' +
        '<div class="sl-team home"><div class="sl-meta"><div class="sl-name">' + esc(m.home.name || m.home.abbr) + '</div></div>' + crest(m.home) + '</div>' +
        '<div class="sl-center"><div class="sl-score"><span>' + esc(m.home.score) + '</span><span class="sep">·</span><span>' + esc(m.away.score) + '</span></div>' + clock + '</div>' +
        '<div class="sl-team away">' + crest(m.away) + '<div class="sl-meta"><div class="sl-name">' + esc(m.away.name || m.away.abbr) + '</div></div></div>' +
      '</div>';

    var winbar = '';
    var wp = m.winProbability;
    if (wp) {
      winbar =
        '<div class="winbar" aria-label="Probabilidad de resultado">' +
          '<div class="winbar__track">' +
            '<span class="winbar__seg h" style="width:' + wp.pHome + '%"></span>' +
            '<span class="winbar__seg d" style="width:' + wp.pDraw + '%"></span>' +
            '<span class="winbar__seg a" style="width:' + wp.pAway + '%"></span>' +
          '</div>' +
          '<div class="winbar__legend"><b>' + esc(m.home.abbr || m.home.name) + ' ' + wp.pHome + '%</b>' +
          '<span class="mid">Empate ' + wp.pDraw + '%</span>' +
          '<b>' + esc(m.away.abbr || m.away.name) + ' ' + wp.pAway + '%</b></div>' +
          (wp.note ? '<div class="winbar__note">' + esc(wp.note) + '</div>' : '') +
        '</div>';
    }
    el('match-header').innerHTML = '<div class="match-hd">' + meta + scoreline + winbar + '</div>';
  }

  // ── Alineación: campo + dos columnas, cruzado con eventos ─────────────────
  function sortedStarters(lineup) {
    return (lineup.starters || []).slice().sort(function (a, b) {
      return (a.formationPlace || 99) - (b.formationPlace || 99);
    });
  }
  function lineCounts(formation, n) {
    var parts = (formation || '').split('-').map(function (x) { return parseInt(x, 10); }).filter(function (x) { return x > 0; });
    var counts = parts.length ? [1].concat(parts) : null;
    var sum = counts ? counts.reduce(function (a, b) { return a + b; }, 0) : 0;
    return (counts && sum === n) ? counts : null;
  }
  function ppChip(p, side, x, t) {
    var badge = '';
    if (p.goals) badge = '<span class="pp__badge" title="Gol">⚽</span>';
    else if (p.red) badge = '<span class="pp__badge" style="background:var(--down)" title="Roja"></span>';
    else if (p.yellow) badge = '<span class="pp__badge yc" title="Amarilla"></span>';
    return '<div class="pp ' + side + '" style="left:' + x + '%;top:' + t + '%">' +
      '<div class="pp__dot">' + esc(p.jersey || '') + '</div>' +
      '<div class="pp__name">' + esc(pname(p)) + '</div>' + badge + '</div>';
  }
  function pitchPlayers(lineup, side) {
    var starters = sortedStarters(lineup);
    var counts = lineCounts(lineup.formation, starters.length);
    if (!counts) return null;
    var L = counts.length, html = '', idx = 0;
    for (var li = 0; li < L; li++) {
      var n = counts[li];
      var frac = L > 1 ? li / (L - 1) : 0;
      var t = side === 'home' ? (93 - frac * (93 - 55)) : (7 + frac * (47 - 7));
      for (var k = 0; k < n; k++) {
        var x = n === 1 ? 50 : (18 + k * (82 - 18) / (n - 1));
        html += ppChip(starters[idx++], side, x.toFixed(1), t.toFixed(1));
      }
    }
    return html;
  }
  var FIELD_MARKS =
    '<div class="pitch__halfway"></div><div class="pitch__mark pitch__circle"></div>' +
    '<div class="pitch__spot"></div><div class="pitch__mark pitch__box top"></div>' +
    '<div class="pitch__mark pitch__box bot"></div><div class="pitch__mark pitch__six top"></div>' +
    '<div class="pitch__mark pitch__six bot"></div>';

  function buildPitch(lu, m) {
    if (!lu.home || !lu.away) return '';
    var awayP = pitchPlayers(lu.away, 'away');
    var homeP = pitchPlayers(lu.home, 'home');
    if (awayP === null || homeP === null) return '';   // formación no resoluble → sin campo
    var forms = '<div class="pitch-forms">' +
      '<span class="pitch-form home"><i></i>' + esc(m.home.abbr || m.home.name) + ' <b>' + esc(lu.home.formation) + '</b></span>' +
      '<span class="pitch-form away"><b>' + esc(lu.away.formation) + '</b> ' + esc(m.away.abbr || m.away.name) + ' <i></i></span>' +
      '</div>';
    return '<div class="pitch-wrap">' + forms +
      '<div class="pitch" role="img" aria-label="Posiciones de ambos equipos sobre el campo">' +
      FIELD_MARKS + awayP + homeP + '</div></div>';
  }
  function playerEv(p) {
    var s = '';
    for (var i = 0; i < (p.goals || 0); i++) s += '<span class="ev-ic ev-goal" title="Gol">⚽</span>';
    if (p.yellow) s += '<span class="ev-yc" title="Amarilla"></span>';
    if (p.red) s += '<span class="ev-rc" title="Roja"></span>';
    if (p.subbedOut) s += '<span class="ev-ic ev-sub-out" title="Sustituido">↓</span><span class="player__min">' + esc(p.subbedOut) + '</span>';
    if (p.subbedIn) s += '<span class="player__min">' + esc(p.subbedIn) + '</span><span class="ev-ic ev-goal" title="Sustituto">↑</span>';
    return s ? '<span class="player__ev">' + s + '</span>' : '';
  }
  function playerRow(p) {
    var gk = p.formationPlace === 1 ? ' gk' : '';
    return '<div class="player' + gk + '"><span class="player__num">' + esc(p.jersey || '') + '</span>' +
      '<span class="player__name">' + esc(pname(p)) + '</span>' + playerEv(p) + '</div>';
  }
  function teamLineupBlock(lineup, team) {
    if (!lineup) return '';
    var cr = team.logo ? '<span class="lineup__crest"><img src="' + esc(team.logo) + '" alt=""></span>' : '<span class="lineup__crest ph"></span>';
    var head = '<div class="lineup__head">' + cr +
      '<div class="lineup__meta"><div class="lineup__team">' + esc(team.name || team.abbr) + '</div>' +
      '<div class="lineup__form">' + esc(lineup.formation || '—') + '</div></div></div>';
    var xi = '<div class="xi">' + sortedStarters(lineup).map(playerRow).join('') + '</div>';
    var subs = lineup.subs || [];
    var bench = subs.length ? '<div class="bench"><p class="bench__label">Suplentes</p>' + subs.map(playerRow).join('') + '</div>' : '';
    return '<div class="lineup ' + lineup.side + '">' + head + xi + bench + '</div>';
  }
  function renderLineups(m) {
    var lu = m.lineups || {};
    if (!lu.home && !lu.away) {
      el('lv-lineups').innerHTML = '<div class="lv-msg">Alineaciones no disponibles todavía.</div>';
      return;
    }
    var cols = teamLineupBlock(lu.home, m.home) + teamLineupBlock(lu.away, m.away);
    el('lv-lineups').innerHTML = buildPitch(lu, m) + '<div class="lineups">' + cols + '</div>';
  }

  // ── Minuto a minuto: timeline con espina central ──────────────────────────
  var EV_SVG = {
    GOAL: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7l2.5 2-1 3h-3l-1-3z"/></svg>',
    YELLOW: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="4" width="10" height="16" rx="1.5"/></svg>',
    RED: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="4" width="10" height="16" rx="1.5"/></svg>',
    SUB: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 7l-4 4 4 4"/><path d="M5 11h10"/><path d="M15 17l4-4-4-4"/><path d="M19 13H9"/></svg>'
  };
  var EV_ICCLS = { GOAL: 'ic-goal', YELLOW: 'ic-yc', RED: 'ic-rc', SUB: 'ic-sub' };
  function periodLabel(p) { return p >= 5 ? 'Penaltis' : p >= 3 ? 'Prórroga' : p === 2 ? '2ª parte' : '1ª parte'; }
  function evContent(e) {
    var t, desc = '';
    if (e.type === 'GOAL') { t = 'Gol · ' + pname(e.players[0]); if (e.players[1]) desc = 'Asistencia: ' + pname(e.players[1]); }
    else if (e.type === 'YELLOW') t = 'Amarilla · ' + pname(e.players[0]);
    else if (e.type === 'RED') t = 'Roja · ' + pname(e.players[0]);
    else if (e.type === 'SUB') { t = 'Cambio'; if (e.players[0]) desc = pname(e.players[0]) + (e.players[1] ? ' por ' + pname(e.players[1]) : ''); }
    else t = e.text || '';
    return '<div class="tl-body"><div class="tl-title">' + esc(t) + '</div>' +
      (desc ? '<div class="tl-desc">' + esc(desc) + '</div>' : '') + '</div>';
  }
  function timelineRow(e) {
    var side = e.teamSide === 'away' ? 'away' : 'home';
    var ic = '<span class="tl-ev-ic ' + (EV_ICCLS[e.type] || '') + '" aria-hidden="true">' + (EV_SVG[e.type] || '') + '</span>';
    var card = '<div class="tl-card' + (e.type === 'GOAL' ? ' tl-goal-card' : '') + '">' + ic + evContent(e) + '</div>';
    var min = '<div class="tl-min' + (e.type === 'GOAL' ? ' goal' : '') + '">' + esc(e.minute) + '</div>';
    return '<div class="tl-row ' + side + '">' + (side === 'home' ? card + min : min + card) + '</div>';
  }
  function renderTimeline(m) {
    var evs = (m.events || []).filter(function (e) { return e.type !== 'OTHER'; });
    if (!evs.length) { el('lv-timeline').innerHTML = '<div class="lv-msg">Aún no hay eventos.</div>'; return; }
    var rev = evs.slice().reverse(), out = '', lastP = null;
    rev.forEach(function (e) {
      if (e.period !== lastP) { out += '<div class="tl-divider"><span>' + periodLabel(e.period) + '</span></div>'; lastP = e.period; }
      out += timelineRow(e);
    });
    el('lv-timeline').innerHTML = '<div class="timeline">' + out + '</div>';
  }

  // ── Datos: posesión + barras divergentes ──────────────────────────────────
  function statRow(s) {
    var h = num(s.home), a = num(s.away), tot = h + a, hp = tot > 0 ? Math.round(h / tot * 100) : 50;
    var lh = h > a ? ' lead-h' : '', la = a > h ? ' lead-a' : '';
    return '<div class="stat"><div class="stat__top">' +
      '<span class="stat__val' + lh + '">' + esc(s.home) + '</span>' +
      '<span class="stat__label">' + esc(s.label) + '</span>' +
      '<span class="stat__val away' + la + '">' + esc(s.away) + '</span></div>' +
      '<div class="stat__bars"><span class="stat__bar home"><span class="stat__fill" style="width:' + hp + '%"></span></span>' +
      '<span class="stat__bar away"><span class="stat__fill" style="width:' + (100 - hp) + '%"></span></span></div></div>';
  }
  function renderStats(m) {
    var stats = m.stats || [];
    if (!stats.length) { el('lv-stats').innerHTML = '<div class="lv-msg">Estadísticas no disponibles todavía.</div>'; return; }
    var poss = null, others = [];
    stats.forEach(function (s) { if (s.key === 'possessionPct') poss = s; else others.push(s); });
    var legend = '<div class="stats-legend"><span class="sl-key home"><i></i>' + esc(m.home.abbr || m.home.name) +
      '</span><span class="sl-key away"><i></i>' + esc(m.away.abbr || m.away.name) + '</span></div>';
    var possHtml = '';
    if (poss) {
      var h = num(poss.home), a = num(poss.away), tot = h + a || 1, hp = Math.round(h / tot * 100);
      possHtml = '<div class="possession"><div class="poss__track">' +
        '<span class="poss__seg home" style="width:' + hp + '%">' + esc(poss.home) + '%</span>' +
        '<span class="poss__seg away" style="width:' + (100 - hp) + '%">' + esc(poss.away) + '%</span>' +
        '</div><p class="poss__label">Posesión</p></div>';
    }
    el('lv-stats').innerHTML = '<div class="stats-card">' + legend + possHtml + others.map(statRow).join('') + '</div>';
  }

  w.PMLive = { init: init };
})(window, document);
