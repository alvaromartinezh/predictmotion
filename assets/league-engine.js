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

  // ── Poisson (v3): marcadores EXACTOS desde fuerzas att/def ────────────────
  // Port de seo/poisson.py. λ_local = base + hfa + k_att·a_h + k_def·d_a ;
  // λ_visita = base + k_att·a_a + k_def·d_h, con a_t/d_t desviaciones de la
  // media de la liga ya ajustadas en el cron y escaladas por el peso de
  // desvanecimiento w. `d` = goles EN CONTRA dev (positivo = recibe más =
  // defensa peor → la defensa mala del RIVAL SUBE la λ propia). Las λ solo
  // dependen del par y de la jornada proyectada, así que los CDF se
  // precomputan UNA vez antes del bucle (CPU ≈ la ruta v2).
  function poissonPmf(k, lam) {
    if (lam <= 0) return k === 0 ? 1 : 0;
    var p = Math.exp(-lam);
    for (var i = 1; i <= k; i++) p *= lam / i;
    return p;
  }
  function poissonCdf(lam, maxGoals) {
    var out = [], acc = 0;
    for (var k = 0; k <= maxGoals; k++) { acc += poissonPmf(k, lam); out.push(Math.min(1, acc)); }
    return out;
  }
  function poissonSample(cdf) {
    var r = rng();
    for (var k = 0; k < cdf.length; k++) if (r < cdf[k]) return k;
    return cdf.length - 1;
  }
  function poissonLambdas(adj, h, a, base, hfa, kAtt, kDef, w) {
    if (!adj) return [Math.max(base + hfa, 0), Math.max(base, 0)];
    var ah = w * adj[h].att, aa = w * adj[a].att;
    var dh = w * adj[h].def, da = w * adj[a].def;
    return [Math.max(base + hfa + kAtt * ah + kDef * da, 0),
            Math.max(base + kAtt * aa + kDef * dh, 0)];
  }
  function simTwoLegsPoisson(home, away, adj, base, hfa, kAtt, kDef, maxGoals) {
    var h = 0, a = 0, l;
    l = poissonLambdas(adj, home, away, base, hfa, kAtt, kDef, 1);
    h += poissonSample(poissonCdf(l[0], maxGoals));
    a += poissonSample(poissonCdf(l[1], maxGoals));
    l = poissonLambdas(adj, away, home, base, hfa, kAtt, kDef, 1);
    h += poissonSample(poissonCdf(l[1], maxGoals));
    a += poissonSample(poissonCdf(l[0], maxGoals));
    if (h > a) return home;
    if (a > h) return away;
    return rng() < 0.5 ? home : away;
  }

  // ── Monte Carlo de la tabla (SOLO temporada en curso) ─────────────────────
  // v3 (Poisson): port de seo/sim_table._simulate_poisson. Los CDF dependen solo
  // de (jornada proyectada, par ordenado), así que se precomputan UNA vez antes
  // del bucle; por partido = 2 rng + barrido corto (CPU ≈ la ruta v2).
  function simulatePoisson(standings, opts, sc, names, teamGp, minGp, totalMd, n, posHist, psf, pf, pw, simN, playoffTop) {
    var base = sc.base, hfa = sc.hfa, kAtt = sc.kAtt, kDef = sc.kDef, maxGoals = sc.maxGoals;
    var adj = sc.adj;
    var w0 = sc.w;
    var horizon = sc.horizon || 0;
    var idx = {}; names.forEach(function (nm, i) { idx[nm] = i; });

    var nMd = totalMd - minGp;
    var tables = [];
    for (var mi = 0; mi < nMd; mi++) {
      var w = horizon ? w0 * Math.max(0, 1 - mi / (horizon * totalMd)) : w0;
      var tab = [];
      for (var hi = 0; hi < n; hi++) {
        var hname = names[hi], row = [];
        for (var ai = 0; ai < n; ai++) {
          var lam = poissonLambdas(adj, hname, names[ai], base, hfa, kAtt, kDef, w);
          row.push([poissonCdf(lam[0], maxGoals), poissonCdf(lam[1], maxGoals)]);
        }
        tab.push(row);
      }
      tables.push(tab);
    }

    for (var it = 0; it < simN; it++) {
      var pts = {}, gd = {}, gf = {};
      standings.forEach(function (t) { pts[t.name] = t.pts; gd[t.name] = t.gf - t.gc; gf[t.name] = t.gf; });

      var mdNum = minGp;
      for (var mi = 0; mi < nMd; mi++) {
        mdNum++;
        var order = shuffle(names.slice());
        var tab = tables[mi];
        for (var k = 0; k < order.length - 1; k += 2) {
          var hh = order[k], aa = order[k + 1];
          if (teamGp[hh] >= mdNum || teamGp[aa] >= mdNum) continue;
          var cdfs = tab[idx[hh]][idx[aa]];
          var hg = poissonSample(cdfs[0]);
          var ag = poissonSample(cdfs[1]);
          if (hg > ag) { pts[hh] += 3; }
          else if (hg === ag) { pts[hh] += 1; pts[aa] += 1; }
          else { pts[aa] += 3; }
          gd[hh] += hg - ag; gd[aa] += ag - hg;
          gf[hh] += hg; gf[aa] += ag;
        }
      }

      var sorted = names.slice().sort(function (x, y) {
        return pts[y] !== pts[x] ? pts[y] - pts[x] :
               gd[y] !== gd[x] ? gd[y] - gd[x] : gf[y] - gf[x];
      });
      for (var p = 0; p < sorted.length; p++) posHist[sorted[p]][p]++;

      // Play-off de ascenso (v3): marcadores Poisson a plena fuerza.
      if (playoffTop && sorted.length >= playoffTop) {
        var sf1H = sorted[opts.promoSlots];
        var sf1A = sorted[playoffTop - 1];
        var sf2H = sorted[opts.promoSlots + 1];
        var sf2A = sorted[playoffTop - 2];
        psf[sf1H]++; psf[sf1A]++; psf[sf2H]++; psf[sf2A]++;
        var w1 = simTwoLegsPoisson(sf1H, sf1A, adj, base, hfa, kAtt, kDef, maxGoals);
        var w2 = simTwoLegsPoisson(sf2H, sf2A, adj, base, hfa, kAtt, kDef, maxGoals);
        pf[w1]++; pf[w2]++;
        var wf = simTwoLegsPoisson(w1, w2, adj, base, hfa, kAtt, kDef, maxGoals);
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
    if (sc && sc.v3) {
      return simulatePoisson(standings, opts, sc, names, teamGp, minGp, totalMd, n,
                             posHist, psf, pf, pw, simN, playoffTop);
    }
    for (var it = 0; it < simN; it++) {
      var pts = {}, gd = {}, gf = {};
      standings.forEach(function (t) { pts[t.name] = t.pts; gd[t.name] = t.gf - t.gc; gf[t.name] = t.gf; });

      var mdNum = minGp;
      var fixtures = buildFixtures(names, minGp, totalMd);
      for (var fi = 0; fi < fixtures.length; fi++) {
        mdNum++;
        // Peso del prior en esta jornada proyectada (port de sim_table.simulate):
        // v2 con horizonte → el prior decae dentro de la temporada proyectada;
        // v1 (o sin horizonte) → constante sc.w.
        var wMd = sc ? (sc.horizon ? sc.w * Math.max(0, 1 - fi / (sc.horizon * totalMd)) : sc.w) : 0;
        var md = fixtures[fi];
        for (var mi = 0; mi < md.length; mi++) {
          var hh = md[mi][0], aa = md[mi][1];
          if (teamGp[hh] >= mdNum || teamGp[aa] >= mdNum) continue;
          // Prior de fuerza (fallback): sesga la cuota local por el rating con
          // desvanecimiento. Sin contexto → pHome/pDraw de siempre.
          var ph = pHome, pd = pDraw;
          if (sc) {
            if (sc.absolute) {                       // v2: rating absoluto + encogido del empate
              var d = wMd * sc.scale * (sc.str[hh] - sc.str[aa]);
              pd = pDraw * Math.exp(-sc.kappa * Math.abs(d));
              ph = (1 - pd) / (1 + Math.exp(-(sc.logitS0 + d)));
            } else {                                 // v1: diferencia escalada, empate fijo
              ph = sc.M / (1 + Math.exp(-(sc.logitS0 + wMd * sc.scale * (sc.str[hh] - sc.str[aa]))));
            }
          }
          var r = rng(), hp, ap, hg, ag;
          if (r < ph) {
            hp = 3; ap = 0;
            hg = (rng() * 2 | 0) + 1 + (rng() * 2 | 0);
            ag = rng() * 2 | 0;
          } else if (r < ph + pd) {
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
  // Modelos de fuerza que este motor sabe reproducir. Si el snapshot declara uno
  // que no está aquí, el dashboard NO debe simular (ver canSimulate): simular con
  // otra fórmula da porcentajes que no son ni los del cron ni los correctos.
  var KNOWN_MODELS = { v1: 1, v2: 1, v3: 1 };

  // ¿Puede el cliente re-simular coherentemente con este snapshot? Sin snapshot, o
  // con uno sin prior de fuerza, sí: la sim uniforme es la correcta ahí. Con prior
  // pero un modelo que este motor no implementa (o que el snapshot ni declara, como
  // los generados antes de publicar `strength_model`), NO: mejor las probabilidades
  // del cron, aunque sean de hace un rato, que unas calculadas con otra fórmula.
  function canSimulate(snapshot) {
    if (!snapshot) return true;
    if (snapshot.strength_model === 'v3') return !!KNOWN_MODELS.v3;
    if (typeof snapshot.strength_scale !== 'number') return true;
    return !!KNOWN_MODELS[snapshot.strength_model];
  }

  // Contexto de prior de fuerza para el fallback en cliente. Lee la `strength` ya
  // calculada en el snapshot y los parámetros del modelo que el cron declara
  // (fuente única: la fórmula la fija `strength_model`, no una constante local).
  // Devuelve null si no hay fuerzas o si el prior ya se desvaneció → sim uniforme.
  function buildStrengthCtx(snapshot, standings, pHome, pDraw) {
    if (!snapshot || !Array.isArray(snapshot.teams)) return null;
    // v3 (Poisson): contexto de att/def DESVIACIONES ya ajustadas por el cron +
    // parámetros del modelo (base/hfa/k_att/k_def/max_goals del snapshot). Sin
    // att/def → null → sim uniforme (solo base + hfa) y sin override en el dashboard.
    if (snapshot.strength_model === 'v3') {
      var attMap = {}, defMap = {}, cnt = 0;
      snapshot.teams.forEach(function (t) {
        if (typeof t.att === 'number') {
          attMap[String(t.id)] = t.att;
          defMap[String(t.id)] = typeof t.def === 'number' ? t.def : 0;
          cnt++;
        }
      });
      if (!cnt) return null;
      var n3 = standings.length;
      var totalMd3 = snapshot.total_md || 2 * (n3 - 1);
      var jornada3 = Math.max.apply(null, standings.map(function (t) { return t.gp; }));
      var span3 = (snapshot.strength_fade_fraction || 0) * totalMd3;
      var w3 = span3 > 0 ? Math.max(0, Math.min(1, 1 - jornada3 / span3)) : 0;
      var adj = {};
      standings.forEach(function (t) {
        var id = String(t.id);
        adj[t.name] = { att: (id in attMap) ? attMap[id] : 0, def: (id in defMap) ? defMap[id] : 0 };
      });
      return {
        v3: true,
        adj: adj,
        w: w3,
        horizon: snapshot.projection_horizon_fade || 0,
        base: snapshot.poisson_base || 1.35,
        hfa: snapshot.poisson_hfa || 0.25,
        kAtt: snapshot.poisson_k_att || 0.7,
        kDef: snapshot.poisson_k_def || 0.7,
        maxGoals: snapshot.poisson_max_goals || 8,
      };
    }
    if (typeof snapshot.strength_scale !== 'number') return null;
    var byId = {}, vals = [];
    snapshot.teams.forEach(function (t) { if (typeof t.strength === 'number') { byId[String(t.id)] = t.strength; vals.push(t.strength); } });
    if (!vals.length) return null;
    var def = Math.min.apply(null, vals);                 // sin histórico → fondo de tabla
    var str = {};
    standings.forEach(function (t) { str[t.name] = (String(t.id) in byId) ? byId[String(t.id)] : def; });
    var n = standings.length, totalMd = snapshot.total_md || 2 * (n - 1);
    var jornada = Math.max.apply(null, standings.map(function (t) { return t.gp; }));
    var span = snapshot.strength_fade_fraction * totalMd;
    var w = span > 0 ? Math.max(0, Math.min(1, 1 - jornada / span)) : 0;
    if (w <= 0) return null;
    var pAway = 1 - pHome - pDraw, M = pHome + pAway;
    var s0 = Math.min(1 - 1e-9, Math.max(1e-9, M > 0 ? pHome / M : 0.5));
    var abs = snapshot.strength_model === 'v2';
    return {
      absolute: abs,
      scale: abs ? snapshot.strength_scale_abs : snapshot.strength_scale,
      kappa: abs ? (snapshot.draw_shrink_kappa || 0) : 0,
      horizon: abs ? (snapshot.projection_horizon_fade || 0) : 0,
      w: w, str: str, M: M, logitS0: Math.log(s0 / (1 - s0)),
    };
  }

  var API = {
    COLOR_PALETTE: COLOR_PALETTE,
    mulberry32: mulberry32, standingsSeed: standingsSeed, initials: initials,
    simulate: simulate, zoneProb: zoneProb,
    snapshotMatches: snapshotMatches, buildStrengthCtx: buildStrengthCtx,
    canSimulate: canSimulate,
  };
  if (typeof window !== 'undefined') window.PMEngine = API;
  // Guard inofensivo en el navegador: permite comparar el motor contra
  // seo/sim_table.py desde Node (mismo snapshot → mismos porcentajes).
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
})();
