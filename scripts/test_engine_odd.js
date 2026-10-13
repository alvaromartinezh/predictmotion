/* league-engine.js — tablas con un número IMPAR de equipos.
 *
 * Había DOS defectos distintos, y se tapaban el uno al otro (2026-10-13):
 *
 *  1. `randomMatchday()` emparejaba de 2 en 2 hasta `t.length`, así que con
 *     impar el último jugaba contra `undefined`: el guarda de `teamGp` no lo
 *     filtra (`undefined >= n` es false), así que se simulaba un partido
 *     FANTASMA y se le sumaban puntos y goles al equipo real de esa pareja.
 *  2. El bucle corría `totalMd - gp` jornadas, pero con impar cada jornada
 *     solo empareja ⌊n/2⌋ partidos (uno descansa): a cada equipo le quedaban
 *     partidos de su temporada SIN simular. Arreglado con un cupo por equipo
 *     (`simGp`) y jornadas de más (`mdCap`).
 *
 * En un grupo de 3 de la Liga D, P(el líder acaba último): 6,0% con el
 * fantasma · 0,3% arreglando solo el emparejamiento (se simulaban ~1,3 de sus 2
 * partidos pendientes, o sea MENOS volatilidad de la real) · 4,5% con los dos
 * arreglados. Arreglar uno solo da un número MÁS equivocado que el original,
 * que es justo por lo que este test no vigila un número, sino los invariantes.
 *
 * Dónde se nota: lo que se simula EN CLIENTE con tabla impar — los grupos de 3
 * de la Liga D de Nations League y de Concacaf (`assets/groups.js`, sin
 * precálculo en el servidor) y el fallback de `equipo.html` para MLS y
 * Argentina (15 equipos, donde el desvío era ≤0,5 pp). `seo/sim_table.py` lleva
 * los mismos dos arreglos; la divergencia la vigila seo/test_engine_parity.py,
 * que solo prueba tablas de 22 y 18 equipos y por eso no veía nada.
 *
 *   node scripts/test_engine_odd.js
 */
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'assets', 'league-engine.js'), 'utf8');

// Se exponen dos internas para poder probarlas directas, con el mismo truco que
// ya usa scripts/test_home_tables.js (reescribir la cola del IIFE).
const EXPOSE = "module.exports = API; API.__randomMatchday = randomMatchday; API.__mdCap = mdCap;";
function load(src) {
  const ctx = { console, module: { exports: {} } };
  vm.createContext(ctx);
  vm.runInContext(src.replace("module.exports = API;", EXPOSE), ctx);
  return ctx.module.exports;
}

const E = load(SRC);

// ── 1. Emparejamiento: nadie juega contra `undefined` ──
['a b c'.split(' '), 'a b c d e'.split(' '), 'a b c d'.split(' ')].forEach(function (names) {
  const md = E.__randomMatchday(names);
  assert.strictEqual(md.length, Math.floor(names.length / 2),
    names.length + ' equipos → ' + Math.floor(names.length / 2) + ' partidos esa jornada');
  md.forEach(function (par) {
    assert.ok(par[0] && par[1], 'ninguna pareja lleva un hueco vacío: ' + JSON.stringify(par));
  });
  // Nadie juega dos veces la misma jornada.
  const vistos = md.reduce((a, p) => a.concat(p), []);
  assert.strictEqual(new Set(vistos).size, vistos.length, 'nadie repite en la misma jornada');
});

// ── 2. El cupo de jornadas NO cambia con tabla par ──
// Es la garantía de que las 21 ligas de siempre siguen dando lo mismo: si esto
// se rompe, cambian los porcentajes publicados de todos los dashboards.
assert.strictEqual(E.__mdCap(new Array(20), 38, 20), 18, 'tabla par: el cupo es totalMd - gp');
assert.strictEqual(E.__mdCap(new Array(22), 42, 18), 24, 'tabla par: el cupo es totalMd - gp');
assert.ok(E.__mdCap(new Array(3), 4, 2) > 2, 'tabla impar: hacen falta jornadas de más');
assert.ok(E.__mdCap(new Array(15), 34, 30) > 4, 'tabla impar: hacen falta jornadas de más');

// ── 3. Grupo de 3 de verdad: ni NaN ni iteraciones perdidas ──
const G3 = () => [
  { rank: 1, id: '1', name: 'Letonia',    pts: 4, gp: 2, gf: 3, gc: 1 },
  { rank: 2, id: '2', name: 'Andorra',    pts: 3, gp: 2, gf: 2, gc: 2 },
  { rank: 3, id: '3', name: 'San Marino', pts: 0, gp: 2, gf: 0, gc: 2 },
];
const OPTS = { pHome: 0.42, pDraw: 0.27, simN: 20000, totalMd: 4 };
const res = E.simulate(G3(), OPTS);

const nums = [];
(function walk(v) {
  if (typeof v === 'number') nums.push(v);
  else if (Array.isArray(v)) v.forEach(walk);
  else if (v && typeof v === 'object') Object.keys(v).forEach(k => walk(v[k]));
})(res);
assert.ok(nums.length && nums.every(Number.isFinite), 'ningún NaN/Infinity con tabla impar');
Object.keys(res.posHist).forEach(function (nm) {
  const total = res.posHist[nm].reduce((a, b) => a + b, 0);
  assert.strictEqual(total, OPTS.simN, 'el histograma de ' + nm + ' suma las iteraciones');
});

// ── 4. Guardas de regresión: revertir CUALQUIERA de los dos arreglos se nota ──
// El PRNG va sembrado desde la tabla (`standingsSeed`), así que estos números
// son deterministas, no estadísticos.
const ultima = r => r.posHist['Letonia'][2] / OPTS.simN * 100;
const actual = ultima(res);

const SIN_CUPO = SRC.replace(
  /if \(names\.every\(function \(nm\) \{ return teamGp\[nm\] \+ simGp\[nm\] >= totalMd; \}\)\) break;\n\s*mdNum\+\+;/,
  'mdNum++;'
).replace(/\n\s*if \(teamGp\[hh\] \+ simGp\[hh\] >= totalMd \|\| teamGp\[aa\] \+ simGp\[aa\] >= totalMd\) continue;/g, '')
 .replace(/return base \+ \(names\.length % 2 \? 4 \* names\.length : 0\);/, 'return base;');
assert.notStrictEqual(SIN_CUPO, SRC, 'el cupo por equipo sigue en el motor');
const sinCupo = ultima(load(SIN_CUPO).simulate(G3(), OPTS));
assert.ok(Math.abs(sinCupo - actual) > 2,
  'sin el cupo, el líder sale con otra probabilidad de acabar último (' + sinCupo.toFixed(1)
  + '% vs ' + actual.toFixed(1) + '%)');

const FANTASMA = SRC.replace('for (var i = 0; i < t.length - 1; i += 2)',
                             'for (var i = 0; i < t.length; i += 2)');
assert.notStrictEqual(FANTASMA, SRC, 'el emparejamiento sigue acotado a t.length - 1');
const conFantasma = ultima(load(FANTASMA).simulate(G3(), OPTS));
assert.ok(Math.abs(conFantasma - actual) > 1,
  'con el rival fantasma el resultado cambia (' + conFantasma.toFixed(1)
  + '% vs ' + actual.toFixed(1) + '%)');

console.log('OK — tabla impar: P(líder último) ' + actual.toFixed(1) + '%'
  + ' (fantasma: ' + conFantasma.toFixed(1) + '% · sin cupo: ' + sinCupo.toFixed(1) + '%)');
