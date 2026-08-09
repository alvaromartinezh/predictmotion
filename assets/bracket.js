/* PredictMotion — Cuadro de eliminatoria RADIAL (concéntrico) para las competiciones
   UEFA. SOLO VISUALIZACIÓN de los cruces reales de ESPN (octavos en adelante); NO
   calcula probabilidades.

   Rediseño (CP-bracket): cada EQUIPO es un escudo circular. Anillos concéntricos de
   fuera (octavos, 16 escudos) hacia dentro (cuartos 8 → semis 4 → finalistas 2 →
   CAMPEÓN en el disco central). Los cruces se dibujan con líneas: la del ganador
   AVANZA hacia el centro con brillo esmeralda/cian; el enfrentamiento del cruce va en
   una línea tenue. Sobre negro, sin scroll horizontal (SVG cuadrado que escala).

   Datos: scoreboard de ESPN de toda la temporada, filtrado a las rondas de
   eliminatoria por `event.season.slug`. Cada cruce junta 1ª+2ª mano; el ganador sale
   de la nota "X advance … on aggregate" / "… on penalties" (o del flag de ESPN para
   el partido único de la final). El árbol se reconstruye enlazando ganador→siguiente
   ronda. Todo en vivo, sin hardcode. */
(function () {
  'use strict';
  var ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer/';
  var ORDER = ['round-of-16', 'quarterfinals', 'semifinals', 'final'];
  var LABEL = { 'round-of-16': 'Octavos', 'quarterfinals': 'Cuartos', 'semifinals': 'Semifinales', 'final': 'Final' };

  function getJSON(u) {
    return fetch(u, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('ESPN ' + r.status); return r.json();
    });
  }

  // ── Parseo: eventos → rondas → cruces ──────────────────────────────────────
  function collectTies(events) {
    var byRound = {}; ORDER.forEach(function (r) { byRound[r] = {}; });
    (events || []).forEach(function (e) {
      var slug = (e.season || {}).slug || '';
      if (ORDER.indexOf(slug) < 0) return;
      var comp = (e.competitions || [])[0]; if (!comp) return;
      var cs = comp.competitors || [];
      var home = cs.filter(function (c) { return c.homeAway === 'home'; })[0];
      var away = cs.filter(function (c) { return c.homeAway === 'away'; })[0];
      if (!home || !away) return;
      function tm(c) {
        var t = c.team || {};
        var logo = (t.logos && t.logos[0] && t.logos[0].href) || t.logo || '';
        return { id: String(t.id), name: t.displayName || '', abbr: t.abbreviation || t.shortDisplayName || '', logo: logo };
      }
      var h = tm(home), a = tm(away);
      var key = [h.id, a.id].sort().join('-');
      var note = (((comp.notes || [])[0] || {}).headline) || '';
      var tie = byRound[slug][key] || (byRound[slug][key] = { teams: {}, winner: null, agg: '', pen: false, legs: 0, score: {}, flag: null });
      tie.teams[h.id] = h; tie.teams[a.id] = a;
      tie.legs += 1;
      tie.score[h.id] = (parseInt(home.score, 10) || 0);
      tie.score[a.id] = (parseInt(away.score, 10) || 0);
      if (home.winner === true) tie.flag = h.id;
      if (away.winner === true) tie.flag = a.id;
      var m = note.match(/(.+?) (advance|win)\b/);
      if (m) {
        var w = m[1].replace(/^.*\s-\s/, '').trim();
        Object.keys(tie.teams).forEach(function (id) { if (tie.teams[id].name === w) tie.winner = id; });
        var am = note.match(/(\d+)\s*-\s*(\d+)/);
        if (am) tie.agg = am[1] + '–' + am[2];
        tie.pen = /penalt/i.test(note);
      }
    });
    var out = {};
    ORDER.forEach(function (r) {
      out[r] = Object.keys(byRound[r]).map(function (k) {
        var t = byRound[r][k], ids = Object.keys(t.teams);
        var winner = t.winner, agg = t.agg;
        if (!winner && t.legs === 1 && t.flag) {
          winner = t.flag;
          if (!agg) { var hi = Math.max(t.score[ids[0]], t.score[ids[1]]), lo = Math.min(t.score[ids[0]], t.score[ids[1]]); agg = hi + '–' + lo; }
        }
        return { teams: [t.teams[ids[0]], t.teams[ids[1]]], winner: winner, agg: agg, pen: t.pen, decided: !!winner };
      });
    });
    return out;
  }

  function findByWinner(ties, teamId) {
    for (var i = 0; i < (ties || []).length; i++) if (ties[i].winner === teamId) return ties[i];
    return null;
  }

  // Árbol desde la FINAL hacia fuera. Cada nodo = un cruce; sus 2 hijos son los cruces
  // de la ronda anterior que ganaron sus 2 equipos. Cruce por jugar → hijo vacío.
  function buildTree(rounds) {
    function node(ri, tie) {
      var n = { ri: ri, tie: tie, children: [] };
      if (ri === 0) return n;
      var childRound = rounds[ORDER[ri - 1]];
      var kids = [null, null];
      if (tie && tie.teams) kids = [findByWinner(childRound, tie.teams[0].id), findByWinner(childRound, tie.teams[1].id)];
      n.children = [node(ri - 1, kids[0]), node(ri - 1, kids[1])];
      return n;
    }
    return node(3, (rounds['final'] || [])[0] || null);
  }
  // Pre-order → cruces por ronda EN ORDEN de posición (hojas alrededor del anillo).
  function slotsFromTree(root) {
    var b = { 0: [], 1: [], 2: [], 3: [] };
    (function walk(n) { b[n.ri].push(n.tie); n.children.forEach(walk); })(root);
    return b;
  }
  // Fallback (eliminatoria a medias, sin final): coloca lo que haya en orden de ESPN.
  // Los conectores se dibujan por enlace de ganador, así que siguen siendo correctos.
  function slotsFallback(rounds) {
    return { 0: rounds['round-of-16'].slice(), 1: rounds['quarterfinals'].slice(),
             2: rounds['semifinals'].slice(), 3: rounds['final'].slice() };
  }

  // ── Geometría radial ───────────────────────────────────────────────────────
  var CX = 500, CY = 500;
  var COUNT = { 0: 8, 1: 4, 2: 2, 3: 1 };            // cruces por anillo
  var RAD_T = { 0: 430, 1: 300, 2: 180, 3: 96 };     // radio del escudo por anillo
  var CREST_R = { 0: 23, 1: 29, 2: 37, 3: 46 };      // tamaño del escudo por anillo (crece hacia dentro)
  var CHAMP_R = 58;                                   // campeón (centro)
  var DELTA = { 0: 11, 1: 15, 2: 22, 3: 30 };        // medio-ángulo (º) que separa los 2 escudos de un cruce
  // Ángulos de cada cruce (grados; 0 = derecha, +horario). Octavos: 8 desde arriba.
  var ANG = { 0: [], 1: [], 2: [], 3: [0] };
  for (var i = 0; i < 8; i++) ANG[0][i] = -90 + i * 45;
  for (var j = 0; j < 4; j++) ANG[1][j] = (ANG[0][2 * j] + ANG[0][2 * j + 1]) / 2;
  for (var k = 0; k < 2; k++) ANG[2][k] = (ANG[1][2 * k] + ANG[1][2 * k + 1]) / 2;

  // Posición del escudo del equipo `side` (0/1) del cruce (ri, idx).
  function teamPos(ri, idx, side) {
    var a = (ANG[ri][idx] + (side === 0 ? -DELTA[ri] : DELTA[ri])) * Math.PI / 180, r = RAD_T[ri];
    return { x: CX + r * Math.cos(a), y: CY + r * Math.sin(a) };
  }

  // ── Render (SVG de escudos circulares + líneas con brillo) ──────────────────
  function esc(s) { return String(s || '').replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  var UID = 0;

  var DEFS = '<defs>' +
    '<filter id="bkGlow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="5"/></filter>' +
    '<filter id="bkGlowS" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="2.2"/></filter>' +
    '<radialGradient id="bkCore" cx="50%" cy="50%" r="50%">' +
    '<stop offset="0%" stop-color="rgba(36,208,138,.32)"/><stop offset="70%" stop-color="rgba(36,208,138,.05)"/><stop offset="100%" stop-color="transparent"/>' +
    '</radialGradient></defs>';

  function crest(team, x, y, cr, opts) {
    opts = opts || {};
    x = +x.toFixed(1); y = +y.toFixed(1);
    if (!team) return '<circle class="bk-ghost" cx="' + x + '" cy="' + y + '" r="' + cr + '"/>';
    var uid = 'bkc' + (UID++);
    var ring = opts.champ ? 'var(--accent)' : (opts.win ? 'rgba(45,224,208,.9)' : 'rgba(150,175,210,.35)');
    var glow = opts.champ
      ? '<circle cx="' + x + '" cy="' + y + '" r="' + (cr + 10) + '" fill="none" stroke="rgba(36,208,138,.5)" stroke-width="3" filter="url(#bkGlow)"/>'
      : (opts.win ? '<circle cx="' + x + '" cy="' + y + '" r="' + (cr + 4) + '" fill="none" stroke="rgba(45,224,208,.35)" stroke-width="3" filter="url(#bkGlow)"/>' : '');
    var img = team.logo
      ? '<image href="' + esc(team.logo) + '" x="' + (x - cr) + '" y="' + (y - cr) + '" width="' + (2 * cr) + '" height="' + (2 * cr) + '" clip-path="url(#' + uid + ')" preserveAspectRatio="xMidYMid slice" ' +
        'onload="this.previousElementSibling.style.display=\'none\'" onerror="this.remove()"/>'
      : '';
    return '<g class="bk-node">' +
      '<title>' + esc(team.name || team.abbr) + '</title>' + glow +
      '<clipPath id="' + uid + '"><circle cx="' + x + '" cy="' + y + '" r="' + cr + '"/></clipPath>' +
      '<circle class="bk-disc" cx="' + x + '" cy="' + y + '" r="' + cr + '"/>' +
      '<text class="bk-init" x="' + x + '" y="' + (y + cr * 0.34).toFixed(1) + '" text-anchor="middle" font-size="' + (cr * 0.8).toFixed(0) + '">' + esc(team.abbr || team.name) + '</text>' +
      img +
      '<circle class="bk-border" cx="' + x + '" cy="' + y + '" r="' + cr + '" fill="none" stroke="' + ring + '" stroke-width="' + (opts.champ ? 3 : 2) + '"/>' +
      '</g>';
  }

  function dimLine(a, b) { return '<line class="bk-tie" x1="' + a.x.toFixed(1) + '" y1="' + a.y.toFixed(1) + '" x2="' + b.x.toFixed(1) + '" y2="' + b.y.toFixed(1) + '"/>'; }
  function glowLine(a, b) {
    var c = 'x1="' + a.x.toFixed(1) + '" y1="' + a.y.toFixed(1) + '" x2="' + b.x.toFixed(1) + '" y2="' + b.y.toFixed(1) + '"';
    return '<line ' + c + ' stroke="rgba(45,224,208,.55)" stroke-width="6" filter="url(#bkGlow)"/>' +
           '<line ' + c + ' stroke="#8ef7d0" stroke-width="1.6" filter="url(#bkGlowS)"/>' +
           '<line ' + c + ' stroke="#d7fff0" stroke-width="1"/>';
  }

  function placedTies(slots) {
    var placed = [];
    [0, 1, 2, 3].forEach(function (ri) { (slots[ri] || []).forEach(function (tie, idx) { if (tie) placed.push({ ri: ri, idx: idx, tie: tie }); }); });
    return placed;
  }
  function winnerSide(tie) { return tie.winner ? (tie.teams[0].id === tie.winner ? 0 : 1) : -1; }

  function edgesSVG(slots) {
    var placed = placedTies(slots), dim = '', glow = '';
    placed.forEach(function (p) {
      dim += dimLine(teamPos(p.ri, p.idx, 0), teamPos(p.ri, p.idx, 1));   // enfrentamiento del cruce
      var ws = winnerSide(p.tie); if (ws < 0) return;
      var from = teamPos(p.ri, p.idx, ws);
      if (p.ri === 3) { glow += glowLine(from, { x: CX, y: CY }); return; }  // finalista → campeón
      var parent = placed.filter(function (q) { return q.ri === p.ri + 1 && q.tie.teams.some(function (t) { return t.id === p.tie.winner; }); })[0];
      if (!parent) return;
      var pside = parent.tie.teams[0].id === p.tie.winner ? 0 : 1;
      glow += glowLine(from, teamPos(p.ri + 1, parent.idx, pside));         // ganador → su escudo en la ronda de dentro
    });
    return { dim: dim, glow: glow };
  }

  function crestsSVG(slots) {
    var s = '';
    [0, 1, 2, 3].forEach(function (ri) {
      for (var idx = 0; idx < COUNT[ri]; idx++) {
        var tie = (slots[ri] || [])[idx] || null, cr = CREST_R[ri];
        var p0 = teamPos(ri, idx, 0), p1 = teamPos(ri, idx, 1);
        if (!tie) { s += crest(null, p0.x, p0.y, cr) + crest(null, p1.x, p1.y, cr); continue; }
        var ws = winnerSide(tie);
        s += crest(tie.teams[0], p0.x, p0.y, cr, { win: ws === 0 });
        s += crest(tie.teams[1], p1.x, p1.y, cr, { win: ws === 1 });
      }
    });
    return s;
  }

  function championSVG(rounds) {
    var fin = (rounds['final'] || [])[0];
    var champ = (fin && fin.winner) ? (fin.teams[0].id === fin.winner ? fin.teams[0] : fin.teams[1]) : null;
    return crest(champ, CX, CY, CHAMP_R, { champ: !!champ }) +
      (champ ? '<text class="bk-champ-lbl" x="' + CX + '" y="' + (CY + CHAMP_R + 28) + '" text-anchor="middle">Campeón</text>' : '');
  }

  function guidesSVG() {
    return [RAD_T[0], RAD_T[1], RAD_T[2]].map(function (r) {
      return '<circle class="bk-guide" cx="' + CX + '" cy="' + CY + '" r="' + r + '"/>';
    }).join('') + '<circle cx="' + CX + '" cy="' + CY + '" r="150" fill="url(#bkCore)"/>';
  }

  function legendHTML() {
    return '<div class="bk-legend">' + ORDER.map(function (r) {
      return '<span class="bk-lg bk-lg--' + r + '">' + LABEL[r] + '</span>';
    }).join('') + '</div>';
  }

  // HTML del cuadro como STRING (sin tocar el DOM) → render determinista en tests.
  function buildHTML(rounds) {
    UID = 0;
    var haveFinal = (rounds['final'] || []).length > 0;
    var slots = haveFinal ? slotsFromTree(buildTree(rounds)) : slotsFallback(rounds);
    var e = edgesSVG(slots);
    var svg = '<svg class="bk-svg" viewBox="0 0 1000 1000" role="img" aria-label="Cuadro de eliminatoria">' +
      DEFS + guidesSVG() +
      '<g class="bk-links-dim">' + e.dim + '</g>' +
      '<g class="bk-links-glow">' + e.glow + '</g>' +
      crestsSVG(slots) + championSVG(rounds) +
      '</svg>';
    return '<div class="bk-head">' + legendHTML() + '</div><div class="bk-stage">' + svg + '</div>';
  }

  function render(el, rounds) { el.innerHTML = buildHTML(rounds); }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { collectTies: collectTies, buildHTML: buildHTML };
  }
  if (typeof window === 'undefined') return;

  window.PMBracket = {
    init: function (code, mountSelector) {
      var el = document.querySelector(mountSelector);
      if (!el || el.dataset.loaded) return;
      el.dataset.loaded = '1';
      el.innerHTML = '<div class="bk-loading">Cargando cuadro…</div>';
      getJSON(ESPN + code + '/scoreboard').then(function (sb) {
        var season = (((sb.leagues || [])[0] || {}).season) || sb.season || {};
        var year = season.year;
        if (!year) { var m = String(season.displayName || '').match(/(\d{4})/); year = m ? +m[1] : new Date().getFullYear(); }
        var start = year + '0801', end = (year + 1) + '0701';
        return getJSON(ESPN + code + '/scoreboard?dates=' + start + '-' + end + '&limit=700');
      }).then(function (d) {
        var rounds = collectTies((d && d.events) || []);
        var any = ORDER.some(function (r) { return rounds[r].length > 0; });
        if (!any) { el.dataset.loaded = ''; el.innerHTML = '<div class="bk-empty">La eliminatoria aún no está definida. Los cruces aparecerán aquí en cuanto se sorteen.</div>'; return; }
        render(el, rounds);
      }).catch(function () {
        el.dataset.loaded = '';
        el.innerHTML = '<div class="bk-empty">No se pudo cargar el cuadro.</div>';
      });
    }
  };
})();
