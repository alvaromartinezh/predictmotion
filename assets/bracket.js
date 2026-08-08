/* PredictMotion — Cuadro de eliminatoria CIRCULAR (concéntrico) para las
   competiciones UEFA. SOLO VISUALIZACIÓN de los cruces reales de ESPN (octavos
   en adelante); NO calcula probabilidades.

   Diseño concéntrico (anillos): borde exterior = Octavos (8 cruces), hacia dentro
   Cuartos (4) → Semis (2) → Final (centro) → campeón. Evita a propósito el bracket
   horizontal antiguo (desbordaba y exigía scroll horizontal en móvil): el cuadrado
   concéntrico escala a cualquier ancho.

   Datos: scoreboard de ESPN de la competición sobre TODO el rango de temporada
   (leagues[0].calendar, igual que fixtures.js), filtrado a las rondas de
   eliminatoria por `event.season.slug`. Cada cruce se arma juntando 1ª y 2ª mano
   por el par de equipos; el ganador sale de la nota "X advance … on aggregate" /
   "X win … on penalties". El árbol se reconstruye enlazando el ganador de cada
   cruce con el participante de la ronda siguiente. Todo en vivo, sin hardcode. */
(function () {
  'use strict';
  var ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer/';
  // Rondas incluidas, de fuera (octavos) hacia el centro (final). El
  // 'knockout-round-playoffs' (repesca 9º–24º) queda FUERA: "octavos en adelante".
  var ORDER = ['round-of-16', 'quarterfinals', 'semifinals', 'final'];
  var LABEL = { 'round-of-16': 'Octavos', 'quarterfinals': 'Cuartos', 'semifinals': 'Semifinales', 'final': 'Final' };

  function getJSON(u) {
    return fetch(u, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('ESPN ' + r.status); return r.json();
    });
  }
  function ymd(d) {
    return d.getFullYear() + ('0' + (d.getMonth() + 1)).slice(-2) + ('0' + d.getDate()).slice(-2);
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
      // Score y flag de ganador de ESPN, útiles como fallback para el partido único
      // (la FINAL): su nota suele venir vacía en Europa/Conference.
      tie.score[h.id] = (parseInt(home.score, 10) || 0);
      tie.score[a.id] = (parseInt(away.score, 10) || 0);
      if (home.winner === true) tie.flag = h.id;
      if (away.winner === true) tie.flag = a.id;
      var m = note.match(/(.+?) (advance|win)\b/);
      if (m) {
        // Quita TODOS los prefijos "… - " (p. ej. "2nd Leg - " y
        // "2nd Leg - Tied on aggregate - "). El nombre de equipo no lleva " - "
        // con espacios ("Saint-Germain" no se ve afectado).
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
        var winner = t.winner;
        var agg = t.agg;
        // Fallback SOLO para partido único (final): el flag `winner`/score de ESPN.
        // En eliminatorias a doble partido NO se usa el flag (indica el ganador de
        // ESE partido, no de la eliminatoria) — ahí manda la nota del agregado.
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

  // Árbol desde la FINAL hacia fuera (final=idx 3 … octavos=idx 0). Cada nodo tiene
  // 2 hijos = los cruces de la ronda anterior que ganaron sus 2 equipos. Si un cruce
  // no existe aún (ronda por jugar) el nodo queda vacío (TBD).
  function buildTree(rounds) {
    function node(ri, tie) {
      var n = { ri: ri, tie: tie, children: [] };
      if (ri === 0) return n;                                   // octavos = hoja
      var childRound = rounds[ORDER[ri - 1]];
      var kids = [null, null];
      if (tie && tie.teams) {
        kids = [findByWinner(childRound, tie.teams[0].id), findByWinner(childRound, tie.teams[1].id)];
      }
      n.children = [node(ri - 1, kids[0]), node(ri - 1, kids[1])];
      return n;
    }
    return node(3, (rounds['final'] || [])[0] || null);
  }

  // Recorrido pre-order → arrays de cruces por ronda EN ORDEN de posición (las 8
  // hojas quedan en orden alrededor del anillo; el cruce j de cuartos lo alimentan
  // las hojas 2j y 2j+1, etc.).
  function slotsFromTree(root) {
    var b = { 0: [], 1: [], 2: [], 3: [] };
    (function walk(n) { b[n.ri].push(n.tie); n.children.forEach(walk); })(root);
    return b;
  }

  // Fallback (eliminatoria a medias, sin final aún): coloca lo que haya en orden de
  // ESPN. Los conectores se dibujan por enlace de ganador, así que siguen siendo
  // correctos aunque las posiciones no formen un árbol perfecto.
  function slotsFallback(rounds) {
    return { 0: rounds['round-of-16'].slice(), 1: rounds['quarterfinals'].slice(),
             2: rounds['semifinals'].slice(), 3: rounds['final'].slice() };
  }

  // ── Geometría concéntrica ──────────────────────────────────────────────────
  var CX = 500, CY = 500;
  // Radio del centro de cada anillo (0=octavos exterior … 3=final centro). Las
  // separaciones dejan hueco para que las tarjetas de anillos contiguos no se
  // solapen; los anillos interiores tienen menos tarjetas y más aire.
  var RAD = { 0: 415, 1: 292, 2: 168, 3: 0 };
  // Bandas de anillo (fondo) para que el conjunto lea como círculos concéntricos.
  var BANDS = [
    { ri: 0, r: 415, w: 128 },
    { ri: 1, r: 292, w: 112 },
    { ri: 2, r: 168, w: 120 },
  ];
  // Ángulos (grados, 0 = derecha, +horario). Octavos: 8 posiciones desde arriba.
  var ANG = { 0: [], 1: [], 2: [] };
  for (var i = 0; i < 8; i++) ANG[0][i] = -90 + i * 45;
  for (var j = 0; j < 4; j++) ANG[1][j] = (ANG[0][2 * j] + ANG[0][2 * j + 1]) / 2;
  for (var k = 0; k < 2; k++) ANG[2][k] = (ANG[1][2 * k] + ANG[1][2 * k + 1]) / 2;

  function posOf(ri, slot) {
    if (ri === 3) return { x: CX, y: CY };
    var a = ANG[ri][slot] * Math.PI / 180, r = RAD[ri];
    return { x: CX + r * Math.cos(a), y: CY + r * Math.sin(a) };
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  function esc(s) { return String(s || '').replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }

  function teamRowHTML(t, isWinner, decided, agg, pen) {
    if (!t) return '<div class="bk-row bk-row--tbd"><span class="bk-ab">—</span></div>';
    var win = decided && isWinner;
    var logo = t.logo ? '<img class="bk-logo" src="' + esc(t.logo) + '" alt="" loading="lazy" onerror="this.style.visibility=\'hidden\'">' : '<span class="bk-logo bk-logo--ph"></span>';
    // El marcador agregado va en la fila del GANADOR (a la derecha); el verde marca
    // quién pasa, sin estrella redundante.
    var sc = (win && agg) ? '<span class="bk-agg">' + esc(agg) + (pen ? '<em>p</em>' : '') + '</span>' : '';
    return '<div class="bk-row' + (win ? ' is-win' : (decided ? ' is-out' : '')) + '">' +
      logo + '<span class="bk-ab">' + esc(t.abbr || t.name) + '</span>' + sc +
      '</div>';
  }

  function tieCardHTML(tie, ri, big) {
    var w = big ? 148 : 124, h = big ? 62 : 52;
    var cls = 'bk-tie' + (ri === 3 ? ' bk-tie--final' : '') + (tie && tie.decided ? ' is-decided' : '') + (!tie ? ' bk-tie--tbd' : '');
    var inner;
    if (!tie) {
      inner = '<div class="bk-row bk-row--tbd"><span class="bk-ab">Por definir</span></div>';
    } else {
      var t0 = tie.teams[0], t1 = tie.teams[1];
      inner = teamRowHTML(t0, tie.winner === t0.id, tie.decided, tie.agg, tie.pen) +
              teamRowHTML(t1, tie.winner === t1.id, tie.decided, tie.agg, tie.pen);
    }
    return { w: w, h: h, html: '<div class="' + cls + '">' + inner + '</div>' };
  }

  // Todos los cruces con posición, para dibujar conectores por enlace de ganador.
  function placeAll(slots) {
    var placed = [];                                          // {tie, ri, x, y}
    [0, 1, 2, 3].forEach(function (ri) {
      (slots[ri] || []).forEach(function (tie, idx) {
        if (!tie) return;
        var p = ri === 3 ? posOf(3, 0) : posOf(ri, idx);
        placed.push({ tie: tie, ri: ri, x: p.x, y: p.y });
      });
    });
    return placed;
  }

  function connectorsSVG(placed) {
    var lines = '';
    placed.forEach(function (child) {
      if (child.ri === 3 || !child.tie.winner) return;       // sin ganador → sin padre aún
      // el padre es el cruce de la ronda siguiente que incluye al ganador de child
      var parent = placed.filter(function (p) {
        return p.ri === child.ri + 1 && p.tie.teams.some(function (t) { return t.id === child.tie.winner; });
      })[0];
      if (!parent) return;
      lines += '<line class="bk-link" x1="' + child.x.toFixed(1) + '" y1="' + child.y.toFixed(1) +
        '" x2="' + parent.x.toFixed(1) + '" y2="' + parent.y.toFixed(1) + '"/>';
    });
    return lines;
  }

  // Bandas de anillo (fondo, en escala de grises del sistema) + disco central para
  // la final. Un `<circle>` con stroke ancho pinta una banda anular.
  function bandsSVG() {
    var s = '';
    BANDS.forEach(function (b) {
      s += '<circle class="bk-band bk-band--r' + b.ri + '" cx="' + CX + '" cy="' + CY + '" r="' + b.r + '" stroke-width="' + b.w + '"/>';
    });
    s += '<circle class="bk-band bk-band--center" cx="' + CX + '" cy="' + CY + '" r="112"/>';
    return s;
  }

  function cardsSVG(slots) {
    var s = '';
    [0, 1, 2, 3].forEach(function (ri) {
      var arr = slots[ri] || [];
      var n = ri === 3 ? 1 : (ri === 0 ? 8 : (ri === 1 ? 4 : 2));
      for (var idx = 0; idx < n; idx++) {
        var tie = arr[idx] || null;
        var p = ri === 3 ? posOf(3, 0) : posOf(ri, idx);
        var card = tieCardHTML(tie, ri, ri === 3);
        var x = (p.x - card.w / 2).toFixed(1), y = (p.y - card.h / 2).toFixed(1);
        s += '<foreignObject x="' + x + '" y="' + y + '" width="' + card.w + '" height="' + card.h + '">' +
          '<div xmlns="http://www.w3.org/1999/xhtml" class="bk-fo">' + card.html + '</div></foreignObject>';
      }
    });
    return s;
  }

  function champCaptionHTML(rounds) {
    var fin = (rounds['final'] || [])[0];
    if (!fin || !fin.winner) return '';
    var w = fin.teams[0].id === fin.winner ? fin.teams[0] : fin.teams[1];
    return '<div class="bk-champ"><span class="bk-champ__crown" aria-hidden="true">🏆</span>' +
      '<span class="bk-champ__lbl">Campeón</span>' +
      (w.logo ? '<img src="' + esc(w.logo) + '" alt="" class="bk-champ__logo">' : '') +
      '<span class="bk-champ__name">' + esc(w.name) + '</span></div>';
  }

  function legendHTML() {
    return '<div class="bk-legend">' + ORDER.map(function (r) {
      return '<span class="bk-lg bk-lg--' + r + '">' + LABEL[r] + '</span>';
    }).join('') + '</div>';
  }

  // Devuelve el HTML del cuadro como STRING (sin tocar el DOM), para poder probar
  // el render de forma determinista fuera del navegador (ver tests).
  function buildHTML(rounds) {
    var haveFinal = (rounds['final'] || []).length > 0;
    var slots = haveFinal ? slotsFromTree(buildTree(rounds)) : slotsFallback(rounds);
    var placed = placeAll(slots);
    var svg =
      '<svg class="bk-svg" viewBox="0 0 1000 1000" role="img" aria-label="Cuadro de eliminatoria">' +
      bandsSVG() + '<g class="bk-links">' + connectorsSVG(placed) + '</g>' +
      cardsSVG(slots) + '</svg>';
    return '<div class="bk-head">' + legendHTML() + champCaptionHTML(rounds) + '</div>' +
      '<div class="bk-stage">' + svg + '</div>';
  }

  function render(el, rounds) { el.innerHTML = buildHTML(rounds); }

  // Semilla de test (inofensiva en el navegador): permite renderizar el cuadro de
  // forma determinista en Node a partir de eventos ESPN guardados.
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
        // Las competiciones UEFA NO traen `calendar` (a diferencia de las ligas
        // domésticas), así que el rango se calcula del AÑO de temporada: una liga
        // europea va de agosto a junio del año siguiente → cubre también la
        // eliminatoria (feb–jun). El scoreboard de una temporada entera es ~2MB/1s.
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
