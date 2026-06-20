/* PMLive — vista de partido en vivo.
   Consume el endpoint interno propio (NUNCA ESPN directamente). Render diferido
   (skeleton → datos) y polling mientras el partido está en vivo. Mismo patrón de
   módulo que PMFixtures/PMTabs. */
(function (w, d) {
  'use strict';

  // Base del API: en producción mismo origen (Caddy proxya /api/*); en local
  // (frontend en otro puerto) apunta al servicio en :8770. Override con
  // window.PM_LIVE_API si hace falta.
  function apiBase() {
    if (w.PM_LIVE_API) return w.PM_LIVE_API;
    var h = location.hostname, p = location.port;
    if ((h === 'localhost' || h === '127.0.0.1') && p !== '8770') return 'http://127.0.0.1:8770/api/live';
    return '/api/live';
  }
  var API = apiBase();
  var POLL_MS = 20000;
  var league = '', eventId = '', timer = null;

  function qs(n) { return new URLSearchParams(location.search).get(n); }
  function getJSON(u) { return fetch(u, { cache: 'no-store' }).then(function (r) { return r.json(); }); }
  function esc(s) { var x = d.createElement('div'); x.textContent = (s == null ? '' : String(s)); return x.innerHTML; }
  function el(id) { return d.getElementById(id); }

  // ── Arranque ────────────────────────────────────────────────────────────────
  function init() {
    league = qs('league'); eventId = qs('id');
    if (league) d.body.classList.add('theme-' + league);
    var back = el('back-link');
    if (back && league) back.href = '/' + league;
    if (!league || !eventId) { unavailable('Partido no especificado.'); return; }

    // Feature flag + disponibilidad: si está apagado o no responde, degrada.
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
  function teamSide(t, align) {
    var img = t.logo ? '<img class="lv-logo" src="' + esc(t.logo) + '" alt="" loading="lazy">' : '';
    return '<div class="lv-team ' + align + '">' + img +
      '<span class="lv-team-name">' + esc(t.name || t.abbr) + '</span></div>';
  }
  function statePill(st) {
    if (!st) return '';
    if (st.state === 'in') return '<span class="lv-state live"><span class="lv-dot"></span>' + esc(st.minute || 'En vivo') + '</span>';
    if (st.state === 'post') return '<span class="lv-state post">Final</span>';
    return '<span class="lv-state pre">Por jugar</span>';
  }
  function renderHeader(m) {
    var wp = m.winProbability;
    var bar = '';
    if (wp) {
      bar =
        '<div class="lv-wp">' +
        '<div class="lv-wp-title">' + esc(wp.note || 'Probabilidad estimada') + '</div>' +
        '<div class="lv-wp-bar">' +
        '<span class="seg home" style="width:' + wp.pHome + '%"></span>' +
        '<span class="seg draw" style="width:' + wp.pDraw + '%"></span>' +
        '<span class="seg away" style="width:' + wp.pAway + '%"></span>' +
        '</div>' +
        '<div class="lv-wp-legend">' +
        '<span><b>' + wp.pHome + '%</b> ' + esc(m.home.abbr) + '</span>' +
        '<span><b>' + wp.pDraw + '%</b> Empate</span>' +
        '<span>' + esc(m.away.abbr) + ' <b>' + wp.pAway + '%</b></span>' +
        '</div></div>';
    }
    el('match-header').innerHTML =
      '<div class="lv-scoreboard">' +
      teamSide(m.home, 'home') +
      '<div class="lv-center">' +
      '<div class="lv-score">' + esc(m.home.score) + '<span>–</span>' + esc(m.away.score) + '</div>' +
      statePill(m.status) +
      (m.stale ? '<div class="lv-stale">datos en diferido</div>' : '') +
      '</div>' +
      teamSide(m.away, 'away') +
      '</div>' + bar;
  }

  // ── Alineación: formación + suplentes, cruzada con eventos ─────────────────
  function playerIcons(p) {
    var s = '';
    for (var i = 0; i < (p.goals || 0); i++) s += '<span class="ic-goal" title="Gol">⚽</span>';
    if (p.yellow) s += '<span class="ic-yc" title="Amarilla"></span>';
    if (p.red) s += '<span class="ic-rc" title="Roja"></span>';
    if (p.subbedOut) s += '<span class="ic-out" title="Sustituido ' + esc(p.subbedOut) + '">▼</span>';
    return s;
  }
  function chip(p) {
    return '<div class="lv-chip">' +
      '<span class="lv-jersey">' + esc(p.jersey || '') + '</span>' +
      '<span class="lv-pname">' + esc(p.athlete.shortName || p.athlete.name) + '</span>' +
      '<span class="lv-icons">' + playerIcons(p) + '</span></div>';
  }
  function pitchLines(lineup) {
    // Líneas a partir de la formación ("4-4-2" → GK + 4 + 4 + 2). Si no cuadra,
    // se muestran los titulares en una rejilla simple.
    var starters = (lineup.starters || []).slice().sort(function (a, b) {
      return (a.formationPlace || 99) - (b.formationPlace || 99);
    });
    var parts = (lineup.formation || '').split('-').map(function (n) { return parseInt(n, 10); }).filter(function (n) { return n > 0; });
    var counts = parts.length ? [1].concat(parts) : null;
    var sum = counts ? counts.reduce(function (a, b) { return a + b; }, 0) : 0;
    if (!counts || sum !== starters.length) {
      return '<div class="lv-grid">' + starters.map(chip).join('') + '</div>';
    }
    var rows = '', k = 0;
    counts.forEach(function (c) {
      rows += '<div class="lv-line">' + starters.slice(k, k + c).map(chip).join('') + '</div>';
      k += c;
    });
    return '<div class="lv-pitch">' + rows + '</div>';
  }
  function teamLineup(lineup) {
    if (!lineup) return '';
    var subs = (lineup.subs || []).filter(function (p) { return p.subbedIn || p.goals || p.yellow || p.red; });
    var subsHtml = (lineup.subs || []).map(function (p) {
      var inTag = p.subbedIn ? '<span class="ic-in" title="Entró ' + esc(p.subbedIn) + '">▲ ' + esc(p.subbedIn) + '</span>' : '';
      return '<li>' + esc(p.athlete.shortName || p.athlete.name) + ' ' + inTag + playerIcons(p) + '</li>';
    }).join('');
    return '<div class="lv-lineup">' +
      '<div class="lv-lineup-head">' + esc(lineup.teamAbbr) + ' · <span>' + esc(lineup.formation || '—') + '</span></div>' +
      pitchLines(lineup) +
      '<div class="lv-subs"><div class="lv-subs-title">Suplentes</div><ul>' + subsHtml + '</ul></div>' +
      '</div>';
  }
  function renderLineups(m) {
    var lu = m.lineups || {};
    if (!lu.home && !lu.away) {
      el('lv-lineups').innerHTML = '<div class="lv-msg">Alineaciones no disponibles todavía.</div>';
      return;
    }
    el('lv-lineups').innerHTML =
      '<div class="lv-lineups">' + teamLineup(lu.home) + teamLineup(lu.away) + '</div>';
  }

  // ── Minuto a minuto: timeline de eventos ──────────────────────────────────
  var EV_ICON = { GOAL: '⚽', YELLOW: '🟨', RED: '🟥', SUB: '🔄' };
  function renderTimeline(m) {
    var evs = (m.events || []).filter(function (e) { return e.type !== 'OTHER'; });
    if (!evs.length) {
      el('lv-timeline').innerHTML = '<div class="lv-msg">Aún no hay eventos.</div>';
      return;
    }
    // Cronológico inverso (lo más reciente arriba).
    var rows = evs.slice().reverse().map(function (e) {
      var side = e.teamSide === 'away' ? 'away' : 'home';
      return '<div class="lv-ev ' + side + ' t-' + e.type + '">' +
        '<span class="lv-ev-min">' + esc(e.minute) + '</span>' +
        '<span class="lv-ev-ic">' + (EV_ICON[e.type] || '•') + '</span>' +
        '<span class="lv-ev-txt">' + esc(e.text) + '</span></div>';
    }).join('');
    el('lv-timeline').innerHTML = '<div class="lv-timeline">' + rows + '</div>';
  }

  // ── Datos: stats local vs visitante ───────────────────────────────────────
  function renderStats(m) {
    var stats = m.stats || [];
    if (!stats.length) {
      el('lv-stats').innerHTML = '<div class="lv-msg">Estadísticas no disponibles todavía.</div>';
      return;
    }
    var rows = stats.map(function (s) {
      var h = parseFloat(String(s.home).replace('%', '')) || 0;
      var a = parseFloat(String(s.away).replace('%', '')) || 0;
      var tot = h + a;
      var hp = tot > 0 ? Math.round(h / tot * 100) : 50;
      return '<div class="lv-stat">' +
        '<div class="lv-stat-row"><span class="hv">' + esc(s.home) + '</span>' +
        '<span class="lb">' + esc(s.label) + '</span>' +
        '<span class="av">' + esc(s.away) + '</span></div>' +
        '<div class="lv-stat-bar"><span class="h" style="width:' + hp + '%"></span>' +
        '<span class="a" style="width:' + (100 - hp) + '%"></span></div></div>';
    }).join('');
    el('lv-stats').innerHTML = '<div class="lv-stats">' + rows + '</div>';
  }

  w.PMLive = { init: init };
})(window, document);
