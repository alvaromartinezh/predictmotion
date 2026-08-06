/* ===== deck-demo.js · demostración en vivo del Monte Carlo ==================
   Réplica de juguete del motor real: PRNG mulberry32, modelo de partido 1X2 con
   logit-shift por fuerza (∝ R_local − R_visitante) y seed determinista. Simula
   los partidos que faltan de una liga de 6 equipos y estima P(Top-2 = ascenso),
   animando la convergencia al acumular iteraciones.
   -------------------------------------------------------------------------- */
(function () {
  "use strict";

  var mount = document.getElementById("mc-demo");
  if (!mount) return;

  // ── Parámetros del motor (los reales del sitio) ──────────────────────────
  var P_HOME = 0.42, P_DRAW = 0.27, P_AWAY = 0.31;
  var STRENGTH_SCALE = 0.28;
  var SEED = 0x9e3779b9;               // fijo → convergencia reproducible
  var CHUNK = 400;                     // iteraciones por frame

  // Liga de juguete (pts actuales + rating de fuerza tipo z-score).
  var TEAMS = [
    { name: "Racing",     pts: 41, str:  1.1 },
    { name: "Almería",    pts: 39, str:  0.7 },
    { name: "Deportivo",  pts: 37, str:  0.4 },
    { name: "Málaga",     pts: 35, str:  0.0 },
    { name: "Cádiz",      pts: 33, str: -0.6 },
    { name: "Eibar",      pts: 31, str: -1.0 }
  ];
  var N = TEAMS.length;

  // Partidos restantes: liga a una vuelta (todos contra todos), local = índice menor.
  var FIXTURES = [];
  for (var a = 0; a < N; a++) for (var b = a + 1; b < N; b++) FIXTURES.push([a, b]);

  function mulberry32(seed) {
    var s = seed >>> 0;
    return function () {
      s = (s + 0x6D2B79F5) | 0;
      var t = Math.imul(s ^ (s >>> 15), 1 | s);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Modelo de partido: sesga la cuota de victoria local por la diferencia de fuerza.
  function playPoints(rh, ra, rnd, out) {
    var cond = P_HOME / (P_HOME + P_AWAY);
    var logit = Math.log(cond / (1 - cond)) + STRENGTH_SCALE * (rh - ra);
    var cond2 = 1 / (1 + Math.exp(-logit));
    var pH = cond2 * (P_HOME + P_AWAY);
    var r = rnd();
    if (r < pH) { out[0] = 3; out[1] = 0; }
    else if (r < pH + P_DRAW) { out[0] = 1; out[1] = 1; }
    else { out[0] = 0; out[1] = 3; }
  }

  // ── Estado de la simulación ──────────────────────────────────────────────
  var counts = new Array(N).fill(0);   // veces que cada equipo acaba Top-2
  var done = 0;                        // iteraciones acumuladas
  var target = 20000;
  var running = false;
  var rnd = mulberry32(SEED);

  var base = TEAMS.map(function (t) { return t.pts; });
  var strn = TEAMS.map(function (t) { return t.str; });
  var order = TEAMS.map(function (_, i) { return i; })
    .sort(function (i, j) { return base[j] - base[i]; }); // orden de fila fijo

  function oneIteration() {
    var pts = base.slice();
    var res = [0, 0];
    for (var k = 0; k < FIXTURES.length; k++) {
      var h = FIXTURES[k][0], v = FIXTURES[k][1];
      playPoints(strn[h], strn[v], rnd, res);
      pts[h] += res[0]; pts[v] += res[1];
    }
    // Ranking final: puntos, desempate por fuerza (proxy estable de DG).
    var idx = pts.map(function (_, i) { return i; }).sort(function (i, j) {
      return (pts[j] - pts[i]) || (strn[j] - strn[i]) || (i - j);
    });
    counts[idx[0]]++; counts[idx[1]]++;      // Top-2 = ascenso directo
  }

  // ── Render ───────────────────────────────────────────────────────────────
  function build() {
    var rows = order.map(function (i) {
      return '<div class="mc-row" data-i="' + i + '">' +
             '<div class="mc-name">' + TEAMS[i].name + ' <small>' + TEAMS[i].pts + ' pts</small></div>' +
             '<div class="mc-track"><span class="mc-fill"></span></div>' +
             '<div class="mc-pct">—</div></div>';
    }).join("");

    mount.innerHTML =
      '<div class="mc-controls">' +
        '<button class="mc-run" id="mc-run">Simular</button>' +
        '<label class="mc-slider">Iteraciones ' +
          '<input id="mc-n" type="range" min="500" max="20000" step="500" value="20000">' +
          '<span id="mc-nval" class="mono">20&nbsp;000</span>' +
        '</label>' +
        '<span class="mc-iter" id="mc-iter"></span>' +
      '</div>' +
      '<div class="mc-rows">' + rows + '</div>' +
      '<p class="mc-legend"><span class="dot up"></span>Top-2 (ascenso) ' +
        '<span class="dot no"></span>resto · seed fijo → mismo resultado siempre</p>';

    document.getElementById("mc-run").addEventListener("click", run);
    var slider = document.getElementById("mc-n");
    slider.addEventListener("input", function () {
      target = parseInt(slider.value, 10);
      document.getElementById("mc-nval").innerHTML = target.toLocaleString("es-ES").replace(/\s/g, "&nbsp;");
    });
  }

  function paint() {
    var fills = mount.querySelectorAll(".mc-row");
    var probs = counts.map(function (c) { return done ? c / done : 0; });
    // Marca en verde los dos equipos con mayor probabilidad ahora mismo.
    var top2 = probs.map(function (p, i) { return [p, i]; })
      .sort(function (x, y) { return y[0] - x[0]; }).slice(0, 2)
      .map(function (x) { return x[1]; });

    fills.forEach(function (row) {
      var i = parseInt(row.getAttribute("data-i"), 10);
      var p = probs[i];
      row.classList.toggle("is-up", top2.indexOf(i) !== -1);
      row.querySelector(".mc-fill").style.width = (p * 100).toFixed(1) + "%";
      row.querySelector(".mc-pct").textContent = done ? (p * 100).toFixed(1) + "%" : "—";
    });
    var iter = document.getElementById("mc-iter");
    if (iter) iter.innerHTML = done ? "iteración <b>" + done.toLocaleString("es-ES") + "</b>" : "";
  }

  function run() {
    if (running) return;
    running = true;
    counts = new Array(N).fill(0);
    done = 0;
    rnd = mulberry32(SEED);            // reseed → reproducible
    var btn = document.getElementById("mc-run");
    if (btn) btn.disabled = true;

    function step() {
      var end = Math.min(done + CHUNK, target);
      for (; done < end; done++) oneIteration();
      paint();
      if (done < target) { requestAnimationFrame(step); }
      else { running = false; if (btn) btn.disabled = false; }
    }
    requestAnimationFrame(step);
  }

  build();
  paint();

  // Al entrar en la slide de la demo, lanza una simulación automática la 1ª vez.
  var autoran = false;
  document.addEventListener("deck:slide", function (e) {
    if (autoran) return;
    if (e.detail.slide && e.detail.slide.contains(mount)) { autoran = true; run(); }
  });
})();
