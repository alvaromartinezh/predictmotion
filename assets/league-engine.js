/* PredictMotion — motor compartido de ligas regulares (Hypermotion, LaLiga, …).
   Sin dependencias. Se carga como <script src="/assets/league-engine.js">.

   Extraído VERBATIM del motor embebido de hypermotion.html/laliga.html (misma
   secuencia de mulberry32, mismo prior de fuerza con desvanecimiento, mismo
   desempate pts→DG→GF, mismo play-off a doble partido). El Monte Carlo acumula
   un HISTOGRAMA de posición final por equipo; cada dashboard deriva sus zonas de
   ahí con zoneProb() — idéntico a contar zonas inline, pero sin duplicar el bucle.

   PARIDAD: la secuencia de llamadas a rng() es exactamente la del simulate()
   original, así que los porcentajes son bit a bit los mismos. El bloque de
   play-off (que consume rng) va gated por opts.playoffTop, de modo que una liga
   sin play-off (LaLiga) reproduce su secuencia exacta y una con play-off
   (Hypermotion) la suya. La rama de temporada TERMINADA la resuelve cada
   dashboard (zonas por nota/rank, específicas de liga); aquí solo va el Monte
   Carlo. Parámetros del modelo inyectados por página (pHome, pDraw, simN). */
(function () {
  'use strict';

  var COLOR_PALETTE = [
    '#e11d48', '#7c3aed', '#2563eb', '#0891b2', '#059669', '#ca8a04', '#ea580c',
    '#db2777', '#4f46e5', '#0284c7', '#16a34a', '#d97706', '#dc2626', '#9333ea',
    '#0369a1', '#15803d', '#b45309', '#be185d', '#6d28d9', '#0e7490', '#166534', '#92400e',
  ];

  // ── PRNG determinista (mulberry32) ────────────────────────────────────────
  function mulberry32(seed) {
    return function () {
      seed |= 0; seed = seed + 0x6D2B79F5 | 0;
      var t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  // Seed derivado de la tabla (nombre+pts+PJ): mismos datos → mismos %.
  function standingsSeed(standings) {
    var str = standings.map(function (t) { return t.name + ':' + t.pts + ':' + t.gp; }).join('|');
    var h = 0;
    for (var i = 0; i < str.length; i++) h = Math.imul(31, h) + str.charCodeAt(i) | 0;
    return h >>> 0;
  }

  // rng a nivel de módulo: simulate() lo fija; shuffle/simTwoLegs lo usan (igual
  // que el motor embebido, que usaba una `rng` global).
  var rng = Math.random;

  function initials(name) {
    return name.split(' ').slice(0, 2).map(function (w) { return w[0]; }).join('').toUpperCase();
  }

  // ── Ayudantes de simulación (verbatim) ────────────────────────────────────
  function shuffle(arr) {
    for (var i = arr.length - 1; i > 0; i--) {
      var j = rng() * (i + 1) | 0;
      var tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
    }
    return arr;
  }
  function randomMatchday(names) {
    var t = shuffle(names.slice());
    var md = [];
    for (var i = 0; i < t.length; i += 2) md.push([t[i], t[i + 1]]);
    return md;
  }
  function buildFixtures(names, gp, totalMd) {
    var mds = [];
    for (var md = gp + 1; md <= totalMd; md++) mds.push(randomMatchday(names));
    return mds;
  }
  // Play-off: eliminatoria a doble partido (verbatim; pHome/pDraw por parámetro).
  function simTwoLegs(home, away, pHome, pDraw) {
    var h = 0, a = 0;
    var r1 = rng();
    if (r1 < pHome) {
      h += (rng() * 2 | 0) + 1 + (rng() * 2 | 0); a += rng() * 2 | 0;
    } else if (r1 < pHome + pDraw) {
      var g1 = rng() * 2 | 0; h += g1; a += g1;
    } else {
      h += rng() * 2 | 0; a += (rng() * 2 | 0) + 1 + (rng() * 2 | 0);
    }
    var r2 = rng();
    if (r2 < pHome) {
      a += (rng() * 2 | 0) + 1 + (rng() * 2 | 0); h += rng() * 2 | 0;
    } else if (r2 < pHome + pDraw) {
      var g2 = rng() * 2 | 0; h += g2; a += g2;
    } else {
      a += rng() * 2 | 0; h += (rng() * 2 | 0) + 1 + (rng() * 2 | 0);
    }
    if (h > a) return home;
    if (a > h) return away;
    return rng() < 0.5 ? home : away;  // empate → penaltis
  }

  // ── Monte Carlo de la tabla (SOLO temporada en curso) ─────────────────────
  // standings: filas con {name, pts, gp, gf, gc}. opts: {pHome, pDraw, simN,
  //   playoffTop?, sc?}. sc = contexto de prior de fuerza (buildStrengthCtx) o null.
  // Devuelve { posHist:{name:[conteos por posición]}, pSemi/pFinal/pWin:{name:%},
  //   simN }. La rama de temporada terminada la maneja el llamador (zonas por liga).
  function simulate(standings, opts) {
    var pHome = opts.pHome, pDraw = opts.pDraw;
    var simN = opts.simN;
    var playoffTop = opts.playoffTop || null;
    var sc = opts.sc || null;

    var n = standings.length;
    // totalMd: partidos por equipo en la temporada. Por defecto doble round-robin
    // 2·(n−1); opts.totalMd lo fija para formatos que no lo son (fase de liga UEFA:
    // 36 equipos, 8 partidos). Los 12 dashboards de liga no lo pasan → sin cambio.
    var totalMd = opts.totalMd || 2 * (n - 1);
    var names = standings.map(function (t) { return t.name; });
    var teamGp = {}; standings.forEach(function (t) { teamGp[t.name] = t.gp; });
    var minGp = Math.min.apply(null, standings.map(function (t) { return t.gp; }));

    var posHist = {}; names.forEach(function (nm) { posHist[nm] = new Array(n).fill(0); });
    var psf = {}, pf = {}, pw = {};
    names.forEach(function (nm) { psf[nm] = 0; pf[nm] = 0; pw[nm] = 0; });

    rng = mulberry32(standingsSeed(standings));
    for (var it = 0; it < simN; it++) {
      var pts = {}, gd = {}, gf = {};
      standings.forEach(function (t) { pts[t.name] = t.pts; gd[t.name] = t.gf - t.gc; gf[t.name] = t.gf; });

      var mdNum = minGp;
      var fixtures = buildFixtures(names, minGp, totalMd);
      for (var fi = 0; fi < fixtures.length; fi++) {
        mdNum++;
        var md = fixtures[fi];
        for (var mi = 0; mi < md.length; mi++) {
          var hh = md[mi][0], aa = md[mi][1];
          if (teamGp[hh] >= mdNum || teamGp[aa] >= mdNum) continue;
          // Prior de fuerza (fallback): sesga la cuota local por el rating con
          // desvanecimiento. Sin contexto → pHome/pDraw de siempre.
          var ph = pHome;
          if (sc) {
            var s = 1 / (1 + Math.exp(-(sc.logitS0 + sc.w * sc.scale * (sc.str[hh] - sc.str[aa]))));
            ph = sc.M * s;
          }
          var r = rng(), hp, ap, hg, ag;
          if (r < ph) {
            hp = 3; ap = 0;
            hg = (rng() * 2 | 0) + 1 + (rng() * 2 | 0);
            ag = rng() * 2 | 0;
          } else if (r < ph + pDraw) {
            hp = ap = 1;
            hg = ag = rng() * 2 | 0;
          } else {
            hp = 0; ap = 3;
            hg = rng() * 2 | 0;
            ag = (rng() * 2 | 0) + 1 + (rng() * 2 | 0);
          }
          pts[hh] += hp; pts[aa] += ap;
          gd[hh] += hg - ag; gd[aa] += ag - hg;
          gf[hh] += hg; gf[aa] += ag;
        }
      }

      var sorted = names.slice().sort(function (x, y) {
        return pts[y] !== pts[x] ? pts[y] - pts[x] :
               gd[y] !== gd[x] ? gd[y] - gd[x] : gf[y] - gf[x];
      });
      for (var p = 0; p < sorted.length; p++) posHist[sorted[p]][p]++;

      // Play-off de ascenso (solo si la liga lo tiene): 3º vs 6º y 4º vs 5º.
      if (playoffTop && sorted.length >= playoffTop) {
        var sf1H = sorted[opts.promoSlots];         // 3º (promoSlots = plazas directas)
        var sf1A = sorted[playoffTop - 1];          // 6º
        var sf2H = sorted[opts.promoSlots + 1];     // 4º
        var sf2A = sorted[playoffTop - 2];          // 5º
        psf[sf1H]++; psf[sf1A]++; psf[sf2H]++; psf[sf2A]++;
        var w1 = simTwoLegs(sf1H, sf1A, pHome, pDraw);
        var w2 = simTwoLegs(sf2H, sf2A, pHome, pDraw);
        pf[w1]++; pf[w2]++;
        var wf = simTwoLegs(w1, w2, pHome, pDraw);
        pw[wf]++;
      }
    }

    var out = { posHist: posHist, pSemi: {}, pFinal: {}, pWin: {}, simN: simN };
    names.forEach(function (nm) {
      out.pSemi[nm] = +(psf[nm] / simN * 100).toFixed(1);
      out.pFinal[nm] = +(pf[nm] / simN * 100).toFixed(1);
      out.pWin[nm] = +(pw[nm] / simN * 100).toFixed(1);
    });
    return out;
  }

  // Probabilidad (%) de terminar entre las posiciones lo..hi (1-based, incl.).
  // Suma los conteos del histograma y redondea igual que el conteo inline.
  function zoneProb(hist, lo, hi, simN) {
    var c = 0;
    for (var i = lo - 1; i < hi && i < hist.length; i++) c += hist[i];
    return +(c / simN * 100).toFixed(1);
  }

  // ── Snapshot / prior de fuerza (verbatim) ─────────────────────────────────
  // El snapshot solo es válido si su tabla coincide EXACTAMENTE con la actual
  // (mismos pts y PJ por equipo). Si no, se re-simula en cliente.
  function snapshotMatches(snap, standings) {
    if (!snap || !Array.isArray(snap.teams)) return false;
    if (snap.teams.length !== standings.length) return false;
    var byId = new Map(snap.teams.map(function (t) { return [String(t.id), t]; }));
    for (var i = 0; i < standings.length; i++) {
      var s = standings[i], t = byId.get(String(s.id));
      if (!t || t.pts !== s.pts || t.gp !== s.gp) return false;
    }
    return true;
  }
  // Contexto de prior de fuerza para el fallback en cliente. Lee la `strength` ya
  // calculada en el snapshot (fuente única; el Python la deriva de la temporada
  // anterior). Devuelve null si no hay fuerzas o si el prior ya se desvaneció.
  function buildStrengthCtx(snapshot, standings, pHome, pDraw) {
    if (!snapshot || typeof snapshot.strength_scale !== 'number' || !Array.isArray(snapshot.teams)) return null;
    var byId = {}, vals = [];
    snapshot.teams.forEach(function (t) { if (typeof t.strength === 'number') { byId[String(t.id)] = t.strength; vals.push(t.strength); } });
    if (!vals.length) return null;
    var def = Math.min.apply(null, vals);                 // sin histórico → fondo de tabla
    var str = {};
    standings.forEach(function (t) { str[t.name] = (String(t.id) in byId) ? byId[String(t.id)] : def; });
    var n = standings.length, totalMd = 2 * (n - 1);
    var jornada = Math.max.apply(null, standings.map(function (t) { return t.gp; }));
    var span = snapshot.strength_fade_fraction * totalMd;
    var w = span > 0 ? Math.max(0, Math.min(1, 1 - jornada / span)) : 0;
    if (w <= 0) return null;
    var pAway = 1 - pHome - pDraw, M = pHome + pAway;
    var s0 = Math.min(1 - 1e-9, Math.max(1e-9, M > 0 ? pHome / M : 0.5));
    return { scale: snapshot.strength_scale, w: w, str: str, M: M, logitS0: Math.log(s0 / (1 - s0)) };
  }

  window.PMEngine = {
    COLOR_PALETTE: COLOR_PALETTE,
    mulberry32: mulberry32, standingsSeed: standingsSeed, initials: initials,
    simulate: simulate, zoneProb: zoneProb,
    snapshotMatches: snapshotMatches, buildStrengthCtx: buildStrengthCtx,
  };
})();
