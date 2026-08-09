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

  // Árbol de EQUIPOS (dendrograma). Raíces = finalistas (anillo 3); cada equipo
  // desciende por los cruces que GANÓ hasta octavos (hojas). Un equipo aparece en cada
  // anillo que alcanzó (su recorrido hacia dentro): el campeón NO se duplica en un disco
  // central (lo marcan el brillo de su recorrido + la etiqueta CAMPEÓN). Cruce sin
  // decidir → la rama se corta ahí, sin escudos vacíos.
  function buildTeam(team, ri, rounds) {
    var n = { team: team, ri: ri, children: [] };
    if (ri > 0) {
      var tie = findByWinner(rounds[ORDER[ri - 1]], team.id);
      if (tie && tie.teams) n.children = [buildTeam(tie.teams[0], ri - 1, rounds), buildTeam(tie.teams[1], ri - 1, rounds)];
    }
    n.leaf = n.children.length === 0;
    return n;
  }

  // ── Geometría radial (anillos concéntricos, simétricos) ────────────────────
  var CX = 500, CY = 500, BASE = 90;                 // BASE=90 → los 2 finalistas caen a izq./dcha.
  var RAD = { 0: 442, 1: 316, 2: 192, 3: 90 };       // radio del escudo por anillo (fuera→dentro)
  var CREST = { 0: 24, 1: 30, 2: 38, 3: 44 };        // tamaño del escudo por anillo (progresión suave)
  function radOf(ri) { return RAD[ri] != null ? RAD[ri] : 90; }
  function crOf(ri) { return CREST[ri] != null ? CREST[ri] : 24; }
  function pos(angDeg, r) { var a = angDeg * Math.PI / 180; return { x: CX + r * Math.cos(a), y: CY + r * Math.sin(a) }; }

  // Coloca el árbol: hojas repartidas por igual en 360°, cada nodo interno en el ángulo
  // MEDIO de sus hijos (malla angular simétrica). Devuelve escudos + conectores + campeón.
  function buildPlacement(rounds) {
    var finalTie = (rounds['final'] || [])[0], roots = [], champion = null, centerLabel = '', haveCenter = false;
    if (finalTie && finalTie.teams) {
      roots = [buildTeam(finalTie.teams[0], 3, rounds), buildTeam(finalTie.teams[1], 3, rounds)];
      champion = finalTie.winner || null;
      centerLabel = champion ? 'CAMPEÓN' : 'FINAL';
      haveCenter = true;
    } else {                                          // eliminatoria a medias (sin final): raíces = ronda más profunda con datos
      var D = 2; while (D >= 0 && !((rounds[ORDER[D]] || []).length)) D--;
      if (D < 0) return null;
      (rounds[ORDER[D]] || []).forEach(function (tie) {
        if (tie && tie.teams) { roots.push(buildTeam(tie.teams[0], D, rounds)); roots.push(buildTeam(tie.teams[1], D, rounds)); }
      });
    }
    function leaves(n) { return n.leaf ? 1 : leaves(n.children[0]) + leaves(n.children[1]); }
    var total = roots.reduce(function (s, t) { return s + leaves(t); }, 0) || 1;
    var step = 360 / total, li = 0, crests = [], edges = [];
    function place(n, parent) {
      var ang;
      if (n.leaf) { ang = BASE + (li + 0.5) * step; li++; }
      else {
        var a0 = place(n.children[0], n), a1 = place(n.children[1], n);
        ang = (a0 + a1) / 2;
        n.children.forEach(function (c) {                                   // conector hijo → padre (línea recta = ángulo limpio)
          edges.push({ a: pos(c._ang, radOf(c.ri)), b: pos(ang, radOf(n.ri)), champPath: champion && c.team.id === champion });
        });
      }
      n._ang = ang;
      var p = pos(ang, radOf(n.ri));
      crests.push({ team: n.team, ri: n.ri, x: p.x, y: p.y, cr: crOf(n.ri),
        champ: !!(champion && n.ri === 3 && n.team.id === champion),
        champPath: !!(champion && n.team.id === champion) });
      return ang;
    }
    roots.forEach(function (r) { place(r, null); });
    if (haveCenter) roots.forEach(function (n) {                            // finalistas → centro (la final): campeón con brillo
      edges.push({ a: pos(n._ang, radOf(3)), b: { x: CX, y: CY }, champPath: !!(champion && n.team.id === champion), center: true });
    });
    crests.sort(function (a, b) { return a.ri - b.ri; });                    // anillos internos encima
    return { crests: crests, edges: edges, champion: champion, centerLabel: centerLabel };
  }

  // ── Render (SVG de escudos circulares + malla + brillo del campeón) ─────────
  function esc(s) { return String(s || '').replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  var UID = 0;

  var DEFS = '<defs>' +
    '<filter id="bkGlow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="5"/></filter>' +
    '<filter id="bkGlowS" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="2.2"/></filter>' +
    '<radialGradient id="bkCore" cx="50%" cy="50%" r="50%">' +
    '<stop offset="0%" stop-color="rgba(36,208,138,.32)"/><stop offset="70%" stop-color="rgba(36,208,138,.05)"/><stop offset="100%" stop-color="transparent"/>' +
    '</radialGradient></defs>';

  function crest(c) {
    var x = +c.x.toFixed(1), y = +c.y.toFixed(1), cr = c.cr, team = c.team;
    var uid = 'bkc' + (UID++);
    var ring = c.champ ? 'var(--accent, #24d08a)' : (c.champPath ? 'rgba(45,224,208,.9)' : 'rgba(150,175,210,.4)');
    var glow = c.champ
      ? '<circle cx="' + x + '" cy="' + y + '" r="' + (cr + 9) + '" fill="none" stroke="rgba(36,208,138,.55)" stroke-width="3" filter="url(#bkGlow)"/>'
      : (c.champPath ? '<circle cx="' + x + '" cy="' + y + '" r="' + (cr + 4) + '" fill="none" stroke="rgba(45,224,208,.3)" stroke-width="2.5" filter="url(#bkGlow)"/>' : '');
    var img = team.logo
      ? '<image href="' + esc(team.logo) + '" x="' + (x - cr) + '" y="' + (y - cr) + '" width="' + (2 * cr) + '" height="' + (2 * cr) + '" clip-path="url(#' + uid + ')" preserveAspectRatio="xMidYMid slice" ' +
        'onload="this.previousElementSibling.style.display=\'none\'" onerror="this.remove()"/>'
      : '';
    return '<g class="bk-node">' +
      '<title>' + esc(team.name || team.abbr) + '</title>' + glow +
      '<clipPath id="' + uid + '"><circle cx="' + x + '" cy="' + y + '" r="' + cr + '"/></clipPath>' +
      '<circle class="bk-disc" cx="' + x + '" cy="' + y + '" r="' + cr + '"/>' +
      '<text class="bk-init" x="' + x + '" y="' + (y + cr * 0.34).toFixed(1) + '" text-anchor="middle" font-size="' + (cr * 0.72).toFixed(0) + '">' + esc(team.abbr || team.name) + '</text>' +
      img +
      '<circle class="bk-border" cx="' + x + '" cy="' + y + '" r="' + cr + '" fill="none" stroke="' + ring + '" stroke-width="' + (c.champ ? 3 : 2) + '"/>' +
      '</g>';
  }

  function edgesSVG(edges) {
    var dim = '', glow = '';
    edges.forEach(function (e) {
      var co = 'x1="' + e.a.x.toFixed(1) + '" y1="' + e.a.y.toFixed(1) + '" x2="' + e.b.x.toFixed(1) + '" y2="' + e.b.y.toFixed(1) + '"';
      if (e.champPath) {
        glow += '<line ' + co + ' stroke="rgba(36,208,138,.5)" stroke-width="6" filter="url(#bkGlow)"/>' +
                '<line ' + co + ' stroke="#7ef0c2" stroke-width="1.7" filter="url(#bkGlowS)"/>' +
                '<line ' + co + ' stroke="#e6fff5" stroke-width="1"/>';
      } else {
        dim += '<line class="bk-tie" ' + co + '/>';
      }
    });
    return '<g class="bk-links-dim">' + dim + '</g><g class="bk-links-glow">' + glow + '</g>';
  }

  function guidesSVG() {
    return [RAD[0], RAD[1], RAD[2], RAD[3]].map(function (r) {
      return '<circle class="bk-guide" cx="' + CX + '" cy="' + CY + '" r="' + r + '"/>';
    }).join('') + '<circle cx="' + CX + '" cy="' + CY + '" r="120" fill="url(#bkCore)"/>';
  }

  function centerSVG(p) {
    if (!p.centerLabel) return '';
    var champ = null;
    (p.crests || []).forEach(function (c) { if (c.champ) champ = c.team; });
    var name = (p.centerLabel === 'CAMPEÓN' && champ)
      ? '<text class="bk-champ-name" x="' + CX + '" y="' + (CY + 16) + '" text-anchor="middle">' + esc(champ.abbr || champ.name) + '</text>' : '';
    return '<text class="bk-champ-lbl" x="' + CX + '" y="' + (CY - 4) + '" text-anchor="middle">' + esc(p.centerLabel) + '</text>' + name;
  }

  function legendHTML() {
    return '<div class="bk-legend">' + ORDER.map(function (r) {
      return '<span class="bk-lg bk-lg--' + r + '">' + LABEL[r] + '</span>';
    }).join('') + '</div>';
  }

  // HTML del cuadro como STRING (sin tocar el DOM) → render determinista en tests.
  function buildHTML(rounds) {
    UID = 0;
    var p = buildPlacement(rounds);
    if (!p) return '<div class="bk-empty">La eliminatoria aún no está definida.</div>';
    var svg = '<svg class="bk-svg" viewBox="0 0 1000 1000" role="img" aria-label="Cuadro de eliminatoria">' +
      DEFS + guidesSVG() +
      edgesSVG(p.edges) +
      p.crests.map(crest).join('') +
      centerSVG(p) +
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
